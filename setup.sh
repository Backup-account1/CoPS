#!/bin/bash
# AKIP-1144 Panel — one-command setup for Raspberry Pi / Debian / Windows(WSL)
# Usage:  ./setup.sh          real device mode
#         DEMO=1 ./setup.sh   emulator mode (no hardware)
set -e
cd "$(dirname "$0")"

echo "==> Installing system dependencies (needs sudo once)..."
if ! python3 -m venv --help >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y python3-venv python3-pip
fi

echo "==> Creating virtualenv..."
[ -d backend/.venv ] || python3 -m venv backend/.venv

echo "==> Installing Python packages (fastapi, uvicorn, pyserial)..."
backend/.venv/bin/pip install --upgrade pip -q
backend/.venv/bin/pip install -r backend/requirements.txt -q

echo "==> Starting panel..."
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "<pi-ip>")
echo
echo "   Open from any device:  http://${IP}:8000"
[ "${DEMO:-0}" = "1" ] && echo "   Mode: EMULATOR (no hardware needed)"
echo "   Stop with Ctrl+C"
echo

cd backend
if [ "${DEMO:-0}" = "1" ]; then
    exec .venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
else
    exec .venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
fi
