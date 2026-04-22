# Hubcap

A self-hosted monitoring service for deployed Ruby on Rails applications.

See [AGENTS.md](AGENTS.md) for architecture details and project structure.

## Adding a Rails App to Monitoring

### Rails App Side

#### 1. Add gems

```ruby
# Gemfile

# Metrics
gem "yabeda-prometheus"
gem "yabeda-rails"
gem "yabeda-puma"
gem "yabeda-sidekiq"   # if using Sidekiq

# Exception tracking (talks to GlitchTip)
gem "sentry-ruby"
gem "sentry-rails"
gem "sentry-sidekiq"   # if using Sidekiq

# Structured logging
gem "lograge"          # or semantic_logger
```

#### 2. Configure Yabeda (metrics)

```ruby
# config/initializers/yabeda.rb
Yabeda.configure do
  # custom metrics can go here
end
```

Expose the `/metrics` endpoint:

```ruby
# config/routes.rb
mount Yabeda::Prometheus::Exporter => "/metrics"
```

Protect this endpoint with basic auth so only your Prometheus instance can scrape it:

```ruby
# config/initializers/yabeda.rb
Yabeda::Prometheus::Exporter.use Rack::Auth::Basic do |user, pass|
  ActiveSupport::SecurityUtils.secure_compare(user, ENV["METRICS_USER"]) &
  ActiveSupport::SecurityUtils.secure_compare(pass, ENV["METRICS_PASSWORD"])
end
```

Then set `METRICS_USER` and `METRICS_PASSWORD` environment variables in the Rails app. Use the same credentials in Hubcap's `prometheus/prometheus.yml` scrape config (see step 6).

#### 3. Configure Sentry → GlitchTip (exceptions)

First, create a project in the GlitchTip web UI to get a DSN.

```ruby
# config/initializers/sentry.rb
Sentry.init do |config|
  config.dsn = "https://key@glitchtip.yourdomain.com/PROJECT_ID"
  config.traces_sample_rate = 0.1
  config.breadcrumbs_logger = [:active_support_logger, :http_logger]
end
```

#### 4. Configure structured JSON logging

```ruby
# config/initializers/lograge.rb
Rails.application.configure do
  config.lograge.enabled = true
  config.lograge.formatter = Lograge::Formatters::Json.new
end
```

#### 5. Ensure logs are accessible to Promtail

Logs need to be written somewhere Promtail can read — either stdout (if containerized) or a log file on disk.

### Hubcap Side

#### 6. Add Prometheus scrape target

```yaml
# prometheus/prometheus.yml — add under scrape_configs:
- job_name: "my-new-rails-app"
  basic_auth:
    username: "prometheus"
    password: "the-same-password-as-METRICS_PASSWORD"
  static_configs:
    - targets: ["my-new-rails-app.example.com:3000"]
  metrics_path: "/metrics"
```

#### 7. Add Promtail log source

```yaml
# promtail/promtail-config.yml — add under scrape_configs:
- job_name: "my-new-rails-app"
  static_configs:
    - targets: [localhost]
      labels:
        app: "my-new-rails-app"
        __path__: "/var/log/my-new-rails-app/*.log"
```

#### 8. Create GlitchTip project

Log into the GlitchTip web UI, create a new project, and copy the DSN into the Rails app's Sentry initializer (step 3).

#### 9. Restart Hubcap services

After updating Prometheus and Promtail configs:

```bash
docker compose restart prometheus promtail
```

#### 10. Verify

- Open Grafana and confirm the new app appears in your dashboards
- Trigger a test exception in the Rails app and confirm it shows up in GlitchTip
- Check Grafana → Explore → Loki to confirm logs are flowing
