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

- Separators: comma, semicolon or tab; a non-numeric first line is a header
- Values are clamped to the safety limits (`MAX_VOLT`, `MAX_CURR` env)
- Points are linearly interpolated; setpoints update 5×/s
- The Program window shows state, progress, a mini live chart; the Chart
  button opens a fullscreen graph with axis marks and a running cursor

## Run

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
