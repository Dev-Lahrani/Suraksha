/* Suraksha dashboard: map, district panel, forecast chart, chat widget. */

const bandColor = { low: "#22c55e", moderate: "#eab308", high: "#ef4444", unknown: "#64748b" };
let map, chart = null, districts = [];
let lastForecast = [];

/* ------------------------------- map ------------------------------- */

function initMap() {
  map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {},
      layers: [{ id: "bg", type: "background", paint: { "background-color": "#0b1220" } }],
    },
    center: [79, 22.5],
    zoom: 4.1,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");

  map.on("load", async () => {
    try {
      const res = await fetch("/api/districts");
      districts = await res.json();
      document.getElementById("count-tag").textContent = `${districts.length} districts`;
      const fc = {
        type: "FeatureCollection",
        features: districts.map((d) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [d.lon, d.lat] },
          properties: { id: d.id, name: d.name_en, state: d.state },
        })),
      };
      map.addSource("districts", { type: "geojson", data: fc });
      map.addLayer({
        id: "district-dots",
        type: "circle",
        source: "districts",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 6, 7, 12],
          "circle-color": "#64748b",
          "circle-stroke-color": "#e6edf7",
          "circle-stroke-width": 1,
        },
      });
      await paintRisks();
      map.on("click", "district-dots", (e) => {
        const id = e.features[0].properties.id;
        openDistrict(id);
      });
      map.on("mouseenter", "district-dots", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "district-dots", () => (map.getCanvas().style.cursor = ""));
    } catch (err) {
      console.error("map init failed", err);
    }
  });
}

async function paintRisks() {
  try {
    const res = await fetch("/api/risk-map");
    const rows = await res.json();
    const colorExpr = ["match", ["get", "id"]];
    const radiusExpr = ["match", ["get", "id"]];
    rows.forEach((r) => {
      const worst = worstHazard(r.hazards);
      const band = worst ? worst.band : "unknown";
      colorExpr.push(r.id, bandColor[band]);
      radiusExpr.push(r.id, band === "high" ? 13 : band === "moderate" ? 10 : 7);
    });
    colorExpr.push("#64748b");
    radiusExpr.push(7);
    if (map.getLayer("district-dots")) {
      map.setPaintProperty("district-dots", "circle-color", colorExpr);
      map.setPaintProperty("district-dots", "circle-radius", radiusExpr);
    }
  } catch (err) {
    console.error("risk paint failed", err);
  }
}

function worstHazard(hazards) {
  const order = { high: 3, moderate: 2, low: 1, unknown: 0 };
  let worst = null;
  Object.values(hazards || {}).forEach((h) => {
    if (!worst || (order[h.band] || 0) > (order[worst.band] || 0)) worst = h;
  });
  return worst;
}

/* --------------------------- district panel --------------------------- */

async function openDistrict(id) {
  const side = document.getElementById("side");
  side.style.display = "block";
  ["d-name", "d-sub"].forEach((x) => (document.getElementById(x).textContent = "…"));

  const res = await fetch(`/api/district/${id}?lang=en`);
  if (!res.ok) return;
  const ctx = await res.json();
  const d = ctx.district;

  document.getElementById("d-name").textContent = `${d.name_en}`;
  document.getElementById("d-sub").textContent = `${d.state} · pop ≈ ${d.population.toLocaleString("en-IN")}`;

  const badges = { heat: "b-heat", flood: "b-flood", air: "b-air" };
  const chips = { heat: "c-heat", flood: "c-flood", air: "c-air" };
  const today = new Date().toISOString().slice(0, 10);
  const latest = {};
  Object.entries(ctx.risks || {}).forEach(([day, hs]) => {
    if (day <= today) Object.entries(hs).forEach(([h, r]) => (latest[h] = r));
  });
  Object.keys(badges).forEach((h) => {
    const r = latest[h];
    document.getElementById(badges[h]).textContent = r && r.score != null ? Math.round(r.score) : "–";
    const chip = document.getElementById(chips[h]);
    const band = r ? r.band : "unknown";
    chip.textContent = band;
    chip.className = `chip ${band}`;
  });

  document.getElementById("advisory").textContent = ctx.advisory || "No advisory available yet.";
  lastForecast = ctx.forecast || [];
  drawForecastChart(lastForecast);
  loadMlOutlook(id);

  document.getElementById("btn-voice").onclick = () => playVoice(id);
  document.getElementById("btn-pdf").onclick = () => window.open(`/api/district/${id}/brief.pdf`, "_blank");
  document.getElementById("btn-forecast").onclick = () => {
    document.getElementById("advisory").textContent =
      (ctx.forecast || []).map((f) => `${f.day}  ${fmt(f.tavg, "°C")}  ${fmt(f.precipitation, "mm")}`).join("\n") ||
      "No forecast data ingested yet.";
  };
  hideMlNote();
  side.scrollIntoView({ behavior: "smooth" });
}

