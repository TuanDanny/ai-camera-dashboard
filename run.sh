#!/bin/bash
echo "Starting SHTP Traffic Server..."

# Resolve paths relative to this script's own location, not the caller's cwd
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Khoa chong chay-chong-chay: da gap thuc te 1 lan systemd tu dong chay
# run.sh luc boot, nguoi dung khong biet lai tu tay chay them 1 lan nua -
# 2 "docker compose up -d" dung luc dam vao nhau, tao container trung ten
# roi ket ("Created", khong len duoc "Up"). flock -n (khong doi) tren 1 fd
# rieng: neu dang co ban khac giu khoa, thoat ngay va bao ro thay vi de 2
# tien trinh dua nhau goi docker/tao process.
exec 200>"$DIR/.run.lock"
if ! flock -n 200; then
    echo "[ERROR] run.sh dang duoc 1 tien trinh khac chay roi (co the la systemd" >&2
    echo "        tu dong luc boot) - thoat de tranh dam vao nhau (docker compose/" >&2
    echo "        edge_agent.py/main.py chay trung). Kiem tra bang:" >&2
    echo "          systemctl status shtp-traffic-server.service" >&2
    echo "        Neu chac chan khong co ban nao khac dang chay, xoa file khoa:" >&2
    echo "          rm '$DIR/.run.lock'" >&2
    exit 1
fi

# Kiem tra tien trinh cu con sot lai TRUOC khi lam gi khac - tung gap truong
# hop 2 bo edge_agent.py/main.py chay chung (1 bo cu quen tat + 1 bo run.sh
# vua mo) tranh nhau CPU va /dev/video0, gay FPS tut manh ma khong ro nguyen
# nhan. Anchor "$" o cuoi pattern de chi khop dong lenh THAT SU ket thuc
# bang "-u edge_agent.py"/"-u main.py" (chay qua .venv nay), tranh nham voi
# process khac (vd shell wrapper) chi tinh co chua chuoi do o giua dong lenh.
AI_WORKER_VENV="$DIR/ai-worker/.venv/bin/python3"
TG_BOT_VENV="$DIR/tg_bot/.venv/bin/python3"
echo ""
echo "[CHECK] Dang kiem tra tien trinh cu con sot lai tu lan chay truoc..."
STRAY_PY=$(pgrep -f "\.venv/bin/python3 -u (edge_agent|main)\.py\$" 2>/dev/null)
# tg_bot chay bang "-m tg_bot.bot" (khong phai "-u <file>.py") nen can pattern
# rieng - QUAN TRONG: neu sot lai 1 ban tg_bot cu con polling, ban moi mo them
# se bi Telegram tra loi "Conflict: terminated by other getUpdates request"
# ngay lap tuc (chi 1 client duoc polling tren 1 bot token cung luc).
STRAY_TG_BOT=$(pgrep -f "tg_bot/\.venv/bin/python3 -m tg_bot\.bot\$" 2>/dev/null)
STRAY_FFMPEG=$(pgrep -f "ffmpeg .*-rtsp_transport tcp rtsp://" 2>/dev/null)
STRAY_ALL=$(printf '%s\n%s\n%s\n' "$STRAY_PY" "$STRAY_TG_BOT" "$STRAY_FFMPEG" | grep -v '^$' | sort -u)

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
    echo "[WARN] ai-worker/config.yaml still has placeholder values - edit mqtt_password, streams,"
    echo "       and model.path (see README.md 'Model Setup') before running ai-worker."
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
# Khong dung "sudo" o day - user chay script nay da nam san trong group
# "docker" (kiem tra: groups $USER phai co "docker") nen goi thang duoc,
# khong can quyen root. Bat buoc phai bo sudo cho truong hop chay tu
# dong luc boot qua systemd (khong co TTY de nhap password sudo, se dung
# yen cho mai neu con "sudo").
#
# Sau 1 lan tat may khong sach (mat dien dot ngot, hoac "shutdown" nhung
# rut nguon truoc khi container kip dung han), da gap thuc te: lan boot
# sau do "docker compose up -d" bao loi "Conflict, container name already
# in use" va cac container bi ket vinh vien o trang thai "Created" (chua
# bao gio thuc su "Running" lan nao ca) - "restart: unless-stopped" trong
# docker-compose.yml KHONG cuu duoc truong hop nay vi policy do chi tu
# khoi dong lai container DA TUNG chay roi bi dung, khong ap dung cho
# container moi tao nhung chua kip start lan nao. Hau qua: toan bo
# Grafana/Node-RED/... "chet" ngay tu dau nhung script van in banner
# "RUNNING!" vi khong kiem tra exit code cua lenh nay.
# Fix: neu "up -d" that bai, don sach roi thu lai 1 lan. "docker compose
# down --remove-orphans" chi dong toi container ma compose NHAN RA la
# thuoc project nay (qua label) - da xac nhan qua test thuc te: container
# bi ket o trang thai "Created" tu 1 lan "up -d" TRUOC do bi loi giua
# chung (vd loi tao network) co the khong duoc gan label day du, khien
# "down" bo qua no, retry van dam vao dung 1 loi "Conflict" y het lan dau.
# Fix chac chan hon: xoa THANG theo dung ten container da biet truoc (danh
# sach service trong docker-compose.yml), bat ke co label hay khong -
# "docker rm -f" tren ten khong ton tai se loi nhung khong sao (|| true).
if ! docker compose up -d; then
    echo "[WARN] 'docker compose up -d' that bai (co the do container ket lai tu lan tat may khong sach truoc do) - dang don sach va thu lai..."
    docker compose down --remove-orphans
    for c in shtp-postgres shtp-mosquitto shtp-mediamtx shtp-mqttx-web shtp-grafana shtp-nodered; do
        docker rm -f "$c" >/dev/null 2>&1 || true
    done
    docker compose up -d
