# 🛡️ Suraksha — Agentic Multi-Hazard Climate Early-Warning Assistant

**PCCOE Indradhanu International Grand Challenge (IGC) 2026 · Theme: AI for Climate Action (SDG 13)**

> *Your district's climate risk, explained in your language, before it hits.*

Suraksha continuously ingests open climate data for Indian districts, scores heat / flood / air-quality risk against 30-year climatology, and an AI agent turns that data into **localized, multilingual, actionable advisories** — delivered on WhatsApp, as voice notes, as a one-page PDF brief for officials, and on a live risk-map dashboard.

| Heat 🔥 | Flood 🌊 | Air 😷 |
|---|---|---|
| NOAA heat index vs NDMA thresholds | 3-day rainfall vs local heavy-rain climatology (p90) | PM2.5 → US-EPA AQI bands |

**Every number is traceable to a source. Every advisory ends with its citations.**

---

## Demo in one command

After installing `requirements.txt`:

```bash
python -m suraksha demo
```

Open **http://localhost:8000**. This seeds a separate, clearly labelled synthetic
workspace: no paid AI keys, no external frontend assets, no weather-network wait.
Run `python -m suraksha doctor` for a local readiness check.

**Judge/team handoff:** [3-minute demo + pitch](docs/DEMO_GUIDE.md) ·
[API guide](docs/API.md) · [Architecture & operations](docs/ARCHITECTURE.md) ·
[Honest audit/limitations](AUDIT.md).

## ✨ Headline features

