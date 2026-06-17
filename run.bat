@echo off
echo Starting SHTP Traffic Server...

IF NOT EXIST ".env" (
    echo [INFO] .env file not found. Creating from .env.example...
    copy .env.example .env
) ELSE (
    echo [INFO] .env file exists.
)

echo [INFO] Creating necessary directories...
mkdir postgres\data 2>nul
mkdir grafana\data 2>nul
mkdir mosquitto\data 2>nul
mkdir mosquitto\log 2>nul

IF NOT EXIST "mosquitto\passwd" (
    echo [INFO] mosquitto/passwd file not found. Creating from passwd.example...
    copy mosquitto\passwd.example mosquitto\passwd
)

echo [INFO] Launching Docker containers...
docker compose up -d

echo.
echo =========================================================
echo  SHTP TRAFFIC SERVER IS RUNNING!
echo =========================================================
echo  - Grafana Dashboard: http://localhost:3000 (admin / 123456)
echo  - Node-RED Flow:     http://localhost:1880
echo  - MQTT Broker:       localhost:1883
echo =========================================================
pause
