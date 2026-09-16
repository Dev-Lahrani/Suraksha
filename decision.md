# Suraksha — Decision Log

Every significant decision, the alternatives considered, why the chosen path won, and its significance to the project. Newest-relevant first within sections. (Format inspired by lightweight ADRs; the team vibe-codes with AI, so decisions optimize for: **offline-verifiable, demo-resilient, judge-legible**.)

---

## D1 — Project choice: Agentic multi-hazard early warning ("Suraksha")

- **Decision:** Build an agentic climate early-warning assistant (disaster resilience track) rather than urban-heat digital twin or agri copilot.
- **Alternatives:**
  - *Urban heat digital twin with generative before/after renders* — visually spectacular but heavy satellite data engineering; high risk of a broken demo.
  - *Agentic farm & water copilot* — big impact but the most crowded idea category; differentiation is hard.
- **Why chosen:** Highest judge-impact per unit of engineering risk. Live open-data feeds make the demo genuinely real-time; the "AI agent + generative AI + multi-modal" framing matches the rulebook's theme sentence verbatim; the last-mile/multilingual angle is emotionally memorable and defensible as novel (the innovation is the delivery layer over existing data, honestly argued).
- **Significance:** Sets the entire architecture: ingestion-first, agent-second, delivery-third. Everything else in this log follows from it.

## D2 — Pan-India scope with a curated 40-district v1 registry

- **Decision:** Ship v1 with ~40 hand-curated districts covering every region (all states represented in the registry), extend to ~780 later via DataMeet/GADM.
- **Alternatives:** Full 780-district registry on day one (slow, error-prone manual data entry); single-state demo (weak "pan-India" story).
- **Why chosen:** Pan-India coverage is the impact story; 40 well-chosen districts demonstrate it convincingly while keeping ingestion cheap and fast. Coordinates were verified against known district HQs.
- **Significance:** The dashboard map and "700+ districts" narrative both flow from here; scaling the registry is a data task, not a code task.

## D3 — Open-Meteo as the single weather/AQ provider (no API keys)

- **Decision:** Use Open-Meteo's three free endpoints (forecast, ERA5 archive, CAMS air quality) for all weather and PM2.5 data.
- **Alternatives:** IMD gridded data (not a clean API), NASA POWER (coarser, slower), NOAA/ERA5 direct (requires CDS account + big downloads), commercial APIs (cost + keys = demo risk).
- **Why chosen:** Zero API keys means zero credential failure modes in a live demo; it serves both *reanalysis history* (climatology + ML training) and *forecast* from one consistent interface; generous rate limits; IST timezone handling built in.
- **Significance:** Makes `python -m suraksha ingest` a one-command reproducible pipeline, and the whole project runnable anywhere with no signups. AQ/CPCB stations are patchy — CAMS model data is uniform across all districts.

## D4 — Deterministic risk engines as the source of truth; ML is an enhancement, not a dependency

- **Decision:** Heat/flood/air scores come from transparent formulas (NOAA heat index, rainfall-vs-climatology ratios, EPA AQI mapping). The GBM forecaster only *adds* predictive rows; nothing depends on it succeeding.
- **Alternatives:** End-to-end ML risk models (black-box, unexplainable, fragile); purely statistical thresholds with no physics (loses credibility).
- **Why chosen:** Judges can read a formula; every number in an advisory is traceable ("heat index 47°C ⇒ high"). ML that fails silently can't break the product — it just falls back to Open-Meteo forecasts. This also satisfies the "clarity" criterion directly.
- **Significance:** The system degrades gracefully: no LLM → templates; no ML → Open-Meteo forecast rows; no AQ → air hazard marked unknown. Nothing crashes the demo.

## D5 — Flood risk labelled honestly as a rainfall proxy

- **Decision:** Flood score = 3-day accumulation vs local heavy-rain (p90) climatology + cloudburst triggers; explicitly labelled "rainfall-based proxy, not a hydrological model" in UI/PDF.
- **Alternatives:** Real hydrological routing (DEM + river networks — weeks of work, out of scope); omitting flood entirely (weakens multi-hazard story).
- **Why chosen:** Best honesty/effort trade-off. A wrong hydrological claim would be a credibility disaster; a well-labelled proxy is defensible and useful.
- **Significance:** Protects the team in Q&A ("is this a hydrological model?" — "No, and here's exactly what it is and why that's useful").

## D6 — LLM agent is tool-grounded with deterministic fallback (never a bare chat model)

- **Decision:** Risk engines produce the numbers; the LLM only rephrases a grounded template. With no API key, the deterministic template IS the product.
- **Alternatives:** Pure LLM chat (hallucination risk on life-safety info); pure templates without LLM (fine but misses the "agentic/generative AI" theme and multilingual fluency).
- **Why chosen:** For early warnings, a hallucinated number is worse than no number. Grounded generation keeps the theme compliance *and* the safety. Also: demo must work with zero credentials.
- **Significance:** `brain.handle_message()` always returns a correct, sourced reply; the LLM is a quality multiplier, not a dependency. Nugen (sponsor) integration is a one-env-var change.

