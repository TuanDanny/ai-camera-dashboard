#!/bin/bash
# Wizard hoi chon nguon camera (CSI / IP Webcam / USB Webcam) va ghi vao
# edge-rpi/config.yaml. Duoc goi tu run.sh, nhan duong dan file config lam
# tham so dau tien - khong tu chay doc lap.
EDGE_CONFIG="$1"

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
