"""SCPI emulator of the AKIP-1144-x supply — test without hardware.

Implements the small pyserial-like interface the backend expects:
    write(bytes), readline() -> bytes, reset_input_buffer(), timeout, close()

Simulated behaviour:
  * VOLT <v> / CURR <a> setpoints, VOLT? / CURR? readback
  * OUTP ON | OFF (default off), *IDN?, *CLS
  * MEAS:VOLT? — soft-start ramp toward the setpoint when output is on
  * Constant-resistance load (EMU_LOAD_R ohm, default 10):
      current = V / R, clamped by the current setpoint -> CV and CC modes
  * Small measurement noise

Enable with:  DEMO=1
"""

import os
import random
import time


class EmulatorSerial:
    def __init__(self):
        self.timeout = 2.0
        self._rx = b""
        self._idn = "EMU AKIP-1144-600-10 EMULATED"
        self.sp_v = 0.0        # voltage setpoint
        self.sp_c = 1.0        # current setpoint
        self.out = False       # output state
        self._v = 0.0          # measured voltage
        self._t = time.time()  # last measurement time (for the ramp)
        self.load_r = float(os.environ.get("EMU_LOAD_R", "10"))

    # ---- pyserial-like API -------------------------------------------
    def reset_input_buffer(self):
        self._rx = b""

    def close(self):
        self.out = False

    def write(self, data: bytes):
        for line in data.decode(errors="ignore").splitlines():
            if line.strip():
                self._cmd(line.strip())
        return len(data)

    def readline(self) -> bytes:
        if not self._rx:
            time.sleep(0.02)
            return b"\n"
        out, self._rx = self._rx, b""
        return out

    # ---- SCPI brain ----------------------------------------------------
    def _cmd(self, line: str):
        u = line.upper()
        if u == "*IDN?":
            self._reply(self._idn)
        elif u == "*CLS":
            pass
        elif u == "VOLT?":
            self._reply(f"{self.sp_v:.3f}")
        elif u == "CURR?":
            self._reply(f"{self.sp_c:.3f}")
        elif u.startswith("VOLT"):
            self._set_float(u, "VOLT", "sp_v")
        elif u.startswith("CURR"):
            self._set_float(u, "CURR", "sp_c")
        elif u == "OUTP ON" or u == "OUTP 1":
            self.out = True
        elif u == "OUTP OFF" or u == "OUTP 0":
            self.out = False
        elif u == "MEAS:VOLT?":
            self._reply(f"{self._measure()['v']:.3f}")
        elif u == "MEAS:CURR?":
            self._reply(f"{self._measure()['i']:.3f}")
        elif u == "MEAS:POW?":
            m = self._measure()
            self._reply(f"{m['v'] * m['i']:.3f}")
        else:
            self._reply("ERROR")  # unknown command

    def _reply(self, text: str):
        self._rx = (text + "\n").encode()

    def _set_float(self, u: str, key: str, attr: str):
        try:
            value = max(0.0, float(u.replace(key, "").strip()))
        except ValueError:
            self._reply("ERROR")
            return
        setattr(self, attr, value)

    def _measure(self) -> dict:
        """Advance the simulation and return (v, i)."""
        now = time.time()
        dt = min(now - self._t, 1.0)
        self._t = now

        target = self.sp_v if self.out else 0.0
        # soft-start: exponential approach, ~0.3 s time constant
        self._v += (target - self._v) * min(1.0, dt / 0.3)
        v = max(0.0, self._v)

        # constant-resistance load, clamped by the current setpoint (CC mode)
        i_load = v / self.load_r if self.load_r > 0 else 0.0
        i = min(i_load, self.sp_c if self.out else 0.0)
        if i < i_load:                 # current-limited -> voltage sags
            v = i * self.load_r
            self._v = v

        v *= random.uniform(0.999, 1.001)   # measurement noise
        i *= random.uniform(0.995, 1.005)
        return {"v": v, "i": i}