## D7 — Nugen-first LLM routing with OpenAI-compatible fallback

- **Decision:** LLM calls route to Nugen's OpenAI-compatible endpoint first (sponsor credits), then to any OpenAI-compatible fallback, then to templates.
- **Alternatives:** Hardcode one provider; abstract multi-provider framework (over-engineering).
- **Why chosen:** Sponsor alignment is strategic for judging, and OpenAI-compatible chat-completions is a de-facto standard — one `httpx` client covers both providers with a settings switch.
- **Significance:** $200+ participant credits fund the demo; switching providers is a `.env` edit.

## D8 — Language strategy: curated en/hi/mr playbooks + script-based detection

- **Decision:** Hand-translate NDMA-style do/don't playbooks for en/hi/mr; detect language via Devanagari script + Marathi marker words; district names localized in the registry.
- **Alternatives:** LLM-translation on the fly (works, but inconsistent and credential-dependent for a safety product); more languages (later — registry has `name_*` columns ready).
- **Why chosen:** Translated safety actions are deterministic, reviewable, and available offline. Marathi matters locally (Pune judges); Hindi covers the widest audience. Script detection is instant and accurate for these three.
- **Significance:** The multilingual advisory is a headline demo moment and hits the inclusion angle judges reward.

## D9 — SQLite for v1, Postgres-ready via SQLAlchemy

- **Decision:** SQLite file DB by default; SQLAlchemy ORM everywhere so swapping to Postgres is a `DATABASE_URL` change.
- **Alternatives:** Postgres/Timescale from day one (setup friction for teammates and judges who run it locally); raw SQL (loses portability).
- **Why chosen:** A hackathon demo should run with `pip install && python -m suraksha run`. SQLite handles our write volume (hourly upserts for ~40 districts) trivially.
- **Significance:** Zero-friction local runs, CI-friendly tests, and a credible scaling story for Stage 3.

## D10 — Async ingestion with concurrency cap and idempotent upserts

- **Decision:** `asyncio` + `httpx` + `Semaphore(5)` for per-district ingestion; natural-key upserts (district+day, district+hour); climatology computed once and reused.
- **Alternatives:** Sequential requests (too slow for 780 districts); Celery/Redis (ops overkill); delete-and-refetch (wasteful, breaks history).
- **Why chosen:** 40 districts × 3 endpoints finish in seconds; idempotency means cron can crash/restart freely without corrupting data.
- **Significance:** The hourly scheduler is safe by construction; the same pipeline scales to all-India by bumping the semaphore.

## D11 — Climatology aligned by day-of-year with leap handling

- **Decision:** 30-year (1995–2024) ERA5 history aggregated per calendar day-of-year, with a leap-day alignment function so Mar–Dec anomalies compare the same dates across years.
- **Alternatives:** Monthly normals (too coarse for monsoon spikes); fixed 1991–2020 WMO window (fine, but 1995–2024 includes recent extremes — a deliberate choice to baseline against a warmer India).
- **Why chosen:** Daily resolution captures monsoon onset/heat spikes that monthly normals blur; including recent years makes "anomaly" mean "unusual even for the new normal," which is the climate-change story.
- **Significance:** Powers both the anomaly bulletins ("3.2× the 30-year normal") and flood p90 thresholds — the credibility engine of the product.

## D12 — Gradient-boosted forecaster predicts *anomalies*, with mandatory baseline evaluation

- **Decision:** scikit-learn GBM where the temperature model predicts the **anomaly vs next-day climatology** (climatology added back at prediction time) and the rain model predicts absolute mm; `evaluate()` must beat the climatology baseline or the model is not surfaced; recursive multi-step for 5 days.
- **Alternatives:** Absolute-value GBM (wastes capacity re-learning the seasonal curve climatology already provides — measured worse than baseline in tests); deep LSTM (slow, data-hungry, no added value at this horizon); shipping without baseline comparison (unfalsifiable claims).
- **Why chosen:** Predicting anomalies decomposes the problem: climatology owns seasonality, the model owns only what's unexplained (persistence, humidity, lags). This made the difference between losing to and beating the baseline on the evaluation harness — an empirical, not aesthetic, choice. "Our model beats climatology by X%" remains a falsifiable, judge-friendly claim.
- **Significance:** Provides the honest ML slide in the deck; the validate-or-withhold rule protects the demo from a quietly bad model; fully offline-tested on synthetic seasonal data with an out-of-sample baseline.

## D13 — Voice: edge-tts Indic voices with a silent-WAV fallback

