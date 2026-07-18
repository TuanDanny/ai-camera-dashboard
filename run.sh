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

EDGE_CONFIG="$DIR/edge-rpi/config.yaml"

get_camera_field() {
    grep -A 9 "^camera:" "$EDGE_CONFIG" | grep "^  $1:" | head -n1 | cut -d':' -f2- | sed 's/^ *//;s/ *$//'
}

set_camera_field() {
    # Only touches lines inside the camera: block (up to the next top-level key)
    sed -i "/^camera:/,/^[a-zA-Z]/ s|^\(  $1:\).*|\1 $2|" "$EDGE_CONFIG"
}

echo ""
echo "[SETUP] Chon nguon camera cho tram nay:"
echo "  1) Raspberry Pi Camera Module (CSI)"
echo "  2) IP Webcam (dien thoai Android, app IP Webcam)"
echo "  3) USB Webcam (camera cam qua cong USB, vd /dev/video0)"
CURRENT_CAM_TYPE=$(get_camera_field "type")
read -p "Nhap 1, 2 hoac 3 (Enter de giu nguyen '${CURRENT_CAM_TYPE}'): " CAMERA_CHOICE

case "$CAMERA_CHOICE" in
    1)
        set_camera_field "type" "csi"
        echo "[INFO] Da dat camera.type = csi trong edge-rpi/config.yaml."
        CSI_TOOL=$(command -v rpicam-hello || command -v libcamera-hello)
        if [ -n "$CSI_TOOL" ]; then
            if timeout 5 "$CSI_TOOL" --list-cameras 2>&1 | grep -qi "no cameras available"; then
                echo "[WARN] Chua phat hien camera CSI nao cam vao - kiem tra lai day/ket noi. Cau hinh van duoc luu, ban co the cam camera sau va chay lai."
            else
                echo "[INFO] Da phat hien camera CSI."
            fi
        fi
        ;;
    2)
        set_camera_field "type" "ip_webcam"
        CURRENT_URL=$(get_camera_field "url")
        ATTEMPT=0
        while true; do
            read -p "Nhap URL IP Webcam (Enter de giu '${CURRENT_URL}'): " NEW_URL
            NEW_URL="${NEW_URL:-$CURRENT_URL}"
            echo "[INFO] Dang kiem tra ket noi toi $NEW_URL ..."
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 5 "$NEW_URL" 2>/dev/null)
            if [[ "$HTTP_CODE" =~ ^2 ]]; then
                echo "[INFO] Ket noi thanh cong (HTTP $HTTP_CODE)."
                set_camera_field "url" "$NEW_URL"
                break
            fi

            ATTEMPT=$((ATTEMPT + 1))
            echo "[WARN] Khong ket noi duoc toi $NEW_URL (HTTP: ${HTTP_CODE:-timeout})."
            CURRENT_URL="$NEW_URL"
            if [ "$ATTEMPT" -ge 3 ]; then
                read -p "Da thu $ATTEMPT lan khong duoc. Van dung URL nay va tiep tuc? (y/N): " FORCE
                if [[ "$FORCE" =~ ^[Yy]$ ]]; then
                    set_camera_field "url" "$NEW_URL"
                    break
                fi
                ATTEMPT=0
            fi
        done
        ;;
    3)
        set_camera_field "type" "webcam"
        CURRENT_DEVICE=$(get_camera_field "device")
        echo "[INFO] Cac thiet bi video dang cam vao:"
        ls /dev/video* 2>/dev/null || echo "  (khong tim thay /dev/video* nao)"
        read -p "Nhap duong dan device (Enter de giu '${CURRENT_DEVICE}'): " NEW_DEVICE
        NEW_DEVICE="${NEW_DEVICE:-$CURRENT_DEVICE}"
        if [ -e "$NEW_DEVICE" ]; then
            echo "[INFO] Da tim thay $NEW_DEVICE."
        else
            echo "[WARN] Khong tim thay $NEW_DEVICE - kiem tra lai day cam USB. Cau hinh van duoc luu."
        fi
        set_camera_field "device" "$NEW_DEVICE"
        ;;
    *)
        echo "[INFO] Giu nguyen cau hinh camera hien tai (type=${CURRENT_CAM_TYPE})."
        ;;
esac

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
