# Hackathon audit — 2026-10-04

## Reliability and coverage pass

- Centralized district calendar dates in Asia/Kolkata across ingestion, APIs,
  advisories, anomalies, alerts, ML freshness checks, PDFs and demo seeding.
  UTC-hosted servers no longer disagree with the frontend at India midnight.
- Unknown hazard entries no longer suppress valid zero-score advisory entries.
- Added per-hazard coverage counts/missing IDs, complete/partial district counts,
  dashboard missing-data drill-down and seven-day district coverage tables.
- Refresh clears previous scores before changing date and shows explicit unknown/
  unavailable states on failed requests. Registry failures also remain visible.
- Source update timestamps are still not tracked per district. The dashboard
  reports API retrieval time and explicitly says freshness is unverified.
- Added real Chromium smoke verification on desktop/mobile, including local
  synthetic demo flows, export targets/bytes, chat, language changes, voice
  fallback and real PWA offline shell. This is not exhaustive accessibility or
  visual verification, nor evidence of live provider delivery.
- Final checks: 145 Python tests passed under `TZ=UTC`; 2 existing ML tests
  skipped because degenerate synthetic models were withheld. All 15 Node tests,
  Python compilation, JavaScript syntax and diff-whitespace checks passed.
  FastAPI/Starlette emits an existing test-client deprecation warning.
- Repeatable browser check: `python tests/browser_smoke.py <local demo URL>`;
  optional Playwright tooling is separate from runtime dependencies.


## Finale demo expansion

- Added seven-day mission briefs with per-hazard missing-data coverage, priority
  drivers/actions and a browser-print flow. Coverage is explicitly not confidence.
- Added finite, bounded educational scenario inputs and heat/rain/air presets;
  scoring uses the same deterministic engines without database writes.
- Added local manifest/icon/service worker and optional install prompt. App-shell
  caching excludes all API/webhook traffic; responses carry no-store headers.
- Added presentation mode, `demo` one-command safe launch and `doctor` readiness
  reporting. Demo seeding now uses one climatology lookup rather than 15,000 queries.
- Fixed accidental unsubscribe questions, English-selector blocking script
  detection, yesterday-driven future advisories, null-score safe displays,
  malformed subscriber inputs and unnecessary retries of invalid provider requests.
- ML outputs now withhold each target that fails its own baseline comparison.
- Added isolated first-launch demo integration test and service-worker cache-policy
  tests, plus pitch/demo, API and architecture handoff docs in `docs/`.

## Command-center expansion (v0.2)

- Replaced overlapping panels with a responsive premium dark workspace,
  operational metrics, explorer, saved districts, comparisons, preparedness,
  detail drawer and grounded assistant.
- Local SVG HQ risk plot and trend charts replace CDN libraries. No external
  frontend assets are required. The plot is not an administrative boundary map.
- Added `/api/overview`, `/api/languages`, `/api/nearest`, `/api/compare`,
  `/api/preparedness`, district history and CSV export routes with bounded inputs.
- Added hazard/date filters, district search, state/severity/sort controls,
  device-local saved districts/checklist progress, share links and nearest-HQ
  lookup. Location access is requested only by clicking Near me.
- Added Gujarati, Punjabi, Malayalam and Urdu templates/actions, script detection,
  selected district aliases, explicit chat-language selection, speech settings
  and RTL advisory rendering. All new translations remain experimental.
- Added single-process ingestion overlap protection and pipeline status reporting.
  Multi-worker/distributed locking remains unimplemented.
- Added defensive requests, timeouts, stale-response guards, local-storage schema
  checks, empty/error states, focus indicators and reduced-motion styling.
- Verification: 126 Python tests passed, 2 intentionally skipped; 7 dependency-free
  Node frontend interaction tests passed. No browser screenshot/visual verification
  was possible in this environment. Node tests simulate DOM behavior, not a browser.


## Completed and covered by offline tests

- Deterministic heat/rainfall-proxy/air scoring, climatology, anomalies,
  ingestion upserts, district advisories, watchlist, chat and PDF endpoints.
- Existing seven-language expansion preserved; added database column upgrades
  and registry refresh so old installations do not crash after upgrading.
- Chat retains a browser session and remembered language/district. API rejects
  invalid/oversized chat bodies; unknown district text/audio routes return 404.
- Map defaults to today's scores rather than arbitrary future/history rows;
  invalid dates return validation errors. Missing data is not labelled safe.
