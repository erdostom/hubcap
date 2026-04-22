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
  ├── yabeda-prometheus  → Prometheus ──→ Grafana (metrics dashboards + alerts → Slack)
  ├── structured logs    → Promtail   ──→ Loki    ──→ Grafana (log search)
  └── sentry-ruby gem   → GlitchTip  (exception tracking + uptime monitoring)
```

## Stack

### Metrics: Prometheus + Grafana + Yabeda

- **Prometheus** — time-series metrics collection, scrapes `/metrics` endpoints from Rails apps
- **Grafana** — dashboards, alerting (Slack/Discord), unified UI for metrics and logs
- **Yabeda** (Rails side) — Ruby-native metrics instrumentation
  - `yabeda-prometheus` — exposes metrics endpoint
  - `yabeda-rails` — request duration, error counts, controller-level metrics
  - `yabeda-puma` — web server metrics
  - `yabeda-sidekiq` — background job metrics

### Log Search: Loki + Promtail

- **Loki** — log aggregation, queried via LogQL inside Grafana
- **Promtail** — ships logs from Rails apps to Loki
- Rails apps should use structured JSON logging (`lograge` or `semantic_logger`)

### Exception Tracking: GlitchTip

- **GlitchTip** — self-hosted, Sentry-compatible exception tracker
- Rails apps integrate via the standard `sentry-ruby` / `sentry-rails` / `sentry-sidekiq` gems, pointed at the GlitchTip instance
- Provides: automatic exception grouping/deduplication, occurrence counts, stack trace rendering, issue state management (resolve/ignore/regress), native Slack alerts, uptime monitoring

### Alerting

- Grafana alert rules for metric-based alerts (error rate spikes, high latency, resource usage) → Slack/Discord
- GlitchTip for per-exception alerts (new issues, regressions) → Slack

## Authentication

### Rails `/metrics` endpoint

- Protected with **HTTP Basic Auth** — credentials stored as environment variables in each Rails app
- Prometheus is configured to send matching credentials when scraping
- Optionally layer on IP allowlisting or private network for defense in depth

### Hubcap services

| Service | Auth | Exposure |
|---|---|---|
| **Caddy** | TLS termination + reverse proxy, automatic Let's Encrypt certs | Public (ports 80/443) |
| **Grafana** | Built-in username/password (configurable via env vars), optional OAuth | Behind Caddy (`grafana.example.com`) |
| **GlitchTip** | Built-in email/password, supports multiple users/orgs | Behind Caddy (`glitchtip.example.com`) |
| **Prometheus** | No built-in auth — not exposed publicly, internal Docker network only | Internal only |
| **Loki** | No built-in auth — not exposed publicly, internal Docker network only | Internal only |
| **Promtail** | Runs alongside apps, no external access needed | Internal only |

Only Caddy gets public-facing ports (80/443). It reverse-proxies to Grafana and GlitchTip by subdomain with automatic HTTPS. All other services communicate over the internal Docker network.

## Deployment

- Docker Compose on a single server (4-8 GB RAM)
- Kamal is an option if we want the same deploy workflow as the Rails apps

## Project Structure

```
hubcap/
├── AGENTS.md
├── docker-compose.yml
├── .env.example
├── caddy/
│   └── Caddyfile                   # reverse proxy config (subdomain → service)
├── prometheus/
│   └── prometheus.yml              # scrape configs for Rails apps
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/            # auto-configure Prometheus + Loki
│   │   └── dashboards/             # dashboard provisioning
│   └── dashboards/
│       ├── rails-overview.json
│       └── sidekiq.json
├── loki/
│   └── loki-config.yml
├── promtail/
│   └── promtail-config.yml
└── alerting/
    └── alert-rules.yml             # Grafana alert rules
```

## Rails App Integration Checklist

Each monitored Rails app needs:

1. **Yabeda gems** — `yabeda-prometheus`, `yabeda-rails`, `yabeda-puma`, `yabeda-sidekiq`
2. **Structured logging** — `lograge` or `semantic_logger` outputting JSON
3. **Sentry gems** — `sentry-ruby`, `sentry-rails`, `sentry-sidekiq` with DSN pointed at GlitchTip
4. **Expose `/metrics`** endpoint for Prometheus scraping
5. **Log shipping** — Promtail configured to read the app's log output
