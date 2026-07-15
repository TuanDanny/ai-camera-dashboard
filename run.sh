#!/bin/bash
echo "Starting SHTP Traffic Server..."

# Resolve paths relative to this script's own location, not the caller's cwd
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

if [ ! -f ".env" ]; then
    echo "[INFO] .env file not found. Creating from .env.example..."
    cp .env.example .env
    echo "[WARN] .env still has placeholder values - edit it with real credentials before relying on this deploy."
else
    echo "[INFO] .env file exists."
fi

echo "[INFO] Setting up directory permissions..."
mkdir -p postgres/data grafana/data mosquitto/data mosquitto/log
chmod -R 777 grafana/data 2>/dev/null || true
chmod -R 777 mosquitto/data 2>/dev/null || true
chmod -R 777 mosquitto/log 2>/dev/null || true

if [ ! -f "mosquitto/passwd" ]; then
    echo "[INFO] mosquitto/passwd file not found. Creating from passwd.example..."
    cp mosquitto/passwd.example mosquitto/passwd
fi

if [ ! -f "ai-worker/config.yaml" ]; then
    echo "[INFO] ai-worker/config.yaml not found. Creating from config.yaml.example..."
    cp ai-worker/config.yaml.example ai-worker/config.yaml
    echo "[WARN] ai-worker/config.yaml still has placeholder values - edit mqtt_password and streams before running ai-worker."
fi

if [ ! -f "edge-rpi/config.yaml" ]; then
    echo "[INFO] edge-rpi/config.yaml not found. Creating from config.yaml.example..."
    cp edge-rpi/config.yaml.example edge-rpi/config.yaml
    echo "[WARN] edge-rpi/config.yaml still has placeholder values - edit mqtt password and camera url before running edge_agent.py."
fi

echo "[INFO] Generating nodered/flows.json from generate_flows.py..."
set -a
source .env
set +a
python3 generate_flows.py

echo "[INFO] Launching Docker containers..."
sudo docker compose up -d

echo "[INFO] Waiting a few seconds for Mosquitto/Postgres to settle before starting the edge/AI processes..."
sleep 5

PROCESSES_STARTED=false
AI_WORKER_VENV="$DIR/ai-worker/.venv/bin/python3"
if [ ! -x "$AI_WORKER_VENV" ]; then
    echo ""
    echo "[WARN] ai-worker/.venv not found - skipping edge_agent.py and main.py."
    echo "        Set it up once with:"
    echo "          cd '$DIR/ai-worker' && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    echo "        Then run this script again."
else
    TERMINAL=""
    for t in x-terminal-emulator lxterminal xterm; do
        if command -v "$t" >/dev/null 2>&1; then
            TERMINAL="$t"
            break
        fi
    done

    if [ -n "$DISPLAY" ] && [ -n "$TERMINAL" ]; then
        echo "[INFO] Opening edge_agent.py and ai-worker/main.py in their own terminal windows ($TERMINAL)..."
        "$TERMINAL" -e bash -c "cd '$DIR/edge-rpi' && '$AI_WORKER_VENV' -u edge_agent.py; echo; echo '[edge_agent.py stopped]'; exec bash" &
        sleep 1
        "$TERMINAL" -e bash -c "cd '$DIR/ai-worker' && '$AI_WORKER_VENV' -u main.py; echo; echo '[main.py stopped]'; exec bash" &
    else
        # Note: the shared logs/ directory is owned by the docker containers
        # (root), not this user, so these host-side process logs live next
        # to their own scripts instead.
        EDGE_LOG="$DIR/edge-rpi/edge_agent.log"
        AI_LOG="$DIR/ai-worker/ai_worker.log"
        echo "[INFO] No graphical display detected (running headless/over SSH) - starting edge_agent.py and main.py in the background instead."
        echo "       Logs: $EDGE_LOG and $AI_LOG"
        (cd "$DIR/edge-rpi" && nohup "$AI_WORKER_VENV" -u edge_agent.py > "$EDGE_LOG" 2>&1 &)
        (cd "$DIR/ai-worker" && nohup "$AI_WORKER_VENV" -u main.py > "$AI_LOG" 2>&1 &)
        echo "       Tail them with: tail -f '$EDGE_LOG' '$AI_LOG'"
    fi
    PROCESSES_STARTED=true
fi

echo ""
echo "========================================================="
echo " SHTP TRAFFIC SERVER IS RUNNING!"
echo "========================================================="
echo " - Grafana Dashboard: http://localhost:3000 (see .env for admin login)"
echo " - Node-RED Flow:     http://localhost:1880"
echo " - MQTT Broker:       localhost:1883"
echo "========================================================="

if [ "$PROCESSES_STARTED" = true ]; then
    echo ""
    read -p "Ban co muon mo view_stream.py de xem truc tiep stream dang duoc AI xu ly khong? (y/N): " SHOW_STREAM
    if [[ "$SHOW_STREAM" =~ ^[Yy]$ ]]; then
        VIEW_VENV="$DIR/ai-worker/.venv-view/bin/python3"
        if [ -z "$DISPLAY" ]; then
            echo "[WARN] Khong phat hien man hinh do hoa (bien DISPLAY trong) - view_stream.py can giao dien GUI de hien cua so video, khong mo duoc qua SSH thuan. Bo qua."
        elif [ ! -x "$VIEW_VENV" ]; then
            echo "[WARN] Khong tim thay $VIEW_VENV - can venv rieng co opencv GUI cho view_stream.py. Cai 1 lan bang:"
            echo "          cd '$DIR/ai-worker' && python3 -m venv .venv-view && .venv-view/bin/pip install ultralytics opencv-python ncnn pyyaml"
        else
            echo "[INFO] Doi vai giay de stream on dinh truoc khi mo cua so xem..."
            sleep 3
            echo "[INFO] Nhan Q hoac ESC tren cua so video de dong va tiep tuc."
            (cd "$DIR/ai-worker" && "$VIEW_VENV" view_stream.py)
        fi
    fi
fi
