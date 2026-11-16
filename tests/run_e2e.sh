#!/bin/sh
# Browser E2E runner for the AKIP-1144 panel.
#
#   tests/run_e2e.sh              # headless (CI-style, no window)
#   tests/run_e2e.sh headed       # visible browser on your screen
#
# First run only:  python3 -m playwright install chromium
set -e
cd "$(dirname "$0")/.."

case "$1" in
  headed|visible|gui)
    export HEADED=1 SLOW_MO="${SLOW_MO:-300}"
    ;;
esac

exec python3 -m pytest tests/test_e2e_ui.py -v --no-header "$@"
