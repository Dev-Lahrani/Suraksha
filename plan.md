# Suraksha — Agentic Multi-Hazard Climate Early-Warning Assistant

**PCCOE-IGC 2026 · Track: Disaster Resilience, Public Health & Community Well-being**
**Theme alignment: "AI for Climate Action" (SDG 13) — also touches SDG 3 (Health), SDG 11 (Cities), SDG 6 (Water)**

> Tagline: *"Your district's climate risk, explained in your language, before it hits."*

---

## 1. Problem Statement

India is one of the world's most climate-vulnerable countries:

- **Heatwaves** kill thousands annually (the 2015 Andhra/Telangana waves killed 3,500+; 2023–2024 saw record wet-bulb events). Deaths are almost entirely *preventable with 48–72h advance advisories*.
- **Floods** affect ~40 million hectares; flash floods and cloudbursts (Himalayan states 2023–2025) give communities only hours of reaction time.
- **Air-quality emergencies** (Delhi NCR winters) cause measurable spikes in respiratory ER visits — but alerts reach urban elites, not the majority.
- Existing IMD/NDMA alerts are **broad, English/technical, and passive** ("heavy rainfall warning"). Ordinary citizens — farmers, daily-wage workers, the elderly — receive nothing *actionable, localized, in their language, at the right time*.

**The gap:** accurate data exists. Translation from *data → personal, local, multilingual, actionable advice delivered where people actually are (WhatsApp)* does not.

## 2. Solution Overview

Suraksha is an **agentic early-warning assistant** that:

1. **Continuously ingests** open multi-hazard data feeds for any Indian district: rainfall, temperature/heat index, river levels, air quality, fire signals.
2. **Runs lightweight ML models** to forecast 7-day risk (flood/heat/AQI) and detect anomalies vs. climatology.
3. **An LLM agent turns model output into human advisories** — localized to the district, written in the user's language (Hindi, Marathi, Tamil, Bengali, Telugu, English), graded by severity, with concrete actions ("Do not irrigate fields Tuesday–Wednesday; move livestock; OTS shelters at…" style).
4. **Delivers where people are:** a WhatsApp chatbot (subscribe to your district), voice notes for low-literacy users, SMS-style plain text fallback, plus a public web dashboard showing live risk maps across India.

### Headline features (the demo moments)
| # | Feature | Why judges remember it |
|---|---------|------------------------|
| 1 | **Live pan-India risk map** — 700+ districts colored by computed flood/heat/AQI risk | Real data, no canned demo |
| 2 | **WhatsApp agent** — "क्या अगले 5 दिन में नागपुर में बाढ़ का खतरा है?" → grounded, cited advisory | The rulebook literally asks for multi-modal + generative AI |
| 3 | **Voice advisories** — TTS in Hindi/Marathi for low-literacy users | Inclusion angle; judges rarely see it |
| 4 | **Anomaly alerts** — "Chennai rainfall is 3.2σ above 30-year climatology for this week" | Real ML, explainable |
| 5 | **District risk brief PDF** — one-click generated situation report for local officials | Govt/policy use-case → impact story |

## 3. Architecture

