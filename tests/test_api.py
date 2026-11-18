"""API-level integration tests — pure HTTP, no browser, fast.

Exercises the feedback loop: send a voltage → read back what the device
acknowledged → measure the real output.
"""
import json
import time
import urllib.error
import urllib.request


def _post(url, data=None, timeout=15):
    req = urllib.request.Request(url, data=data or b"", method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _get(url):
    return json.loads(urllib.request.urlopen(url, timeout=15).read())


def test_verify_needs_connection(base_url):
    try:
        _post(f"{base_url}/api/verify")
        raise AssertionError("verify must fail when not connected")
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_verify_send_and_readback(base_url):
    _post(f"{base_url}/api/connect")
    r = _post(f"{base_url}/api/verify")
    assert r.get("ok") is True, r
    # the device acknowledged exactly the setpoints we sent
    assert abs(float(r["ack"]["volt"]) - r["set"]["volt"]) < 0.05
    assert abs(float(r["ack"]["curr"]) - r["set"]["curr"]) < 0.05
    # and the measured output matches (soft-start/noise tolerance)
    assert abs(float(r["meas"]["volt"]) - r["set"]["volt"]) < 0.25
    _post(f"{base_url}/api/disconnect")


def test_poweroff_is_demo_safe(base_url):
    r = _post(f"{base_url}/api/poweroff")
    assert r["ok"] is True and r["demo"] is True
    # the demo server must still be alive afterwards
    assert _get(f"{base_url}/api/status")["demo"] is True


def test_curve_progress_returns_measured_values(base_url):
    csv = b"# loop=1\n# end=off\n0,2.0,0.2\n3,2.0,0.2\n"
    req = urllib.request.Request(
        f"{base_url}/api/curve?name=t.csv", data=csv,
        headers={"Content-Type": "text/plain"}, method="POST")
    urllib.request.urlopen(req, timeout=10)
    _post(f"{base_url}/api/connect")
    _post(f"{base_url}/api/curve/start")
    try:
        for _ in range(20):
            p = _get(f"{base_url}/api/curve/progress")
            if p.get("meas_volt") is not None:
                assert abs(p["meas_volt"] - 2.0) < 0.3, p
                return
            time.sleep(0.25)
        raise AssertionError("no measured voltage in /api/curve/progress within 5 s")
    finally:
        _post(f"{base_url}/api/curve/stop")
        _post(f"{base_url}/api/disconnect")

def test_meters_demo_polling_and_recording(base_url):
    s = _get(f"{base_url}/api/meters")
    assert len(s["meters"]) == 2
    m1, m2 = s["meters"]
    assert (m1["role"], m1["connected"]) == ("volt", True)
    assert (m2["role"], m2["connected"]) == ("curr", True)
    assert isinstance(m1["value"], float) and isinstance(m2["value"], float)

    r = _post(f"{base_url}/api/meters/record/start")
    assert r["ok"] and r["file_name"].endswith(".csv")
    time.sleep(1.2)
    r = _post(f"{base_url}/api/meters/record/stop")
    fname = r["file_name"]
    try:
        logs = _get(f"{base_url}/api/meters/logs")
        assert any(l["name"] == fname for l in logs), logs
        body = urllib.request.urlopen(
            f"{base_url}/api/meters/logs/{fname}", timeout=10).read().decode()
        assert body.startswith("timestamp,meter,function,value,unit")
        assert body.count("\n") > 5, body
    finally:
        if r.get("file"):
            try:
                import os
                os.remove(r["file"])
            except OSError:
                pass
