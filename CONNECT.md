# Connect to the Pi (pi4)

```sh
ssh pi4        # same WiFi as the Pi (fast, direct)
ssh pi4-ts     # from anywhere — works over the internet (Tailscale)
```

No password needed (SSH key auth, configured in `~/.ssh/config`).

## Details

| Item        | Value                              |
| ----------- | ---------------------------------- |
| Host        | pi4 (Raspberry Pi 4, 64-bit OS)    |
| User        | `a`                                |
| LAN IP      | `192.168.100.35` (changes by WiFi) |
| Tailscale   | `100.75.135.63` (never changes)    |
| SSH key     | `~/.ssh/id_ed25519`                |

## Useful commands

```sh
ssh pi4-ts 'uptime'              # run a command remotely
ssh pi4-ts 'sudo reboot'         # reboot the Pi
ssh pi4-ts 'sudo poweroff'       # shut down the Pi
```

## Notes

- **Remote access is SSH-only** (`ssh pi4-ts`) — it uses `ProxyCommand tailscale nc`,
  which works everywhere the Pi has internet. Direct TCP to `100.75.135.63`
  doesn't route; always use the `pi4-ts` alias.
- The **panel is LAN-only**: open `http://<pi-LAN-IP>:8000` from a phone or
  laptop on the same WiFi as the Pi.
- If the LAN IP changed, update it in `~/.ssh/config` under `Host pi4`
  (find the new IP with `ssh pi4-ts 'hostname -I'`).