fi

echo "[INFO] Waiting a few seconds for Mosquitto/Postgres to settle before starting the edge/AI processes..."
sleep 5

if [ ! -x "$AI_WORKER_VENV" ]; then
    echo ""
    echo "[WARN] ai-worker/.venv not found - skipping edge_agent.py and main.py."
    echo "        Set it up once with:"
    echo "          cd '$DIR/ai-worker' && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    echo "        Then run this script again."
else
    # Qua SSH, "$DISPLAY" co the van con set (vd Pi dang login desktop cuc
    # bo, bien nay sot lai trong session) nhung khong co man hinh nao de
    # x-terminal-emulator/xterm mo cua so len ca - hoac se fail thang, hoac
    # te hon la mo nham len man hinh vat ly cua Pi ma nguoi dang SSH khong
    # thay duoc. Nhan dien phien SSH qua cac bien chuan (SSH dat san khi
    # login) va ep ve nhanh chay nen ngay ca khi "$DISPLAY" co gia tri.
    IS_SSH_SESSION=false
    if [ -n "$SSH_CONNECTION" ] || [ -n "$SSH_TTY" ] || [ -n "$SSH_CLIENT" ]; then
        IS_SSH_SESSION=true
    fi

    TERMINAL=""
    if [ "$IS_SSH_SESSION" = false ]; then
        for t in x-terminal-emulator lxterminal xterm; do
            if command -v "$t" >/dev/null 2>&1; then
                TERMINAL="$t"
                break
            fi
        done
    fi

    # 200>&- tren moi lenh chay nen ben duoi: DONG fd cua khoa flock (mo o
    # dong "exec 200>..." dau file) truoc khi tach tien trinh con - neu
    # khong, edge_agent.py/main.py (hoac cua so terminal rieng) se THUA KE
    # fd nay va tiep tuc GIU khoa song mai ngay ca sau khi ban than run.sh
    # da thoat xong. Hau qua thuc te da gap: lan chay run.sh SAU khong bao
    # gio toi duoc doan "[CHECK] do tien trinh cu" o tren (dung ra se hoi
    # co muon tat ban cu de chay lai sach khong) - ma bi flock chan ngay tu
    # dau, tuong nham "co ban khac dang chay" trong khi thuc ra chi la
    # tien trinh nen cua chinh lan chay TRUOC do con giu khoa. Dong fd nay
    # o day de khoa chi con song dung trong vong doi cua rieng "run.sh"
    # goc, giai phong ngay sau khi no in xong banner ket thuc.
    if [ -n "$DISPLAY" ] && [ -n "$TERMINAL" ] && [ "$IS_SSH_SESSION" = false ]; then
        echo "[INFO] Opening edge_agent.py and ai-worker/main.py in their own terminal windows ($TERMINAL)..."
        "$TERMINAL" -e bash -c "cd '$DIR/edge-rpi' && '$AI_WORKER_VENV' -u edge_agent.py; echo; echo '[edge_agent.py stopped]'; exec bash" 200>&- &
        sleep 1
        "$TERMINAL" -e bash -c "cd '$DIR/ai-worker' && '$AI_WORKER_VENV' -u main.py; echo; echo '[main.py stopped]'; exec bash" 200>&- &
    else
        # Note: the shared logs/ directory is owned by the docker containers
        # (root), not this user, so these host-side process logs live next
        # to their own scripts instead.
        EDGE_LOG="$DIR/edge-rpi/edge_agent.log"
        AI_LOG="$DIR/ai-worker/ai_worker.log"
        if [ "$IS_SSH_SESSION" = true ]; then
            echo "[INFO] Running over SSH - starting edge_agent.py and main.py in the background instead of opening terminal windows."
        else
            echo "[INFO] No graphical display detected (running headless) - starting edge_agent.py and main.py in the background instead."
        fi
        echo "       Logs: $EDGE_LOG and $AI_LOG"
        # Dong fd 200 NGAY DAU subshell (khong chi tren lenh nohup ben trong)
        # - da xac nhan qua test thuc te: neu chi dong tren lenh nohup, ban
        # than tien trinh "vo boc" cua subshell "(...)" van con giu fd 200
        # mo (thay bang fuser .run.lock van thay 2 tien trinh bash con song
        # sau khi script chinh da thoat), khien khoa van khong giai phong.
        #
        # Cung ly do do, redirect luon ca stdout/stderr (>/dev/null 2>&1) cua
        # BAN THAN subshell (khong chi cua nohup ben trong): da xac nhan qua
        # test thuc te (bash run.sh | tail ...) - neu khong, subshell "vo boc"
        # nay tiep tuc giu fd 1/2 tro toi stdout/stderr GOC cua run.sh (vd 1
        # pipe hoac phien SSH khong tuong tac) song mai ngay ca sau khi
        # run.sh da in xong banner va thoat, khien bat ky ai/cai gi doc output
        # cua run.sh qua pipe treo cho EOF vo thoi han du script that su da
        # chay xong tu lau.
        (exec 200>&- >/dev/null 2>&1; cd "$DIR/edge-rpi" && nohup "$AI_WORKER_VENV" -u edge_agent.py > "$EDGE_LOG" 2>&1 &)
        (exec 200>&- >/dev/null 2>&1; cd "$DIR/ai-worker" && nohup "$AI_WORKER_VENV" -u main.py > "$AI_LOG" 2>&1 &)
        echo "       Tail them with: tail -f '$EDGE_LOG' '$AI_LOG'"
    fi
fi

if [ ! -x "$TG_BOT_VENV" ]; then
    echo ""
    echo "[WARN] tg_bot/.venv not found - skipping tg_bot (bot Telegram dieu khien)."
    echo "        Set it up once with:"
    echo "          cd '$DIR/tg_bot' && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    echo "        Then run this script again."
else
    TG_BOT_LOG="$DIR/tg_bot/tg_bot.log"
    echo "[INFO] Starting tg_bot (bot Telegram dieu khien) in the background..."
    echo "       Log: $TG_BOT_LOG"
    (exec 200>&- >/dev/null 2>&1; cd "$DIR" && nohup "$TG_BOT_VENV" -m tg_bot.bot > "$TG_BOT_LOG" 2>&1 &)
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
# Xem truc tiep stream (co ve box/nhan) gio da co san ngay tren Grafana -
# panel "Live Camera View" trong dashboard Traffic Overview (bien
# "live_view" de bat/tat, "pi_host" de doi IP khi xem tu may khac LAN) -
# khong can view_stream.py/venv rieng nua cho muc dich xem thuong.
