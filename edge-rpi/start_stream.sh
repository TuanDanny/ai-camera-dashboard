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

STATION_ID=$(get_config_val "station_id")
SERVER_HOST=$(grep -A 3 "^server:" "$CONFIG_FILE" | grep "host:" | cut -d':' -f2- | tr -d ' "''')
RTSP_PORT=$(grep -A 3 "^server:" "$CONFIG_FILE" | grep "mediamtx_rtsp_port:" | cut -d':' -f2- | tr -d ' "''')

WIDTH=$(grep -A 9 "^camera:" "$CONFIG_FILE" | grep "width:" | cut -d':' -f2- | tr -d ' "''')
HEIGHT=$(grep -A 9 "^camera:" "$CONFIG_FILE" | grep "height:" | cut -d':' -f2- | tr -d ' "''')
FPS=$(grep -A 9 "^camera:" "$CONFIG_FILE" | grep "fps:" | cut -d':' -f2- | tr -d ' "''')
BITRATE=$(grep -A 9 "^camera:" "$CONFIG_FILE" | grep "bitrate:" | cut -d':' -f2- | tr -d ' "''')
CAMERA_TYPE=$(grep -A 9 "^camera:" "$CONFIG_FILE" | grep "type:" | cut -d':' -f2- | tr -d ' "''')
DEVICE=$(grep -A 9 "^camera:" "$CONFIG_FILE" | grep "device:" | cut -d':' -f2- | tr -d ' "''')
CAMERA_URL=$(grep -A 9 "^camera:" "$CONFIG_FILE" | grep "url:" | cut -d':' -f2- | tr -d ' "''')

RTSP_URL="rtsp://$SERVER_HOST:$RTSP_PORT/$STATION_ID"

echo "[INFO] Starting stream for Station: $STATION_ID"
echo "[INFO] Target URL: $RTSP_URL"
echo "[INFO] Resolution: ${WIDTH}x${HEIGHT} @ ${FPS}fps"
echo "[INFO] Camera Type: $CAMERA_TYPE"

if [ "$CAMERA_TYPE" == "csi" ]; then
    # CSI Camera (using libcamera-vid)
    echo "[INFO] Executing libcamera-vid stream..."
    libcamera-vid -t 0 --inline --width "$WIDTH" --height "$HEIGHT" --framerate "$FPS" --bitrate "$BITRATE" -o - | \
    ffmpeg -re -i - -vcodec copy -an -f rtsp -rtsp_transport tcp "$RTSP_URL"
elif [ "$CAMERA_TYPE" == "webcam" ]; then
    # USB Webcam (using ffmpeg)
    echo "[INFO] Executing USB Webcam ffmpeg stream..."
    # Check if webcam supports H264 hardware encoding directly, else transpile
    ffmpeg -re -f v4l2 -codec:v h264 -s "${WIDTH}x${HEIGHT}" -r "$FPS" -i "$DEVICE" -an -vcodec copy -f rtsp -rtsp_transport tcp "$RTSP_URL" || \
    ffmpeg -re -f v4l2 -s "${WIDTH}x${HEIGHT}" -r "$FPS" -i "$DEVICE" -an -vcodec libx264 -preset ultrafast -pix_fmt yuv420p -f rtsp -rtsp_transport tcp "$RTSP_URL"
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