/* -------- ML outlook (only shown when the model beat climatology) -------- */

async function loadMlOutlook(id) {
  const note = document.getElementById("ml-note");
  try {
    const res = await fetch(`/api/district/${id}/ml-outlook`);
    if (!res.ok) return hideMlNote();
    const ml = await res.json();
    if (!ml.available || !ml.rows || !ml.rows.length) return hideMlNote();
    const v = ml.validation || {};
    const parts = ml.rows.map((r) => `${r.day.slice(5)}: ${fmt(r.tavg, "°C")}, ${fmt(r.precipitation, "mm")}`);
    let meta = "";
    if (v.mae_tavg != null && v.mae_tavg_baseline != null) {
      meta = ` · beats climatology (MAE ${v.mae_tavg.toFixed(2)}°C vs ${v.mae_tavg_baseline.toFixed(2)}°C)`;
    }
    note.textContent = `🤖 ML outlook (experimental):\n${parts.join("\n")}${meta}`;
    note.style.display = "block";
    drawForecastChart(lastForecast, ml.rows);
  } catch {
    hideMlNote(); // ML is an enhancement, never a dependency
  }
}

function hideMlNote() {
  const note = document.getElementById("ml-note");
  if (note) {
    note.style.display = "none";
    note.textContent = "";
  }
}

function fmt(v, unit) {
  return v == null ? "–" : `${v.toFixed(1)}${unit}`;
}

async function playVoice(id) {
  const btn = document.getElementById("btn-voice");
  btn.textContent = "⏳ generating…";
  try {
    const res = await fetch(`/api/district/${id}/voice?lang=hi`, { method: "POST" });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    new Audio(url).play();
  } finally {
    btn.textContent = "▶ Voice advisory";
  }
}

/* ----------------------------- chart ----------------------------- */

function drawForecastChart(rows, mlRows) {
  const el = document.getElementById("chart");
  if (chart) chart.destroy();
  if (!rows.length) return;
  const mlByDay = {};
  (mlRows || []).forEach((r) => (mlByDay[r.day] = r));
  const datasets = [
    {
      label: "Rain mm",
      data: rows.map((r) => r.precipitation ?? 0),
      backgroundColor: "#3b82f6",
      yAxisID: "y1",
    },
    {
      label: "Tavg °C",
      data: rows.map((r) => r.tavg),
      type: "line",
      borderColor: "#f97316",
      tension: 0.35,
      yAxisID: "y",
    },
  ];
  if (mlRows && mlRows.length) {
    datasets.push({
      label: "ML tavg",
      data: rows.map((r) => (mlByDay[r.day] ? mlByDay[r.day].tavg : null)),
      type: "line",
      borderColor: "#a78bfa",
      borderDash: [6, 4],
      tension: 0.35,
      yAxisID: "y",
    });
  }
  chart = new Chart(el, {
    type: "bar",
    data: { labels: rows.map((r) => r.day.slice(5)), datasets },
    options: {
      responsive: true,
      scales: {
        y: { position: "left", ticks: { color: "#8b9bb8" }, grid: { color: "#1f2b47" } },
        y1: { position: "right", ticks: { color: "#8b9bb8" }, grid: { display: false } },
        x: { ticks: { color: "#8b9bb8" }, grid: { display: false } },
      },
      plugins: { legend: { labels: { color: "#8b9bb8" } } },
    },
  });
}

/* ----------------------------- chat ----------------------------- */

function initChat() {
  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  document.getElementById("chat-head").onclick = () => {
    const body = document.getElementById("chat-body");
    const hidden = body.style.display === "none";
    body.style.display = hidden ? "block" : "none";
    document.getElementById("chat-toggle").textContent = hidden ? "–" : "+";
  };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    addMsg(text, "user");
    input.value = "";
    const typing = addMsg("…", "bot");
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: "web-" + Math.random().toString(36).slice(2, 8), message: text }),
      });
      const data = await res.json();
      typing.textContent = data.reply || "No reply.";
    } catch {
      typing.textContent = "Network error — is the API running?";
    }
  };
}

function addMsg(text, cls) {
  const log = document.getElementById("chat-log");
  const div = document.createElement("div");
  div.className = `msg ${cls}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

/* ----------------------------- boot ----------------------------- */

initMap();
initChat();
