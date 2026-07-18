var p = msg.payload;
msg.query = `INSERT INTO hardware_metrics (
    station_id, recorded_at, fps, inference_ms
) VALUES ($1, to_timestamp($2), $3, $4)`;
msg.params = [p.station_id, p.timestamp, p.fps, p.inference_ms];
return msg;