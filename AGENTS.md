# Hubcap

A self-hosted monitoring service for deployed Ruby on Rails applications.

## Goals

- Metrics collection and dashboards
- Performance analysis (response times, slow queries, queue latency)
- Exception tracking with grouping and issue management
- Log search
- Alerting to Slack/Discord

## Architecture

```
Rails Apps
  ├── opentelemetry-ruby  → SigNoz    (APM: traces, infra dashboards + alerts)
  ├── stdout              → FluentBit → SigNoz (logs — FluentBit runs on the Rails app host)
  ├── hostmetrics + docker_stats
  │   └── otel-collector-contrib → SigNoz (infrastructure metrics)
  └── sentry-ruby gem     → GlitchTip (exception tracking + uptime monitoring)
```

## Stack

### APM + Metrics + Logs: SigNoz

- **SigNoz** — unified observability UI: traces, metrics dashboards, logs, alerting
- Built on **ClickHouse** for fast, efficient storage
- Receives data via the **OpenTelemetry** protocol (OTLP) on ports 4317 (gRPC) and 4318 (HTTP)
- Out-of-box dashboards for p99 latency, error rates, DB query times, Sidekiq job latency — no manual dashboard building required
- Alerts to Slack/Discord via built-in alert rules

**Rails side — OpenTelemetry gems:**
- `opentelemetry-sdk` — core SDK
- `opentelemetry-exporter-otlp` — sends data to SigNoz
- `opentelemetry-instrumentation-all` — auto-instruments Rails, ActiveRecord, Sidekiq, Redis, Puma, and 50+ more libraries

### Log Shipping: FluentBit → SigNoz

- **FluentBit** — lightweight log shipper (~1MB binary), runs on the **Rails app host** (not in Hubcap)
- Tails Docker container stdout logs from `/var/lib/docker/containers`
- Parses Docker's JSON log wrapper, then attempts a second JSON parse of the inner `log` field (picks up structured logs from `lograge` etc.)
- Sets `service.name` from the app's structured JSON log field `service_name`, with `OTEL_SERVICE_NAME` env var fallback, then Docker container ID fallback
- Sets `host.name` from the `HOST_NAME` env var for every log line
- Forwards to SigNoz OTel collector via OTLP HTTP on port 443 (TLS) through the Caddy-proxied `OTEL_DOMAIN`, or port 4318 for direct local connections
- Logs appear in SigNoz Logs Explorer, searchable by service, level, and full-text
- Trace correlation works automatically when the log line contains a `trace_id` (emitted by `opentelemetry-ruby`)
- See [README.md](README.md) for full FluentBit config and setup instructions

### Infrastructure Metrics: OTel Collector → SigNoz

- **OpenTelemetry Collector Contrib** — runs on the **Rails app host** (not in Hubcap)
- Collects host-level metrics via `hostmetrics` receiver (`cpu`, `load`, `memory`, `disk`, `filesystem`, `network`, `processes`, `process`)
- Collects per-container Docker stats via `docker_stats` receiver, reading from a read-only Docker-socket proxy
- Sets `service.name` and `host.name` explicitly from `OTEL_SERVICE_NAME` and `HOST_NAME` env vars via the `resource` processor
- Augments with auto-detected metadata (OS, CPU type, etc.) via `resourcedetection` processor
- Exports to SigNoz via OTLP HTTP (`https://<OTEL_DOMAIN>`) on port 443 with TLS
- Metrics appear in SigNoz under the service dashboard and can drive alert rules
- See [README.md](README.md) for full collector config and setup instructions

### Exception Tracking: GlitchTip

- **GlitchTip** — self-hosted, Sentry-compatible exception tracker
- Rails apps integrate via the standard `sentry-ruby` / `sentry-rails` / `sentry-sidekiq` gems, pointed at the GlitchTip instance
- Provides: exception grouping/deduplication, occurrence counts, stack trace rendering, issue state management (resolve/ignore/regress), uptime monitoring, Slack alerts

### Alerting

- SigNoz alert rules for metric-based alerts (error rate spikes, high latency, resource usage) → Slack/Discord
- GlitchTip for per-exception alerts (new issues, regressions) → Slack

## Authentication

### Hubcap services

| Service | Auth | Exposure |
|---|---|---|
| **Caddy** | TLS termination + reverse proxy, automatic Let's Encrypt certs | Public (ports 80/443) |
| **SigNoz** | Built-in username/password (set on first login) | Behind Caddy (`signoz.example.com`) |
| **GlitchTip** | Built-in email/password, supports multiple users/orgs | Behind Caddy (`glitchtip.example.com`) |
| **ClickHouse** | No auth — internal Docker network only | Internal only |
| **Zookeeper** | No auth — internal Docker network only | Internal only |
| **OTel Collector** | No auth — accepts OTLP on ports 4317/4318 | Ports open to Rails apps |
| **FluentBit** | No auth — runs on Rails app host, not in Hubcap | Rails app host only |

