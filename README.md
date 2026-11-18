# AKIP-1144 Panel

Touch web panel for the **АКИП-1144-x** programmable DC power supply
(SCPI over USB). Control it manually or run uploaded **voltage/current
curves** (CSV programs) with live charts.

- **Vanilla JS** frontend — no build step, works in any browser
  (Raspberry Pi 3 touchscreen, Windows, Android/iPhone)
- **FastAPI** backend — one Python codebase for Linux (Pi) and Windows
- **SQLite** — settings, event history and the last uploaded curve persist
- **Built-in emulator** — test everything without the hardware
- **i18n** — English, Русский, 中文（简体）; add a language by dropping one file

## Buttons

| Button       | Action                                            |
| ------------ | ------------------------------------------------- |
| Connect      | Auto-detect the supply (COM port or emulator)     |
| Disconnect   | Close the connection                              |
| Test         | `*IDN?` + voltage/current measurement             |
| Settings     | Connection mode, port, baud, language             |
| Program      | Load a CSV curve, start/stop, live status + chart |

## Curve programs (CSV)

One file holds both curves — voltage and current share the time axis:

```csv
# loop=2        <- repeats (0 = infinite), default 1
# end=off       <- "off" or "hold" at the end, default off
t,v,i
0,0,0.5
5,12,0.5
10,12,2
```

**Format rules**

| Rule | Detail |
|------|--------|
| **Columns** | **3 columns exactly**: `t` (seconds), `v` (volts), `i` (amps) |
| **Separators** | comma, semicolon, tab, or spaces |
| **Comments / params** | Lines starting with `#` — comments are ignored; `# loop=`, `# end=` set parameters |
| **Header row** | Any non-numeric first line is skipped automatically |
| **Time axis** | `t` in seconds, must strictly increase; first point `t=0` is typical |
| **Values** | Clamped to safety limits (`MAX_VOLT` / `MAX_CURR` from Settings or env vars) |
| **Min points** | At least 2 points required |

**Parameters (in comment lines)**

- `# loop=2` — number of repeats (`0` = infinite, default `1`)
- `# end=off` — final state: `off` (output off, 0 V) or `hold` (keep last setpoint)

**Example**

```csv
# loop=10
# end=off
0,0,5
10,20,5
20,0,5
```

**Behaviour**

- Setpoints are linearly interpolated between points
- The runner updates setpoints at 5 Hz; measured V/A are reported back every ~0.4 s
- In the Program window you see live progress, a mini chart, and lap count
- The Chart button opens a fullscreen graph with axis marks and a running cursor
- On start, the curve is saved to SQLite; next boot it's available in the Program dropdown

## Hardware notes: USBTMC (ITECH/AKIP over USB)

Some units enumerate as **USBTMC** (`/dev/usbtmc0`) instead of a virtual COM
port (`lsusb` shows e.g. `2ec7:6700 ITECH Ltd. IT6726G`). The backend supports
this automatically via `backend/usbtmc.py` (kernel usbtmc driver + EOM ioctl).
One-time permission setup on Linux:

```sh
sudo cp backend/99-usbtmc.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

Then replug the USB cable. Do **not** use `usbreset`-style resets on ITECH
supplies — they drop off the bus and require a physical replug.

## Deploy to Raspberry Pi

One command on the Pi (needs internet + sudo once):

```sh
git clone https://github.com/Backup-account1/CoPS.git
cd CoPS
./setup.sh          # DEMO=1 ./setup.sh for emulator mode
```

It creates `backend/.venv`, installs the packages and starts the server on
`0.0.0.0:8000`. Re-run `./setup.sh` after `git pull` to update dependencies.

## Run (manual)

```sh
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open `http://<device-ip>:8000` from any browser on the same network.

### With the emulator (no hardware)

```sh
DEMO=1 uvicorn main:app --host 0.0.0.0 --port 8000
```

Or choose **Connection → Emulator** in Settings. The emulator implements
`VOLT`/`CURR`/`OUTP`/`MEAS:*` with soft-start, a constant-resistance load
(`EMU_LOAD_R`, default 10 Ω) and CV/CC behaviour.

### With the real supply

Set **Connection → Device** in Settings, plug in USB, press Connect.
Port `auto` tries `/dev/ttyACM*`, `/dev/ttyUSB*` and `COM1…COM20`;
set an explicit port (e.g. `COM3`) if needed. If the supply enumerates as
USBTMC instead of a virtual COM port, a PyVISA layer will be added later.

## Storage

`backend/panel.db` (SQLite, created automatically) — settings, events
(`GET /api/events`), last curve. Safe to delete; everything is recreated.

## Safety

The supply can deliver up to 600 V / 3 kW. The curve runner clamps
setpoints to `MAX_VOLT` / `MAX_CURR` and switches the output off at the
end (unless `end=hold`). Always verify the SCPI command set against the
АКИП-1144 programming manual before running on real hardware.
