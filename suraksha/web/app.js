/* Suraksha command center. No build step, paid services or CDN dependencies. */
"use strict";
const $ = id => document.getElementById(id);
const COLORS = { high: "#ff827f", moderate: "#edbd69", low: "#5ee5bd", unknown: "#758594" };
const HAZARDS = { heat: "Heat", flood: "Flood proxy", air: "Air quality" };
const store = {
  read(key, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem("suraksha-" + key));
      if (value == null) return fallback;
      if (Array.isArray(fallback)) return Array.isArray(value) ? value : fallback;
      if (fallback && typeof fallback === "object") return typeof value === "object" && !Array.isArray(value) ? value : fallback;
      return typeof value === "string" ? value : fallback;
    } catch { return fallback; }
  },
  write(key, value) { try { localStorage.setItem("suraksha-" + key, JSON.stringify(value)); } catch { /* private browsing */ } },
};
const state = { districts: [], risks: [], languages: [], view: "overview", hazard: "all", day: "", demo: false,
  saved: new Set(store.read("saved", []).filter(id => typeof id === "string")), compare: [],
  checks: store.read("checks", {}), selected: null, context: null, generation: 0, refreshGeneration: 0, prepGeneration: 0,
  session: store.read("session", null) || "web-" + (globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2)), chatBusy: false };
