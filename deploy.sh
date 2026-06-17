#!/bin/bash
# Script triển khai tự động SHTP Traffic Server

echo "=== SHTP Traffic Server Deployment ==="

# 1. Kiểm tra Docker
if ! command -v docker &> /dev/null
then
    echo "[!] Docker chưa được cài đặt. Vui lòng cài Docker và Docker Compose."
    exit 1
fi

# 2. Cấp quyền cho thư mục (Tránh lỗi Access Denied trên Linux)
echo "[*] Thiết lập quyền thư mục..."
mkdir -p mosquitto/data logs/mosquitto logs/nodered media nodered
chmod -R 777 mosquitto/data
chmod -R 777 logs/mosquitto
chmod -R 777 logs/nodered
chmod -R 777 media
chmod -R 777 nodered

# 3. Chạy hệ thống bằng Docker Compose
echo "[*] Khởi động các dịch vụ (Mosquitto, Postgres, Node-RED, Grafana)..."
docker compose up -d

echo "[*] Đang chờ 10s để Postgres và Node-RED khởi tạo..."
sleep 10

# 4. In ra trạng thái
echo "=== TRẠNG THÁI HỆ THỐNG ==="
docker compose ps

echo "======================================"
echo "Triển khai thành công!"
echo "Truy cập Grafana: http://<IP>:3000 (admin / GrafanaShtp2026!)"
echo "Truy cập Node-RED: http://<IP>:1880"
echo "MQTT Broker đang chạy ở cổng 1883"
echo "======================================"
