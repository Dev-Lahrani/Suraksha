# Suraksha: judge-ready demo runbook

## One-sentence pitch

**Suraksha turns open climate signals into explainable district priorities and
multilingual safety guidance—even when paid AI keys and venue internet fail.**

This is a decision-support prototype, not an official warning authority.

## Start safely

From the repository root, after installing requirements:

```bash
python -m suraksha doctor
python -m suraksha demo
```

Open http://localhost:8000. The `demo` command uses a separate `data/demo.db`,
seeds all 42 curated districts, disables live ingestion, and labels synthetic
results. It binds localhost by default. Use `--port 8001` if 8000 is occupied.

For live data use `python -m suraksha run` without DEMO_MODE; allow time for first
archive ingestion and public API rate limits. Keep an explicitly labelled demo
fallback ready. Never describe synthetic scores as a real weather event.

## 3-minute script

| Time | Action | What to say |
|---|---|---|
| 0:00–0:20 | Show Overview and demo banner | “The problem is not a shortage of climate data. It is getting clear local next steps to people in time.” |
| 0:20–0:45 | Click the top priority district | “This watchlist answers where to look first. The reason comes from the engine's drivers, not invented AI text.” |
| 0:45–1:10 | Open Mission brief | “We show the next seven days, missing hazards, priorities and safety actions. Coverage is availability—not a fake confidence score.” |
| 1:10–1:35 | Switch Hindi/Marathi, listen, download PDF | “The same numbers become guidance in a user's language. Deterministic templates work without a paid model. New translations remain experimental.” |
| 1:35–2:00 | Compare two districts and export CSV | “Officials get triage, traceability and a portable brief, not just a chatbot.” |
| 2:00–2:25 | What-if lab → Heavy-rain example | “Here is the mechanism. Change the inputs and inspect the rainfall proxy. This simulation never changes live records.” |
| 2:25–2:45 | Check a preparedness task; toggle presentation | “Guidance leads to an action, with device-local progress and a responsive interface.” |
| 2:45–3:00 | Sources & limitations | “42 curated districts today; an extendable registry. Our next step is field validation with local responders—not claiming a tested emergency service.” |

Use sidebar shortcuts 1–5 for overview, explorer, compare, preparedness and lab.
Use ⛶ to hide the sidebar for a clean presentation. Select a district before
using a chat quick prompt, or save one first.

## Demo safety checklist

- [ ] Confirm the DEMO banner is visible when using synthetic data.
- [ ] Open a high-risk watchlist entry; confirm Mission brief loads.
- [ ] Download one PDF and CSV before the presentation.
- [ ] Test browser audio on the actual machine; device voices vary.
- [ ] Use English/Hindi/Marathi for the primary safety demo.
- [ ] Show Urdu RTL as experimental language reach, not validated translation.
- [ ] Keep a recorded demo backup; do not depend on WhatsApp credentials.
- [ ] Run the offline test suites before recording.
- [ ] Verify no .env, local database or credentials appear in slides/screenshots.

## Questions judges may ask

**Is the flood score a hydrological prediction?** No. It is an explainable
rainfall-accumulation proxy against daily climatology. No river routing is claimed.

**What does the AI do?** Deterministic engines own the numbers. Optional grounded
LLM wording has fallback guards. The GBM temperature/rain targets are surfaced
only when each beats its holdout climatology baseline.

**Does 11-language support mean all translations are validated?** No. Detection,
formatting and delivery wiring are tested. New language safety content needs
native-speaker and responder review. Numeric data remains shared and traceable.

**Is it entirely free?** The local synthetic/web demo needs no paid services or
API keys. Live feeds have provider quotas. Hosting and WhatsApp can have limits
or charges. Device speech varies. Do not promise unlimited free production use.

**Will it work offline?** The local demo needs no internet. A service worker caches
the installed app shell, never warnings/chat APIs. Without a running server or
API connection, current risk data is unavailable—not silently served stale.

**What impact have you measured?** Engineering evidence: runnable end-to-end demo,
regression tests, explainable formulas, accessible delivery paths. No field-study
impact, lives-saved estimate or forecast-accuracy claim is asserted.

## Recovery

- Empty live workspace: wait for ingestion, inspect health pipeline status, or
  restart with `python -m suraksha demo` and announce synthetic mode.
- Voice unavailable: read the advisory; browser fallback requires installed
  voices. Audio failure must never hide the complete text.
- Wrong/old frontend after updating: close all installed tabs and reopen; old
  service worker updates activate when previous clients close. Browser clear-site
  data removes saved districts/checklists too.
- Location blocked: use search. “Near me” chooses a curated HQ, not district borders.
- PDF/CSV failure: verify the district exists and the local server is running.
