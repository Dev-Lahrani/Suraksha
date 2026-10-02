# Hackathon audit — 2026-10-03

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
5. Map uses district HQ points, not boundary polygons/base-map geography. CDN
   assets are not bundled; fully offline map/chart rendering is not guaranteed.
   No automated browser visual tests ran (Chrome unavailable).
6. First ingestion stores only a short recent history; ML normally stays withheld
   until sufficient observations accumulate. Backfill is not implemented. A
   model can beat one target's baseline while losing the other; per-target
   withholding and clearer validation presentation are still needed.
7. Daily AQ uses available CAMS hourly model values, not a certified station
   24-hour measurement. Future days without AQ are unknown. Heat uses daily
   maximum temperature and mean humidity (not concurrent peak observations).
   Flood is a rainfall proxy, not a hydrological forecast. No official alert
   authority or validated emergency-service product is claimed.
8. Remaining production work: global IST date handling, authentication for
   public chat identities, quotas/rate limits, pipeline overlap locking,
   persistent audit retention, dependency locking/security scanning and full
   privacy deletion. Admin key/local restriction is not a complete auth system.
9. Registry covers 42 curated districts, not 700+. Historical roadmap items such
   as river/fire ingestion, ASR, PWA caching and public production deployment are
   unimplemented. plan.md is the original proposal, not a completion checklist.

Live provider reliability, free-tier quotas and hosting availability are external
constraints. Offline/mocked tests verify application paths, not those services.
