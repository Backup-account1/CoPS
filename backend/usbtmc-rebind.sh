#!/bin/sh
# Unbind+bind the usbtmc driver to reset message-tag sync (IT6726G quirk).
# Exit codes: 0 = rebound ok, 3 = driver not bound (device off the bus), 1 = bind failed.
iface=$(ls /sys/bus/usb/drivers/usbtmc/ 2>/dev/null | grep ':1\.0' | head -n1)
[ -n "$iface" ] || exit 3
echo "$iface" > /sys/bus/usb/drivers/usbtmc/unbind 2>/dev/null || true
sleep 0.5
n=0
while [ $n -lt 3 ]; do
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