- Zero rainfall scores low instead of disappearing. Missing input removes stale
  risk scores. Duplicate natural keys within ingestion batches are coalesced.
- AQ scores use each day's available CAMS readings rather than one latest/future
  hour for every historical/forecast day. Latest context AQ is a past-24h mean.
- Wet-spell units corrected; old observations and missing climatology no longer
  generate misleading fresh anomaly alerts. ML calendar-day feature alignment
  corrected, including non-leap-year February boundaries and inference dates.
- TTS output is correctly served/uploaded as MP3; seven voice configurations,
  bounded network synthesis, browser speech fallback and truthful text fallback.
- WhatsApp verification accepts Meta's hub.* parameters; configured webhook
  integration requires app-secret HMAC signatures. Administrative APIs require
  a configured key for remote callers. Alert actions use subscriber language;
  duplicate anomaly log keys are collapsed before saving.
- LLM replies with invented numbers or removed safety actions/citations fall
  back to deterministic text. This is a guardrail, not a semantic safety proof.
- Startup ingestion runs after the server becomes available; scheduler uses IST.
  Docker build excludes secrets/local data. Offline test environment disables
  external services. CI runs tests, compilation and JavaScript syntax checks.
- Explicit offline synthetic demo mode uses a separate database, disables live
  ingestion/scheduling, and displays a demo label. District and language pickers,
  refresh, panel close and asynchronous district-selection protection added.

## Free end-to-end hackathon path

`DEMO_MODE=true DATABASE_URL=sqlite:///data/demo.db python -m suraksha run`

Open localhost:8000, select a district/language, inspect watchlist and forecast,
ask a district question then `forecast`, download PDF, and try voice. No LLM or
WhatsApp credentials are required. Synthetic air quality is deliberately absent
rather than made up. Demo mode refuses a database URL without `demo` in its name.

## Incomplete / limitations (do not pitch as finished)

1. Tamil/Telugu/Kannada/Bengali safety translations and district spellings came
   from existing uncommitted work and still need native-speaker review. Some
   phrases are visibly poor. Detection/wiring tests do not certify translation
   quality. English/Hindi/Marathi remain the safer demo choices.
2. WhatsApp needs a Meta account, token, phone ID, app secret, externally reachable
   HTTPS webhook and provider-side setup. Live delivery was not verified without
   credentials. Proactive messages outside the conversation window generally
   need approved templates; free unlimited WhatsApp delivery is not guaranteed.
3. Webhook parser handles only the first supported message; durable message-ID
   deduplication/retry queues and approved-template delivery remain future work.
4. Web subscriptions are recorded but do not deliver browser push notifications.
   Incoming voice is not transcribed. A missing TTS service can return a flagged
   placeholder WAV from the API; dashboard never plays it as a spoken advisory.
   Browser fallback language availability depends on installed device voices.
5. Geographic plot uses district HQ points, not boundary polygons/base-map
   geography. Plot/chart rendering now uses local SVG with no CDN. Trend series
   are independently scaled and explicitly labelled; consult tables for values.
   Chromium smoke checks now run on desktop/mobile; screenshot artifacts exist,
   but exhaustive visual/accessibility auditing is still outstanding.
6. First ingestion stores only a short recent history; ML normally stays withheld
   until sufficient observations accumulate. Backfill is not implemented. A
   model can beat one target's baseline while losing the other; the losing
   target is now withheld independently. Validation remains holdout-based,
   not field-proven operational accuracy.
7. Daily AQ uses available CAMS hourly model values, not a certified station
   24-hour measurement. Future days without AQ are unknown. Heat uses daily
   maximum temperature and mean humidity (not concurrent peak observations).
   Flood is a rainfall proxy, not a hydrological forecast. No official alert
   authority or validated emergency-service product is claimed.
8. Remaining production work: per-district source freshness timestamps, authentication for
   public chat identities, quotas/rate limits, distributed pipeline locking,
   persistent audit retention, dependency locking/security scanning and full
   privacy deletion. Admin key/local restriction is not a complete auth system.
9. Registry covers 42 curated districts, not 700+. Historical roadmap items such
   as river/fire ingestion, ASR and public production deployment are
   unimplemented. plan.md is the original proposal, not a completion checklist.

Live provider reliability, free-tier quotas and hosting availability are external
constraints. Offline/mocked tests verify application paths, not those services.