- 🗺️ **Premium climate command center** — responsive dark workspace with a locally rendered geographic HQ risk plot, coverage metrics, hazard filters and a 7-day date selector. Real data in live mode; clearly labelled synthetic data in demo mode.
- 🔎 **Hazard coverage inspector** — distinguish complete/partial district coverage, drill into missing heat/flood/air scores, and inspect seven-day district coverage. Unknown is never safe; API retrieval time is separated from unverified source freshness.
- ⭐ **Personal monitoring** — district search, state/risk filters, device-local saved districts, shareable district links and nearest curated HQ lookup.
- ⇄ **District comparison + exports** — compare 2–4 districts, inspect history/forecast trends, export CSV or download PDF briefs.
- ☑ **Preparedness workspace** — severity-specific multilingual safety checklists with device-local progress.
- 📋 **District mission briefs** — seven-day risk timeline, priorities, missing-hazard coverage and printable guidance.
- ⚗ **What-if lab** — interactive heatwave/rainfall/pollution scenarios using the same explainable engines; simulations never alter live data.
- 📱 **Installable app shell** — local PWA assets and offline navigation shell; warnings/chat APIs are never cached as current data.
- ⛶ **Presentation mode** — clean judge-facing overview, keyboard navigation, a documented 3-minute demo and local readiness check.
- 🚨 **Watchlist — highest risk now** — districts ranked by worst expected hazard for the next 48h, each with a one-line reason traced to the engine drivers ("3-day rain 210mm vs heavy-day p90 45mm"). Officials' answer to "where do we act first?": `GET /api/watchlist` + a ranked panel on the dashboard.
- 💬 **WhatsApp + web chat agent** — ask *"क्या अगले 5 दिन में नागपुर में बाढ़ का खतरा है?"* and get a grounded advisory in Hindi. Language auto-detected (English / हिन्दी / मराठी / தமிழ் / తెలుగు / ಕನ್ನಡ / বাংলা / ગુજરાતી / ਪੰਜਾਬੀ / മലയാളം / اردو). New language translations are experimental and need native-speaker safety review.
- 🔊 **Voice advisories** — Indic neural TTS (edge-tts) for low-literacy users; on WhatsApp, send **"voice <district>"** or just a voice note and get the advisory back as an audio message.
- ⚠️ **Explainable anomaly alerts** — *"Daily rainfall 80mm is 4.1× the 30-year normal for this date."*
- 📄 **One-page PDF district brief** — color-coded risk table, 7-day outlook, anomalies, sources. For district officials.
- 🤖 **Grounded LLM agent** — the model only *phrases* the numbers produced by deterministic risk engines; numeric/action guards reject unsupported wording, with deterministic fallback (not a semantic safety guarantee). Works with **zero API keys** (deterministic fallback), better with [Nugen](https://www.nugen.info) (sponsor) or any OpenAI-compatible API.
- 📈 **Honest ML outlook** — the GBM forecaster predicts next-day temperature anomalies + rainfall, but each target is **only shown when it beats its climatology baseline** (validate-or-withhold). When available, the forecast panel reports its validation MAE against climatology; losing targets remain withheld.

## 🚀 Quickstart

```bash
cd suraksha
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1. Create the database and seed 40 districts
python -m suraksha init-db

# 2. Pull live data + build climatology + score risk (first run: ~2 min)
python -m suraksha ingest

# 3. Ask something (offline templates, no keys needed)
python -m suraksha ask "Is there flood risk in Pune this week?"
python -m suraksha ask "पुणे में गर्मी का खतरा क्या है?"

# 4. Run the dashboard + hourly scheduler
python -m suraksha run            # → http://localhost:8000
```

Open **http://localhost:8000** → use the risk landscape or district explorer → advisory, voice, PDF, CSV, forecast and history. The assistant supports 11 languages. Gujarati/Punjabi/Malayalam/Urdu accept selected localized district aliases; all districts remain searchable by English name or ID. Urdu advisory text renders right-to-left. New translations are experimental.

### Optional: enable the LLM agent + WhatsApp

```bash
cp .env.example .env               # then edit:
# NUGEN_API_KEY=...                # sponsor credits; any OpenAI-compatible endpoint works
# OPENAI_API_KEY=...               # fallback provider
# WHATSAPP_TOKEN=...               # Meta WhatsApp Cloud API (sandbox is enough to demo)
# WHATSAPP_PHONE_NUMBER_ID=...
```

Without keys everything still works — the agent falls back to deterministic multilingual templates.

## Hackathon demo without API keys

```bash
# Separate synthetic database; never use this mode for real warnings.
python -m suraksha demo
# equivalent manual environment configuration:
# DEMO_MODE=true DATABASE_URL=sqlite:///data/demo.db python -m suraksha run
```

The dashboard labels this mode **DEMO / synthetic data**. Mission brief and
what-if lab are available from district tabs and sidebar shortcut 5. The ⛶
button toggles presentation mode. Supported browsers can install the workspace;
visit once while online to cache the shell. No live API responses are cached. Chat, the watchlist,
district advisories, forecast charts and PDF briefs work without external APIs.
The dashboard, coordinate plot and trend charts render from local assets without
CDNs, so the workspace can load over localhost without internet access. Voice falls back
to the browser's installed speech voices, or an explicit text-only message.

Live mode starts ingestion in the background immediately and then hourly. First
archive ingestion can take several minutes due to free API rate limits. Public
hosting needs persistent storage if you want to retain history; `render.yaml`'s
free container storage is ephemeral. No paid LLM is required. WhatsApp requires
your own Meta credentials and may have provider charges/limits; web chat is the
credential-free demo path.

For public hosting, set `ADMIN_API_KEY` and use `X-API-Key` for administrative
endpoints. Without a key, administration is local-only. Set `WHATSAPP_APP_SECRET`
for signed incoming webhooks and a unique `WHATSAPP_VERIFY_TOKEN` for verification.
Subscription management APIs are administrative; web-chat subscription commands
remain available for demo users. See [AUDIT.md](AUDIT.md) for remaining limitations.

## 🧪 Tests (fully offline)

```bash
python -m pytest -q
node --test tests/frontend.test.cjs tests/service-worker.test.cjs
node --check suraksha/web/app.js
node --check suraksha/web/sw.js
```

Offline tests cover: risk engines, i18n, forecaster + model persistence (synthetic data), anomaly detection (seeded DB), ingestion pipeline (mocked HTTP), chat brain, voice synthesis, PDF brief, and FastAPI endpoints. No network or keys. Frontend interaction tests use Node's built-in test runner.

## 🏗️ Architecture

```
DATA LAYER (hourly cron)          INTELLIGENCE LAYER            AGENT LAYER                 DELIVERY
Open-Meteo forecast ─┐            risk engines (heat/flood/air) LLM (Nugen/OpenAI) ─┐      WhatsApp Cloud API
Open-Meteo ERA5   ───┼─► SQLite ► climatology & anomalies ► grounded templates ──┼─►   Indic TTS voice notes
Open-Meteo CAMS AQ ──┘            GBM forecaster (if it beats      chat brain            PDF brief (ReportLab)
                                  the climatology baseline)       (auto language)  ────┘    Local SVG dashboard
```

- **Backend:** Python, FastAPI, SQLAlchemy, APScheduler, httpx
- **ML:** scikit-learn GradientBoosting (beats climatology baseline or it isn't shown)
- **Data:** Open-Meteo forecast + ERA5 archive + CAMS air quality — all free, no API keys
- **Frontend:** dependency-free HTML/CSS/JavaScript with local SVG coordinate plots and trend charts (zero build step, no CDN).

## 📂 Project layout

```
suraksha/
├── plan.md                  # competition plan: problem, timeline, demo script
├── decision.md              # decision log: alternatives, rationale, significance
├── resources/               # district registry + en/hi/mr NDMA-style playbooks
├── suraksha/
│   ├── core/                # risk engines, climatology, forecaster, anomaly
│   ├── data/                # Open-Meteo clients + ingestion pipeline
│   ├── ml/                  # model training/serving bridge (validate-or-withhold)
│   ├── agent/               # i18n, LLM providers, tools, chat brain
│   ├── delivery/            # WhatsApp, voice, PDF brief
│   ├── server/              # FastAPI app + scheduler
│   └── web/                 # dashboard (index.html + app.js)
└── tests/                   # offline pytest suite
```

## 📅 Competition mapping (PCCOE-IGC 2026)

| Stage | Deliverable | Status |
|---|---|---|
| Stage 1 (Jul 1 – Sep 10) | Idea PPT (`teamName_ppt`) | ✅ content in `plan.md` |
| Stage 2 (Oct 1 – Nov 15) | Prototype video | 🔜 demo script in `plan.md` §8 |
| Stage 3 (Jan 2027) | Grand finale live demo | 🔜 stretch goals queued |

## ⚠️ Honest limitations (by design)

- Flood risk is a **rainfall-based proxy**, not a hydrological model — labelled as such everywhere.
- District registry is 42 curated districts in v1, not all Indian districts (extendable; the schema is ready).
- The GBM forecaster is next-day only and is shown only when it beats the climatology baseline; on typical district history (~2 years of observations) it may legitimately be withheld.
- WhatsApp voice-note *input* is not transcribed yet (Indic ASR is a stretch goal) — it triggers the voice-advisory flow instead.

## 📄 License

MIT — see [LICENSE](LICENSE). Data: Open-Meteo (CC-BY 4.0), playbooks adapted from public NDMA/WHO guidance.
