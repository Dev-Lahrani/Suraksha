# Architecture and operations

## Data-to-action path

```text
Open-Meteo forecast / ERA5 / CAMS
                 ↓ async bounded ingestion
SQLite ← SQLAlchemy natural-key upserts
  ↓                   ↓
Climatology       Observations / forecast
  ↓                   ↓
Deterministic heat / rainfall proxy / AQ risk engines
  ↓ drivers JSON + scores + availability
Advisory templates / mission brief / watchlist / scenario lab
  ↓ optional guarded LLM wording (not numeric source)
Local HTML/CSS/JS workspace · PDF/CSV · optional edge-tts / WhatsApp
```

The scenario lab invokes the same scoring functions but never writes SQLite.
The synthetic demo stores only in a separate demo-named database. Installed PWA
caching covers static shell assets only, not API results.

## Modules

- `core/risks.py`: NOAA-style heat index, rainfall proxy and EPA AQI mapping.
- `core/climatology.py`, `core/anomaly.py`: calendar-day normals and explainable
  anomalies; not a statistical guarantee of predictive accuracy.
- `core/forecaster.py`, `ml/runner.py`: optional GBM training/persistence, holdout
  comparison and per-target validate-or-withhold serving.
- `data/pipeline.py`: scheduler/manual overlap guard in a single process,
  five-district concurrency, idempotent upserts, optional AQ/ML degradation.
- `agent/`: language detection/templates, district resolution and session memory.
- `server/insights.py`: overview, comparison, history/export, nearest HQ/checklists.
- `server/missions.py`: mission priorities/timeline and isolated scenario inputs.
- `delivery/`: PDF, TTS, WhatsApp and proactive-alert logging.
- `web/`: locally served workspace; no npm build/runtime dependencies.

## Run modes

`python -m suraksha demo` is the reliable local presentation mode. It binds
127.0.0.1, creates/seeds `data/demo.db` and labels synthetic results.
`python -m suraksha run` initializes live storage and starts background ingestion.
`python -m suraksha doctor` reports local readiness; it does not call providers or
print credential values. `ingest` and `ask` initialize storage before use.

Use Python 3.11+ and one Uvicorn worker for the SQLite hackathon deployment. Set
server timezone to IST for calendar alignment. A persistent data volume is needed
to retain observations, subscriptions and models across container replacement.
Free hosting descriptors are not a promise of durable storage or availability.
Docker ignores .env, local databases, virtual environments and .git.

## Tests

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m pytest -q
node --test tests/frontend.test.cjs tests/service-worker.test.cjs
node --check suraksha/web/app.js
node --check suraksha/web/sw.js
python -m compileall -q suraksha tests
```

Python fixtures set a disposable DB and disable network-backed optional services.
An isolated subprocess starts a fresh demo with TestClient and exercises registry,
watchlist, mission brief, chat, comparison, scenario, PDF/CSV and PWA assets.
Node tests exercise DOM logic and service-worker API exclusions without packages.
They are not real-browser visual/accessibility tests. Provider integrations are
mocked; live availability and WhatsApp setup must be verified separately.

## Not production claims

- Registry is 42 HQ points, not 700+ boundaries.
- Daily mean humidity with maximum temperature is an approximate driver pairing.
- Flood is a rainfall proxy; no basin routing/shelter database exists.
- AQ is CAMS model data, not certified station measurements.
- Language expansions need native-speaker safety review.
- LLM numeric/action guards cannot prove semantic correctness.
- Single-process overlap control is not distributed locking.
- Authentication, rate limiting, complete erasure, durable webhook dedupe/template
  delivery and dependency locking/security scanning remain production work.
- PWA install capability/device speech depends on browser/platform; offline shell
  without API access does not create current warnings.

See [DEMO_GUIDE.md](DEMO_GUIDE.md), [API.md](API.md) and ../AUDIT.md for handoff.
