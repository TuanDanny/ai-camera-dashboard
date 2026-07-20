#!/bin/bash
# Wizard hoi chon nguon camera (CSI / IP Webcam / USB Webcam) va ghi vao
# edge-rpi/config.yaml. Duoc goi tu run.sh, nhan duong dan file config lam
# tham so dau tien - khong tu chay doc lap.
EDGE_CONFIG="$1"

get_camera_field() {
    # sed range "/^camera:/,/^[a-zA-Z]/" bat dung toan bo block "camera:"
    # cho toi dong bat dau block ke tiep - KHONG dem so dong co dinh (khac
    # "grep -A 9" cu, da xac nhan thuc te bi vo khi block co them comment
    # dai hon 9 dong, khien "device" nam sau bi bo lot, tra ve rong).
    sed -n "/^camera:/,/^[a-zA-Z]/p" "$EDGE_CONFIG" \
        | grep -v '^[[:space:]]*#' \
        | grep -E "^[[:space:]]+$1:" \
        | head -n1 | cut -d':' -f2- | sed 's/^ *//;s/ *$//'
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
        echo "[INFO] Dang do cac camera USB dang cam vao..."

        # Truoc day script chi lam "ls /dev/video*" roi bat go tay so - liet
        # ke ca node "Metadata Capture" (khong quay duoc anh, vd -video-
        # index1 cua nhieu camera UVC) lan cac node video noi bo cua Pi
        # (video19-35), khien nguoi dung de go nham 1 node khong quay duoc
        # anh (da xac nhan thuc te: gay loi RTSP 404 lien tuc). Gio TU DONG
        # loc chi con node co capability "Video Capture" THAT, va uu tien
        # tra ve duong dan /dev/v4l/by-id/ (co dinh theo serial cua camera,
        # KHONG doi khi reboot/cam lai USB - khac voi /dev/videoN, so nay
        # kernel gan lai theo thu tu enumerate, co the doi giua cac lan).
        CANDIDATES=()
        CANDIDATE_LABELS=()

        if [ -d /dev/v4l/by-id ]; then
            for link in /dev/v4l/by-id/*-video-index*; do
                [ -e "$link" ] || continue
                REAL=$(readlink -f "$link")
                if v4l2-ctl -d "$REAL" --all 2>/dev/null | grep -A3 "Device Caps" | grep -q "Video Capture"; then
                    MODEL=$(udevadm info -q property -n "$REAL" 2>/dev/null | grep "^ID_MODEL=" | cut -d= -f2)
                    CANDIDATES+=("$link")
                    CANDIDATE_LABELS+=("$link  (${MODEL:-?} -> $REAL)")
                fi
            done
        fi

        # Fallback hiem gap: chua co /dev/v4l/by-id (vd udev chua kip tao) -
        # quet thang /dev/video* voi cung dieu kien loc capability.
        if [ ${#CANDIDATES[@]} -eq 0 ]; then
            for dev in /dev/video*; do
                [ -e "$dev" ] || continue
                if v4l2-ctl -d "$dev" --all 2>/dev/null | grep -A3 "Device Caps" | grep -q "Video Capture"; then
                    CANDIDATES+=("$dev")
                    CANDIDATE_LABELS+=("$dev")
                fi
            done
        fi

        if [ ${#CANDIDATES[@]} -eq 0 ]; then
            echo "[WARN] Khong tim thay camera USB nao quay duoc anh (Video Capture) - kiem tra lai day cam. Giu nguyen cau hinh cu '${CURRENT_DEVICE}'."
            NEW_DEVICE="$CURRENT_DEVICE"
        elif [ ${#CANDIDATES[@]} -eq 1 ]; then
            NEW_DEVICE="${CANDIDATES[0]}"
            echo "[INFO] Tu dong chon 1 camera duy nhat tim thay: ${CANDIDATE_LABELS[0]}"
        else
            echo "[INFO] Tim thay ${#CANDIDATES[@]} camera quay duoc anh:"
            for i in "${!CANDIDATES[@]}"; do
                echo "  $((i + 1))) ${CANDIDATE_LABELS[$i]}"
            done
            read -p "Chon so (Enter de giu cau hinh cu '${CURRENT_DEVICE}'): " PICK
            if [[ "$PICK" =~ ^[0-9]+$ ]] && [ "$PICK" -ge 1 ] && [ "$PICK" -le "${#CANDIDATES[@]}" ]; then
                NEW_DEVICE="${CANDIDATES[$((PICK - 1))]}"
            else
                NEW_DEVICE="$CURRENT_DEVICE"
            fi
        fi

        echo "[INFO] Dat camera.device = $NEW_DEVICE"
        set_camera_field "device" "$NEW_DEVICE"
        ;;
    *)
        echo "[INFO] Giu nguyen cau hinh camera hien tai (type=${CURRENT_CAM_TYPE})."
        ;;
esac
