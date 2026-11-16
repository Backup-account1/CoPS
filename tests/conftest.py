"""Fixtures: boot a demo-mode panel server on a free port, hand out base_url."""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"


def chrome_executable():
    """Prefer the Playwright-bundled chromium; env E2E_CHROME overrides."""
    return os.environ.get("E2E_CHROME") or None


def headed() -> bool:
    return bool(os.environ.get("HEADED"))


SLOW_MO = int(os.environ.get("SLOW_MO", "0"))  # ms between visible actions


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def base_url():
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "main:app",
            "--host", "127.0.0.1", "--port", str(port),
        ],
        cwd=BACKEND,
        env={**os.environ, "DEMO": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{url}/api/status", timeout=2)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("demo server did not start")
    yield url
    # leave settings clean for real use
    try:
        req = urllib.request.Request(
            f"{url}/api/settings",
            data=b'{"language": "en", "port": "auto", "baud": 9600, "mode": "emulator"}',
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        urllib.request.urlopen(req, timeout=5)
        urllib.request.urlopen(f"{url}/api/disconnect", timeout=5)
    except Exception:
        pass
    proc.terminate()
    proc.wait(timeout=10)
