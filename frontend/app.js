/* AKIP-1144 panel — vanilla JS, no dependencies. */
"use strict";

const $ = (id) => document.getElementById(id);

/* ---- i18n: labels live in lang/<code>.json --------------------------- */
const LANG = { current: "en", dict: {}, cache: {} };   // cache: code -> dict

const t = (key) => LANG.dict[key] ?? key;

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

async function loadManifest() {
  const list = await fetchJson("lang/index.json");
  $("set-language").innerHTML = list
    .map((l) => `<option value="${l.code}">${l.name}</option>`)
    .join("");
  $("langLabel").textContent = list.map((l) => l.label).join(" · ");
}

async function setLang(code) {
  LANG.current = code;
  if (!LANG.cache[code]) {
    try {
      LANG.cache[code] = await fetchJson(`lang/${code}.json`);
    } catch {
      LANG.cache[code] = {};           // fall back to English below
    }
  }
  LANG.dict = { ...LANG.cache.en, ...LANG.cache[code] };
  document.documentElement.lang = code;
  applyLang();
  render();
}

function applyLang() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
}

/* ---- helpers --------------------------------------------------------- */
function toast(msg, ms = 3000) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), ms);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.text()).slice(0, 160));
  return res.json();
}

const timeStr = (ts) => new Date(ts * 1000).toLocaleTimeString();

/* ---- status ---------------------------------------------------------- */
let state = { connected: false, demo: false };

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    state = s;
    $("set-language").value = s.settings.language;
    $("set-port").value = s.settings.port;
    $("set-baud").value = s.settings.baud;
    if ($("set-mode").value !== s.settings.mode) $("set-mode").value = s.settings.mode;
    updateDeviceFields();
    if (LANG.current !== s.settings.language) await setLang(s.settings.language);
  } catch {
    state = { connected: false, demo: false };
  }
  render();
}

function render() {
  $("dot").className = "dot " + (state.connected ? "on" : state.demo ? "demo" : "off");
  $("status").textContent = state.connected
    ? `${t("connected")} — ${state.idn || ""}`
    : t("status");
  $("btn-connect").disabled = state.connected;
  $("btn-disconnect").disabled = !state.connected;
  $("btn-test").disabled = !state.connected;
}

/* ---- history ---------------------------------------------------------- */
async function refreshEvents() {
  try {
    const events = await api("/api/events?limit=20");
    const ul = $("events");
    ul.innerHTML = events.length
      ? events
          .map(
            (e) =>
              `<li><span class="t">${timeStr(e.ts)}</span> ` +
              `<b>${e.kind}</b> ${e.detail ? "— " + e.detail : ""}</li>`
          )
          .join("")
      : `<li class="muted">${t("empty")}</li>`;
  } catch {
    /* backend down — ignore */
  }
}

/* ---- buttons ----------------------------------------------------------- */
$("btn-connect").addEventListener("click", async () => {
  try {
    const r = await api("/api/connect", { method: "POST" });
    toast((r.emulated ? "[EMULATOR] " : "") + r.idn);
  } catch (e) {
    toast("✗ " + e.message);
  }
  refreshStatus();
  refreshEvents();
  updateCurve();
});

$("btn-disconnect").addEventListener("click", async () => {
  try {
    await api("/api/disconnect", { method: "POST" });
  } catch (e) {
    toast("✗ " + e.message);
  }
  refreshStatus();
  refreshEvents();
  updateCurve();
});

$("btn-test").addEventListener("click", async () => {
  try {
    const r = await api("/api/test", { method: "POST" });
    toast(`✓ ${r.idn} | ${r.volt} V | ${r.curr} A`);
  } catch (e) {
    toast("✗ " + e.message);
  }
  refreshEvents();
});

/* ---- drawers ------------------------------------------------------------- */
function openDrawer(el, open) {
  el.classList.toggle("hidden", !open);
  $("overlay").classList.toggle("hidden", !open);
}
function closeDrawers() {
  openDrawer($("drawer"), false);
  openDrawer($("pdrawer"), false);
}

