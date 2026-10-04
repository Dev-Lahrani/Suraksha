# API and integration guide

Interactive OpenAPI documentation: `/docs`. Schema: `/openapi.json`.
All examples target a running local server. Dates use YYYY-MM-DD. Most backend
calendar logic uses Asia/Kolkata independently of the server timezone, matching
the dashboard and Open-Meteo district dates.

## Public read endpoints

| Route | Purpose / parameters |
|---|---|
| `GET /api/health` | Service health, demo flag, current-process ingestion status |
| `GET /api/districts` | 42 curated districts and available localized names |
| `GET /api/languages` | 11 languages, direction, locale, experimental flag |
| `GET /api/risk-map?day=` | Scores on selected day, defaults to today |
| `GET /api/overview?day=` | Coverage and severity counts; population is registry total, not exposure |
| `GET /api/watchlist?limit=6&hazard=all&days=2` | Peak-ranked future-window districts; limit 1–50, days 0–7 |
| `GET /api/resolve?name=Pune` | Resolve district ID/name/selected aliases |
| `GET /api/nearest?lat=18.52&lon=73.86` | Nearest curated HQ, not boundary lookup |
| `GET /api/compare?ids=PUNE,NAGPUR&lang=en` | 2–4 unique districts, peak advisory-window comparison |
| `GET /api/preparedness?hazard=flood&band=high&lang=hi` | Localized checklist actions; progress is frontend-local |
| `GET /api/district/PUNE?lang=en` | Context plus deterministic advisory |
| `GET /api/district/PUNE/forecast` | Available daily weather forecast |
| `GET /api/district/PUNE/forecast-text?lang=hi` | Text forecast |
| `GET /api/district/PUNE/advisory?lang=hi` | Text advisory and language |
| `GET /api/district/PUNE/air-quality` | Stored recent CAMS hourly model readings |
| `GET /api/district/PUNE/history?days=30` | Bounded history plus forecast, days 1–365 |
| `GET /api/district/PUNE/export.csv?days=30` | Downloadable CSV, including synthetic-demo flag |
| `GET /api/district/PUNE/mission?lang=en` | Seven-day mission timeline, priorities, missing hazards, availability coverage |
| `GET /api/district/PUNE/brief.pdf` | English PDF brief (ReportLab) |
| `GET /api/district/PUNE/ml-outlook` | Optional validated ML targets; losing targets are null |

Unknown district endpoints return 404. Invalid bounded parameters return 422.
`null` scores mean unknown, never zero/safe. Partial hazard availability is
reported explicitly; the overall maximum uses only scored hazards.

### Hazard coverage schema

`GET /api/overview?day=YYYY-MM-DD` additionally returns `fully_covered` (all three
hazards scored), `partial` (one or two) and `hazard_coverage`. Each `heat`, `flood`
and `air` entry has `covered`, `unknown` and sorted `missing_district_ids`.
Zero is a known score; null is unknown. These counts describe stored score
availability, **not source freshness or model confidence**. Source ingestion
timestamps are not yet stored per district; the dashboard explicitly labels
freshness unverified and reports API retrieval time separately.

## Public action endpoints

### Chat

`POST /api/chat`

```json
{"session_id":"web-example","message":"Pune advisory","language":"hi"}
```

Message maximum: 4,000 characters. Session ID maximum: 128. Omit language/null for
script detection and remembered language; explicit supported language selects
that response language. Browser English selection leaves script detection enabled.
Chat identities are not authenticated; do not treat this demo API as private.

### Educational scenario

`POST /api/scenario`

```json
{"tmax":44,"humidity":65,"rain_today":110,"rain_3day":260,"rain_p90":35,"pm25":180,"language":"en"}
```

Returns input echoes, deterministic scores/drivers/actions, `simulation: true`
and `persisted: false`. No district records are written. Rain_3day must include
rain_today. Temperature/humidity/rain/PM2.5 have bounded finite numeric validation.
Omitted PM2.5 is unknown. This is not forecast or real-world validation evidence.

### Voice

`POST /api/district/PUNE/voice?lang=hi`

Real edge-tts bytes are `audio/mpeg`, `X-TTS-Engine: edge-tts`. Failed synthesis
returns a flagged placeholder WAV (`X-TTS-Engine: fallback`); the frontend never
plays this as speech, instead attempting device speech or showing text guidance.

## Administrative endpoints

`POST /api/ingest?force=false`, `POST /api/alerts/sweep`, subscription create/read/
soft-delete/hard-delete routes require `X-API-Key` when ADMIN_API_KEY is set.
Without that key, only local clients may administer. This is a prototype-level
control, not a full user authentication system. Demo mode blocks live ingestion.

Webhook verification accepts Meta's `hub.mode`, `hub.verify_token` and
`hub.challenge`. Configured incoming delivery requires WHATSAPP_APP_SECRET and
valid `X-Hub-Signature-256`. Approved templates, retry deduplication and credential
setup are still required for robust real proactive delivery.

## Offline and privacy behavior

- API/webhook responses carry `Cache-Control: no-store`.
- Service worker caches only `/`, JavaScript, CSS, manifest and icon.
- No live warnings, chat replies, location coordinates or subscription API data
  are stored by the service worker.
- Saved district IDs/checklist flags/language/session ID live in browser local
  storage. These are not cloud-synced; clear site data to remove them.
- Browser location is requested on explicit click and sent to the nearest-HQ API.
- API availability coverage is not an accuracy/confidence estimate.
