# Refactor Verification Log

Copy this file into the target repo (e.g. `refactor/CHECKLIST.md`) and fill
it in as you go. One row per step. Do not start step N+1 until step N is ✅.

## Smoke checklist (define once at Step 0, run after every step)

- [ ] App loads with no NEW console errors (baseline errors listed below)
- [ ] Logging present where applicable: `log()` helper in `02-utils.js`, `api()` auto-logs every fetch, per-module entry-point logs (set `APP_BOOT.debug = true` locally to see them)
- [ ] Auth / session flow works
- [ ] Primary data loads (list the endpoints: ____________)
- [ ] Media recording + live transcript (if applicable)
- [ ] Audio/TTS playback (if applicable)
- [ ] Canvas/whiteboard interactions (if applicable)
- [ ] Main render/coaching/chat views update correctly
- [ ] Compare/secondary views work
- [ ] Export / download works
- [ ] Tested on deployed HTTPS URL (not just localhost) for media flows

## Pre-existing console errors (Step 0 baseline)

```
(paste here — anything listed is NOT a regression)
```

## Step log

| Step | Commit hash | Smoke pass | New console errors | Notes |
|------|-------------|------------|--------------------|-------|
| 0 baseline | | ☐ | | |
| 1 CSS extracted | | ☐ | | Jinja grep result: |
| 2 JS split verbatim | | ☐ | | |
| 3 reorganized | | ☐ | | | per-module log() entry points added |
| 3.5 logging added | | ☐ | | | log() in 02-utils.js; api() auto-logs |
| 4 api() wrapper (per endpoint) | | ☐ | | | each migrated endpoint logs via api() |
| 5 state centralized (per global) | | ☐ | | | |
| 6 (optional) handlers | | ☐ | | user opted in? ☐ |

## Deploy checks

- [ ] `?v=` bumped on all `<link>` / `<script>` tags
- [ ] Hard-refresh test: old cached assets do not load against new HTML
