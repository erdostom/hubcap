-- FluentBit Lua filter: sets service_name and hostname for SigNoz OTLP ingestion.
--
-- Usage: add to fluent-bit.conf
--
--   [FILTER]
--       Name   lua
--       Match  docker.*
--       Script /fluent-bit/etc/service-name.lua
--       Call   set_service_name
--
-- The script reads `service_name` from the parsed JSON log record
-- (e.g. emitted by lograge).  If the field is missing it falls back
-- to the OTEL_SERVICE_NAME environment variable, and finally to the
-- Docker container ID, which FluentBit extracts from the filename via
-- Tag_Regex and embeds in the tag as `docker.<container_id>`.
--
-- The `hostname` field is set from the HOST_NAME environment variable
-- so that SigNoz can group logs by host as well as by service.

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
