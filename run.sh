#!/bin/bash
echo "Starting SHTP Traffic Server..."

# Resolve paths relative to this script's own location, not the caller's cwd
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Kiem tra tien trinh cu con sot lai TRUOC khi lam gi khac - tung gap truong
# hop 2 bo edge_agent.py/main.py chay chung (1 bo cu quen tat + 1 bo run.sh
# vua mo) tranh nhau CPU va /dev/video0, gay FPS tut manh ma khong ro nguyen
# nhan. Anchor "$" o cuoi pattern de chi khop dong lenh THAT SU ket thuc
# bang "-u edge_agent.py"/"-u main.py" (chay qua .venv nay), tranh nham voi
# process khac (vd shell wrapper) chi tinh co chua chuoi do o giua dong lenh.
AI_WORKER_VENV="$DIR/ai-worker/.venv/bin/python3"
echo ""
echo "[CHECK] Dang kiem tra tien trinh cu con sot lai tu lan chay truoc..."
STRAY_PY=$(pgrep -f "\.venv/bin/python3 -u (edge_agent|main)\.py\$" 2>/dev/null)
STRAY_FFMPEG=$(pgrep -f "ffmpeg .*-rtsp_transport tcp rtsp://" 2>/dev/null)
STRAY_ALL=$(printf '%s\n%s\n' "$STRAY_PY" "$STRAY_FFMPEG" | grep -v '^$' | sort -u)

if [ -n "$STRAY_ALL" ]; then
    echo "[WARN] Phat hien tien trinh cu dang chay tu truoc - neu mo them ban moi se"
    echo "       tranh chap CPU/camera voi ban nay (day chinh la nguyen nhan tung gay"
    echo "       FPS tut khi 2 bo main.py/edge_agent.py vo tinh chay chung mot luc):"
    ps -o pid,etime,cmd -p "$(echo "$STRAY_ALL" | tr '\n' ',' | sed 's/,$//')" 2>/dev/null
    read -p "Tat cac tien trinh nay truoc khi tiep tuc? (Y/n): " KILL_STRAY
    if [[ ! "$KILL_STRAY" =~ ^[Nn]$ ]]; then
        echo "$STRAY_ALL" | xargs -r kill -9
        echo "[INFO] Da tat tien trinh cu. Doi 2 giay de giai phong camera..."
        sleep 2
    else
        echo "[WARN] Giu nguyen - co the gay tranh chap CPU/camera voi tien trinh sap mo."
    fi
else
    echo "[INFO] Khong co tien trinh cu nao con sot lai - an toan de tiep tuc."
fi

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
bash "$DIR/scripts/setup_camera.sh" "$EDGE_CONFIG"

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

# Cac port tren da duoc docker-compose.yml publish ra 0.0.0.0 san (khong
# gioi han 127.0.0.1), nen may khac CUNG mang LAN/WiFi voi Pi nay da truy
# cap duoc ngay tu truoc (da kiem chung bang ss -tlnp) - chi can biet dung
# IP LAN thay vi localhost. In them o day cho tien, khong phai bat/mo them
# gi ca. LAN_IP lay IP dau tien tu hostname -I (thuong la NIC that, cac IP
# docker bridge 172.17.x/172.18.x duoc gan sau nen nam phia sau trong danh
# sach).
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -n "$LAN_IP" ]; then
    echo ""
    echo " May khac cung mang LAN/WiFi truy cap qua IP: $LAN_IP"
    echo " - Grafana Dashboard: http://$LAN_IP:3000"
    echo " - Node-RED Flow:     http://$LAN_IP:1880"
    echo " - MQTT Broker:       $LAN_IP:1883 (van can user/pass hop le trong mosquitto/passwd)"
fi
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
            echo "          cd '$DIR/ai-worker' && python3 -m venv .venv-view && .venv-view/bin/pip install opencv-python pyyaml"
            echo "        Mac dinh script nay dung 'view_stream.py --backend relay' (chi nhan lai ket qua"
            echo "        da xu ly san tu main.py qua socket, khong tu chay YOLO rieng nua) - chi can 2 goi"
            echo "        tren la du. Neu muon tu mo NPU rieng de debug ('view_stream.py --backend hailo',"
            echo "        chi dung duoc khi main.py KHONG chay), .venv-view can them wiring toi"
            echo "        hailo_platform/picamera2 cua he thong (file .pth) va cai them lap/cython_bbox/scipy."
        else
            echo "[INFO] Doi vai giay de stream on dinh truoc khi mo cua so xem..."
            sleep 3
            echo "[INFO] Nhan Q hoac ESC tren cua so video de dong va tiep tuc."
            # main.py da chay san va LUON phat lai ket qua da xu ly (frame +
            # box + fps) qua socket noi bo, bat ke dang dung backend cpu hay
            # hailo (xem FrameBroadcaster trong main.py). Dung
            # "--backend relay" de view_stream.py chi nhan lai ket qua co
            # san nay ma hien thi - KHONG tu chay YOLO rieng (nhe hon backend
            # cpu cu) va KHONG dung toi NPU nen khong bao gio dung do
            # HAILO_OUT_OF_PHYSICAL_DEVICES (2 tien trinh OS rieng biet khong
            # the cung mo 1 NPU vat ly). Muon xem qua chinh NPU (nang hon,
            # chi de debug rieng) thi phai tat main.py truoc roi tu chay
            # "view_stream.py --backend hailo" tay.
            (cd "$DIR/ai-worker" && "$VIEW_VENV" view_stream.py --backend relay)
        fi
    fi
fi
