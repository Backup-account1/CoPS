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
