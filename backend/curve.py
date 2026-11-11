"""CSV curve parser + linear interpolation for the supply sequencer.

File format (one file, both curves — voltage and current share the timeline):

    # loop=2        <- repeats (0 = infinite), default 1
    # end=off       <- "off" or "hold" at the end, default off
    t,v,i
    0,0,0.5
    5,12,0.5
    10,12,2

Separators: comma, semicolon or tab. A non-numeric first line is treated as a
header. Values are clamped to the safety limits.
"""

import re
from bisect import bisect_right


def parse_curve(text: str, max_v: float = 610.0, max_c: float = 10.5) -> dict:
    params = {"loop": 1, "end": "off"}
    pts = []

    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            body = line.lstrip("# ").strip()
            if "=" in body:
                k, _, v = body.partition("=")
                k, v = k.strip().lower(), v.strip().lower()
                if k == "loop":
                    try:
                        params["loop"] = max(0, int(float(v)))
                    except ValueError:
                        pass
                elif k == "end" and v in ("off", "hold"):
                    params["end"] = v
            continue
        parts = re.split(r"[,;\t]+", line)
        try:
            t, v, i = float(parts[0]), float(parts[1]), float(parts[2])
        except (ValueError, IndexError):
            if not pts:
                continue  # header row
            raise ValueError(f"line {n}: expected t,v,i")
        if t < 0 or v < 0 or i < 0:
            raise ValueError(f"line {n}: negative value")
        if pts and t <= pts[-1][0]:
            raise ValueError(f"line {n}: time must strictly increase")
        pts.append((t, min(v, max_v), min(i, max_c)))

    if len(pts) < 2:
        raise ValueError("need at least 2 points")
    return {"points": pts, "params": params, "duration": pts[-1][0]}


def interp(points, t: float):
    """Linear interpolation of (v, i) at time t. Holds first/last value outside."""
    if t <= points[0][0]:
        return points[0][1], points[0][2]
    if t >= points[-1][0]:
        return points[-1][1], points[-1][2]
    ts = [p[0] for p in points]
    j = bisect_right(ts, t) - 1
    t0, v0, i0 = points[j]
    t1, v1, i1 = points[j + 1]
    f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
    return v0 + (v1 - v0) * f, i0 + (i1 - i0) * f
