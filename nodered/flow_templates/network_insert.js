var p = msg.payload;
msg.query = `INSERT INTO network_quality (
    station_id, recorded_at, operator, technology, band, rssi_dbm, rsrp_dbm, rsrq_db, sinr_db, latency_ms, packet_loss_pct, reconnect_count, bytes_sent, bytes_received, mqtt_reconnect_count
) VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)`;
msg.params = [p.station_id, p.timestamp, p.network.operator, p.network.technology, p.network.band, p.network.rssi_dbm, p.network.rsrp_dbm, p.network.rsrq_db, p.network.sinr_db, p.network.latency_ms, p.network.packet_loss_percent, p.network.reconnect_count, p.network.bytes_sent_total, p.network.bytes_received_total, p.network.mqtt_reconnect_count];
return msg;