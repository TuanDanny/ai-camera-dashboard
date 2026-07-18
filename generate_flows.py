import json
import os

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodered", "flow_templates")

def _load_template(name):
    # Doc dung 1 lan tai import - moi function-node trong Node-RED can 1 chuoi
    # JS rieng (khong dung chung), nhung noi dung file .js tren disk deu la
    # nguon "that", khong phai duplicate.
    with open(os.path.join(TEMPLATES_DIR, name), "r", encoding="utf-8") as f:
        return f.read().rstrip("\n")

def generate_flows():
    # Read from the real environment (docker-compose sources .env into this
    # container/process) rather than hardcoding a secret in this file, since
    # this script and its output (nodered/flows.json) are version-controlled.
    mqtt_nodered_user = os.environ.get("MQTT_NODERED_USER", "nodered_service")
    mqtt_nodered_password = os.environ.get("MQTT_NODERED_PASSWORD", "changeme")

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
            "willPayload": "offline",
            "credentials": {
                "user": mqtt_nodered_user,
                "password": mqtt_nodered_password
            }
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
            "sslFieldType": "bool",
            "user": "POSTGRES_USER",
            "userFieldType": "env",
            "password": "POSTGRES_PASSWORD",
            "passwordFieldType": "env"
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
            "verboselogging": False,
            "credentials": {
                "token": "${TELEGRAM_BOT_TOKEN}"
            }
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
                "func": _load_template("dedup.js"),
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
    # NOTE: node-red-contrib-postgresql runs client.query(query, params) whenever msg.params
    # is non-empty, which forces Postgres' extended/prepared-statement protocol. That protocol
    # rejects a query string containing more than one semicolon-separated command ("cannot
    # insert multiple commands into a prepared statement"), so the two INSERTs in
    # telemetry_insert.js are combined into a single statement via a data-modifying CTE
    # instead of being two separate ";"-terminated statements.
    telemetry_sql = _load_template("telemetry_insert.js")
    add_pipeline("telemetry", "traffic/station/+/telemetry", True, telemetry_sql)

    # 2. Heartbeat
    heartbeat_sql = _load_template("heartbeat_insert.js")
    add_pipeline("heartbeat", "traffic/station/+/heartbeat", False, heartbeat_sql)

    # 3. Alert
    alert_sql = _load_template("alert_insert.js")
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
    watchdog_sql = _load_template("watchdog_insert.js")
    add_pipeline("watchdog", "traffic/station/+/watchdog", False, watchdog_sql)

    # 5. Network Quality
    network_sql = _load_template("network_insert.js")
    add_pipeline("network", "traffic/station/+/network_quality", False, network_sql)

    # 6. Snapshot
    snapshot_sql = _load_template("snapshot_insert.js")
    add_pipeline("snapshot", "traffic/station/+/snapshot", False, snapshot_sql)

    # 6b. AI Worker fast status pulse - fps/inference_ms only, published every
    # publish.status_interval_s (default 3s) by ai-worker/main.py, completely
    # independent of the vehicle-counting window (publish.interval_s, 10s) so
    # a faster refresh here never affects counting accuracy.
    ai_status_sql = _load_template("ai_status_insert.js")
    add_pipeline("ai_status", "traffic/station/+/ai_status", False, ai_status_sql)

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
        "func": _load_template("accuracy_insert.js"),
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
