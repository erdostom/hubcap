# Hubcap

A self-hosted monitoring service for deployed Ruby on Rails applications.

See [AGENTS.md](AGENTS.md) for full architecture details and project structure.

## Stack

| Service | Purpose |
|---|---|
| **SigNoz** | APM: traces, metrics dashboards, logs, alerting |
| **GlitchTip** | Exception tracking, uptime monitoring |
| **Caddy** | Reverse proxy with automatic TLS |

## Deployment

```bash
cp .env.example .env
# fill in .env — at minimum: SIGNOZ_DOMAIN, GLITCHTIP_DOMAIN,
#   SIGNOZ_JWT_SECRET, GLITCHTIP_SECRET_KEY, GLITCHTIP_DB_PASSWORD
docker compose up -d
```

On first start, SigNoz runs its own DB migrations automatically. Visit `https://<SIGNOZ_DOMAIN>` and create your admin account.

Firewall ports 4317 and 4318 to only accept connections from your Rails app servers.

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
OTEL_EXPORTER_OTLP_ENDPOINT=http://<hubcap-server>:4317
```

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

#### Install FluentBit on the Rails app host

```bash
curl https://raw.githubusercontent.com/fluent/fluent-bit/master/install.sh | sh
```

Or via Docker — add to the Rails app's `docker-compose.yml`:

```yaml
fluent-bit:
  image: fluent/fluent-bit:5.0.3
  restart: unless-stopped
  volumes:
    - ./fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf:ro
    - ./fluent-bit-parsers.conf:/fluent-bit/etc/parsers.conf:ro
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
    Tag               docker.<container_name>
    Path              /var/lib/docker/containers/*/*.log
    Path_Key          filename
    Parser            docker
    DB                /var/log/flb_docker.db
    Mem_Buf_Limit     10MB
    Skip_Long_Lines   On
    Refresh_Interval  10
    Docker_Mode       On

[FILTER]
    Name         parser
    Match        docker.*
    Key_Name     log
    Parser       json
    Reserve_Data On
    Preserve_Key On

[FILTER]
    Name    modify
    Match   docker.*
    Copy    container_name service.name

[OUTPUT]
    Name                 opentelemetry
    Match                docker.*
    Host                 <hubcap-server>
    Port                 4318
    Logs_uri             /v1/logs
    Log_response_payload True
    Tls                  Off
    Tls.verify           Off
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

Logs appear in SigNoz Logs Explorer tagged by `service.name` (from container name). Trace correlation works automatically when `trace_id` is present (emitted by `opentelemetry-ruby`).

#### Structured logging (recommended)

Use `lograge` for richer structured fields in logs:

```ruby
# config/initializers/lograge.rb
Rails.application.configure do
  config.lograge.enabled = true
  config.lograge.formatter = Lograge::Formatters::Json.new
  config.lograge.custom_options = lambda do |event|
    {
      request_id: event.payload[:request_id],
      user_id:    event.payload[:user_id],
    }
  end
end
```

### 4. Create GlitchTip project

Log into `https://<GLITCHTIP_DOMAIN>`, create a project, and copy the DSN into `SENTRY_DSN` on the Rails app server.

### 5. Verify

- **SigNoz** → Services — confirm your app appears with traces
- **SigNoz** → Logs Explorer — filter by `service.name = my-rails-app`
- **GlitchTip** — trigger a test exception and confirm it appears