$("btn-settings").addEventListener("click", () => openDrawer($("drawer"), true));
$("btn-close").addEventListener("click", () => openDrawer($("drawer"), false));
$("overlay").addEventListener("click", closeDrawers);

$("btn-save").addEventListener("click", async () => {
  try {
    const body = {
      language: $("set-language").value,
      port: $("set-port").value.trim() || "auto",
      baud: parseInt($("set-baud").value, 10),
      mode: $("set-mode").value,
    };
    const r = await api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    toast(t("save") + " ✓");
    closeDrawers();
    if (r.reconnect_needed) toast("connection params changed — reconnect", 4000);
  } catch (e) {
    toast("✗ " + e.message);
  }
  refreshStatus();
});

/* live language preview while choosing */
$("set-language").addEventListener("change", () => setLang($("set-language").value));

/* show port/baud only when a real device is selected */
function updateDeviceFields() {
  $("device-fields").classList.toggle("gone", $("set-mode").value === "emulator");
}
$("set-mode").addEventListener("change", updateDeviceFields);

/* ---- curve program -------------------------------------------------------- */
let lastProgress = null;

async function updateCurve() {
  // skip only when neither the Program window nor the chart is open
  if ($("pdrawer").classList.contains("hidden") &&
      $("chart-view").classList.contains("hidden")) return;
  let p;
  try {
    p = await api("/api/curve/progress");
  } catch {
    return;
  }
  lastProgress = p;
  updateCursor();
  $("curve-status").classList.toggle("gone", !p.loaded);
  $("btn-run").disabled = p.running || !state.connected || !p.loaded;
  $("btn-stop").disabled = !p.loaded;
  if (!p.loaded) return;

  const key = `${p.name}:${p.points}`;
  if (key !== miniKey) { miniKey = key; buildMini(); }

  $("cs-info").textContent =
    `${p.name} — ${p.points} ${t("points")} · ${p.duration} ${t("duration")}` +
    ` · loop=${p.params.loop} · end=${p.params.end}`;
  const badge = $("cs-state");
  badge.textContent = p.running ? t("running") : t("idle");
  badge.className = "cs-badge " + (p.running ? "running" : "idle");

  if (p.running) {
    const pct = p.duration ? Math.min(100, ((p.elapsed % p.duration) / p.duration) * 100) : 0;
    $("cs-bar").style.width = pct + "%";
    $("cs-v").textContent = p.volt.toFixed(2);
    $("cs-i").textContent = p.curr.toFixed(2);
    $("cs-lap").textContent = `${t("lap")} #${p.lap}`;
    const pos = p.params.loop !== 1 ? p.elapsed % p.duration : Math.min(p.elapsed, p.duration);
    $("cs-time").textContent = `t=${pos.toFixed(1)}/${p.duration} s`;
    updateMini(pos, true);
  } else {
    $("cs-bar").style.width = "0%";
    $("cs-lap").textContent = "";
    $("cs-time").textContent = "";
    updateMini(0, false);
  }
}

$("btn-program").addEventListener("click", () => {
  openDrawer($("pdrawer"), true);
  updateCurve();
});
$("btn-pclose").addEventListener("click", () => openDrawer($("pdrawer"), false));

$("btn-load").addEventListener("click", () => $("curve-file").click());
$("curve-file").addEventListener("change", async () => {
  const f = $("curve-file").files[0];
  if (!f) return;
  try {
    const m = await api(`/api/curve?name=${encodeURIComponent(f.name)}`, {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: await f.text(),
    });
    toast(`✓ ${m.name}: ${m.points} ${t("points")}`);
  } catch (e) {
    toast("✗ " + e.message);
  }
  $("curve-file").value = "";
  updateCurve();
});

