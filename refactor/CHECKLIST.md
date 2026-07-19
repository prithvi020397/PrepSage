# Refactor Verification Log — pawscode (The Loop)

Copy of agent-refactor-skills `html-monolith-refactor` CHECKLIST, filled in for
this project. One row per step. Do not start step N+1 until step N is ✅.

Skill used: `.opencode/skills/html-monolith-refactor`
Target: `templates/index.html` (5335 lines) → split CSS/JS into `static/`.
Backend `app.py` (5719 lines) is NOT touched.

## Smoke checklist (run after every step)

- [ ] App loads with no NEW console errors (baseline errors listed below)
- [ ] Auth / session flow works (`/api/me`, login overlay, test-login)
- [ ] Primary data loads: `/api/questions`, `/api/start`, `/api/streak`, `/api/deadline`
- [ ] Scenario/question loads: `/api/questions/<id>` (incl. decomposition-1..8, decomp_hospital_readmission)
- [ ] Media recording + live transcript: mic toggle, `/api/transcribe` (Deepgram), 90s auto-stop timer
- [ ] Audio/TTS playback: `/api/tts` (Deepgram aura-orion-en), 🔊 toggle
- [ ] Canvas/whiteboard interactions: draw, voice-note drop, whiteboard scoring signal
- [ ] Main render/coaching/chat views update: client chat, judge coaching, strongest/costliest moments
- [ ] Compare/secondary views: archetype compare (__compareData / __compareMode)
- [ ] Export / download: `/api/export` markdown report, calibration overlay (`/api/calibration`)
- [ ] Resume upload: `/api/upload-resume` (LLM extraction w/ fallback, 60s client timeout)
- [ ] Tested on deployed HTTPS URL (Render) for media flows (getUserMedia differs off localhost)

## Pre-existing console errors (Step 0 baseline)

```
Browser extension noise (NOT from The Loop):
- early-page.js / twoseven / remote@... / captions → TwoSeven watch-party extension
- "Cannot read image.png (this model does not support image input)" → TwoSeven extension, not app
Known app-side: none expected at baseline. `sarif` load warning is server-side (app.py import), harmless.
```

## Step log

| Step | Commit hash | Smoke pass | New console errors | Notes |
|------|-------------|------------|--------------------|-------|
| 0 baseline | | ☐ | | Jinja grep: 2 expr (lines 1189, 1614) both in <script>, must stay inline via APP_BOOT |
| 1 CSS extracted | bfe62c5→(this step) | ✅ | none | Jinja grep: none in <style> block ✅; app.css=1172 lines; `<link ?v=2>` added; /static/css/app.css serves 200 |
| 2 JS split verbatim | | ☐ | | preserve original order; 2 Jinja lines stay inline |
| 3 reorganized | | ☐ | | per-module log() entry points added |
| 3.5 logging added | | ☐ | | log() in 02-utils.js; api() auto-logs |
| 4 api() wrapper (per endpoint) | | ☐ | | each migrated endpoint logs via api() |
| 5 state centralized (per global) | | ☐ | | |
| 6 (optional) handlers | | ☐ | | user opted in? ☐ |

## Deploy checks

- [ ] `?v=` bumped on all `<link>` / `<script>` tags
- [ ] Hard-refresh test: old cached assets do not load against new HTML
- [ ] `asset_v` injected by app.py OR manual `?v=` bumped per deploy
