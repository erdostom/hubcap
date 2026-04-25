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
  ├── opentelemetry-ruby  → SigNoz    (APM: traces, metrics, infra dashboards + alerts)
  ├── stdout              → FluentBit → SigNoz (logs — FluentBit runs on the Rails app host)
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
- Sets `service.name` from the app's structured JSON log field `service_name` (with container ID fallback) for attribution in SigNoz
- Forwards to SigNoz OTel collector via OTLP HTTP on port 4318
- Logs appear in SigNoz Logs Explorer, searchable by service, level, and full-text
- Trace correlation works automatically when the log line contains a `trace_id` (emitted by `opentelemetry-ruby`)
- See [README.md](README.md) for full FluentBit config and setup instructions

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
OTEL_EXPORTER_OTLP_ENDPOINT=http://<hubcap-server>:4317
# Use OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf and port 4318 if you prefer HTTP
```

This automatically instruments:
- HTTP requests (controller, action, path, status, duration)
- ActiveRecord queries (SQL, duration, DB name)
- Sidekiq jobs (job class, queue, duration, retries)
- Redis commands
- Puma worker metrics
- External HTTP calls

### 2. Sentry gems (exceptions + logs → GlitchTip)

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

### 3. Structured logging (optional, improves GlitchTip log quality)

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