$("btn-run").addEventListener("click", async () => {
  try {
    await api("/api/curve/start", { method: "POST" });
  } catch (e) {
    toast("✗ " + e.message);
  }
  updateCurve();
});

$("btn-stop").addEventListener("click", async () => {
  try {
    await api("/api/curve/stop", { method: "POST" });
  } catch (e) {
    toast("✗ " + e.message);
  }
  setTimeout(updateCurve, 300);
});

/* shared: interpolate (v, i) at time pos */
function interpAt(P, pos) {
  let j = 0;
  while (j < P.length - 2 && P[j + 1][0] < pos) j++;
  const [t0, v0, i0] = P[j], [t1, v1, i1] = P[j + 1];
  const f = t1 > t0 ? Math.max(0, Math.min(1, (pos - t0) / (t1 - t0))) : 0;
  return { v: v0 + (v1 - v0) * f, i: i0 + (i1 - i0) * f };
}

/* ---- fullscreen curve chart ------------------------------------------------ */
let chartPts = null;   // [[t,v,i],...] of the loaded curve
let chartScale = null; // { dur, vMin, vRange, iMin, iRange }

function openChart() {
  $("chart-view").classList.remove("hidden");
  buildChart();
}

function closeChart() {
  $("chart-view").classList.add("hidden");
}

async function buildChart() {
  let m;
  try {
    m = await api("/api/curve?full=1");
  } catch {
    return;
  }
  $("cv-title").textContent = m.loaded ? m.name : t("curve-none");
  chartPts = m.loaded ? m.pts : null;
  $("cv-cursor").setAttribute("opacity", 0);
  $("cv-time").textContent = "";
  if (!chartPts) {
    $("cv-v").setAttribute("points", "");
    $("cv-i").setAttribute("points", "");
    $("cv-ticks").innerHTML = "";
    ["cv-vmax", "cv-vmin", "cv-imax", "cv-imin"].forEach((id) => ($(id).textContent = ""));
    chartScale = null;
    return;
  }
  const dur = chartPts[chartPts.length - 1][0] || 1;
  const vs = chartPts.map((p) => p[1]), is = chartPts.map((p) => p[2]);
  const vMin = Math.min(...vs), iMin = Math.min(...is);
  const vRange = Math.max(Math.max(...vs) - vMin, 0.001);
  const iRange = Math.max(Math.max(...is) - iMin, 0.001);
  chartScale = { dur, vMin, vRange, iMin, iRange };
  // Both curves share one plot area, each normalized to its own min..max,
  // so the voltage maximum and the current maximum sit on the same level (y=4).
  const pt = (vals, min, range) =>
    chartPts
      .map(([x], k) => {
        const px = (x / dur) * 100;
        const py = 56 - ((vals[k] - min) / range) * 52;   // y 4..56
        return `${px.toFixed(2)},${py.toFixed(2)}`;
      })
      .join(" ");
  $("cv-v").setAttribute("points", pt(vs, vMin, vRange));
  $("cv-i").setAttribute("points", pt(is, iMin, iRange));
  // numbers only on the axes: V on the left edge, I on the right edge
  $("cv-vmax").textContent = Math.max(...vs).toFixed(2) + " V";
  $("cv-vmin").textContent = vMin.toFixed(2) + " V";
  $("cv-imax").textContent = Math.max(...is).toFixed(2) + " A";
  $("cv-imin").textContent = iMin.toFixed(2) + " A";
  // time marks on the axis
  $("cv-ticks").innerHTML = [0, 0.25, 0.5, 0.75, 1]
    .map((f) => `<span>${(dur * f).toFixed(f ? 1 : 0)}s</span>`)
    .join("");
  updateCursor();
}

