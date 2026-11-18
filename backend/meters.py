"""OWON XDM1041 bench DMMs — live polling + CSV recording.

Fixed roles in settings ("meters"): Meter 1 -> voltage, Meter 2 -> current.
The meter front panel is NOT remote-controlled: the function is only read
via FUNC?, so the operator chooses VOLT/CURR on the device itself.

A background thread polls every configured meter as fast as it answers
(~9 Hz demo, a few Hz real — the meter converts internally at ~2–5 Hz, so
faster polls just repeat the cached reading). Recording (Start/Stop from
the panel) writes one CSV row per reading per meter to
backend/logs/meters_YYYYMMDD_HHMMSS.csv — one file per session, kept
forever.

CSV columns: timestamp,meter,function,value,unit
"""

import csv
import glob
import math
import os
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import serial

BAUD = 115200
LOGS = Path(__file__).resolve().parent / "logs"
LOGS.mkdir(exist_ok=True)

FUNC_UNIT = {"VOLT": "V", "CURR": "A", "RES": "Ω", "FREQ": "Hz",
             "CAP": "F", "TEMP": "°C", "DIODE": "V"}

DEFAULT_METERS = [
    {"name": "Meter 1", "port": "auto", "role": "volt"},
    {"name": "Meter 2", "port": "auto", "role": "curr"},
]

_stop = threading.Event()
_thread = None
_settings_loader = None          # callable -> dict (injected from main.py)

# per-slot runtime state: slot -> dict
_meters = [None, None]           # MeterConn | _DemoMeter | None

def _blank_state(slot: int) -> dict:
    m = DEFAULT_METERS[slot]
    return {"slot": slot, "name": m["name"], "role": m["role"], "port": None,
            "connected": False, "idn": None, "func": None,
            "value": None, "unit": "V" if m["role"] == "volt" else "A",
            "ts": None, "min": None, "max": None,
            "error": None, "wrong_func": False}


_values = [_blank_state(i) for i in range(2)]


_rec = {"active": False, "file": None, "rows": 0, "started": 0.0,
        "_fh": None, "_writer": None}


# ---- demo (emulator) meter -------------------------------------------
class _DemoMeter:
    def __init__(self, slot: int):
        self.slot = slot
        self.t0 = time.time()
        self.role = DEFAULT_METERS[slot]["role"]

    def open(self):
        return True

    def close(self):
        pass

    def query(self, cmd: str, timeout: float = 0.4) -> str:
        time.sleep(0.01)                       # simulate a fast bus
        u = cmd.strip().upper()
        if u == "*IDN?":
            return f"OWON,XDM1041,DEMO{self.slot + 1:04d},V4.1.0-DEMO"
        if u == "FUNC?":
            return '"VOLT"' if self.role == "volt" else '"CURR"'
        if u in ("MEAS:VOLT?", "MEAS:CURR?"):
            el = time.time() - self.t0
            if self.role == "volt":
                v = 2.0 + 1.5 * math.sin(el / 3.0) + random.uniform(-0.01, 0.01)
                return f"{v:.4e}"
            i = max(0.0, 0.5 + 0.4 * math.sin(el / 3.0 + 0.6)
                    + random.uniform(-0.005, 0.005))
            return f"{i:.4e}"
        return ""


# ---- real meter ------------------------------------------------------
class MeterConn:
    def __init__(self, port: str):
        self.port = port
        self.s = None
        self.func = None
        self.last_func = 0.0
        self.last_try = 0.0

    def open(self) -> bool:
        self.last_try = time.time()
        try:
            s = serial.Serial(self.port, BAUD, timeout=0.6)
            time.sleep(0.2)
            s.reset_input_buffer()
            s.write(b"*IDN?\n")
            line = s.readline().decode(errors="ignore").strip()
            if "XDM1041" not in line.upper() and "OWON" not in line.upper():
                s.close()
                return False
            self.s = s
            return True
        except Exception:
            try:
                if self.s:
                    self.s.close()
            except Exception:
                pass
            self.s = None
            return False

    def close(self):
        try:
            if self.s:
                self.s.close()
        except Exception:
            pass
        self.s = None

    def query(self, cmd: str, timeout: float = 0.8) -> str:
        if self.s is None:
            raise IOError("not open")
        self.s.timeout = timeout
        self.s.reset_input_buffer()
        self.s.write((cmd + "\n").encode())
        return self.s.readline().decode(errors="ignore").strip()


