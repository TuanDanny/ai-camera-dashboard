#!/bin/bash
# start_stream.sh - Stream Raspberry Pi Camera to MediaMTX Server

# Get directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CONFIG_FILE="$DIR/config.yaml"

# Simple parser for config.yaml (extract values)
get_config_val() {
    local key=$1
    # Find key and get its value, stripping whitespace and quotes
    grep -E "^[[:space:]]*$key:" "$CONFIG_FILE" | head -n 1 | cut -d':' -f2- | tr -d ' "'''
}

# Doc 1 key BEN TRONG 1 block cap 1 (vd "camera:", "server:") - dung range
# sed "/^block:/,/^[a-zA-Z]/" (dung ky thuat da dung o set_camera_field cua
# scripts/setup_camera.sh) de bat DUNG toan bo block cho toi khi gap dong
# bat dau block ke tiep, KHONG dem so dong co dinh. Truoc day dung "grep -A
# N" (N co dinh) - da xac nhan thuc te bi vo khi 1 block co them comment
# giai thich dai hon N dong, khien cac key nam sau (vd width/height/fps)
# roi ra NGOAI vung "-A N", tra ve rong -> ffmpeg nhan "-s x" (rong) -> loi
# "Invalid argument", stream khong len duoc.
get_block_val() {
    local block="$1" key="$2"
    sed -n "/^${block}:/,/^[a-zA-Z]/p" "$CONFIG_FILE" \
        | grep -v '^[[:space:]]*#' \
        | grep -E "^[[:space:]]+${key}:" \
        | head -n 1 | cut -d':' -f2- | tr -d ' "'''
}

# Moi bien uu tien lay tu bien moi truong da duoc truyen san (vd tu
# edge_agent.py - noi da doc config.yaml bang yaml.safe_load() dang hoang),
# chi fallback ve grep/sed tu doc file khi chay tay doc lap (khong qua
# edge_agent.py) de tranh 2 noi doc lech nhau 1 file config ma khong ai biet.
STATION_ID="${STATION_ID:-$(get_config_val "station_id")}"
SERVER_HOST="${SERVER_HOST:-$(get_block_val server host)}"
RTSP_PORT="${RTSP_PORT:-$(get_block_val server mediamtx_rtsp_port)}"

WIDTH="${WIDTH:-$(get_block_val camera width)}"
HEIGHT="${HEIGHT:-$(get_block_val camera height)}"
FPS="${FPS:-$(get_block_val camera fps)}"
BITRATE="${BITRATE:-$(get_block_val camera bitrate)}"
CAMERA_TYPE="${CAMERA_TYPE:-$(get_block_val camera type)}"
DEVICE="${DEVICE:-$(get_block_val camera device)}"
CAMERA_URL="${CAMERA_URL:-$(get_block_val camera url)}"

RTSP_URL="rtsp://$SERVER_HOST:$RTSP_PORT/$STATION_ID"

echo "[INFO] Starting stream for Station: $STATION_ID"
echo "[INFO] Target URL: $RTSP_URL"
echo "[INFO] Resolution: ${WIDTH}x${HEIGHT} @ ${FPS}fps"
echo "[INFO] Camera Type: $CAMERA_TYPE"

if [ "$CAMERA_TYPE" == "csi" ]; then
    # CSI Camera - rpicam-vid is the current tool name (rpicam-apps package,
    # Bookworm/Trixie); libcamera-vid is the old name still found on some
    # older Bullseye installs. Prefer whichever is actually installed.
    CSI_BIN=$(command -v rpicam-vid || command -v libcamera-vid)
    if [ -z "$CSI_BIN" ]; then
        echo "[ERROR] Khong tim thay rpicam-vid hay libcamera-vid. Cai dat goi rpicam-apps truoc (sudo apt install rpicam-apps)."
        exit 1
    fi
    echo "[INFO] Executing $CSI_BIN stream..."
    "$CSI_BIN" -t 0 --inline --width "$WIDTH" --height "$HEIGHT" --framerate "$FPS" --bitrate "$BITRATE" -o - | \
    ffmpeg -re -i - -vcodec copy -an -f rtsp -rtsp_transport tcp "$RTSP_URL"
elif [ "$CAMERA_TYPE" == "webcam" ]; then
    # USB Webcam (using ffmpeg)
    echo "[INFO] Executing USB Webcam ffmpeg stream..."
    # Thu truoc: camera co ho tro xuat H264 phan cung truc tiep khong
    # (-codec:v h264 la dinh dang input rieng, khong dung chung voi mjpeg).
    ffmpeg -re -f v4l2 -codec:v h264 -s "${WIDTH}x${HEIGHT}" -r "$FPS" -i "$DEVICE" -an -vcodec copy -f rtsp -rtsp_transport tcp "$RTSP_URL" || \
    # Fallback: da so USB webcam chi dat FPS cao (25-30fps) o dang nen MJPG -
    # neu khong ep dinh dang, ffmpeg co the tu chon YUYV (thuong chi dat
    # ~10fps o 720p), khien camera khong doc kip toc do yeu cau, sinh khung
    # hinh loi/thieu/toi.
    ffmpeg -re -f v4l2 -input_format mjpeg -s "${WIDTH}x${HEIGHT}" -r "$FPS" -i "$DEVICE" -an -vcodec libx264 -preset ultrafast -pix_fmt yuv420p -f rtsp -rtsp_transport tcp "$RTSP_URL"
elif [ "$CAMERA_TYPE" == "ip_webcam" ]; then
    # Android "IP Webcam" app - HTTP MJPEG source, always needs transcoding
    # to H264 (no hardware passthrough possible from an MJPEG source).
    echo "[INFO] Executing IP Webcam (phone) ffmpeg stream..."
    echo "[INFO] Source: $CAMERA_URL"
    ffmpeg -re -i "$CAMERA_URL" -an -vcodec libx264 -preset ultrafast -pix_fmt yuv420p -s "${WIDTH}x${HEIGHT}" -r "$FPS" -f rtsp -rtsp_transport tcp "$RTSP_URL"
else
    # Fallback / Simulation test pattern
    echo "[INFO] Executing simulation test pattern stream..."
    ffmpeg -re -f lavfi -i testsrc=size="${WIDTH}x${HEIGHT}":rate="$FPS" -vcodec libx264 -preset ultrafast -pix_fmt yuv420p -f rtsp -rtsp_transport tcp "$RTSP_URL"
fi
