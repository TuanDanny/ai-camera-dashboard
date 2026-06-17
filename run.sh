#!/bin/bash
echo "Starting SHTP Traffic Server..."

if [ ! -f ".env" ]; then
    echo "[INFO] .env file not found. Creating from .env.example..."
    cp .env.example .env
else
    echo "[INFO] .env file exists."
fi

echo "[INFO] Setting up directory permissions..."
mkdir -p postgres/data grafana/data mosquitto/data mosquitto/log
chmod -R 777 grafana/data
chmod -R 777 mosquitto/data
chmod -R 777 mosquitto/log

echo "[INFO] Launching Docker containers..."
docker compose up -d

echo ""
echo "========================================================="
echo " SHTP TRAFFIC SERVER IS RUNNING!"
echo "========================================================="
echo " - Grafana Dashboard: http://localhost:3000 (admin / 123456)"
echo " - Node-RED Flow:     http://localhost:1880"
echo " - MQTT Broker:       localhost:1883"
echo "========================================================="
