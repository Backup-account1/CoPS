"""Browser integration tests: real Chromium clicks through the whole panel.

Runs against a demo-mode server (fixture in conftest.py), no hardware needed.

    python3 -m pytest tests/test_e2e_ui.py -v            # headless
    HEADED=1 python3 -m pytest tests/test_e2e_ui.py -v   # visible window
"""
import re

import pytest
from playwright.sync_api import expect, sync_playwright

from conftest import REPO, SLOW_MO, chrome_executable, headed

SAMPLE_CSV = REPO / "samples" / "demo_curve.csv"


@pytest.fixture(scope="module")
def page(base_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome_executable(),
            headless=not headed(),
            slow_mo=SLOW_MO,          # visible, human-paced clicks
            args=["--no-sandbox"],
        )
        pg = browser.new_page(viewport={"width": 412, "height": 850})  # phone-ish
        pg.goto(base_url, wait_until="networkidle")
        yield pg, base_url
        browser.close()


def wait_status(page):
    """The app polls /api/status on load; wait for the header to be ready."""
    expect(page.locator("#status")).not_to_have_text("", timeout=5000)


def ensure_connected(page):
    page.locator("#btn-connect").click()
    expect(page.locator("#dot")).to_have_class("dot on", timeout=10_000)


# ---------------------------------------------------------------- load -----
def test_page_loads_with_tiles(page):
    pg, _ = page
    wait_status(pg)
    for btn in ("#btn-connect", "#btn-disconnect", "#btn-test",
                "#btn-settings", "#btn-program"):
        expect(pg.locator(btn)).to_be_visible()
    # safety: Test/Disconnect locked while disconnected
    expect(pg.locator("#btn-disconnect")).to_be_disabled()
    expect(pg.locator("#btn-test")).to_be_disabled()
    expect(pg.locator("#dot")).to_have_class("dot demo")


# ---------------------------------------------------------- connect flow ---
def test_connect_test_disconnect(page):
    pg, _ = page
    ensure_connected(pg)
    # header shows the emulator IDN
    expect(pg.locator("#status")).to_contain_text("EMU AKIP-1144", timeout=8000)
    expect(pg.locator("#btn-connect")).to_be_disabled()

    # Test -> toast with live values
    pg.locator("#btn-test").click()
    expect(pg.locator("#toast")).to_contain_text("V", timeout=5000)

    # Disconnect -> header back to "disconnected"
    pg.locator("#btn-disconnect").click()
    expect(pg.locator("#dot")).to_have_class("dot demo", timeout=8000)
    expect(pg.locator("#btn-test")).to_be_disabled()


# ------------------------------------------------------------- settings ----
def test_settings_language_switch_and_save(page):
    pg, base_url = page
    pg.locator("#btn-settings").click()
    expect(pg.locator("#drawer")).to_be_visible()

    # switch to Russian: every data-i18n label re-renders instantly
    pg.locator("#set-language").select_option("ru")
    expect(pg.locator("main span[data-i18n='connect']")).to_have_text("Подключить")

    # save -> drawer closes, language persisted
    pg.locator("#btn-save").click()
    expect(pg.locator("#drawer")).to_have_class("hidden", timeout=5000)

    # reopen and switch back to English the same way a user would
    pg.locator("#btn-settings").click()
    pg.locator("#set-language").select_option("en")
    expect(pg.locator("main span[data-i18n='connect']")).to_have_text("Connect")
    pg.locator("#btn-save").click()
    expect(pg.locator("#drawer")).to_have_class("hidden", timeout=5000)


def test_settings_mode_switch_hides_device_fields(page):
    pg, _ = page
    pg.locator("#btn-settings").click()
    expect(pg.locator("#drawer")).to_be_visible()
    pg.locator("#set-mode").select_option("device")
    expect(pg.locator("#device-fields")).to_be_visible()
    pg.locator("#set-mode").select_option("emulator")
    expect(pg.locator("#device-fields")).to_have_class("gone")
    pg.locator("#btn-close").click()
    expect(pg.locator("#drawer")).to_have_class("hidden")


# --------------------------------------------------------------- program ---
def test_program_load_start_stop_chart(page):
    pg, _ = page
    ensure_connected(pg)
    pg.locator("#btn-program").click()
    expect(pg.locator("#pdrawer")).to_be_visible()

    # load the commented sample CSV through the real file input
    pg.locator("#curve-file").set_input_files(str(SAMPLE_CSV))
    expect(pg.locator("#curve-status")).not_to_have_class("gone", timeout=5000)
    expect(pg.locator("#cs-info")).to_contain_text("demo_curve.csv")
    expect(pg.locator("#cs-info")).to_contain_text("7")
    expect(pg.locator("#cs-state")).to_have_class("cs-badge idle")  # language-neutral

    # Start -> badge runs, live values move, progress bar fills
    pg.locator("#btn-run").click()
    expect(pg.locator("#cs-state")).to_have_class("cs-badge running", timeout=8000)
    expect(pg.locator("#cs-bar")).to_have_attribute(
        "style", re.compile(r"width:\s*[\d.]+%"), timeout=5000)
    # mini chart built from the loaded curve (first point: v=0 -> y bottom)
    expect(pg.locator("#cs-mini-v")).to_have_attribute(
        "points", re.compile(r"^0\.00,13\.00"), timeout=5000)

    # Stop -> idle again
    pg.locator("#btn-stop").click()
    expect(pg.locator("#cs-state")).to_have_class("cs-badge idle", timeout=8000)

    # fullscreen chart renders both curves + axis numbers + time ticks
    pg.locator("#btn-chart").click()
    expect(pg.locator("#chart-view")).to_be_visible()
    expect(pg.locator("#cv-title")).to_have_text("demo_curve.csv")
    expect(pg.locator("#cv-v")).to_have_attribute("points", re.compile(r".+"), timeout=5000)
    expect(pg.locator("#cv-i")).to_have_attribute("points", re.compile(r".+"))
    expect(pg.locator("#cv-vmax")).to_contain_text("24.00 V")
    expect(pg.locator("#cv-vmin")).to_contain_text("0.00 V")
    expect(pg.locator("#cv-imax")).to_contain_text("2.00 A")
    expect(pg.locator("#cv-ticks")).to_contain_text("0s")
    expect(pg.locator("#cv-ticks")).to_contain_text("30.0s")
    pg.locator("#btn-cv-close").click()
    expect(pg.locator("#chart-view")).to_have_class("hidden")

    pg.locator("#btn-pclose").click()
    expect(pg.locator("#pdrawer")).to_have_class("hidden")


# --------------------------------------------------------------- history ---
def test_history_shows_events(page):
    pg, _ = page
    expect(pg.locator("#events li").first).to_contain_text("connect", timeout=5000)
