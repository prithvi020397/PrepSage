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

## Retest #4 — v4 (ce44338)
- Auth 500 (broke all logged-in features, degraded anonymous after login attempt). ROOT CAUSE: c.auth.set_session(token, "") crashed on empty refresh token. FIXED: use c.postgrest.auth(token) for RLS; hardened before_request so no Supabase error 500s (degrades to legacy). Verified /api/me with valid Bearer -> 200 (was 500).
- Flow 4 JD confirm not persisting on reload. ROOT CAUSE: load_progress rebuilt PROGRESS only from per-question rows, dropping _jd/_resume/_deadline. FIXED: store underscore-meta in __meta__ row (new meta jsonb column) + merge back on load. User must run: alter table progress add column if not exists meta jsonb not null default '{}'::jsonb; (done).
- Flow 7 FDE category not hiding at 0 matches. ROOT CAUSE: trailing browseHint div treated as q-item -> .querySelector('.q-title').textContent on null threw, aborting the loop before FDE. FIXED: skip non-q-item siblings in applySidebarFilter.
- Flow 11 mobile /practice side-by-side overflow. FIXED: #main display:block at <=900px so columns stack (can't sit side-by-side). Bumped app.css ?v=4.
- Flow 12 /login -> /dashboard: left as reasonable deviation.

## Remaining (none blocking)
- Real-credential login/persistence verified only after auth fix ships; re-run v4 QA checklist Flow 8/9/14 to confirm.

## Retest #4b — Flow 4 render (dad30bd)
- Confirmed concepts not removed from gap list in UI (server-side persisted fine). ROOT CAUSE: _compute_concept_match early-returned the no-resume (JD-only) path WITHOUT applying user_confirmed. FIXED: split concepts_required into real_gaps/self_reported by user_confirmed in that path too. Verified cloud_platform moves to self_reported, out of gaps, with JD-only (no resume).
- Flow 4 now FULLY fixed: backend + render.
