from __future__ import annotations

# A single self-contained page: inline CSS + JS, no CDN or external assets,
# because job sites frequently have no internet access. Served verbatim from
# the aiohttp handler. The client discovers its own token from the page URL and
# forwards it to the WebSocket and JSON endpoints.

PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="dark" />
<title>Fluke Live View</title>
<style>
  :root {
    --bg: #06090f;
    --panel: #0e1520;
    --ink: #f4f7fb;
    --muted: #8ea0b7;
    --accent: #35e08a;
    --warn: #ffbf47;
    --bad: #ff5d5d;
    --line: #1d2938;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    padding: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    -webkit-text-size-adjust: 100%;
  }
  body { min-height: 100vh; display: flex; flex-direction: column; }
  header {
    display: flex; align-items: center; justify-content: space-between;
    gap: .5rem; padding: .6rem .9rem; border-bottom: 1px solid var(--line);
  }
  .brand { font-weight: 700; letter-spacing: .04em; font-size: .95rem; }
  .status {
    display: inline-flex; align-items: center; gap: .45rem;
    font-size: .8rem; text-transform: uppercase; letter-spacing: .05em;
    color: var(--muted);
  }
  .dot { width: .7rem; height: .7rem; border-radius: 50%; background: var(--muted); }
  .dot.connected { background: var(--accent); box-shadow: 0 0 10px var(--accent); }
  .dot.connecting { background: var(--warn); }
  .dot.disconnected, .dot.error { background: var(--bad); }
  .dot.stale { background: var(--warn); box-shadow: 0 0 10px var(--warn); }

  main { flex: 1; display: flex; flex-direction: column; padding: 1rem; gap: 1rem; }

  .reading-card {
    background: var(--panel); border: 1px solid var(--line); border-radius: 1rem;
    padding: 1.2rem 1rem; text-align: center; position: relative; overflow: hidden;
  }
  .reading-card.stale { border-color: var(--warn); }
  .mode-line {
    font-size: 1rem; color: var(--muted); text-transform: uppercase; letter-spacing: .08em;
    min-height: 1.2em;
  }
  .value-line {
    display: flex; align-items: baseline; justify-content: center; gap: .5rem;
    flex-wrap: wrap; line-height: 1;
  }
  .value {
    font-variant-numeric: tabular-nums; font-weight: 800;
    font-size: clamp(4rem, 22vw, 12rem); letter-spacing: -.02em;
  }
  .unit { font-size: clamp(1.6rem, 7vw, 4rem); font-weight: 700; color: var(--accent); }
  .display-text { margin-top: .4rem; font-size: 1.1rem; color: var(--muted); min-height: 1.2em; }
  .stale-banner {
    display: none; margin-top: .8rem; color: var(--warn); font-weight: 700;
    text-transform: uppercase; letter-spacing: .06em; font-size: .95rem;
  }
  .reading-card.stale .stale-banner { display: block; }

  .stats {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: .6rem;
  }
  .stat {
    background: var(--panel); border: 1px solid var(--line); border-radius: .8rem;
    padding: .7rem .5rem; text-align: center;
  }
  .stat .k { font-size: .7rem; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
  .stat .v { font-size: 1.5rem; font-weight: 700; font-variant-numeric: tabular-nums; margin-top: .2rem; }

  .chart-card {
    background: var(--panel); border: 1px solid var(--line); border-radius: .9rem;
    padding: .6rem; flex: 1; min-height: 140px; display: flex;
  }
  canvas { width: 100%; height: 100%; display: block; }

  footer {
    padding: .5rem .9rem; border-top: 1px solid var(--line);
    font-size: .72rem; color: var(--muted); display: flex; justify-content: space-between; gap: .5rem;
  }
  footer a { color: var(--muted); }

  @media (orientation: landscape) and (max-height: 520px) {
    main { flex-direction: row; flex-wrap: wrap; }
    .reading-card { flex: 1 1 55%; }
    .side { flex: 1 1 40%; display: flex; flex-direction: column; gap: 1rem; }
    .chart-card { min-height: 120px; }
  }
</style>
</head>
<body>
<header>
  <span class="brand">FLUKE · LIVE</span>
  <span class="status"><span id="dot" class="dot connecting"></span><span id="statusText">connecting</span></span>
</header>
<main>
  <section id="card" class="reading-card">
    <div id="mode" class="mode-line">&mdash;</div>
    <div class="value-line">
      <span id="value" class="value">--</span>
      <span id="unit" class="unit"></span>
    </div>
    <div id="displayText" class="display-text"></div>
    <div class="stale-banner">Data stale &mdash; no fresh reading</div>
  </section>

  <div class="side">
    <section class="stats">
      <div class="stat"><div class="k">Min</div><div id="min" class="v">--</div></div>
      <div class="stat"><div class="k">Avg</div><div id="avg" class="v">--</div></div>
      <div class="stat"><div class="k">Max</div><div id="max" class="v">--</div></div>
    </section>
    <section class="chart-card"><canvas id="chart"></canvas></section>
  </div>
</main>
<footer>
  <span id="meta">samples 0 · 0s</span>
  <span><a href="/api/status">/api/status</a> · <a href="/api/latest">/api/latest</a></span>
</footer>

<script>
(function () {
  "use strict";
  var params = new URLSearchParams(window.location.search);
  var token = params.get("token");
  var tokenQuery = token ? ("?token=" + encodeURIComponent(token)) : "";

  var el = function (id) { return document.getElementById(id); };
  var dot = el("dot"), statusText = el("statusText"), card = el("card");
  var valueEl = el("value"), unitEl = el("unit"), modeEl = el("mode");
  var displayTextEl = el("displayText");
  var minEl = el("min"), avgEl = el("avg"), maxEl = el("max"), metaEl = el("meta");

  var state = null;           // last snapshot from server
  var lastMessageAt = 0;      // client clock of last ws message
  var staleAfterMs = 3000;    // overwritten by server snapshot
  var history = [];           // [elapsed_s, value]

  function fmtNum(n) {
    if (n === null || n === undefined || isNaN(n)) return "--";
    var a = Math.abs(n);
    if (a !== 0 && (a < 0.001 || a >= 1e6)) return n.toExponential(3);
    return (Math.round(n * 1000) / 1000).toString();
  }

  function applyStatus(status, stale) {
    var cls = stale ? "stale" : status;
    dot.className = "dot " + cls;
    statusText.textContent = stale ? "stale" : status;
    if (stale) { card.classList.add("stale"); } else { card.classList.remove("stale"); }
  }

  function render() {
    if (!state) return;
    var clientStale = (Date.now() - lastMessageAt) > staleAfterMs;
    var stale = state.stale || clientStale;
    applyStatus(state.connection_status, stale);

    var r = state.reading;
    if (r) {
      valueEl.textContent = (r.value === null || r.value === undefined) ? (r.display_text || "OL") : fmtNum(r.value);
      unitEl.textContent = r.unit || "";
      modeEl.textContent = (r.measurement_type || "") + (r.mode ? (" · " + r.mode) : "");
      displayTextEl.textContent = r.display_text || "";
    }
    minEl.textContent = fmtNum(state.min_value);
    avgEl.textContent = fmtNum(state.avg_value);
    maxEl.textContent = fmtNum(state.max_value);
    metaEl.textContent = "samples " + state.sample_count + " · " + Math.round(state.uptime_s) + "s";
    drawChart();
  }

  // ---- rolling live chart (hand-rolled canvas, no external lib) ----
  var canvas = el("chart");
  var ctx = canvas.getContext("2d");
  function sizeCanvas() {
    var ratio = window.devicePixelRatio || 1;
    var w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = Math.max(1, Math.floor(w * ratio));
    canvas.height = Math.max(1, Math.floor(h * ratio));
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }
  function drawChart() {
    sizeCanvas();
    var w = canvas.clientWidth, h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);
    if (!history.length) return;
    var pad = 6;
    var xs = history.map(function (p) { return p[0]; });
    var ys = history.map(function (p) { return p[1]; });
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
    var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    if (maxX === minX) maxX = minX + 1;
    var spanY = maxY - minY; if (spanY === 0) { spanY = Math.abs(maxY) || 1; minY -= spanY / 2; maxY += spanY / 2; }
    var sx = function (x) { return pad + (x - minX) / (maxX - minX) * (w - 2 * pad); };
    var sy = function (y) { return h - pad - (y - minY) / (maxY - minY) * (h - 2 * pad); };

    ctx.lineWidth = 2;
    ctx.strokeStyle = "#35e08a";
    ctx.beginPath();
    for (var i = 0; i < history.length; i++) {
      var px = sx(history[i][0]), py = sy(history[i][1]);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.stroke();
    // latest point marker
    var last = history[history.length - 1];
    ctx.fillStyle = "#35e08a";
    ctx.beginPath();
    ctx.arc(sx(last[0]), sy(last[1]), 3, 0, Math.PI * 2);
    ctx.fill();
  }

  // ---- websocket with automatic reconnect ----
  var ws = null, reconnectDelay = 500;
  function connect() {
    var proto = (window.location.protocol === "https:") ? "wss:" : "ws:";
    var url = proto + "//" + window.location.host + "/ws" + tokenQuery;
    try { ws = new WebSocket(url); } catch (e) { scheduleReconnect(); return; }

    ws.onopen = function () { reconnectDelay = 500; };
    ws.onmessage = function (ev) {
      var snap;
      try { snap = JSON.parse(ev.data); } catch (e) { return; }
      state = snap;
      lastMessageAt = Date.now();
      if (typeof snap.stale_after_s === "number") staleAfterMs = snap.stale_after_s * 1000;
      if (Array.isArray(snap.history)) history = snap.history;
      render();
    };
    ws.onclose = function () { applyStatus("disconnected", false); scheduleReconnect(); };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }
  function scheduleReconnect() {
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 5000);
  }

  // Local staleness watchdog so the big number visibly freezes even if the
  // socket is up but the meter stopped sending.
  setInterval(function () { if (state) render(); }, 500);
  window.addEventListener("resize", drawChart);
  connect();
})();
</script>
</body>
</html>
"""


def render_page() -> str:
    return PAGE_HTML
