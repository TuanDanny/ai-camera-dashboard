var p = msg.payload;
// Giải mã base64 và lưu file (Trong thực tế Node-RED sẽ dùng file node, ở đây ta chỉ lưu metadata)
msg.query = `INSERT INTO snapshots (
    station_id, captured_at, format, resolution, size_bytes, lighting_condition, file_path
) VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7)`;
var filename = `/media/${p.station_id}_${p.timestamp}.jpeg`;
msg.params = [p.station_id, p.timestamp, p.format, p.resolution, p.size_bytes, p.lighting_condition, filename];
return msg;