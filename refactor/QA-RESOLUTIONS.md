# QA Report Resolutions — The Loop

Live: https://the-loop-zfn5.onrender.com
Source QA: The-Loop-QA-Test-Report.pdf (local download)

Status: ALL reported items resolved or explicitly deferred (infra-limited).

## Critical / High
- `/api/interview` missing `question_id` → 400 JSON (was 500 HTML). FIXED (e73e0e6).
- `CHATS_FILE`/`JUDGES_FILE`/`REPLAY_COMMENTS_FILE` not in `save_*` imports (NameError). FIXED (ff8f17c).
- Resume `skills`/`domains` dict-shape joins (coach/study-plan). FIXED (ff8f17c).
- `QUESTIONS is not defined` on Start Practice (60-module.js). FIXED (456c7fb).
- JD-parse 500 → 200 (service namespace lazy-import). FIXED (456c7fb).

## Medium
- Framed-practice `/?q=` → `/practice?q=`. FIXED (456c7fb).
- Mobile practice layout stacks. FIXED (456c7fb, app.css @media).
- Gap tooltip shows concept name. FIXED (456c7fb).
- Tradeoff grader addresses "you". FIXED (456c7fb).
- Editor cross-language code leak. FIXED (ed2dc99, lang guard).
- Sidebar filter counts update. FIXED (ed2dc99).
- Login reason messaging (`requireAuth(reason)`). FIXED (ed2dc99).
- Erase-modal wrong-input hint. FIXED (ed2dc99).
- Postmortem UTC→local date. FIXED (ed2dc99, client formatter).
- "I've done this" 400 for no-JD/anon. FIXED (ed2dc99, gated on `jd_loaded`).
- Duplicate bank question `sql-2`/`sql-10`. FIXED (ed2dc99, sql-10 retitled "Recurring emails (appears more than once)").

## Low / Minor
- Custom 404 page + `/login`,`/signup` 302→`/`. FIXED (815be51, templates/404.html).
- "⚡ Test drive" stays anonymous. FIXED (815be51, testLogin always reloads).

## Deferred (infra / out of scope)
- 4.2-4 Anonymous state volatile on free-tier — infra (instance recycling). Mitigated by signup banner.
- 4.3-5 — already fixed in prior pass (grader addresses "you").

## Verification
- 63 pytest tests pass.
- All JS modules `node --check` clean.
- Live smoke (815be51): /login→302 /, /signup→302 /, /nope→404 styled, /api/me→anonymous, /api/interview {}→JSON error, /api/jd→200.

## Retest #2 — regressions from fixes (76dae67)
- Timezone script pasted without <script> tags (raw code visible + date fix never ran). FIXED: moved inside <script> in dashboard.html. Verified live: block inside a script tag.
- Sidebar category counts all showed 204 (used total .q-item count of parent). FIXED: count per-section siblings; hide empty categories while filtering (60-module.js).
- Mobile /practice layout never collapsed. ROOT CAUSE: index.html had no <meta viewport> so mobile rendered at desktop width. FIXED: added viewport to index.html + dashboard.html; strengthened @media (max-width:900px) to stack #body/#sidebar/#main, drop min-widths; added 560px phone tier; bumped app.css?v=3.

## Still open (retest #2)
- Onboarding accepts empty form (Skip exists — likely intentional; confirm with product).
- Anonymous state volatility / ephemeral Render disk — infra; move persistence off local disk (Supabase already the cloud path).
- /api/me 401 for anonymous — cosmetic monitoring noise; body already says mode:anonymous.
