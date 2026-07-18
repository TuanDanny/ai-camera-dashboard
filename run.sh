#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
export XDG_RUNTIME_DIR=/run/user/1000

echo "========================================================="
echo "       SHTP AI CAMERA - MASTER CONTROL PANEL"
echo "========================================================="
echo "  1) Chay he thong ngam (Systemd)"
echo "  2) Tat toan bo he thong"
echo "  3) DEMO FULL: Mo cac Terminal rieng biet (Agent + AI/View)"
echo "========================================================="
read -p "Chon thao tac (1-3): " CHOICE

case "$CHOICE" in
    1)
        sudo systemctl start shtp_docker shtp_agent shtp_camera
        echo "[OK] He thong dang chay ngam."
        ;;
    2)
        sudo systemctl stop shtp_camera shtp_agent shtp_docker
        sudo pkill -9 -f edge_agent.py
        sudo pkill -9 -f main.py
        echo "[OK] Da tat toan bo."
        ;;
    3)
        echo "[INFO] Dang tat cac tien trinh cu de giai phong NPU..."
        sudo systemctl stop shtp_camera shtp_agent
        sudo pkill -9 -f edge_agent.py
        sudo pkill -9 -f main.py
        
        echo "[INFO] Doi 3 giay de chip Hailo NPU duoc giai phong hoan toan..."
        sleep 3
        
        echo "[INFO] Dang mo cac Terminal..."
        sudo systemctl start shtp_docker
        
        # Terminal 1: Edge Agent (Stream Camera)
        lxterminal --title="Edge Agent (Camera Stream)" -e bash -c "cd '$DIR/edge-rpi' && /home/shtp/yolo-cam/.venv/bin/python edge_agent.py; echo '[Da dong]'; exec bash" &
        
        sleep 2
        
        # Terminal 2: AI Worker + View (Dashboard + GUI)
        # Dung .venv-view/bin/python3 vi no chay GUI va NPU on dinh nhat
        lxterminal --title="AI Worker (Dashboard + View)" -e bash -c "cd '$DIR/ai-worker' && .venv-view/bin/python3 main.py --view; echo '[Da dong]'; exec bash" &
        
        echo "[OK] Da mo 2 Terminal tren man hinh Pi!"
        ;;
    *)
        echo "Thoat."
        ;;
esac
