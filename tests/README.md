# Panel tests

Browser integration tests (Playwright) that click through the whole panel UI
like a real user. They run against a **demo-mode** server started
automatically on a free port — no power supply or hardware needed.

## Run

```sh
pip3 install playwright pytest          # once
python3 -m playwright install chromium  # once (browser download)

tests/run_e2e.sh            # headless — no window, for CI
tests/run_e2e.sh headed     # visible — a Chromium window opens and
                            # you watch the mouse click the buttons
```

Or call pytest directly:

```sh
python3 -m pytest tests/test_e2e_ui.py -v                  # headless
HEADED=1 SLOW_MO=300 python3 -m pytest tests/test_e2e_ui.py -v   # visible, slow clicks
```

## Env switches

| Var        | Effect                                            |
| ---------- | ------------------------------------------------- |
| `HEADED=1` | show a real browser window (visible UI testing)   |
| `SLOW_MO`  | delay (ms) between actions; default **600** in headed, 0 headless |
| `E2E_CHROME` | path to an alternative Chromium/Chrome binary   |

In headed mode a **virtual cursor** (red arrow) glides to every button and a
red ripple marks each click, so you can follow the test like a user.

## What the 6 tests cover

1. **tiles** — all five main buttons render; Test/Disconnect locked while disconnected
2. **connect → test → disconnect** — header shows the emulator IDN, Test toast shows live V/A, safe state after disconnect
3. **language** — switch EN→RU and back through Settings; labels re-render and persist
4. **mode switch** — device fields hide in emulator mode
5. **program** — load `samples/demo_curve.csv`, Start (running badge, progress bar, mini chart), Stop, fullscreen chart with axes and time ticks
6. **history** — events log records the activity

## Notes

- The server under test is spawned by `tests/conftest.py` with `DEMO=1`
  (emulator, no USB device).
- Every run resets settings to English / emulator mode afterwards.
