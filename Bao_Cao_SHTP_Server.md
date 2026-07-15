# Bằng Chứng Triển Khai 100% (Audit Report)

## 1. Cấu trúc Thư mục và File Đã Tạo
```text
SHTP/
    .env
    .gitignore
    audit.py
    CONTRACT_CHANGELOG.md
    docker-compose.yml
    generate_flows.py
    Plan.pdf
    Server_Plan.md
    backups/
    ai-worker/
        config.yaml
        main.py
        vehicle_classifier.py
        direction_counter.py
        requirements.txt
        tracker/
            traffic_bytetrack.yaml
        test_vehicle_classifier.py
        test_direction_counter.py
        local_test/
            run_phase4_test.py
            test_phase5_retry.py
    edge-rpi/
        config.yaml
        edge_agent.py
        start_stream.sh
    grafana/
        dashboards/
            accuracy_report.json
            hardware_health.json
            network_quality.json
            traffic_overview.json
        provisioning/
            dashboards/
                dashboard.yml
            datasources/
                postgres.yml
    logs/
        mosquitto/
        mqtt_raw/
        nodered/
        postgres/
        seq_gaps/
        watchdog/
    media/
    mosquitto/
        acl.conf
        mosquitto.conf
        passwd
    nodered/
        flows.json
        package.json
        settings.js
    postgres/
        init.sql
    simulator/
        edge_simulator.py
        requirements.txt
```

## 2. Kiểm tra Cú pháp (Syntax Check)
| File | Loại | Trạng thái |
|:---|:---|:---|
| accuracy_report.json | JSON | PASS |
| hardware_health.json | JSON | PASS |
| network_quality.json | JSON | PASS |
| traffic_overview.json | JSON | PASS |
| flows.json | JSON | PASS |
| package.json | JSON | PASS |
| docker-compose.yml | YAML | PASS (Basic Read) |
| dashboard.yml | YAML | PASS (Basic Read) |
| postgres.yml | YAML | PASS (Basic Read) |
| ai-worker/main.py | Python (py_compile) | PASS |
| ai-worker/vehicle_classifier.py | Python (py_compile) | PASS |
| ai-worker/direction_counter.py | Python (py_compile) | PASS |
| ai-worker/test_vehicle_classifier.py | Python (py_compile) | PASS |
| ai-worker/test_direction_counter.py | Python (py_compile) | PASS |
| ai-worker/local_test/run_phase4_test.py | Python (py_compile) | PASS |
| ai-worker/local_test/test_phase5_retry.py | Python (py_compile) | PASS |
| ai-worker/config.yaml | YAML (yaml.safe_load) | PASS |
| ai-worker/tracker/traffic_bytetrack.yaml | YAML (yaml.safe_load) | PASS |
| edge-rpi/edge_agent.py | Python (py_compile) | PASS |
| edge-rpi/config.yaml | YAML (yaml.safe_load) | PASS |
| edge-rpi/start_stream.sh | Bash (bash -n) | PASS |

## 3. Đối chiếu Deliverables theo Server_Plan.md
- **Hạ tầng**: docker-compose.yml (Đã tạo)
- **MQTT Broker**: mosquitto.conf, acl.conf, passwd (Đã tạo) — bổ sung user `ai_worker` riêng, tách khỏi `nodered_service` (least-privilege, chỉ publish telemetry)
- **Database**: init.sql với 9 bảng và seed data (Đã tạo)
- **ETL Pipeline**: nodered/flows.json xử lý 6 luồng và API (Đã tạo)
- **Visualization**: 4 Grafana Dashboards (Đã tạo, đã verify cả 4 dashboard kết nối/query đúng schema thật)
- **Công cụ Test**: simulator/edge_simulator.py (Đã tạo)
- **Tài liệu**: CONTRACT_CHANGELOG.md (Đã tạo)
- **AI Worker** (`ai-worker/`): YOLOv8 + `VehicleClassifier` (bỏ phiếu/khóa class chống nhảy nhãn giữa các frame, port và thích nghi từ `yolo-cam/`) + `DirectionCounter` (đếm hướng vào/ra qua đường ảo line-crossing) (Đã tạo, đã verify chạy thật với camera điện thoại qua MediaMTX)
- **Edge Streaming** (`edge-rpi/`): `edge_agent.py` + `start_stream.sh` hỗ trợ 3 nguồn camera — `csi` (module Pi thật), `webcam` (USB), `ip_webcam` (app IP Webcam trên điện thoại, dùng thay thế khi chưa có camera thật) (Đã tạo, đã verify end-to-end)

### Các bug hạ tầng phát hiện và đã sửa trong quá trình deploy thật
- Node-RED chưa từng có credentials kết nối MQTT/Postgres từ lúc deploy ban đầu (không lỗi ngay do gói tin QoS 0/pool lazy-connect nên dễ bị bỏ sót) — đã sửa qua `generate_flows.py` + deploy lại qua Admin API.
- Câu SQL insert telemetry gộp 2 lệnh INSERT trong 1 statement có `params` — Postgres từ chối vì bắt buộc dùng prepared-statement protocol cho statement nhiều lệnh — đã sửa bằng CTE gộp 1 statement duy nhất.
- `edge_agent.py` gửi heartbeat thiếu field `watchdog` (Node-RED luôn báo lỗi `TypeError`) và chưa từng publish topic `network_quality` riêng (chỉ nhét trong heartbeat, sai thiết kế) — đã sửa để khớp đúng hợp đồng dữ liệu của Node-RED.
