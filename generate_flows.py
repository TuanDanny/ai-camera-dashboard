import json

def generate_flows():
    flows = [
        {
            "id": "tab1",
            "type": "tab",
            "label": "SHTP Traffic Pipeline",
            "disabled": False,
            "info": ""
        },
        {
            "id": "mqtt_broker",
            "type": "mqtt-broker",
            "name": "Local Mosquitto",
            "broker": "mosquitto",
            "port": "1883",
            "clientid": "nodered_internal",
            "autoConnect": True,
            "usetls": False,
            "protocolVersion": "4",
            "keepalive": "60",
            "cleansession": True,
            "birthTopic": "traffic/server/status",
            "birthQos": "1",
            "birthPayload": "online",
            "closeTopic": "traffic/server/status",
            "closeQos": "1",
            "closePayload": "offline",
            "willTopic": "traffic/server/status",
            "willQos": "1",
            "willPayload": "offline"
        },
        {
            "id": "pg_db",
            "type": "postgreSQLConfig",
            "name": "Postgres SHTP",
            "host": "postgres",
            "hostFieldType": "str",
            "port": "5432",
            "portFieldType": "num",
            "database": "shtp_traffic",
            "databaseFieldType": "str",
            "ssl": "false",
            "sslFieldType": "bool"
        },
        {
            "id": "telegram_bot",
            "type": "telegram bot",
            "botname": "SHTP_Alert_Bot",
            "usernames": "",
            "chatids": "",
            "baseapiurl": "",
            "updatemode": "polling",
            "pollinterval": "300",
            "usesocks": False,
            "sockshost": "",
            "socksport": "6667",
            "socksusername": "anonymous",
            "sockspassword": "",
            "bothost": "",
            "botpath": "",
            "localbotport": "8443",
            "publicbotport": "8443",
            "privatekey": "",
            "certificate": "",
            "useselfsignedcertificate": False,
            "sslterminated": False,
            "verboselogging": False
        }
    ]

    y_pos = 100

    def add_pipeline(name, topic, dedup, parse_func, wires_to=None):
        nonlocal y_pos
        mqtt_id = f"mqtt_in_{name}"
        func_id = f"func_sql_{name}"
        pg_id = f"pg_insert_{name}"
        dedup_id = f"dedup_{name}"

        flows.append({
            "id": mqtt_id,
            "type": "mqtt in",
            "z": "tab1",
            "name": f"Sub {name.capitalize()}",
            "topic": topic,
            "qos": "1",
            "datatype": "json",
            "broker": "mqtt_broker",
            "x": 150,
            "y": y_pos,
            "wires": [[dedup_id if dedup else func_id]]
        })

        if dedup:
            flows.append({
                "id": dedup_id,
                "type": "function",
                "z": "tab1",
                "name": "Dedup QoS 1",
                "func": "var cache = context.get('dedup_cache') || {};\nvar p = msg.payload;\nvar key = p.station_id + '_' + (p.seq || p.timestamp);\nvar now = Date.now();\nfor (var k in cache) {\n    if (now - cache[k] > 300000) delete cache[k];\n}\nif (cache[key]) { return null; }\ncache[key] = now;\ncontext.set('dedup_cache', cache);\nreturn msg;",
                "outputs": 1,
                "x": 350,
                "y": y_pos,
                "wires": [[func_id]]
            })

        wires_out = [[pg_id]]
        if wires_to:
            wires_out[0].append(wires_to)

        flows.append({
            "id": func_id,
            "type": "function",
            "z": "tab1",
            "name": f"Format {name} SQL",
            "func": parse_func,
            "outputs": 1,
            "x": 550 if dedup else 350,
            "y": y_pos,
            "wires": wires_out
        })

        flows.append({
            "id": pg_id,
            "type": "postgresql",
            "z": "tab1",
            "postgreSQLConfig": "pg_db",
            "name": f"Insert {name.capitalize()}",
            "output": False,
            "outputs": 0,
            "x": 750,
            "y": y_pos,
            "wires": []
        })

        y_pos += 80

    # 1. Telemetry
    telemetry_sql = """var p = msg.payload;
msg.query = `INSERT INTO traffic_records (
    station_id, recorded_at, seq, interval_seconds, 
    motorbike_count, car_count, truck_count, bus_count, 
    bicycle_count, unknown_count, total_count, 
    avg_confidence, min_confidence, detections_raw, 
    detections_filtered, lighting_condition
) VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)`;
msg.params = [p.station_id, p.timestamp, p.seq, p.interval_seconds, p.data.vehicles.motorbike, p.data.vehicles.car, p.data.vehicles.truck, p.data.vehicles.bus, p.data.vehicles.bicycle, p.data.vehicles.unknown, p.data.total, p.data.avg_confidence, p.data.min_confidence, p.data.detections_raw, p.data.detections_filtered, p.data.lighting_condition];

msg.query2 = `INSERT INTO hardware_metrics (
    station_id, recorded_at, uptime_seconds, cpu_temp_c, 
    enclosure_temp_c, input_voltage_v, signal_rssi_dbm, 
    signal_quality_pct, free_memory_kb, disk_usage_pct, fps, 
    inference_ms, watchdog_luckfox_ok, watchdog_esp32_ok, 
    camera_status, last_reboot_reason
) VALUES ($1, to_timestamp($2), null, $3, $4, $5, $6, $7, $8, $9, $10, $11, null, null, null, null)`;
msg.params2 = [p.station_id, p.timestamp, p.status.cpu_temp_c, p.status.enclosure_temp_c, p.status.input_voltage_v, p.status.signal_rssi_dbm, p.status.signal_quality_pct, p.status.free_memory_kb, p.status.disk_usage_pct, p.status.fps, p.status.inference_ms];

// In Node-RED postgres node you can pass array of queries if needed, or we just insert traffic_records. 
// Actually for simplicity we will just do traffic_records here. Hardware metrics will be parsed by heartbeat.
return msg;"""
    # Wait, the plan says hardware metrics are in telemetry. 
    # Let's write them both. Node-RED postgres node supports msg.query. We can use pg-pool or just multiple nodes.
    # To keep it simple, let's just insert traffic_records here and I will add a second pg insert node for hardware in telemetry.
    telemetry_sql = """var p = msg.payload;
msg.query = `
    INSERT INTO traffic_records (
        station_id, recorded_at, seq, interval_seconds, 
        motorbike_count, car_count, truck_count, bus_count, 
        bicycle_count, unknown_count, total_count, 
        avg_confidence, min_confidence, detections_raw, 
        detections_filtered, lighting_condition
    ) VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16);
    
    INSERT INTO hardware_metrics (
        station_id, recorded_at, cpu_temp_c, enclosure_temp_c, 
        input_voltage_v, signal_rssi_dbm, signal_quality_pct, 
        free_memory_kb, disk_usage_pct, fps, inference_ms
    ) VALUES ($1, to_timestamp($2), $17, $18, $19, $20, $21, $22, $23, $24, $25);
`;
msg.params = [
    p.station_id, p.timestamp, p.seq, p.interval_seconds, 
    p.data.vehicles.motorbike, p.data.vehicles.car, p.data.vehicles.truck, p.data.vehicles.bus, 
    p.data.vehicles.bicycle, p.data.vehicles.unknown, p.data.total, 
    p.data.avg_confidence, p.data.min_confidence, p.data.detections_raw, 
    p.data.detections_filtered, p.data.lighting_condition,
    p.status.cpu_temp_c, p.status.enclosure_temp_c, p.status.input_voltage_v, p.status.signal_rssi_dbm, 
    p.status.signal_quality_pct, p.status.free_memory_kb, p.status.disk_usage_pct, p.status.fps, p.status.inference_ms
];
return msg;"""

    add_pipeline("telemetry", "traffic/station/+/telemetry", True, telemetry_sql)

    # 2. Heartbeat
    heartbeat_sql = """var p = msg.payload;
msg.query = `INSERT INTO hardware_metrics (
    station_id, recorded_at, uptime_seconds, cpu_temp_c, 
    enclosure_temp_c, input_voltage_v, signal_rssi_dbm, 
    signal_quality_pct, free_memory_kb, disk_usage_pct, fps, 
    inference_ms, watchdog_luckfox_ok, watchdog_esp32_ok, 
    camera_status, last_reboot_reason
) VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)`;
msg.params = [p.station_id, p.timestamp, p.uptime_seconds, p.hardware.cpu_temp_c, p.hardware.enclosure_temp_c, p.hardware.input_voltage_v, p.hardware.signal_rssi_dbm, p.hardware.signal_quality_pct, p.hardware.free_memory_kb, p.hardware.disk_usage_pct, p.hardware.fps, p.hardware.inference_ms, p.watchdog.luckfox_ok, p.watchdog.esp32_ok, p.camera_status, p.last_reboot_reason];
return msg;"""
    add_pipeline("heartbeat", "traffic/station/+/heartbeat", False, heartbeat_sql)

    # 3. Alert
    alert_sql = """var p = msg.payload;
msg.query = `INSERT INTO device_alerts (
    station_id, alert_at, severity, code, message, details
) VALUES ($1, to_timestamp($2), $3, $4, $5, $6)`;
msg.params = [p.station_id, p.timestamp, p.severity, p.code, p.message, JSON.stringify(p.details || {})];
// Chuẩn bị payload cho Telegram
if (p.severity === 'critical' || p.severity === 'warning') {
    msg.telegram_payload = {
        chatId: process.env.TELEGRAM_CHAT_ID,
        type: 'message',
        content: `🚨 **ALERT** 🚨\\nStation: ${p.station_id}\\nCode: ${p.code}\\nMessage: ${p.message}`
    };
}
return msg;"""
    add_pipeline("alert", "traffic/station/+/alert", False, alert_sql, "check_telegram")

    # Add Check Telegram node and Sender
    flows.append({
        "id": "check_telegram",
        "type": "switch",
        "z": "tab1",
        "name": "If Critical",
        "property": "telegram_payload",
        "propertyType": "msg",
        "rules": [{"t": "nnull"}],
        "checkall": "true",
        "repair": False,
        "outputs": 1,
        "x": 550,
        "y": y_pos - 30,
        "wires": [["telegram_sender"]]
    })
    
    flows.append({
        "id": "telegram_sender",
        "type": "telegram sender",
        "z": "tab1",
        "name": "Send Alert",
        "bot": "telegram_bot",
        "haserroroutput": False,
        "outputs": 1,
        "x": 750,
        "y": y_pos - 30,
        "wires": [[]]
    })

    # 4. Watchdog
    watchdog_sql = """var p = msg.payload;
msg.query = `INSERT INTO watchdog_events (
    station_id, event_at, event_type, reason, details, uptime_before_reset_s, reset_count_since_boot
) VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7)`;
msg.params = [p.station_id, p.timestamp, p.event, p.details.reason, JSON.stringify(p.details || {}), p.details.uptime_before_reset_s, p.details.reset_count_since_boot];
return msg;"""
    add_pipeline("watchdog", "traffic/station/+/watchdog", False, watchdog_sql)

    # 5. Network Quality
    network_sql = """var p = msg.payload;
msg.query = `INSERT INTO network_quality (
    station_id, recorded_at, operator, technology, band, rssi_dbm, rsrp_dbm, rsrq_db, sinr_db, latency_ms, packet_loss_pct, reconnect_count, bytes_sent, bytes_received, mqtt_reconnect_count
) VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)`;
msg.params = [p.station_id, p.timestamp, p.network.operator, p.network.technology, p.network.band, p.network.rssi_dbm, p.network.rsrp_dbm, p.network.rsrq_db, p.network.sinr_db, p.network.latency_ms, p.network.packet_loss_percent, p.network.reconnect_count, p.network.bytes_sent_total, p.network.bytes_received_total, p.network.mqtt_reconnect_count];
return msg;"""
    add_pipeline("network", "traffic/station/+/network_quality", False, network_sql)

    # 6. Snapshot
    snapshot_sql = """var p = msg.payload;
// Giải mã base64 và lưu file (Trong thực tế Node-RED sẽ dùng file node, ở đây ta chỉ lưu metadata)
msg.query = `INSERT INTO snapshots (
    station_id, captured_at, format, resolution, size_bytes, lighting_condition, file_path
) VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7)`;
var filename = `/media/${p.station_id}_${p.timestamp}.jpeg`;
msg.params = [p.station_id, p.timestamp, p.format, p.resolution, p.size_bytes, p.lighting_condition, filename];
return msg;"""
    add_pipeline("snapshot", "traffic/station/+/snapshot", False, snapshot_sql)

    # 7. Accuracy HTTP Endpoint
    y_pos += 40
    flows.append({
        "id": "http_accuracy_in",
        "type": "http in",
        "z": "tab1",
        "name": "POST /api/accuracy",
        "url": "/api/accuracy",
        "method": "post",
        "upload": False,
        "swaggerDoc": "",
        "x": 150,
        "y": y_pos,
        "wires": [["func_accuracy_sql"]]
    })

    flows.append({
        "id": "func_accuracy_sql",
        "type": "function",
        "z": "tab1",
        "name": "Format Accuracy SQL",
        "func": "var p = msg.payload;\nmsg.query = `INSERT INTO accuracy_evaluations (\n    station_id, eval_period_start, eval_period_end, evaluator_name, lighting_condition, auto_total, manual_total, accuracy_pct, false_positives, false_negatives, notes\n) VALUES ($1, to_timestamp($2), to_timestamp($3), $4, $5, $6, $7, $8, $9, $10, $11)`;\nmsg.params = [p.station_id, p.eval_start, p.eval_end, p.evaluator, p.lighting, p.auto_total, p.manual_total, p.accuracy_pct, p.false_positives, p.false_negatives, p.notes];\nreturn msg;",
        "outputs": 1,
        "x": 400,
        "y": y_pos,
        "wires": [["pg_insert_accuracy"]]
    })

    flows.append({
        "id": "pg_insert_accuracy",
        "type": "postgresql",
        "z": "tab1",
        "postgreSQLConfig": "pg_db",
        "name": "Insert Accuracy",
        "output": False,
        "outputs": 0,
        "x": 650,
        "y": y_pos,
        "wires": [["http_accuracy_out"]]
    })

    flows.append({
        "id": "http_accuracy_out",
        "type": "http response",
        "z": "tab1",
        "name": "200 OK",
        "statusCode": "200",
        "headers": {},
        "x": 850,
        "y": y_pos,
        "wires": []
    })

    # 8. Server Self-Monitoring Loop
    y_pos += 80
    flows.append({
        "id": "inject_self_check",
        "type": "inject",
        "z": "tab1",
        "name": "Check every 60s",
        "props": [{"p": "payload"}],
        "repeat": "60",
        "crontab": "",
        "once": False,
        "onceDelay": 0.1,
        "topic": "",
        "payload": "",
        "payloadType": "date",
        "x": 150,
        "y": y_pos,
        "wires": [["func_self_check"]]
    })

    flows.append({
        "id": "func_self_check",
        "type": "function",
        "z": "tab1",
        "name": "Query",
        "func": "msg.query = 'SELECT 1;'; return msg;",
        "outputs": 1,
        "x": 350,
        "y": y_pos,
        "wires": [["pg_self_check"]]
    })

    flows.append({
        "id": "pg_self_check",
        "type": "postgresql",
        "z": "tab1",
        "postgreSQLConfig": "pg_db",
        "name": "Test DB Connection",
        "output": True,
        "outputs": 1,
        "x": 550,
        "y": y_pos,
        "wires": [["mqtt_self_check"]]
    })

    flows.append({
        "id": "mqtt_self_check",
        "type": "mqtt out",
        "z": "tab1",
        "name": "Test MQTT",
        "topic": "traffic/server/health",
        "qos": "0",
        "retain": "",
        "respTopic": "",
        "contentType": "",
        "userProps": "",
        "correl": "",
        "expiry": "",
        "broker": "mqtt_broker",
        "x": 750,
        "y": y_pos,
        "wires": []
    })

    with open("nodered/flows.json", "w", encoding='utf-8') as f:
        json.dump(flows, f, indent=4)
        print("Generated nodered/flows.json successfully!")

if __name__ == "__main__":
    generate_flows()
