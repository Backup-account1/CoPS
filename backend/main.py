"""Minimal backend for the AKIP-1144 control panel.

Buttons: Connect / Disconnect / Test / Settings / Program.
Settings (language, connection mode, port, baud) persist in SQLite,
as does the event history and the last uploaded curve.

Run:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000

Without hardware (built-in emulator):
    DEMO=1 uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import glob
import os
import subprocess
import threading
import time

import db
from curve import interp, parse_curve
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DEFAULTS = {"language": "en", "port": "auto", "baud": 9600, "mode": "device"}

app = FastAPI(title="AKIP-1144 Panel")

_ser = None          # serial.Serial or EmulatorSerial when connected
_idn = None
_lock = threading.Lock()

_curve = {"name": None, "points": None, "params": {}}
_run = {"task": None, "stopped": False, "started": 0.0}
_meas = {"volt": None, "curr": None}   # last real device measurements during a run


def _limits():
    return (
        float(os.environ.get("MAX_VOLT", "610")),
        float(os.environ.get("MAX_CURR", "10.5")),
    )


@app.on_event("startup")
def startup():
    db.init()
    row = db.load_curve()
    if row:
        try:
            parsed = parse_curve(row["content"], *_limits())
            _curve.update(name=row["name"], points=parsed["points"],
                          params=parsed["params"])
        except Exception:
            pass


# ---- settings (SQLite) -----------------------------------------------
class Settings(BaseModel):
    language: str = "en"
    port: str = "auto"
    baud: int = 9600
    mode: str = "device"   # "device" or "emulator"


def load_settings() -> dict:
    return db.get_settings(DEFAULTS)


def save_settings(s: dict):
    db.save_settings(s)


# ---- device ----------------------------------------------------------
def _is_demo() -> bool:
    return os.environ.get("DEMO", "").strip() in ("1", "true", "yes")


def _candidate_ports() -> list:
    ports = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    ports += glob.glob("/dev/usbtmc*")   # USBTMC supplies (ITECH/AKIP over USB)
    ports += [f"COM{n}" for n in range(1, 21)]
    return ports


def _scpi(cmd: str, timeout: float = 2.0) -> str:
    """Write a SCPI command. Queries (ending '?') return the response.
    Plain commands are written WITHOUT reading — the IT6726G does not
    answer them, and a read after a plain write desyncs/stalls USBTMC
    (root cause of "curve runs but the output stays 0")."""
    if _ser is None:
        raise HTTPException(400, "not connected")
    _ser.timeout = timeout
    try:
        if not cmd.rstrip().endswith("?"):
            _ser.write((cmd + "\n").encode())
            return ""
        _ser.reset_input_buffer()
        _ser.write((cmd + "\n").encode())
        return _ser.readline().decode(errors="ignore").strip()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"io error: {e}") from e


def _drain_errq() -> int:
    """Drain the device error queue. A full queue ('-350 Too many errors')
    makes the IT6726G firmware drop commands silently."""
    n = 0
    try:
        for _ in range(30):
            r = _scpi("SYST:ERR?", timeout=1.0)
            if r.startswith("0,") or r.strip() in ("0", ""):
                break
            n += 1
    except Exception:
        pass
    return n


# ---- endpoints: status / connection ----------------------------------
@app.get("/api/status")
def status():
    return {
        "connected": _ser is not None,
        "idn": _idn,
        "demo": _is_demo() or load_settings()["mode"] == "emulator",
        "settings": load_settings(),
    }


@app.post("/api/connect")
def connect():
    global _ser, _idn
    with _lock:
        if _ser is not None:
            return {"ok": True, "idn": _idn}
        cfg = load_settings()
        try:
            if _is_demo() or cfg["mode"] == "emulator":
                from emulator import EmulatorSerial
                globals()["_ser"] = EmulatorSerial()
                globals()["_idn"] = _scpi("*IDN?", timeout=3.0)
                db.add_event("connect", _idn + " (emulated)")
                return {"ok": True, "idn": _idn, "emulated": True}
            import serial
        except ImportError:
            raise HTTPException(500, "pyserial not installed")
        ports = _candidate_ports() if cfg["port"] == "auto" else [cfg["port"]]
        last_err = "no ports found"
        for p in ports:
            try:
                if "usbtmc" in p:
                    from usbtmc import UsbTmcSerial
                    s = UsbTmcSerial(p, timeout=2.0)
                else:
                    s = serial.Serial(p, baudrate=cfg["baud"], timeout=2.0)
            except Exception as e:
                last_err = str(e)
                continue
            try:
                globals()["_ser"] = s
                idn = _scpi("*IDN?", timeout=3.0)
                if len(idn) < 5:
                    raise ValueError("no *IDN? response")
                globals()["_idn"] = idn
                n = _drain_errq()
                _scpi("SYST:REM")   # pure write: enable REMOTE mode — the
                                    # device rejects all setpoints otherwise
                                    # (-200 Execution error every write)
                n2 = _drain_errq()  # SYST:REM itself logs an error entry
                db.add_event("connect",
                             f"{idn} remote=on drained={n}+{n2}")
                return {"ok": True, "idn": idn}
            except Exception as e:
                s.close()
                globals()["_ser"] = None
                last_err = f"{p}: {e}"
        db.add_event("connect_failed", last_err)
        raise HTTPException(502, f"connect failed — {last_err}")


@app.post("/api/disconnect")
def disconnect():
    global _ser, _idn
    _run["stopped"] = True   # abort a running curve first
    with _lock:
        if _ser is not None:
            try:
                _ser.close()
            except Exception:
                pass
        _ser, _idn = None, None
    db.add_event("disconnect")
    return {"ok": True}


@app.post("/api/test")
def test():
    idn = _scpi("*IDN?")
    try:
        volt = _scpi("MEAS:VOLT?")
        curr = _scpi("MEAS:CURR?")
    except HTTPException:
        volt = curr = "?"
    db.add_event("test", f"idn={idn} V={volt} A={curr}")
    return {"ok": True, "idn": idn, "volt": volt, "curr": curr}


@app.post("/api/verify")
def verify():
    """Closed-loop feedback check: send a voltage, read back what the device
    acknowledged (VOLT?/CURR?) and what it really outputs (MEAS:VOLT? etc.),
    then restore the previous state. Safe: 2 V / 0.5 A for ~1 s."""
    if _ser is None:
        raise HTTPException(400, "not connected")
    if _running():
        raise HTTPException(409, "curve is running — stop it first")

    set_v, set_i = 2.0, 0.5
    out = {"set": {"volt": set_v, "curr": set_i},
           "ack": {"volt": None, "curr": None},
           "meas": {"volt": None, "curr": None}, "ok": False}
    old_v = old_i = "0.000"
    old_out = "0"                        # assume output was off (safe restore)
    with _lock:
        try:
            old_v, old_i = _scpi("VOLT?"), _scpi("CURR?")
            old_out = _scpi("OUTP?")
            _scpi(f"VOLT {set_v}")            # pure write — device does not answer
            out["ack"]["volt"] = _scpi("VOLT?")   # separate readback query
            _scpi(f"CURR {set_i}")
            out["ack"]["curr"] = _scpi("CURR?")
            _scpi("OUTP ON")
            out["ack"]["outp"] = _scpi("OUTP?")
            time.sleep(1.0)                      # let the output settle
            out["meas"]["volt"] = _scpi("MEAS:VOLT?")
            out["meas"]["curr"] = _scpi("MEAS:CURR?")
        except HTTPException as e:
            out["error"] = str(e.detail)
            db.add_event("verify_failed", out["error"])
            return out
        finally:
            try:                                 # restore previous state
                _scpi(f"VOLT {_safe(old_v)}")
                _scpi(f"CURR {_safe(old_i)}")
                was_on = float(old_out or "0") >= 0.5
            except Exception:
                was_on = False
            if not was_on:
                try:
                    _scpi("OUTP OFF")
                except Exception:
                    pass

    def _f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    av, mv = _f(out["ack"]["volt"]), _f(out["meas"]["volt"])
    out["ok"] = (av is not None and abs(av - set_v) < 0.05 and
                 mv is not None and abs(mv - set_v) < 0.25)
    db.add_event("verify", f"ack={out['ack']['volt']} meas={out['meas']['volt']} ok={out['ok']}")
    return out


def _safe(raw: str) -> str:
    """Return a printable SCPI float from a readback string."""
    try:
        return f"{float(raw):.3f}"
    except (TypeError, ValueError):
        return "0.000"


@app.post("/api/poweroff")
def poweroff():
    """Shut the Pi down safely: abort any running curve, park the supply at
    0 V / output off, then trigger the OS shutdown a moment after this reply
    reaches the panel. Demo mode never shuts down."""
    if _is_demo():
        db.add_event("poweroff_demo", "demo — no real shutdown")
        return {"ok": True, "demo": True}
    if _running():
        _run["stopped"] = True
        for _ in range(12):                  # give the runner up to ~2.4 s
            if not _running():
                break
            time.sleep(0.2)
    try:                                     # supply to a safe state
        _scpi("VOLT 0")
        _scpi("OUTP OFF")
    except Exception:
        pass
    db.add_event("poweroff", "safe shutdown requested")
    subprocess.Popen(
        ["sudo", "-n", "/usr/local/bin/pi-poweroff.sh"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "demo": False}


@app.put("/api/settings")
def update_settings(s: Settings):
    if s.language not in ("en", "ru", "zh"):
        raise HTTPException(422, "language must be en, ru or zh")
    if s.mode not in ("device", "emulator"):
        raise HTTPException(422, "mode must be device or emulator")
    old = load_settings()
    save_settings(s.model_dump())
    # reconnect required if connection params changed
    if (old["port"], old["baud"], old["mode"]) != (s.port, s.baud, s.mode) and _ser is not None:
        disconnect()
        return {"ok": True, "reconnect_needed": True}
    return {"ok": True}


@app.get("/api/events")
def events(limit: int = 30):
    return db.list_events(min(limit, 200))


# ---- curve sequencer ---------------------------------------------------
def _curve_meta() -> dict:
    if not _curve["points"]:
        return {"loaded": False}
    pts = _curve["points"]
    return {
        "loaded": True,
        "name": _curve["name"],
        "points": len(pts),
        "duration": pts[-1][0],
        "params": _curve["params"],
    }


def _running() -> bool:
    t = _run["task"]
    return t is not None and not t.done()


@app.get("/api/curve")
def get_curve(full: bool = False):
    meta = _curve_meta()
    if full and meta["loaded"]:
        meta["pts"] = [[t, v, i] for (t, v, i) in _curve["points"]]
    return meta


@app.post("/api/curve")
async def upload_curve(request: Request, name: str = "curve.csv"):
    if _running():
        raise HTTPException(409, "stop the run first")
    body = (await request.body()).decode(errors="ignore")
    if not body.strip():
        raise HTTPException(422, "empty file")
    try:
        parsed = parse_curve(body, *_limits())
    except ValueError as e:
        raise HTTPException(422, str(e))
    _curve.update(name=name, points=parsed["points"], params=parsed["params"])
    db.save_curve(name, body)
    db.add_event("curve_load", f'{name}: {len(parsed["points"])} pts')
    return _curve_meta()


@app.delete("/api/curve")
def delete_curve():
    if _running():
        raise HTTPException(409, "stop the run first")
    _curve.update(name=None, points=None, params={})
    db.clear_curve()
    db.add_event("curve_delete")
    return {"ok": True}


@app.post("/api/curve/start")
async def curve_start():
    if not _curve["points"]:
        raise HTTPException(404, "no curve loaded")
    if _running():
        return {"ok": True, "already": True}
    _run["stopped"] = False
    _run["started"] = time.time()
    _run["task"] = asyncio.create_task(_run_curve())
    return {"ok": True}


async def _run_curve():
    pts, prm = _curve["points"], _curve["params"]
    loops = prm["loop"] if prm["loop"] > 0 else 10 ** 9
    dur = pts[-1][0]
    err = None
    db.add_event("curve_start", f'{_curve["name"]} x{prm["loop"] or "inf"}')
    _meas.update(volt=None, curr=None)
    try:
        _scpi("OUTP ON")                     # pure write — no readback
        for _ in range(loops):
            t0 = time.time()
            tick = 0
            while True:
                if _run["stopped"]:
                    return
                el = time.time() - t0
                v, i = interp(pts, min(el, dur))
                _scpi(f"VOLT {v:.3f}")       # pure write, NO read after
                _scpi(f"CURR {i:.3f}")
                tick += 1
                if tick % 2 == 0:            # real feedback: MEAS every ~0.4 s
                    try:
                        _meas["volt"] = float(_scpi("MEAS:VOLT?", timeout=0.8) or 0)
                        _meas["curr"] = float(_scpi("MEAS:CURR?", timeout=0.8) or 0)
                    except Exception:
                        pass                 # keep last known values
                if el >= dur:
                    break
                await asyncio.sleep(0.2)
    except Exception as e:
        err = str(e)
    finally:
        if err or _run["stopped"] or prm["end"] != "hold":
            try:
                _scpi("OUTP OFF")
            except Exception:
                pass
        db.add_event("curve_error", err) if err else db.add_event(
            "curve_stop", f'{_curve["name"]} after {time.time() - _run["started"]:.0f}s'
        )
        _run["stopped"] = False


@app.post("/api/curve/stop")
async def curve_stop():
    if not _running():
        return {"ok": True}
    _run["stopped"] = True
    try:
        await asyncio.wait_for(asyncio.shield(_run["task"]), timeout=1.5)
    except Exception:
        pass
    return {"ok": True}


@app.get("/api/curve/progress")
def curve_progress():
    if not _running():
        return {"running": False, **_curve_meta()}
    dur = _curve["points"][-1][0]
    el = time.time() - _run["started"]
    lap = int(el // dur) + 1 if dur > 0 else 1
    pos = (el % dur) if _curve["params"]["loop"] != 1 else min(el, dur)
    v, i = interp(_curve["points"], pos)
    return {
        "running": True, "elapsed": el, "duration": dur,
        "lap": lap, "volt": v, "curr": i,
        "meas_volt": _meas["volt"], "meas_curr": _meas["curr"],
        **_curve_meta(),
    }


# ---- static frontend (mounted last) ----------------------------------
app.mount("/", StaticFiles(directory="../frontend", html=True), name="ui")
