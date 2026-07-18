var p = msg.payload;
msg.query = `INSERT INTO watchdog_events (
    station_id, event_at, event_type, reason, details, uptime_before_reset_s, reset_count_since_boot
) VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7)`;
msg.params = [p.station_id, p.timestamp, p.event, p.details.reason, JSON.stringify(p.details || {}), p.details.uptime_before_reset_s, p.details.reset_count_since_boot];
return msg;