Only Caddy gets public-facing ports (80/443). The OTel Collector ports (4317/4318) should be firewalled to only accept connections from your Rails app servers.

## Deployment

- Docker Compose on a single server (4-8 GB RAM)
- SigNoz requires at least 4 GB RAM; 6-8 GB recommended for comfortable operation

## Project Structure

```
hubcap/
├── AGENTS.md
├── docker-compose.yml
├── .env.example
├── caddy/
│   └── Caddyfile                        # reverse proxy config (subdomain → service)
└── signoz/
    ├── otel-collector-config.yaml        # OTel collector pipeline config
    ├── otel-collector-opamp-config.yaml  # OpAMP management config
    └── clickhouse/
        ├── config.xml                    # ClickHouse server config
        ├── users.xml                     # ClickHouse users/quotas
        ├── custom-function.xml           # histogram UDF registration
        └── cluster.xml                   # single-node cluster + ZooKeeper config
```

## Rails App Integration Checklist

Each monitored Rails app needs:

### 1. OpenTelemetry gems (APM → SigNoz)

Add to `Gemfile`:

```ruby
gem 'opentelemetry-sdk'
gem 'opentelemetry-exporter-otlp'
gem 'opentelemetry-instrumentation-all'
```

Create `config/initializers/opentelemetry.rb`:

```ruby
require 'opentelemetry/sdk'
require 'opentelemetry/exporter/otlp'
require 'opentelemetry/instrumentation/all'

OpenTelemetry::SDK.configure do |c|
  c.use_all({
    'OpenTelemetry::Instrumentation::ActiveRecord' => {
      db_statement: :obfuscate,  # include SQL but mask values
    },
  })
end
```

Set environment variables on the Rails app server:

```bash
OTEL_SERVICE_NAME=my-rails-app
OTEL_EXPORTER_OTLP_ENDPOINT=https://<OTEL_DOMAIN>
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

> For local development or when the Rails app and Hubcap are on the same Docker network, you can fall back to the direct unencrypted endpoint `http://<hubcap-server>:4318`.

This automatically instruments:
- HTTP requests (controller, action, path, status, duration)
- ActiveRecord queries (SQL, duration, DB name)
- Sidekiq jobs (job class, queue, duration, retries)
- Redis commands
- Puma worker metrics
- External HTTP calls

#### Additional env vars for FluentBit and infrastructure metrics

Set these on the same Rails app host so FluentBit and the hostmetrics collector can attribute data correctly:

```bash
OTEL_SERVICE_NAME=my-rails-app   # shared by Rails, FluentBit, and hostmetrics collector
HOST_NAME=web-01.example.com    # the host's public or canonical hostname
```

### 2. FluentBit + infrastructure metrics (logs + host metrics → SigNoz)

Both the FluentBit log shipper and the hostmetrics collector need environment variables:

```bash
OTEL_SERVICE_NAME=my-rails-app
HOST_NAME=web-01.example.com
```

When running as Docker containers or Kamal accessories, inject them via the container `env` block. See [README.md](README.md) for full configuration files.

### 3. Sentry gems (exceptions + logs → GlitchTip)

Add to `Gemfile`:

```ruby
gem 'sentry-ruby'
gem 'sentry-rails'
gem 'sentry-sidekiq'  # if using Sidekiq
```

Create `config/initializers/sentry.rb`:

```ruby
Sentry.init do |config|
  config.dsn = ENV['SENTRY_DSN']  # GlitchTip project DSN

  # Breadcrumbs from Rails logs
  config.breadcrumbs_logger = [:active_support_logger]

  # Include request params and user info in events and logs
  # Set to false if you handle sensitive data and haven't reviewed filtering
  config.send_default_pii = true

  # Performance tracing — set low in production to reduce overhead
  config.traces_sample_rate = 0.1

  # Optional: attach request_id to every event/log for cross-tool correlation
  config.before_send = lambda do |event, _hint|
    event.tags[:request_id] = Current.request_id if defined?(Current)
    event
  end
end
```

Point `SENTRY_DSN` at your GlitchTip project DSN (found in GlitchTip project settings).

### 4. Structured logging (optional, improves GlitchTip log quality)

Use `lograge` for concise single-line request logs:

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
