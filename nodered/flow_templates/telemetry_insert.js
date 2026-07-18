var p = msg.payload;
msg.query = `
    WITH ins_traffic AS (
        INSERT INTO traffic_records (
            station_id, recorded_at, seq, interval_seconds,
            motorbike_count, car_count, truck_count, bus_count,
            bicycle_count, unknown_count, total_count,
            inbound_count, outbound_count,
            avg_confidence, min_confidence, detections_raw,
            detections_filtered, lighting_condition
        ) VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
    )
    INSERT INTO hardware_metrics (
        station_id, recorded_at, cpu_temp_c, enclosure_temp_c,
        input_voltage_v, signal_rssi_dbm, signal_quality_pct,
        free_memory_kb, disk_usage_pct, fps, inference_ms
    ) VALUES ($1, to_timestamp($2), $19, $20, $21, $22, $23, $24, $25, $26, $27);
`;
msg.params = [
    p.station_id, p.timestamp, p.seq, p.interval_seconds,
    p.data.vehicles.motorbike, p.data.vehicles.car, p.data.vehicles.truck, p.data.vehicles.bus,
    p.data.vehicles.bicycle, p.data.vehicles.unknown, p.data.total,
    p.data.direction.inbound, p.data.direction.outbound,
    p.data.avg_confidence, p.data.min_confidence, p.data.detections_raw,
    p.data.detections_filtered, p.data.lighting_condition,
    p.status.cpu_temp_c, p.status.enclosure_temp_c, p.status.input_voltage_v, p.status.signal_rssi_dbm,
    p.status.signal_quality_pct, p.status.free_memory_kb, p.status.disk_usage_pct, p.status.fps, p.status.inference_ms
];
return msg;