store.write("session", state.session);
const language = () => $("language").value;
const band = score => score == null ? "unknown" : score >= 60 ? "high" : score >= 25 ? "moderate" : "low";
const number = value => value == null || !Number.isFinite(value) ? "—" : Math.round(value).toLocaleString("en-IN");
const decimal = value => value == null || !Number.isFinite(value) ? "—" : value.toFixed(1);
const today = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
const dateOffset = offset => { const d = new Date(today() + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + offset); return d.toISOString().slice(0, 10); };
const escape = text => String(text ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function node(tag, cls, text) { const el = document.createElement(tag); if (cls) el.className = cls; if (text != null) el.textContent = text; return el; }
function notify(text) { $("toast").textContent = text; $("toast").hidden = false; clearTimeout(notify.timer); notify.timer = setTimeout(() => $("toast").hidden = true, 4500); }
async function api(url, options = {}) {
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 25000);
  try { const res = await fetch(url, { ...options, signal: controller.signal, cache: "no-store" }); if (!res.ok) throw new Error(`Request failed (${res.status})`); return await res.json(); }
  finally { clearTimeout(timer); }
}
function riskFor(id) { return state.risks.find(r => r.id === id)?.hazards || {}; }
function overall(hazards) { const values = Object.values(hazards).map(h => h.score).filter(v => v != null); return values.length ? Math.max(...values) : null; }
function nameFor(d) { return d["name_" + language()] || d.name_en; }
function setView(view) {
  if (!$("view-" + view)) return;
  state.view = view;
  document.querySelectorAll(".view").forEach(el => el.hidden = el.id !== "view-" + view);
  document.querySelectorAll("[data-view]").forEach(el => el.classList.toggle("active", el.dataset.view === view));
  const titles = { overview: "Overview", explore: "District explorer", saved: "Saved districts", compare: "Compare districts", preparedness: "Preparedness", scenario: "What-if lab" };
  $("view-title").textContent = titles[view];
  $("page-title").textContent = view === "overview" ? "A clearer view of climate risk." : titles[view];
  if (view === "saved") renderSaved();
  if (view === "compare") loadCompare();
  if (view === "preparedness") loadPreparedness();
}
function populateRegistry() {
  const picker = $("compare-picker"); picker.replaceChildren(node("option", "", "Add a district…")); picker.firstChild.value = "";
  state.districts.forEach(d => { const option = node("option", "", `${d.name_en} · ${d.state}`); option.value = d.id; picker.append(option); });
  [...new Set(state.districts.map(d => d.state))].sort().forEach(s => { const option = node("option", "", s); option.value = s; $("state-filter").append(option); });
}
async function refresh() {
  const generation = ++state.refreshGeneration;
  $("refresh").disabled = true;
  const results = await Promise.allSettled([api("/api/health"), api(`/api/overview?day=${state.day}`), api(`/api/risk-map?day=${state.day}`), api(`/api/watchlist?limit=6&hazard=${state.hazard}`)]);
  if (generation !== state.refreshGeneration) return;
  const [health, metrics, risks, watchlist] = results;
  if (!state.districts.length) {
    try { state.districts = await api("/api/districts"); populateRegistry(); renderPlot(); renderExplorer(); renderSaved(); }
    catch { /* keep the retry affordance */ }
  }
  if (generation !== state.refreshGeneration) return;
  if (health.status === "fulfilled") {
    state.demo = health.value.demo;
    $("connection").lastChild.textContent = health.value.pipeline?.running ? " Updating data" : " API connected";
    $("mode-banner").hidden = !state.demo;
  } else $("connection").lastChild.textContent = " Connection unavailable";
  if (metrics.status === "fulfilled") renderMetrics(metrics.value);
  if (risks.status === "fulfilled") { state.risks = risks.value; renderPlot(); renderExplorer(); renderSaved(); }
  if (watchlist.status === "fulfilled") renderWatchlist(watchlist.value);
  $("error-banner").hidden = results.every(r => r.status === "fulfilled");
  $("error-banner").textContent = "Some data could not be refreshed. Previous results may be stale. Retry with the refresh button.";
  $("refresh").disabled = false;
}
function renderMetrics(data) {
  const population = data.population_in_high_risk_districts;
  const items = [
    ["Districts monitored", number(data.districts), `${data.covered} with at least one scored hazard`, "◈", ""],
    ["High-risk districts", number(data.high), `Selected day · ${data.day}`, "↗", "danger"],
    ["Registry population · high risk", population >= 1e6 ? (population / 1e6).toFixed(1) + "M" : number(population), "District totals · not exposed-person estimates", "◎", ""],
    ["Data coverage", data.districts ? Math.round(data.covered / data.districts * 100) + "%" : "—", `${data.unknown} districts without scores`, "⌁", ""],
  ];
  $("metrics").replaceChildren(...items.map(([title, value, caption, icon, cls]) => {
    const article = node("article", "metric " + cls); article.append(node("span", "", title), node("span", "metric-icon", icon), node("strong", "", value), node("small", "", caption)); return article;
  }));
  $("map-coverage").textContent = `${data.covered} / ${data.districts} scored`;
}
function renderPlot() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", "0 0 580 360");
  const make = (tag, attrs) => { const el = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k,v]) => el.setAttribute(k,v)); return el; };
  // A geographic coordinate plot, deliberately not a fabricated boundary map.
  for (let lat = 10; lat <= 35; lat += 5) { const text = make("text", { x: 12, y: 335 - (lat - 7) / 30 * 310, class: "geo-label" }); text.textContent = lat + "°N"; svg.append(text); }
  const label = make("text", { x: 225, y: 330, class: "geo-label" }); label.textContent = "INDIAN OCEAN"; svg.append(label);
  const region = make("text", { x: 235, y: 40, class: "geo-label" }); region.textContent = "INDIA · DISTRICT HQs"; svg.append(region);
  state.districts.forEach(d => {
    const hazards = riskFor(d.id); const score = state.hazard === "all" ? overall(hazards) : hazards[state.hazard]?.score ?? null;
    const status = band(score); const x = 70 + (d.lon - 68) / 30 * 455; const y = 325 - (d.lat - 7) / 30 * 295;
    if (status === "high") svg.append(make("circle", { cx:x, cy:y, r:12, fill:COLORS.high, opacity:.09 }));
    const circle = make("circle", { cx:x, cy:y, r:score == null ? 3.5 : status === "high" ? 6 : 4.5, fill:COLORS[status], class:"geo-point", tabindex:0, role:"button", "aria-label":`${d.name_en}: ${status}, score ${number(score)}` });
    const title = make("title", {}); title.textContent = `${d.name_en} · ${d.state}\n${status}: ${number(score)}/100`; circle.append(title);
    circle.onclick = () => openDistrict(d.id); circle.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDistrict(d.id); } }; svg.append(circle);
  });
  $("geo-plot").replaceChildren(svg);
  if (!state.districts.length) $("geo-plot").append(node("p", "empty", "Registry unavailable. Refresh to retry."));
}
function renderWatchlist(rows) {
  $("watchlist-list").replaceChildren();
  if (!rows.length) { $("watchlist-list").append(node("p", "empty", "No scored districts in the next 48 hours. Missing data is not a safe signal.")); return; }
  rows.forEach((r,i) => {
    const button = node("button", "watch-row"); const name = node("span", "watch-name"); name.append(node("strong", "", r.name_en), node("small", "", r.reason));
    const score = node("span", "watch-score " + band(r.overall), number(r.overall)); score.append(node("small", "", HAZARDS[r.top_hazard] || "Unknown"));
    button.append(node("span", "watch-rank", String(i+1).padStart(2,"0")), name, score); button.title = `Peak ${r.peak_day} · ${r.reason}`; button.onclick = () => openDistrict(r.id); $("watchlist-list").append(button);
  });
}
function scoreChip(score) { const chip = node("span", "score-chip " + band(score)); chip.append(node("span", "", number(score)), node("span", "", band(score) === "unknown" ? "No data" : band(score))); return chip; }
function renderExplorer() {
  const search = $("search").value.trim().toLocaleLowerCase();
  const rows = state.districts.filter(d => Object.values(d).some(v => typeof v === "string" && v.toLocaleLowerCase().includes(search)) && (!$("state-filter").value || d.state === $("state-filter").value) && (!$("band-filter").value || band(overall(riskFor(d.id))) === $("band-filter").value));
  rows.sort((a,b) => $("sort").value === "name" ? a.name_en.localeCompare(b.name_en) : $("sort").value === "state" ? a.state.localeCompare(b.state) || a.name_en.localeCompare(b.name_en) : (overall(riskFor(b.id)) ?? -1) - (overall(riskFor(a.id)) ?? -1));
  $("result-count").textContent = `${rows.length} districts · ${state.day}`;
  $("district-rows").replaceChildren();
  rows.forEach(d => {
    const row = node("tr"); const name = node("td"); const open = node("button", "", nameFor(d)); open.onclick = () => openDistrict(d.id); name.append(open, node("small", "", d.state)); row.append(name);
    Object.keys(HAZARDS).forEach(h => { const cell = node("td"); cell.append(scoreChip(riskFor(d.id)[h]?.score)); row.append(cell); });
    const all = node("td"); all.append(scoreChip(overall(riskFor(d.id)))); row.append(all);
    const actions = node("td"); const save = node("button", "table-action" + (state.saved.has(d.id) ? " selected" : ""), state.saved.has(d.id) ? "★" : "☆"); save.setAttribute("aria-label", `${state.saved.has(d.id) ? "Unsave" : "Save"} ${d.name_en}`); save.onclick = () => toggleSaved(d.id);
    const compare = node("button", "table-action", "⇄"); compare.setAttribute("aria-label", "Compare " + d.name_en); compare.onclick = () => addCompare(d.id);
    actions.append(save, compare); row.append(actions); $("district-rows").append(row);
  });
  if (!rows.length) { const row = node("tr"); const cell = node("td", "empty", "No districts match these filters."); cell.colSpan = 6; row.append(cell); $("district-rows").append(row); }
}
function toggleSaved(id) {
  state.saved.has(id) ? state.saved.delete(id) : state.saved.add(id); store.write("saved", [...state.saved]); renderSaved(); renderExplorer(); updateSaveButton();
}
function updateSaveButton() { $("save-district").textContent = state.saved.has(state.selected) ? "★ Saved" : "☆ Save"; }
function renderSaved() {
  const districts = state.districts.filter(d => state.saved.has(d.id)); $("saved-count").textContent = districts.length;
  $("saved-preview").replaceChildren(); $("saved-grid").replaceChildren();
  if (!districts.length) {
    $("saved-preview").append(node("p", "empty", "Keep the places that matter close. Save a district to monitor it here."));
    $("saved-grid").append(node("p", "empty", "No saved districts yet. Open the district explorer and select ☆."));
  }
  districts.forEach(d => {
    const score = overall(riskFor(d.id)); const mini = node("button", "saved-mini", d.name_en); mini.append(node("small", band(score), `${band(score)} · ${number(score)}/100`)); mini.onclick = () => openDistrict(d.id); if ($("saved-preview").children.length < 3) $("saved-preview").append(mini);
    const card = node("article", "card saved-card"); const head = node("div", "card-heading"); const remove = node("button", "icon-button", "×"); remove.setAttribute("aria-label", "Unsave " + d.name_en); remove.onclick = () => toggleSaved(d.id); head.append(node("h2", "", d.name_en), remove);
    const open = node("button", "secondary", "Open district ↗"); open.onclick = () => openDistrict(d.id); card.append(head, node("p", "", d.state), scoreChip(score), open); $("saved-grid").append(card);
  });
}
function addCompare(id) {
  if (!id) return;
  if (state.compare.includes(id)) { notify("District already in your comparison."); return; }
  if (state.compare.length >= 4) { notify("Compare up to four districts at a time."); return; }
  state.compare.push(id); setView("compare"); notify("District added to comparison.");
}
async function loadCompare() {
  const ids = [...state.compare]; const token = ids.join(",") + ":" + language();
  $("compare-chips").replaceChildren(...ids.map(id => { const button = node("button", "", `${state.districts.find(d => d.id === id)?.name_en || id} ×`); button.onclick = () => { state.compare = state.compare.filter(d => d !== id); loadCompare(); }; return button; }));
  if (ids.length < 2) { $("compare-results").replaceChildren(node("p", "empty", "Choose at least two districts to start comparing.")); return; }
  $("compare-results").replaceChildren(node("p", "empty", "Loading comparison…"));
  try {
    const data = await api(`/api/compare?ids=${encodeURIComponent(ids.join(","))}&lang=${language()}`);
    if (token !== state.compare.join(",") + ":" + language()) return;
    $("compare-results").replaceChildren(...data.districts.map(item => {
      const card = node("article", "compare-item"); card.append(node("h3", "", item.district.name_en), node("p", "", item.district.state));
      Object.keys(HAZARDS).forEach(h => { const hazard = item.hazards.find(r => r.hazard === h); const row = node("div", "compare-hazard"); row.append(node("span", "", HAZARDS[h]), node("strong", band(hazard?.score), number(hazard?.score))); card.append(row); });
      card.append(node("p", "", `${item.forecast.length} forecast days · ${item.anomalies.length} anomalies`)); const open = node("button", "text-button", "Open full advisory ↗"); open.onclick = () => openDistrict(item.district.id); card.append(open); return card;
    }));
  } catch { if (token === state.compare.join(",") + ":" + language()) $("compare-results").replaceChildren(node("p", "empty", "Comparison unavailable. Please retry.")); }
}
async function loadPreparedness() {
  const generation = ++state.prepGeneration;
  try {
    const data = await api(`/api/preparedness?hazard=${$("prep-hazard").value}&band=${$("prep-band").value}&lang=${language()}`);
    if (generation !== state.prepGeneration) return;
    $("checklist").replaceChildren(...data.actions.map(action => {
      const label = node("label"); label.dir = "auto"; const checkbox = node("input"); checkbox.type = "checkbox"; checkbox.checked = !!state.checks[action.id]; checkbox.onchange = () => { state.checks[action.id] = checkbox.checked; store.write("checks", state.checks); updateProgress(); }; label.append(checkbox, node("span", "", action.text)); return label;
    })); updateProgress();
  } catch { if (generation === state.prepGeneration) $("checklist").replaceChildren(node("p", "empty", "Checklist unavailable. Please retry.")); }
}
function updateProgress() { const inputs = [...$("checklist").querySelectorAll("input")]; $("check-progress").textContent = `${inputs.filter(el => el.checked).length} / ${inputs.length} completed`; }
function selectTab(tab) {
  document.querySelectorAll(".drawer-tabs button").forEach(el => { el.classList.toggle("active", el.dataset.tab === tab); el.setAttribute("aria-selected", String(el.dataset.tab === tab)); });
  document.querySelectorAll(".tab-panel").forEach(el => el.hidden = el.id !== "tab-" + tab);
  if (tab === "history") loadHistory();
  if (tab === "mission") loadMission();
}
async function openDistrict(id) {
  state.selected = id; state.context = null; state.mission = null; const generation = ++state.generation;
  $("district-drawer").hidden = false; $("drawer-backdrop").hidden = false; document.body.style.overflow = "hidden";
  $("d-name").textContent = "Loading district…"; $("d-sub").textContent = ""; $("advisory").textContent = "Loading grounded guidance…";
  ["district-badges", "anomalies", "forecast-chart", "forecast-table", "history-chart", "history-table", "mission-content"].forEach(id => $(id).replaceChildren());
  $("ml-note").hidden = true; selectTab("advisory"); updateSaveButton();
  const url = new URL(location.href); url.searchParams.set("district", id); history.replaceState(null, "", url);
  try {
    const ctx = await api(`/api/district/${encodeURIComponent(id)}?lang=${language()}`);
    if (generation !== state.generation) return;
    state.context = ctx; $("d-name").textContent = nameFor(ctx.district); $("d-sub").textContent = `${ctx.district.state} · registry population ${number(ctx.district.population)}`;
    const risks = ctx.risks[today()] || {};
    $("district-badges").replaceChildren(...Object.keys(HAZARDS).map(h => { const score = risks[h]?.score; const tile = node("div", "hazard-tile"); tile.append(node("span", "", HAZARDS[h]), node("strong", band(score), number(score)), node("small", band(score), "Today · " + (score == null ? "No data" : band(score)))); return tile; }));
    $("advisory").textContent = ctx.advisory; $("advisory").dir = language() === "ur" ? "rtl" : "auto";
    $("translation-note").hidden = !state.languages.find(l => l.code === language())?.experimental;
    ctx.anomalies.forEach(e => $("anomalies").append(node("div", "anomaly-item", `${e.day} · ${e.message}`)));
    drawChart("forecast-chart", ctx.forecast, ["tavg", "precipitation"]); renderDataTable("forecast-table", ctx.forecast);
    const known = Object.values(risks).filter(r => r.score != null).length;
    $("district-quality").textContent = `${known}/3 hazards scored today · ${ctx.forecast.length}/7 forecast days. Availability is not accuracy. ${state.demo ? "Synthetic demo data." : "Check official warnings."}`;
    loadMl(id, generation); $("close-district").focus();
  } catch { if (generation === state.generation) { $("d-name").textContent = "District unavailable"; $("advisory").textContent = "Could not load district data. Close this panel and try again."; } }
}
function closeDistrict() {
  if ($("district-drawer").hidden) return;
  ++state.generation; state.selected = null; state.context = null; $("district-drawer").hidden = true; $("drawer-backdrop").hidden = true; document.body.style.overflow = "";
  const url = new URL(location.href); url.searchParams.delete("district"); history.replaceState(null, "", url);
  $("main").focus();
}
async function loadHistory() {
  if (!state.selected) return;
  const id = state.selected, generation = state.generation, days = $("history-days").value;
  $("history-table").replaceChildren(node("p", "empty", "Loading history…"));
  try { const data = await api(`/api/district/${id}/history?days=${days}`); if (generation !== state.generation || days !== $("history-days").value) return; drawChart("history-chart", data.rows, ["tavg", "precipitation"]); renderDataTable("history-table", data.rows); }
  catch { if (generation === state.generation) $("history-table").replaceChildren(node("p", "empty", "History unavailable. Try another window.")); }
}
function renderDataTable(id, rows) {
  const table = node("table", "data-table"); const head = node("thead"); const tr = node("tr"); ["Day", "Tavg °C", "Tmax °C", "Rain mm", ...(id === "history-table" ? ["Heat /100", "Flood /100", "Air /100"] : [])].forEach(t => tr.append(node("th", "", t))); head.append(tr); table.append(head); const body = node("tbody");
  rows.forEach(r => { const tr = node("tr"); [r.day, decimal(r.tavg), decimal(r.tmax), decimal(r.precipitation), ...(id === "history-table" ? Object.keys(HAZARDS).map(h => number(r.risks?.[h]?.score)) : [])].forEach(t => tr.append(node("td", "", t))); body.append(tr); }); table.append(body); $(id).replaceChildren(rows.length ? table : node("p", "empty", "No stored data available for this window."));
}
function drawChart(id, rows, fields) {
  const available = rows.filter(r => fields.some(f => r[f] != null)); if (!available.length) { $(id).replaceChildren(node("p", "empty", "No chart data yet.")); return; }
  const ns = "http://www.w3.org/2000/svg"; const svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", "0 0 460 150"); svg.classList.add("spark-chart"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "Temperature and rainfall trend; values in the table below");
  const colors = ["#5ee5bd", "#73aef5"];
  fields.forEach((field,index) => {
    const values = rows.map(r => r[field]).filter(v => v != null); if (!values.length) return;
    const min = Math.min(...values, 0), max = Math.max(...values, min + 1); let path = "", gap = true;
    rows.forEach((r,i) => { if (r[field] == null) { gap = true; return; } const x = 20 + i / Math.max(rows.length-1,1) * 420; const y = 125 - (r[field]-min)/(max-min)*100; path += `${gap ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)} `; gap = false; });
    const line = document.createElementNS(ns,"path"); line.setAttribute("d",path); line.setAttribute("fill","none"); line.setAttribute("stroke",colors[index]); line.setAttribute("stroke-width","2"); svg.append(line);
  });
  const legend = node("div", "chart-legend", "Mint: temperature °C · Blue: rain mm · independently scaled; see table for values"); $(id).replaceChildren(svg,legend);
}
async function loadMl(id, generation) {
  try { const ml = await api(`/api/district/${id}/ml-outlook`); if (generation !== state.generation || !ml.available) return; $("ml-note").hidden = false; $("ml-note").textContent = "Experimental ML outlook available. Validation: temperature MAE " + decimal(ml.validation?.mae_tavg) + " vs baseline " + decimal(ml.validation?.mae_tavg_baseline) + "; rain MAE " + decimal(ml.validation?.mae_rain) + " vs baseline " + decimal(ml.validation?.mae_rain_baseline) + "."; } catch { /* optional model */ }
}
async function copy(text) { try { await navigator.clipboard.writeText(text); notify("Copied to clipboard."); } catch { notify("Clipboard unavailable. Select and copy the text manually."); } }
async function listen() {
  if (!state.context) return;
  const text = state.context.advisory; $("voice").disabled = true;
  try {
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(),22000); let res;
    try { res = await fetch(`/api/district/${state.selected}/voice?lang=${language()}`, {method:"POST",signal:controller.signal}); } finally {clearTimeout(timer);}
    if (!res.ok) throw new Error("Voice unavailable");
    if (res.headers.get("X-TTS-Engine") === "fallback") {
      if (!("speechSynthesis" in globalThis)) throw new Error("No browser voice");
      const utterance = new SpeechSynthesisUtterance(text); utterance.lang = state.languages.find(l => l.code === language())?.locale || "en-IN"; utterance.onerror = () => notify("Device speech unavailable. Read the advisory text."); speechSynthesis.cancel(); speechSynthesis.speak(utterance); notify("Using device speech; language availability depends on your device.");
    } else { const url = URL.createObjectURL(await res.blob()); const audio = new Audio(url); audio.onended = audio.onerror = () => URL.revokeObjectURL(url); try { await audio.play(); } catch(e) { URL.revokeObjectURL(url); throw e; } }
  } catch { notify("Voice unavailable. The complete text advisory is still available."); }
  finally { $("voice").disabled = false; }
}
function openChat() { $("chat-panel").hidden = false; $("chat-input").focus(); }
function message(text, type) { const msg = node("div", "msg " + type, text); msg.dir = "auto"; $("chat-log").append(msg); $("chat-log").scrollTop = $("chat-log").scrollHeight; return msg; }
async function sendChat(text) {
  if (state.chatBusy || !text.trim()) return; state.chatBusy = true; $("chat-send").disabled = true; message(text,"user"); const pending = message("Thinking with district data…","bot");
  try { const response = await api("/api/chat", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:state.session,message:text,language:language() === "en" ? null : language()})}); pending.textContent = response.reply; }
  catch { pending.textContent = "Connection unavailable. Please retry. Your district advisory is also available in the explorer."; }
  finally { state.chatBusy = false; $("chat-send").disabled = false; $("chat-log").scrollTop = $("chat-log").scrollHeight; }
}
async function locate() {
  if (!navigator.geolocation) { notify("Your browser does not support location lookup."); return; }
  $("locate").disabled = true;
  navigator.geolocation.getCurrentPosition(async position => {
    try { const d = await api(`/api/nearest?lat=${position.coords.latitude}&lon=${position.coords.longitude}`); openDistrict(d.id); notify(`Nearest curated HQ: ${d.name_en}, ${d.distance_km} km away. Not a boundary lookup.`); }
    catch { notify("Location lookup unavailable. Search your district instead."); } finally { $("locate").disabled = false; }
  }, () => { $("locate").disabled = false; notify("Location permission denied or unavailable. Search your district instead."); }, {timeout:10000,maximumAge:300000});
}
async function loadMission() {
  if (!state.selected) return;
  const id = state.selected, generation = state.generation;
  $("mission-content").replaceChildren(node("p", "empty", "Building district mission brief…"));
  try {
    const data = await api(`/api/district/${id}/mission?lang=${language()}`);
    if (generation !== state.generation) return;
    state.mission = data;
    const content = $("mission-content"); content.replaceChildren();
    content.append(node("p", "translation-note", `${data.demo ? "DEMO · " : ""}${data.coverage.percent}% hazard-day coverage · ${data.coverage.scored_hazard_days}/21 slots scored. Not confidence.`));
    const timeline = node("div", "mission-timeline");
    data.timeline.forEach(row => { const cell = node("div", "timeline-cell " + band(row.overall)); cell.append(node("small", "", row.day.slice(5)), node("strong", "", number(row.overall)), node("small", "", `${row.known_hazards}/3 known`)); timeline.append(cell); }); content.append(timeline);
    data.priorities.forEach(priority => { const section = node("section", "mission-priority"); section.append(node("h3", band(priority.score), `${HAZARDS[priority.hazard]} · ${number(priority.score)}/100`), node("p", "muted", `Peak ${priority.peak_day} · ${priority.reason}`)); priority.steps.forEach(step => { const p = node("p", "", "→ " + step); p.dir="auto"; section.append(p); }); content.append(section); });
    if (!data.priorities.length) content.append(node("p", "empty", "No scored hazards in the mission window. Do not interpret this as safe."));
    content.append(node("p", "fine-print", data.limitations.join(" ")));
  } catch { if (generation === state.generation) $("mission-content").replaceChildren(node("p", "empty", "Mission brief unavailable. Please retry.")); }
}
function printMission() {
  if (!state.mission) {notify("Load the mission brief before printing.");return;}
  document.body.classList.add("printing-mission");
  window.print();
  document.body.classList.remove("printing-mission");
}
async function runScenario() {
  const form = $("scenario-form"), inputs = {};
  for (const key of ["tmax","humidity","rain_today","rain_3day","rain_p90","pm25"]) inputs[key] = form.elements[key].value === "" ? null : Number(form.elements[key].value);
  inputs.language = language();
  const generation = (state.scenarioGeneration || 0) + 1; state.scenarioGeneration = generation;
  if (inputs.rain_3day < inputs.rain_today) {notify("3-day rain must include today’s rain.");return;}
  $("scenario-run").disabled = true;
  try {
    const result = await api("/api/scenario",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(inputs)});
    if (generation !== state.scenarioGeneration) return;
    $("scenario-results").replaceChildren();
    Object.entries(result.risks).forEach(([hazard,risk]) => { const card = node("section","mission-priority");card.append(node("h3",band(risk.score),`${HAZARDS[hazard]} · ${number(risk.score)}/100`),node("p","muted",risk.band));
      Object.entries(risk.detail).forEach(([key,value]) => card.append(node("p","driver-line",`${key}: ${value}`)));
      risk.actions.forEach(action => {const p=node("p","", "→ " + action);p.dir="auto";card.append(p);});$("scenario-results").append(card); });
    notify("Simulation complete. Live district data was not changed.");
  } catch { $("scenario-results").replaceChildren(node("p","empty","Simulation unavailable or invalid inputs. Check values and retry.")); }
  finally {if (generation === state.scenarioGeneration) $("scenario-run").disabled=false;}
}
function bind() {
  document.querySelectorAll("[data-view]").forEach(el => el.onclick = () => setView(el.dataset.view));
  $("refresh").onclick = refresh; $("explore-all").onclick = () => setView("explore"); $("saved-all").onclick = () => setView("saved");
  ["search","state-filter","band-filter","sort"].forEach(id => $(id).addEventListener(id === "search" ? "input" : "change",renderExplorer));
  document.querySelectorAll("[data-hazard]").forEach(el => el.onclick = () => { state.hazard = el.dataset.hazard; document.querySelectorAll("[data-hazard]").forEach(b => b.classList.toggle("active",b===el)); renderPlot(); refresh(); });
  $("risk-day").onchange = () => { state.day = $("risk-day").value; refresh(); };
  $("language").onchange = () => { store.write("language",language()); renderExplorer(); if(state.selected) openDistrict(state.selected); if(state.view === "preparedness") loadPreparedness(); if(state.view === "compare") loadCompare(); };
  $("compare-add").onclick = () => addCompare($("compare-picker").value); $("compare-clear").onclick = () => {state.compare=[];loadCompare();};
  $("prep-hazard").onchange = $("prep-band").onchange = loadPreparedness; $("reset-checklist").onclick = () => {state.checks={};store.write("checks",{});loadPreparedness();};
  $("save-district").onclick = () => state.selected && toggleSaved(state.selected); $("compare-district").onclick = () => {const id=state.selected;closeDistrict();addCompare(id);};
  $("share-district").onclick = async () => {if(navigator.share) {try {await navigator.share({title:"Suraksha district intelligence",url:location.href});} catch { /* dismissed */ }} else copy(location.href);};
  $("copy-advisory").onclick = () => state.context && copy(state.context.advisory);
  $("close-district").onclick = $("drawer-backdrop").onclick = closeDistrict;
  document.querySelectorAll("[data-tab]").forEach(el => el.onclick = () => selectTab(el.dataset.tab)); $("history-days").onchange = loadHistory;
  $("voice").onclick = listen; $("pdf").onclick = () => state.selected && window.open(`/api/district/${state.selected}/brief.pdf`,"_blank","noopener"); $("csv").onclick = () => state.selected && window.open(`/api/district/${state.selected}/export.csv?days=${$("history-days").value}`,"_blank","noopener");
  $("open-chat").onclick = $("hero-chat").onclick = openChat; $("close-chat").onclick = () => $("chat-panel").hidden = true;
  $("chat-form").onsubmit = e => {e.preventDefault();const text=$("chat-input").value;$("chat-input").value="";sendChat(text);};
  document.querySelectorAll("[data-prompt]").forEach(el => el.onclick = () => { const district = state.districts.find(d => d.id === state.selected) || state.districts.find(d => state.saved.has(d.id)); if (!district) {notify("Name a district in chat, or save one first.");return;} sendChat(`${district.name_en} ${el.dataset.prompt}`); });
  $("locate").onclick = locate;
  $("print-mission").onclick = printMission;
  $("scenario-form").onsubmit = e => { e.preventDefault(); runScenario(); };
  document.querySelectorAll("[data-preset]").forEach(el => el.onclick = () => {
    const values = {heat:{tmax:44,humidity:65,rain_today:0,rain_3day:0,rain_p90:30,pm25:""},rain:{tmax:29,humidity:90,rain_today:110,rain_3day:260,rain_p90:35,pm25:""},air:{tmax:30,humidity:50,rain_today:0,rain_3day:0,rain_p90:30,pm25:180}}[el.dataset.preset];
    Object.entries(values).forEach(([key,value]) => $("scenario-form").elements[key].value = value); runScenario();
  });
  $("present").onclick = () => { document.body.classList.toggle("presentation"); notify("Presentation mode toggled. Press ⛶ again to exit."); };
  let installEvent = null;
  window.addEventListener("beforeinstallprompt", e => {e.preventDefault();installEvent=e;$("install-app").hidden=false;});
  $("install-app").onclick = async () => {if(installEvent){await installEvent.prompt();installEvent=null;$("install-app").hidden=true;}};
  ["about-button","footer-about"].forEach(id => $(id).onclick = () => $("about-dialog").showModal()); $("close-about").onclick = () => $("about-dialog").close();
  document.addEventListener("keydown", e => {
    if(e.key === "Escape") {closeDistrict();$("chat-panel").hidden=true;}
    if (e.key === "Tab" && !$("district-drawer").hidden && $("chat-panel").hidden && !$("about-dialog").open) {
      const focusable = [...$("district-drawer").querySelectorAll("button:not(:disabled), select")].filter(el => el.offsetParent !== null);
      if (focusable.length && e.shiftKey && (document.activeElement === focusable[0] || !$("district-drawer").contains(document.activeElement))) {e.preventDefault();focusable.at(-1).focus();}
      else if (focusable.length && !e.shiftKey && document.activeElement === focusable.at(-1)) {e.preventDefault();focusable[0].focus();}
    }
    if(["INPUT","SELECT","TEXTAREA"].includes(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
    const views={1:"overview",2:"explore",3:"compare",4:"preparedness",5:"scenario"}; if(views[e.key]) setView(views[e.key]);
  });
  window.addEventListener("offline",() => {$("connection").lastChild.textContent=" Offline";notify("You’re offline. Previously loaded results may be stale.");});
  window.addEventListener("online",refresh);
}
async function boot() {
  state.day = today(); for(let offset=0;offset<7;offset++){const option=node("option","",offset===0?"Today":dateOffset(offset).slice(5));option.value=dateOffset(offset);$("risk-day").append(option);}
  $("date-label").textContent = new Intl.DateTimeFormat("en-IN",{dateStyle:"medium",timeZone:"Asia/Kolkata"}).format(new Date()) + " · IST";
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  bind(); message("Welcome to Suraksha. Ask about a district’s climate risks, forecasts or unusual weather. Try ‘Pune advisory’. No paid AI key required.","bot");
  const [districts,languages] = await Promise.allSettled([api("/api/districts"),api("/api/languages")]);
  if(districts.status === "fulfilled") {state.districts=districts.value;populateRegistry();} else notify("District registry could not load. Reload the page to retry.");
  if(languages.status === "fulfilled") {state.languages=languages.value;$("language").replaceChildren(...state.languages.map(l=>{const option=node("option","",l.name);option.value=l.code;return option;}));const saved=store.read("language","en");if(state.languages.some(l=>l.code===saved))$("language").value=saved;}
  await refresh(); const id=new URL(location.href).searchParams.get("district");if(id&&state.districts.some(d=>d.id===id))openDistrict(id);
  setInterval(()=>{if(!document.hidden)refresh();},60000);
}
boot().catch(()=>{$("error-banner").hidden=false;$("error-banner").textContent="Workspace could not initialize. Reload to retry.";});
