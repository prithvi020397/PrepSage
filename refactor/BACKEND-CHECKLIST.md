# Backend Refactor Verification Log

Copy this file into the target repo (e.g. `refactor/BACKEND-CHECKLIST.md`)
and fill it in as you go. One row per phase. Do not start phase N+1 until
phase N is ✅.

## Baseline (capture BEFORE Phase 0)

- [x] `app.url_map` dumped to `refactor/routes-baseline.txt` (72 rules)
- [x] JSON responses of 2–3 representative endpoints captured via curl (`/api/questions`, `/api/start`, `/api/streak` → `refactor/json-baseline.txt`)
- [x] Full test suite green (count: 43)
- [x] Pre-existing errors/warnings listed below

```
- "Could not load 'sarif': No module named 'sarif_om'" — from bandit (security linter), not our app. Harmless; appears at import. NOT a regression.
- TwoSeven browser extension errors in browser console (image.png "does not support image input", onUpdate-profile). External extension noise, not app.
```

## Fragile-fix inventory (from reading the whole file)

| Function / constant | Why it's fragile | Preserved? |
|---------------------|------------------|------------|
| `topic_for()` | schema-agnostic: handles classic (`prompt`) AND v2 decomposition (`persona`/`triggers`/`rubric`, no `prompt`). Breaking it broke `/api/start` before. | ☑ preserved (not touched in Phase 0) |
| `run_judge` `max_tokens=4096` + `_repair_truncated_json()` | depth-aware brace rebalance for truncated judge JSON. Broke scoring before. | ☑ preserved (not touched in Phase 0) |
| `/api/transcribe` defined TWICE (L4965 + L5565) | Flask keeps only one handler; dedup needed in Phase 1. | ☐ pending Phase 1 |
| gunicorn `workers 1` | module-level state not concurrency-safe; do NOT raise worker count. | ☑ preserved |

## Phase log

| Phase | Commit hash | Tests green | url_map unchanged | curl diff clean | Notes |
|-------|-------------|-------------|-------------------|-----------------|-------|
| 0 logging | (local, not pushed) | ☑ 43 passed | ☑ 72 rules match | ☑ (no route/behavior change) | RotatingFileHandler(5MB×5) + stderr; log.exception in 18 LLM/parse/auth except blocks; print()→log.debug for 3 debug dumps; after_request already logged method/path/status/ms |
| 1 duplicate routes | (local, not pushed) | ☑ 44 passed | ☑ 72 rules match | ☑ | Removed Whisper `transcribe()` dup at L5600; kept Deepgram `transcribe_audio` (returns `transcript`, matches frontend). Added test_route_inventory asserting exactly one `/api/transcribe`. NOTE: this was a live bug — Flask served the last-registered (Whisper) route, which returns `text` + needs OPENAI_API_KEY (unset in cloud), so transcription was effectively broken in production. |
| 2 characterization tests | (local, not pushed) | ☑ 63 passed | ☑ 72 rules match | ☑ | Added test_backend_characterization.py (19 tests) pinning: topic_for (classic + v2 decomposition schema, no `prompt`), _repair_truncated_json (5 cases incl LIFO closers + unterminated string), hire_verdict bands (pct 0.85/0.60 + points 0/-3 boundaries), is_solved/is_due, schedule_review interval (0→7, 1-2→3, >2→1). No behavior change — these were verified against CURRENT behavior (fixed 2 wrong assumptions about schedule_review truncation + hire_verdict points). |
| 3 core/ extracted | | ☐ | ☐ | ☐ | |
| 4 services/ extracted | | ☐ | ☐ | ☐ | |
| 5 blueprints | | ☐ | ☐ | ☐ | |
| 6 (optional) persistence | | ☐ | ☐ | ☐ | user opted in? ☐ |

## Push gate

- [ ] User explicitly approved push
- [ ] All phases above ✅ at time of push