def _is_demo() -> bool:
    if os.environ.get("DEMO", "").strip() in ("1", "true", "yes"):
        return True
    try:
        return bool(_settings_loader()["mode"] == "emulator")
    except Exception:
        return False


def _auto_ports() -> list:
    return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))


def _scan_real():
    """Open each auto port once, keep the ones that answer as XDM1041.
    Returns list of (port, idn) in stable (sorted) order."""
    found = []
    for p in _auto_ports():
        try:
            s = serial.Serial(p, BAUD, timeout=0.8)
            time.sleep(0.15)
            s.reset_input_buffer()
            s.write(b"*IDN?\n")
            line = s.readline().decode(errors="ignore").strip()
            s.close()
            if "XDM1041" in line.upper() or "OWON" in line.upper():
                found.append((p, line))
        except Exception:
            continue
    return found

def _configs() -> list:
    try:
        cfg = _settings_loader()
        m = cfg.get("meters") or DEFAULT_METERS
    except Exception:
        m = DEFAULT_METERS
    out = []
    for i in range(2):
        src = (m[i] if i < len(m) else {}) or {}
        role = src.get("role") if src.get("role") in ("volt", "curr") else DEFAULT_METERS[i]["role"]
        out.append({"name": src.get("name") or DEFAULT_METERS[i]["name"],
                    "port": (src.get("port") or "auto").strip() or "auto",
                    "role": role})
    return out


def _config_sig(cfgs) -> tuple:
    return tuple((c["port"], c["role"]) for c in cfgs) + (_is_demo(),)


_sig = None


def _other_port(slot: int):
    m = _meters[1 - slot]
    return m.port if isinstance(m, MeterConn) else None


def _hold_connection(slot: int, cfg: dict, scan: list, demo: bool):
    """(Re)establish slot connection if needed. Returns meter object or None."""
    cur = _meters[slot]
    if demo:
        if not isinstance(cur, _DemoMeter):
            _meters[slot] = _DemoMeter(slot)
        return _meters[slot]
    if isinstance(cur, MeterConn):
        want = cfg["port"]
        if want == "auto" or cur.port == want:
            if cur.s is not None:
                return cur
            if time.time() - cur.last_try < 2.0:
                return None
            return cur if cur.open() else None
        cur.close()
        _meters[slot] = None
    # fresh (re)connect
    if cfg["port"] == "auto":
        other = _other_port(slot)
        for p, _idn in scan:
            if p != other:
                conn = MeterConn(p)
                if conn.open():
                    _meters[slot] = conn
                    return conn
        return None
    conn = MeterConn(cfg["port"])
    return conn if conn.open() else None


def _set(slot: int, **kw):
    _values[slot].update(kw)


def _poll_one(slot: int, meter, cfg: dict):
    st = _values[slot]
    now = time.time()
    # function query occasionally (keeps the label honest; cheap enough)
    if meter.__class__ is MeterConn:
        if now - meter.last_func > 3.0 or st["func"] is None:
            try:
                f = meter.query("FUNC?").upper().strip().strip('"').strip()
                if f:
                    st["func"] = f
                    meter.last_func = now
            except Exception:
                pass
    else:                                   # demo meter
        f = meter.query("FUNC?").upper().strip('"')
        st["func"] = f
    func = st["func"] or ("VOLT" if cfg["role"] == "volt" else "CURR")
    unit = FUNC_UNIT.get(func, func)
    raw = meter.query(f"MEAS:{func}?")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        _set(slot, value=None, unit=unit, error=f"bad reading: {raw!r}", ts=now)
        return
    mn, mx = st["min"], st["max"]
    mn = val if mn is None else min(mn, val)
    mx = val if mx is None else max(mx, val)
    expect = "VOLT" if cfg["role"] == "volt" else "CURR"
    _set(slot, connected=True, error=None, value=val, unit=unit, ts=now,
         min=mn, max=mx, wrong_func=(func != expect), port=getattr(meter, "port", "demo"))
    if not st.get("idn"):
        try:
            _set(slot, idn=meter.query("*IDN?") or None)
        except Exception:
            pass
    # recording
    with _rec_lock:
        if _rec["active"]:
            ts = datetime.now().isoformat(timespec="milliseconds")
            try:
                _rec["_writer"].writerow([ts, cfg["name"], func, f"{val:.6g}", unit])
                _rec["rows"] += 1
                if _rec["rows"] % 20 == 0:
                    _rec["_fh"].flush()
            except Exception as e:
                _rec_stop_locked()
                _values[slot]["error"] = f"record write failed: {e}"


