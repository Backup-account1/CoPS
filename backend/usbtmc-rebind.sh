#!/bin/sh
# Hard reset of the ITECH USBTMC device (IT6726G wedge recovery):
#   1) electrical USB device reset (USBDEVFS_RESET) — a software replug,
#      clears endpoint stalls that a plain driver rebind cannot
#   2) driver unbind/bind — resets USBTMC message-tag sync
# Exit codes: 0 = reset ok, 3 = device not on the bus, 1 = reset failed.
set -u

dev=""
for d in /sys/bus/usb/devices/*/idVendor; do
    [ "$(cat "$d" 2>/dev/null)" = "2ec7" ] || continue
    D=$(dirname "$d")
    dev="/dev/bus/usb/$(printf %03d "$(cat "$D/busnum")")/$(printf %03d "$(cat "$D/devnum")")"
    break
done
[ -n "$dev" ] && [ -e "$dev" ] || exit 3

python3 - "$dev" <<'PY'
import fcntl, os, sys
try:
    fd = os.open(sys.argv[1], os.O_RDWR)
    fcntl.ioctl(fd, 21780)          # USBDEVFS_RESET
    os.close(fd)
    print("usb reset ok")
except OSError as e:
    print("usb reset failed:", e)
PY
sleep 2

iface=$(ls /sys/bus/usb/drivers/usbtmc/ 2>/dev/null | grep ':1\.0' | head -n1)
[ -n "$iface" ] || exit 3
echo "$iface" > /sys/bus/usb/drivers/usbtmc/unbind 2>/dev/null || true
sleep 0.5
n=0
while [ $n -lt 5 ]; do
    if echo "$iface" > /sys/bus/usb/drivers/usbtmc/bind 2>/dev/null; then
        sleep 0.5
        if [ -e /dev/usbtmc0 ]; then
            chmod 666 /dev/usbtmc0
            exit 0
        fi
    fi
    sleep 0.5
    n=$((n + 1))
done
exit 1