```
┌──────────────────────────── DATA LAYER (cron ingestion) ───────────────────────────┐
│  Open-Meteo (weather+history)   NASA FIRMS (fire)   OpenAQ/CPCB (air quality)      │
│  ERA5/Copernicus (climatology)  ReliefWeb/GDACS     ERDDAP/CWC (river, best-effort)│
└──────────────┬─────────────────────────────────────────────────────────────────────┘
               ▼
        PostgreSQL / TimescaleDB (district-day series)        Parquet archive
               ▼
┌──────────────────────────── INTELLIGENCE LAYER ────────────────────────────────────┐
│  • Risk engines: heat index (NOAA formula), flood potential (rainfall accumulation │
│    + climatology percentile), AQI band + forecast                                  │
│  • Forecaster: gradient-boosted / seq model for 7-day rainfall & temp anomalies    │
│  • Anomaly detector: per-district climatological z-scores                          │
│  • Exposure: district population & vulnerability weights (WorldPop/SEDAC)          │
└──────────────┬──────────────────────────────────────────────────────────────────────┘
               ▼
┌──────────────────────────── AGENT LAYER (LLM) ─────────────────────────────────────┐
│  Tool-calling agent (Nugen API — sponsor credits) + RAG over:                      │
│  NDMA/WHO do-and-don't playbooks, state disaster authority SOPs                    │
│  → outputs structured advisory (severity, actions, rationale) in chosen language   │
└──────────────┬──────────────────────────────────────────────────────────────────────┘
               ▼
┌──────────────────────────── DELIVERY LAYER ────────────────────────────────────────┐
│  FastAPI backend  ·  Next.js dashboard (MapLibre)  ·  WhatsApp Cloud API bot       │
│  Voice: Indic TTS (AI4Bharat / edge-tts)  ·  PDF brief generator                   │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Tech stack (all vibe-codeable, boring-where-it-matters):**
- Backend: Python, FastAPI, SQLAlchemy, APScheduler (cron ingestion)
- Data: pandas, xarray, Postgres (+ Postgres+Timescale optional)
- ML: scikit-learn (GBM) + statsmodels baseline; optional PyTorch LSTM later — **only if time permits**
- Agent: Nugen API for LLM tool-calling (sponsor!), fallback OpenAI-compatible
- Frontend: Next.js + MapLibre GL + Tailwind; Recharts for time series
- Messaging: Meta WhatsApp Cloud API sandbox (free), Twilio fallback
- Voice: AI4Bharat Indic TTS or edge-tts
- Deploy: Docker Compose; demo on a single $5 VM or Fly.io/Railway

## 4. Data Sources (100% free & open)

| Hazard | Source | Access |
|--------|--------|--------|
| Weather forecast + reanalysis | Open-Meteo API (archive + forecast) | Free, no key |
| Climatology baselines | ERA5 via Open-Meteo archive API | Free, no key |
| Air quality | OpenAQ (global), CPCB/SAFAR if reachable | Free |
| Fire | NASA FIRMS API | Free key |
| Disaster events | ReliefWeb API, GDACS feeds | Free |
| Population/exposure | WorldPop / SEDAC GPW rasters | Free |
| District boundaries | Survey of India / GeoBoundaries | Free |
| River/flood | Central Water Commission (CWC) flood forecast where available | Best-effort |

> Every number the agent says is **traceable to a source** — that's the credibility story.

## 5. ML Plan (scope-disciplined)

**Ship these three, in order:**
1. **Climatological risk engine** (week 1): per-district 30-year baselines; heat index, 3-day accumulated rainfall percentiles → flood/heat risk scores 0–100. Deterministic, defensible, always works.
2. **7-day forecast anomaly model** (week 2–3): per-state gradient-boosted regressors predicting rainfall/temperature deltas vs. normal from Open-Meteo forecast features; evaluate MAE vs. naive climatology baseline. A model that *beats climatology* is a great slide; one that doesn't ship as "model v2".
3. **Anomaly detection** (week 3): rolling z-scores + rate-of-change triggers for alerting.

**Deliberately out of scope:** satellite nowcasting, hydrological routing, cyclone tracking. Stretch goals only.

## 6. Timeline (mapped to the rulebook)

Current date: **Sept 16, 2026** → Idea-submission phase (closed Sept 10; assume submitted). Build targets Stage 2.

| Window | Milestone | Deliverable |
|--------|-----------|-------------|
| Sept 16–30 | Wait for shortlist (Sept 30); meanwhile: repo scaffold, ingestion for Open-Meteo, risk engine v0, one manual WhatsApp send | "Can pull live data for 10 districts" |
| Oct 1–15 | All-India ingestion + dashboard v1 (risk map); agent v1 (English) | Internal alpha |
| Oct 16–31 | ML forecaster + anomaly alerts; multilingual agent; WhatsApp bot live | Beta |
| Nov 1–8 | Voice notes, PDF briefs, polish dashboard, load-test, deploy | Release candidate |
| **Nov 9–15** | **Record prototype video; buffer** | **Stage 2 video submitted** |
| Nov 16–30 | Judging period — respond to any portal queries | — |
| Dec 16–30 | Finalists announced; prep Stage 3 live-demo (offline fallback videos) | Finale deck |
| Jan 2027 | Grand finale at PCCOE | Live demo |

**Weekly cadence:** each week ends with a *working deploy*, never a broken main.

## 7. Stage Deliverables Checklist

- [ ] **Stage 1** — Idea PPT (`<teamName>_ppt`): problem, solution, architecture sketch, impact metrics, roadmap ✍️ *adapt §1–2, 5, 6 above*
- [ ] `<teamName>_noc`, `<teamName>_id_cards` (combined PDF) — team lead owns
- [ ] **Stage 2** — 2–3 min prototype video (`<teamName>_prototype_video` if portal names it): scripted per §8
- [ ] Public dashboard URL + WhatsApp sandbox join link in video description
- [ ] **Stage 3** — live demo + 1-page PDF brief demo + impact metrics slide

## 8. Prototype Video Script (2:30)

1. **0:00–0:20 Hook** — news clip-style text: "May 2024: 40°C night in Delhi…" → "What if every resident got a WhatsApp advisory 72h earlier?"
2. **0:20–0:50 Live dashboard** — pan-India risk map, click a district, show real Open-Meteo data + risk score
3. **0:50–1:20 WhatsApp agent** — phone screen recording: ask in Marathi → get grounded advisory with sources; show anomaly alert triggered by a real event
4. **1:20–1:50 How it works** — 30s architecture animation (data → models → agent → delivery)
5. **1:50–2:15 Voice note + PDF brief** — the inclusion and gov-use stories
6. **2:15–2:30 Close** — impact math ("₹0 infrastructure, 700 districts, any language") + team

## 9. Evaluation-Criteria Mapping

| Criterion | How Suraksha scores |
|-----------|--------------------|
| Innovation | Agentic + multilingual + voice delivery of *existing* open data — the innovation is the last-mile layer, honestly argued |
| Feasibility | Every component is proven tech; 8-week plan ships a working system; zero paid infra |
| Clarity | One sentence pitch, live demo, traceable numbers |
| Impact | Pan-India, 700+ districts, SDG 13 aligned, explicit govt/policy use-case (PDF briefs), inclusion via voice |

## 10. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| WhatsApp API approval delays | Demo in sandbox mode (instant); fall back to web-chat UI that mirrors the bot |
| LLM hallucination | Agent is tool-grounded: model output is injected as structured JSON; advisory template constrains generation; cite sources in-output |
| River/flood data too patchy | Flood risk = rainfall-based proxy; label it honestly in UI |
| Diwali/college schedule collisions Nov | Everything demo-critical done by Nov 8 |
| Judging network fails at finale | Local Docker demo + pre-recorded backup videos |

## 11. Team Roles (2–5 members, all vibe-coding)

| Role | Owns |
|------|------|
| Team Lead / Product | Rulebook compliance, submissions, PPT, video narrative |
| Data/ML lead | Ingestion pipelines, risk engine, forecaster |
| Backend/Agent lead | FastAPI, agent orchestration, WhatsApp integration |
| Frontend lead | Dashboard, map, charts |
| Story lead (can double-role) | Video recording/editing, docs, sponsor (Nugen) coordination |

## 12. Stretch Goals (post-video, finale wow)

- Voice *input* (Indic ASR) for the WhatsApp bot
- Mobile PWA with offline caching
- Historical "what if" replay: "show Kerala, Aug 2018" — risk engine retro-run
- Fine-tune advisory tone per audience (farmer / school / municipal)
