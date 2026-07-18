var p = msg.payload;
if (!p || !p.hardware) {
    return null;
}
msg.query = `INSERT INTO hardware_metrics (
    station_id, recorded_at, uptime_seconds, cpu_temp_c,
    enclosure_temp_c, input_voltage_v, signal_rssi_dbm,
    signal_quality_pct, free_memory_kb, disk_usage_pct, fps,
    inference_ms, cpu_count, cpu_core0_pct, cpu_core1_pct,
    cpu_core2_pct, cpu_core3_pct, watchdog_luckfox_ok, watchdog_esp32_ok,
    camera_status, last_reboot_reason
) VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21)`;
msg.params = [p.station_id, p.timestamp, p.uptime_seconds, p.hardware.cpu_temp_c, p.hardware.enclosure_temp_c, p.hardware.input_voltage_v, p.hardware.signal_rssi_dbm, p.hardware.signal_quality_pct, p.hardware.free_memory_kb, p.hardware.disk_usage_pct, p.hardware.fps, p.hardware.inference_ms, p.hardware.cpu_count, p.hardware.cpu_core0_pct, p.hardware.cpu_core1_pct, p.hardware.cpu_core2_pct, p.hardware.cpu_core3_pct, p.watchdog.luckfox_ok, p.watchdog.esp32_ok, p.camera_status, p.last_reboot_reason];
return msg;