function updateCursor() {
  if (!chartPts || !chartScale || $("chart-view").classList.contains("hidden")) return;
  // reuse the last progress values fetched by updateCurve()
  $("cv-clock").textContent = new Date().toLocaleTimeString();  // system time
  if (!lastProgress || !lastProgress.running) {
    $("cv-cursor").setAttribute("opacity", 0);
    ["cv-dot-v", "cv-dot-i"].forEach((id) => $(id).setAttribute("opacity", 0));
    $("cv-time").textContent = "";
    return;
  }
  const { dur, vMin, vRange, iMin, iRange } = chartScale;
  const pos = lastProgress.params.loop !== 1
    ? lastProgress.elapsed % dur
    : Math.min(lastProgress.elapsed, dur);
  const { v, i } = interpAt(chartPts, pos);
  const x = (pos / dur) * 100;
  $("cv-cursor").setAttribute("opacity", 0.7);
  $("cv-cursor").setAttribute("x1", x);
  $("cv-cursor").setAttribute("x2", x);
  const dotV = $("cv-dot-v"), dotI = $("cv-dot-i");
  dotV.setAttribute("cx", x);
  dotV.setAttribute("cy", 56 - ((v - vMin) / vRange) * 52);
  dotI.setAttribute("cx", x);
  dotI.setAttribute("cy", 56 - ((i - iMin) / iRange) * 52);
  dotV.setAttribute("opacity", 1);
  dotI.setAttribute("opacity", 1);
  $("cv-time").textContent = `${v.toFixed(2)} V · ` +
    `${i.toFixed(2)} A · t=${pos.toFixed(1)}/${dur} s`;
}

/* mini live chart inside the status group */
let mini = null;      // { P, dur, vmin, imin, vRange, iRange }
let miniKey = "";

async function buildMini() {
  try {
    const m = await api("/api/curve?full=1");
    if (!m.loaded) { mini = null; return; }
    const P = m.pts;
    const dur = P[P.length - 1][0] || 1;
    const vs = P.map((p) => p[1]), is = P.map((p) => p[2]);
    const vmin = Math.min(...vs), imin = Math.min(...is);
    const vRange = Math.max(Math.max(...vs) - vmin, 0.001);
    const iRange = Math.max(Math.max(...is) - imin, 0.001);
    const mk = (vals, min, range, yTop, yBot) =>
      P.map(([x], k) => {
        const px = (x / dur) * 100;
        const py = yBot - ((vals[k] - min) / range) * (yBot - yTop);
        return `${px.toFixed(2)},${py.toFixed(2)}`;
      }).join(" ");
    $("cs-mini-v").setAttribute("points", mk(vs, vmin, vRange, 2, 13));
    $("cs-mini-i").setAttribute("points", mk(is, imin, iRange, 17, 28));
    mini = { P, dur, vmin, imin, vRange, iRange };
  } catch {
    mini = null;
  }
}

function updateMini(pos, running) {
  if (!mini) return;
  if (!running) {
    ["cs-dot-v", "cs-dot-i"].forEach((id) => $(id).setAttribute("opacity", 0));
    return;
  }
  const { dur, vmin, imin, vRange, iRange } = mini;
  const { v, i } = interpAt(mini.P, pos);
  const cx = (pos / dur) * 100;
  const dotV = $("cs-dot-v"), dotI = $("cs-dot-i");
  dotV.setAttribute("cx", cx);
  dotV.setAttribute("cy", 13 - ((v - vmin) / vRange) * 11);
  dotI.setAttribute("cx", cx);
  dotI.setAttribute("cy", 28 - ((i - imin) / iRange) * 11);
  dotV.setAttribute("opacity", 1);
  dotI.setAttribute("opacity", 1);
}

$("btn-chart").addEventListener("click", openChart);
$("btn-cv-close").addEventListener("click", closeChart);
$("btn-cv-full").addEventListener("click", () => {
  const el = $("chart-view");
  try {
    if (document.fullscreenElement) document.exitFullscreen();
    else el.requestFullscreen().catch(() => {});
  } catch {}
});

setInterval(updateCurve, 700);

/* ---- init ---- */
loadManifest().catch(() => {});
refreshStatus();
refreshEvents();
updateCurve();