- **Decision:** Use edge-tts (free, high-quality Indic neural voices) when available; otherwise synthesize a valid low-amplitude WAV sized to text length, flagged via `X-TTS-Engine` header.
- **Alternatives:** AI4Bharat TTS (better Indic quality but heavier setup); gTTS (Google dependency, flaky); no voice (loses the inclusion story).
- **Why chosen:** edge-tts needs no API key; the fallback guarantees the voice-button demo can never hard-fail on stage Wi-Fi.
- **Significance:** Voice advisories for low-literacy users is a signature feature; demo resilience is preserved.

## D14 — WhatsApp Cloud API in sandbox mode for the demo

- **Decision:** Integrate Meta's WhatsApp Cloud API (text + voice notes via media upload); demo in the free sandbox; webhook verification implemented for production mode later.
- **Alternatives:** Twilio (cost + account setup); Telegram-first (great API, but WhatsApp is where the audience actually is); web-chat only (weakens "delivery where people are" story).
- **Why chosen:** Sandbox gives a real WhatsApp experience with zero approval latency; the delivery layer is already the same message-pipeline the web chat uses.
- **Significance:** The WhatsApp phone-recording is the video centerpiece; production hardening is config, not code.

## D15 — One-page PDF situation brief per district

- **Decision:** ReportLab-rendered district brief: latest risk table with color-coded bands, 7-day outlook, anomalies, and an honest sources/limitations footer.
- **Alternatives:** HTML print stylesheet (inconsistent); skip it (loses the government/policy use-case narrative).
- **Why chosen:** A tangible artifact the team can hand a district collector is a powerful impact story, and it's cheap to build.
- **Significance:** Differentiates the project from "yet another dashboard" — it's a product for officials, not just citizens.

## D16 — Dashboard: server-rendered SPA with CDN libs, no build step

- **Decision:** Single `index.html` + `app.js` served by FastAPI; MapLibre GL for the dark risk map; Chart.js for the 7-day outlook; no npm/webpack.
- **Alternatives:** Next.js/React (nice DX, but build tooling = more failure modes for a hackathon); plain tables (weak wow factor).
- **Why chosen:** Zero build step means zero node_modules pain for teammates; MapLibre + Chart.js from CDN give the professional look. The dark theme demos beautifully on a projector.
- **Significance:** The live risk map over real data is the first thing judges see; it must never fail to load.

## D17 — Testing: fully offline pytest suite, network mocked

- **Decision:** ~40 tests covering risk engines, i18n, forecaster (synthetic data), anomalies (seeded DB), pipeline (mocked HTTP), brain, voice and API endpoints; conftest forces `DATABASE_URL` to a throwaway SQLite and empty LLM keys.
- **Alternatives:** Live integration tests (flaky, slow, credential-dependent); no tests (unacceptable for a "feasibility" pitch).
- **Why chosen:** The whole suite runs in seconds with no network — it will pass in front of judges, in CI, anywhere. Mocked-HTTP pipeline tests double as documentation of the API contract.
- **Significance:** "Feasibility" is a scored criterion; a green offline test suite is proof. It also made this codebase verifiable during development.

## D19 — Completing the loop: forecaster persistence, voice notes, and the PDF-brief fix

- **Decision:** Three closing changes after the initial build: (1) the GBM forecaster is wired into the pipeline via a `model_runs` table (pickled payload + validation MAEs) with a 24-hour retrain throttle and a serve-only-if-it-beats-climatology rule; (2) WhatsApp voice notes are reachable end-to-end — "voice <district>" or an incoming audio message triggers TTS synthesis and a media-upload voice note; (3) a missing `date` import in `pdf_brief.py` (NameError on every PDF request) is fixed with dedicated regression tests.
- **Alternatives:** Serving the GBM unconditionally (dishonest when it loses to climatology); regenerating TTS on every voice request without a WhatsApp path (the feature existed but was unreachable); leaving the PDF bug for "polish week" (it is a headline demo feature).
- **Why chosen:** Each of these was a gap between the plan and the build: the ML slide had no product surface, voice had no WhatsApp path, and the PDF endpoint crashed. All three follow the established resilience pattern — ML withheld is valid, no TTS falls back to text, no WhatsApp credentials degrade to text replies.
- **Significance:** The prototype video can now honestly show all five headline features live: map, chat, voice note, anomaly alert, PDF brief — plus the ML-vs-climatology chart as the falsifiable-claims moment.

## D18 — Scope discipline: what we deliberately did NOT build

- **Decision:** Excluded NASA FIRMS ingestion, real hydrology, satellite nowcasting, Indic ASR input, and PWA offline caching from v1.
- **Alternatives:** Building them (each adds days of work and new failure modes before the video deadline).
- **Why chosen:** Every excluded item is listed in `plan.md` as a stretch goal with a rationale; the demo narrative doesn't depend on them. FIRMS fire data in particular was cut because CAMS AQ covers the air story and fire is seasonal.
- **Significance:** Protects the Nov 8 "everything works" deadline; stretch goals become finale surprises instead of beta blockers.
