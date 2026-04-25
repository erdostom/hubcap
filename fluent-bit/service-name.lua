-- FluentBit Lua filter: sets service_name for SigNoz OTLP ingestion.
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
-- to the container ID, which FluentBit extracts from the filename
-- via Tag_Regex and embeds in the tag as `docker.<container_id>`.

function set_service_name(tag, timestamp, record)
    local svc = record["service_name"]

    -- Fallback to container_id extracted from tag: docker.<container_id>
    if svc == nil or svc == "" then
        svc = string.gsub(tag, "^docker%.", "")
    end

    record["service_name"] = svc
    return 1, timestamp, record
end
