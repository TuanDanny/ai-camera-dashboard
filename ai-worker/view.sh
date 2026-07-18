#!/bin/bash
# Helper script to launch view_stream.py with proper environment and venv
export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
export XDG_RUNTIME_DIR=/run/user/1000

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

if [ -f ".venv-view/bin/python3" ]; then
    PYTHON_CMD=".venv-view/bin/python3"
elif [ -f ".venv/bin/python3" ]; then
    PYTHON_CMD=".venv/bin/python3"
else
    PYTHON_CMD="/usr/bin/python3"
fi

echo "[INFO] Using Python: $PYTHON_CMD"
"$PYTHON_CMD" view_stream.py "$@"
