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
from playwright.sync_api import Locator

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"


def chrome_executable():
    """Prefer the Playwright-bundled chromium; env E2E_CHROME overrides."""
    return os.environ.get("E2E_CHROME") or None


def headed() -> bool:
    return bool(os.environ.get("HEADED"))


# ms between Playwright actions; headed runs default to a slow, watchable 600
SLOW_MO = int(os.environ.get("SLOW_MO", "600" if bool(os.environ.get("HEADED")) else "0"))


CURSOR_JS = """
(() => {
  if (document.getElementById('e2e-cursor')) return;
  const css = document.createElement('style');
  css.textContent = `
    #e2e-cursor{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;
      transition:transform .28s cubic-bezier(.2,.7,.3,1);will-change:transform;
      filter:drop-shadow(0 1px 2px rgba(0,0,0,.45));}
    #e2e-ping{position:fixed;z-index:2147483646;pointer-events:none;width:26px;height:26px;
      margin:-13px 0 0 -13px;border:3px solid #ff3b30;border-radius:50%;
      animation:e2e-ping .45s ease-out forwards;}
    @keyframes e2e-ping{from{opacity:.9;transform:scale(.3)}to{opacity:0;transform:scale(1.6)}}
  `;
  (document.head || document.documentElement).appendChild(css);
  const c = document.createElement('div');
  c.id = 'e2e-cursor';
  c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24">'
    + '<path d="M5.5 3.21V20.8c0 .45.54.67.85.35l4.86-4.86a.5.5 0 0 1 .35-.15h6.87'
    + 'c.45 0 .67-.54.35-.85L6.35 2.85a.5.5 0 0 0-.85.36z" '
    + 'fill="#ff3b30" stroke="#fff" stroke-width="1.2" stroke-linejoin="round"/></svg>';
  document.documentElement.appendChild(c);
  window.__cursor = (x, y) => { c.style.transform = `translate(${x - 5}px, ${y - 3}px)`; };
  window.__ping = (x, y) => {
    const p = document.createElement('div');
    p.id = 'e2e-ping';
    p.style.left = `${x}px`; p.style.top = `${y}px`;
    document.documentElement.appendChild(p);
    setTimeout(() => p.remove(), 500);
  };
})();
"""


def install_virtual_cursor(pg):
    """Headed runs only: a red arrow glides to every button before the click.

    Survives page reloads (init script) and patches Locator.click /
    Locator.select_option, so the tests themselves stay unchanged.
    """
    pg.add_init_script(CURSOR_JS)
    if getattr(Locator, "_cursor_patch", False):
        return
    orig_click, orig_select = Locator.click, Locator.select_option

    def _aim(loc):
        try:
            box = loc.bounding_box(timeout=2000)
        except Exception:
            return None
        if not box:
            return None
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        pg.evaluate("([x, y]) => { if (window.__cursor) window.__cursor(x, y); }", [x, y])
        pg.wait_for_timeout(280)            # let the arrow glide into place
        return x, y

    def click(self, *a, **k):
        pos = _aim(self)
        if pos:                             # ripple where the click lands
            pg.evaluate("([x, y]) => { if (window.__ping) window.__ping(x, y); }",
                        list(pos))
        return orig_click(self, *a, **k)

    def select_option(self, *a, **k):
        _aim(self)
        return orig_select(self, *a, **k)

    Locator.click = click
    Locator.select_option = select_option
    Locator._cursor_patch = True


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
