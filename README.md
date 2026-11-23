# Hubcap

A self-hosted monitoring service for deployed Ruby on Rails applications.

See [AGENTS.md](AGENTS.md) for full architecture details and project structure.

## Stack

| Service | Purpose |
|---|---|
| **SigNoz** | APM: traces, metrics dashboards, logs, alerting |
| **GlitchTip** | Exception tracking, uptime monitoring |
| **kamal-proxy** | TLS termination + reverse proxy (via Kamal) |

> A legacy `docker-compose.yml` setup is kept for reference; new deployments should use Kamal.

## Deployment

Hubcap deploys with [Kamal](https://kamal-deploy.org). Everything runs as Kamal **accessories** (prebuilt upstream images — nothing is built), and `kamal-proxy` replaces Caddy for TLS termination on ports 80/443.

### 0. Install Kamal

```bash
gem install kamal        # 2.x; requires Ruby 3.1+ locally
```

### 1. Configure

Edit the clear settings directly in **`config/deploy.yml`**: server address,
registry username, accessory `env.clear` values, and `proxy.host` domains.
The deployment file is plain YAML.

Keep private values in **1Password**. Install the [1Password CLI](https://developer.1password.com/docs/cli/)
and enable its desktop-app integration or sign in to your account.

The `kamal secrets fetch` command in **`.kamal/secrets`** selects account
`my.1password.com` and vault/item **`hubcap/deployment`**. Create the item with
these five concealed fields, using the names exactly:

| Field | Value |
|---|---|
| `KAMAL_REGISTRY_PASSWORD` | Docker Hub access token |
| `SIGNOZ_TOKENIZER_JWT_SECRET` | SigNoz JWT signing secret |
| `GLITCHTIP_SECRET_KEY` | GlitchTip's Django signing secret |
| `GLITCHTIP_POSTGRES_PASSWORD` | GlitchTip PostgreSQL password |
| `GLITCHTIP_EMAIL_URL` | SMTP URL, or `consolemail://` for email written to container logs |

`.kamal/secrets` generates `GLITCHTIP_DATABASE_URL` from
`GLITCHTIP_POSTGRES_PASSWORD`. No `GLITCHTIP_DATABASE_URL` field is needed in
1Password. The URL's user and database name must match the PostgreSQL accessory's
`env.clear` settings.
Changing the secret does not rotate the password inside an existing PostgreSQL
database; update the database role as well when rotating it.

For the existing deployment, copy the current values from the gitignored
`.kamal/secrets.local` migration copy. Remove that copy after importing and
verifying the secrets. For a fresh deployment, `openssl rand -hex 32` generates
a suitable signing secret or database password.

The Git-safe `.kamal/secrets` uses Kamal's native `secrets fetch` and
`secrets extract` commands. GlitchTip containers receive `GLITCHTIP_SECRET_KEY`
as `SECRET_KEY` and `GLITCHTIP_DATABASE_URL` as `DATABASE_URL`. PostgreSQL receives
`GLITCHTIP_POSTGRES_PASSWORD` as `POSTGRES_PASSWORD`. Email credentials are
injected as `EMAIL_URL` for both GlitchTip web and worker containers.

All accessory `proxy.host` domains must have DNS A records pointing at `x-server`
before first boot — kamal-proxy provisions Let's Encrypt certificates automatically.
Keep GlitchTip's `GLITCHTIP_DOMAIN` URL in both web and worker `env.clear` settings
aligned with its public proxy hostname.

Run the offline configuration check, which uses a mock 1Password CLI:

```bash
ruby test/configuration_test.rb
```

### 2. Boot

```bash
kamal server bootstrap    # once — installs Docker on the server
kamal proxy boot          # starts kamal-proxy on ports 80/443
kamal accessory boot all  # boots every container, in the order defined in config/deploy.yml
```

Boot order (as defined in `config/deploy.yml`): zookeeper → clickhouse-init (one-shot) → clickhouse → clickhouse-migrator (one-shot, runs the SigNoz schema migrations) → signoz → otel-collector → otel-gateway → glitchtip-db → glitchtip-redis → glitchtip-migrate → glitchtip-web → glitchtip-worker. Every one-shot and long-running container retries until its dependencies are ready, so a slow start self-heals.

Visit the SigNoz and GlitchTip proxy domains to create your accounts. `ENABLE_USER_REGISTRATION` and `ENABLE_ORGANIZATION_CREATION` under `glitchtip-web.env.clear` start as `"true"` for initial setup — set both to `"false"` afterwards and run `kamal accessory reboot glitchtip-web`.

Firewall port 4318 to only accept connections from your Rails app servers. No other ports besides 80/443 need to be public.

### 3. Day-2 operations

```bash
kamal accessory logs signoz -f         # follow SigNoz UI logs
kamal accessory logs otel-collector    # collector logs
kamal accessory reboot signoz          # re-create a container after an image/env/config change
kamal accessory exec glitchtip-web --reuse -i sh # shell into the running GlitchTip web container
kamal accessory reboot glitchtip-migrate # re-run GlitchTip DB migrations (one-shot container)
```

Bumping an image version: edit the `image:` in `config/deploy.yml`, then `kamal accessory reboot <name>` re-pulls and re-creates that container. Uploaded config files (ClickHouse XML, collector YAML, Caddyfile) are re-uploaded on every boot, so config changes just need a `reboot` too.

> **Note:** do not run `kamal deploy` — Hubcap runs prebuilt images and is managed entirely through `kamal accessory` commands.

### 4. Cutover from the legacy docker-compose setup

1. Back up volumes on the old server (ClickHouse, `signoz_sqlite`, `glitchtip_db_data`) with `docker run --rm -v <vol>:/data -v $PWD:/backup alpine tar czf /backup/<vol>.tgz /data`.
2. Boot the new server per the steps above (fresh server — no volume migration needed).
3. Create the GlitchTip projects again and point the Rails apps' `SENTRY_DSN` at the new DSNs. The `OTEL_EXPORTER_OTLP_ENDPOINT` (`https://<OTEL_DOMAIN>`) and FluentBit config need no changes.
4. Once the new server is verified, retire the old one. The legacy reference files are `docker-compose.yml`, `.env.example`, and `caddy/Caddyfile`.

The legacy Compose file uses clear settings from `.env` (copy `.env.example`)
and the same secret names as Kamal. To run it with secrets fetched from
1Password, pass the resolved values through the process environment:

```bash
ruby -rkamal -e '
  config = Kamal::Configuration.create_from(config_file: Pathname.new("config/deploy.yml"))
  %w[SIGNOZ_TOKENIZER_JWT_SECRET GLITCHTIP_SECRET_KEY GLITCHTIP_POSTGRES_PASSWORD GLITCHTIP_DATABASE_URL GLITCHTIP_EMAIL_URL].each do |key|
    ENV[key] = config.secrets[key]
  end
  ENV["SECRET_KEY"] = ENV["GLITCHTIP_SECRET_KEY"]
  ENV["POSTGRES_PASSWORD"] = ENV["GLITCHTIP_POSTGRES_PASSWORD"]
  ENV["DATABASE_URL"] = ENV["GLITCHTIP_DATABASE_URL"]
  exec("docker", "compose", *ARGV)
' -- up -d
```

    ## Dashboards as code

Keep exported dashboard JSON in `signoz/dashboards/` and preview or apply it with
`bin/signoz_dashboards [--apply]`. See the
[dashboard workflow](signoz/dashboards/README.md) for ownership tags, API key setup,
safe updates, and offline tests.

## Adding a Rails App

### 1. OpenTelemetry — APM → SigNoz

```ruby
# Gemfile
gem 'opentelemetry-sdk'
gem 'opentelemetry-exporter-otlp'
gem 'opentelemetry-instrumentation-all'
```

```ruby
# config/initializers/opentelemetry.rb
require 'opentelemetry/sdk'
require 'opentelemetry/exporter/otlp'
require 'opentelemetry/instrumentation/all'

OpenTelemetry::SDK.configure do |c|
  c.use_all({
    'OpenTelemetry::Instrumentation::ActiveRecord' => {
      db_statement: :obfuscate,
    },
  })
end
```

Set on the Rails app server:

```bash
OTEL_SERVICE_NAME=my-rails-app
OTEL_EXPORTER_OTLP_ENDPOINT=https://<OTEL_DOMAIN>
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

> **Production recommendation:** Always use HTTPS (`https://<OTEL_DOMAIN>`) with `http/protobuf`. kamal-proxy terminates TLS and proxies to the SigNoz collector on port 4318 (via the internal otel-gateway container). For local development or when FluentBit and the collector are on the same Docker network, you can fall back to the direct unencrypted endpoint `http://<hubcap-server>:4318`.

This auto-instruments HTTP requests, ActiveRecord queries, Sidekiq jobs, Redis, Puma, and external HTTP calls.

### 2. Sentry gems — exceptions → GlitchTip

Create a project in the GlitchTip UI to get a DSN, then:

```ruby
# Gemfile
gem 'sentry-ruby'
gem 'sentry-rails'
gem 'sentry-sidekiq'  # if using Sidekiq
```

```ruby
# config/initializers/sentry.rb
Sentry.init do |config|
  config.dsn = ENV['SENTRY_DSN']
  config.breadcrumbs_logger = [:active_support_logger]
  config.send_default_pii = true
  config.traces_sample_rate = 0.1
end
```

Set `SENTRY_DSN` to the GlitchTip project DSN.

### 3. Log shipping — stdout → SigNoz

Logs are shipped by a **FluentBit** agent running on the same host as the Rails app (not on the Hubcap server). FluentBit tails Docker container stdout and forwards to the SigNoz OTel collector via OTLP HTTP.

#### Environment variables

FluentBit needs two environment variables for correct attribution in SigNoz:

| Variable | Purpose | Example |
|---|---|---|
| `OTEL_SERVICE_NAME` | Fallback `service.name` when the log record does not already contain a `service_name` field | `my-rails-app` |
| `HOST_NAME` | `host.name` resource attribute for every log line | `web-01.example.com` |

When running FluentBit as a Docker container or Kamal accessory, inject them via `env`:

```yaml
# docker-compose.yml or Kamal deploy.yml accessory
  fluent-bit:
    image: fluent/fluent-bit:5.0.3
    restart: unless-stopped
    environment:
      OTEL_SERVICE_NAME: my-rails-app
      HOST_NAME: web-01.example.com
    volumes:
      - ./fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf:ro
      - ./fluent-bit-parsers.conf:/fluent-bit/etc/parsers.conf:ro
      - ./service-name.lua:/fluent-bit/etc/service-name.lua:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - fluent_bit_db:/var/log/
```

#### `fluent-bit.conf`

```ini
[SERVICE]
    Flush         5
    Daemon        Off
    Log_Level     warn
    Parsers_File  /fluent-bit/etc/parsers.conf

[INPUT]
    Name              tail
    Tag               docker.<container_id>
    Path              /var/lib/docker/containers/*/*.log
    Path_Key          filename
    Parser            docker
    DB                /var/log/flb_docker.db
    Mem_Buf_Limit     10MB
    Skip_Long_Lines   On
    Refresh_Interval  10
    Docker_Mode       On
    Tag_Regex         (?<container_id>[a-f0-9]{64})-json\.log$

[FILTER]
    Name         parser
    Match        docker.*
    Key_Name     log
    Parser       json
    Reserve_Data On
    Preserve_Key On

[FILTER]
    Name   lua
    Match  docker.*
    Script /fluent-bit/etc/service-name.lua
    Call   set_service_name

[OUTPUT]
    Name                 opentelemetry
    Match                docker.*
    Host                 <OTEL_DOMAIN>
    Port                 443
    Logs_uri             /v1/logs
    Log_response_payload True
    Tls                  On
    Tls.verify           On
    Logs_body_key        log
```

> **Production:** Use `Host <OTEL_DOMAIN>` (e.g. `otel.example.com`) with `Tls On` and port `443`. For local development on the same Docker network you can use `Host <hubcap-server>` with `Port 4318`, `Tls Off`, and `Tls.verify Off`. OTLP gRPC is not exposed — use OTLP HTTP.

#### `service-name.lua`

Save alongside `fluent-bit.conf` and mount it into the FluentBit container:

```lua
function set_service_name(tag, timestamp, record)
    -- service_name comes from parsed JSON log (e.g. lograge output)
    local svc = record["service_name"]

    -- Fallback to OTEL_SERVICE_NAME env var
    if svc == nil or svc == "" then
        svc = os.getenv("OTEL_SERVICE_NAME")
    end

    -- Last-resort fallback to container_id extracted from tag: docker.<container_id>
    if svc == nil or svc == "" then
        svc = string.gsub(tag, "^docker%.", "")
    end

    record["service_name"] = svc
    record["hostname"] = os.getenv("HOST_NAME") or "unknown"
    return 1, timestamp, record
end
```

#### `fluent-bit-parsers.conf`

```ini
[PARSER]
    Name        docker
    Format      json
    Time_Key    time
    Time_Format %Y-%m-%dT%H:%M:%S.%L
    Time_Keep   On

[PARSER]
    Name        json
    Format      json
    Time_Key    time
    Time_Format %Y-%m-%dT%H:%M:%S.%L
    Time_Keep   On
```

Logs appear in SigNoz Logs Explorer tagged by `service.name`. The value is taken from the `service_name` field in your app's structured JSON logs (via `lograge`); if that field is missing it falls back to `OTEL_SERVICE_NAME` and finally the Docker container ID. Trace correlation works automatically when `trace_id` is present (emitted by `opentelemetry-ruby`).

#### Structured logging (recommended)

Use `lograge` for richer structured fields in logs:

```ruby
# config/initializers/lograge.rb
Rails.application.configure do
  config.lograge.enabled = true
  config.lograge.formatter = Lograge::Formatters::Json.new
  config.lograge.custom_options = lambda do |event|
    {
      request_id:   event.payload[:request_id],
      user_id:      event.payload[:user_id],
      service_name: ENV.fetch("OTEL_SERVICE_NAME", Rails.application.class.module_parent_name.underscore),
      hostname:     ENV.fetch("HOST_NAME", `hostname`.strip),
    }
  end
end
```

### 4. Infrastructure metrics — host + container → SigNoz

In addition to application-level APM traces and logs, you can collect host-level metrics (CPU, memory, disk, network, load) and per-container Docker stats with a second **OpenTelemetry Collector** running on the Rails app host.

#### Environment variables

| Variable | Purpose | Example |
|---|---|---|
| `OTEL_SERVICE_NAME` | `service.name` resource attribute on every metric | `my-rails-app` |
| `HOST_NAME` | `host.name` resource attribute on every metric | `web-01.example.com` |

#### Sample `otel-collector.yml`

```yaml
receivers:
  hostmetrics:
    root_path: /hostfs
    collection_interval: 30s
    scrapers:
      cpu:
      load:
      memory:
      disk:
      filesystem:
        exclude_mount_points:
          mount_points: [/dev/*, /proc/*, /sys/*, /run/*, /var/lib/docker/*]
          match_type: regexp
        exclude_fs_types:
          fs_types: [autofs, binfmt_misc, bpf, cgroup2, configfs, debugfs,
                     devpts, devtmpfs, fusectl, hugetlbfs, iso9660, mqueue,
                     nsfs, overlay, proc, procfs, pstore, rpc_pipefs, securityfs,
                     selinuxfs, squashfs, sysfs, tracefs, tmpfs]
          match_type: strict
      network:
      processes:
      process:
        mute_process_name_error: true
        mute_process_exe_error: true
        mute_process_io_error: true
        mute_process_user_error: true

  docker_stats:
    endpoint: http://my-app-docker-socket-proxy:2375
    collection_interval: 30s
    timeout: 10s

processors:
  resource:
    attributes:
      - key: service.name
        value: ${env:OTEL_SERVICE_NAME}
        action: upsert
      - key: host.name
        value: ${env:HOST_NAME}
        action: upsert

  resourcedetection:
    detectors: [env, system]
    system:
      hostname_sources: [lookup]
    timeout: 5s
    override: false

  batch:
    timeout: 10s

exporters:
  otlphttp:
    endpoint: https://<OTEL_DOMAIN>

service:
  pipelines:
    metrics:
      receivers: [hostmetrics, docker_stats]
      processors: [resource, resourcedetection, batch]
      exporters: [otlphttp]
```

#### Required mounts

- `/:/hostfs:ro,rslave` — host filesystem for `hostmetrics` scrapers
- `/proc:/hostfs/proc:ro` — process info
- `/sys:/hostfs/sys:ro` — system info
- `/etc/hostname:/etc/hostname:ro` — optional, used by `resourcedetection`

#### Docker socket proxy

The `docker_stats` receiver reads from a **read-only** docker-socket proxy (e.g. `tecnativa/docker-socket-proxy`) so the collector never mounts the raw Docker socket. Configure the proxy with `CONTAINERS=1` and `STATS=1` only.

#### Docker Compose / Kamal accessory example

```yaml
  otel-hostmetrics:
    image: otel/opentelemetry-collector-contrib:latest
    environment:
      OTEL_SERVICE_NAME: my-rails-app
      HOST_NAME: web-01.example.com
    volumes:
      - ./otel-collector.yml:/etc/otel-collector.yml:ro
      - /:/hostfs:ro,rslave
      - /proc:/hostfs/proc:ro
      - /sys:/hostfs/sys:ro
      - /etc/hostname:/etc/hostname:ro
    command: "--config=/etc/otel-collector.yml"
```

Metrics appear in SigNoz under **Services** → `<OTEL_SERVICE_NAME>` and can be used for alert rules (CPU > 80%, memory pressure, disk full, etc.).

### 5. Create GlitchTip project

Log into `https://<GLITCHTIP_DOMAIN>`, create a project, and copy the DSN into `SENTRY_DSN` on the Rails app server.

### 6. Verify

- **SigNoz** → Services — confirm your app appears with traces and infrastructure metrics
- **SigNoz** → Logs Explorer — filter by `service.name = my-rails-app`
- **GlitchTip** — trigger a test exception and confirm it appears