def _loop():
    global _sig
    while not _stop.is_set():
        demo = _is_demo()
        cfgs = _configs()
        sig = _config_sig(cfgs)
        if sig != _sig:                    # config changed: drop connections
            for i, m in enumerate(_meters):
                if m is not None:
                    try:
                        m.close()
                    except Exception:
                        pass
                _meters[i] = None
                keep = _values[i]
                _values[i] = _blank_state(i)
                _values[i]["role"] = cfgs[i]["role"]
                _values[i]["name"] = cfgs[i]["name"]
            _sig = sig
        scan = [] if demo else _scan_real()
        for i in range(2):
            cfg = cfgs[i]
            meter = _hold_connection(i, cfg, scan, demo)
            if meter is None:
                if _values[i]["connected"]:
                    _set(i, connected=False, error="lost")
                continue
            try:
                _poll_one(i, meter, cfg)
            except Exception as e:
                # connection died — drop it, retry next passes
                try:
                    meter.close()
                except Exception:
                    pass
                _meters[i] = None
                _set(i, connected=False, error=str(e))
        time.sleep(0.02)


def start(settings_loader):
    global _thread, _settings_loader
    _settings_loader = settings_loader
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="meters", daemon=True)
    _thread.start()


_rec_lock = threading.Lock()


def snapshot() -> dict:
    meters = [dict(_values[i]) for i in range(2)]
    with _rec_lock:
        rec = {k: _rec[k] for k in ("active", "file", "rows", "started")}
        if rec["active"]:
            rec["file_name"] = Path(rec["file"]).name
            rec["seconds"] = round(time.time() - rec["started"], 1)
    return {"meters": meters, "recording": rec}


# ---- recording (called from the API) ---------------------------------
def _rec_stop_locked() -> dict:
    """Stop an active recording. Caller must hold _rec_lock."""
    if not _rec["active"]:
        return {"ok": True, "active": False}
    try:
        _rec["_fh"].flush()
        _rec["_fh"].close()
    except Exception:
        pass
    out = {"ok": True, "active": False,
           "file": _rec["file"], "file_name": Path(_rec["file"]).name,
           "rows": _rec["rows"],
           "seconds": round(time.time() - _rec["started"], 1)}
    _rec.update(active=False, file=None, _fh=None, _writer=None, rows=0, started=0.0)
    return out


def record_start() -> dict:
    with _rec_lock:
        if _rec["active"]:
            return {"ok": True, "active": True,
                    "file_name": Path(_rec["file"]).name}
        name = "meters_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
        path = LOGS / name
        fh = open(path, "w", newline="", encoding="utf-8")
        w = csv.writer(fh)
        w.writerow(["timestamp", "meter", "function", "value", "unit"])
        fh.flush()
        _rec.update(active=True, file=str(path), _fh=fh, _writer=w,
                    rows=0, started=time.time())
        return {"ok": True, "active": True, "file_name": name}


def record_stop() -> dict:
    with _rec_lock:
        return _rec_stop_locked()


def list_logs() -> list:
    out = []
    for p in sorted(LOGS.glob("meters_*.csv"), reverse=True):
        try:
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size,
                        "mtime": st.st_mtime})
        except OSError:
            continue
    return out


def log_path(name: str):
    """Validated path inside LOGS, or None (prevents path traversal)."""
    if not name or "/" in name or "\\" in name or not re.fullmatch(r"meters_[\w.-]+\.csv", name):
        return None
    p = (LOGS / name).resolve()
    if p.parent != LOGS.resolve() or not p.is_file():
        return None
    return p


def reset_minmax() -> dict:
    for i in range(2):
        _values[i]["min"] = None
        _values[i]["max"] = None
    return {"ok": True}
