---
name: html-monolith-refactor
description: >
  Use this skill whenever the user asks to refactor, split, restructure, or
  clean up an HTML file that contains inline <style> and/or <script> blocks —
  especially a single-file frontend served by Flask/Jinja (or Django) via
  render_template. Covers extracting CSS/JS into static files, splitting a
  monolithic script into ordered modules, and centralizing global state,
  all WITHOUT changing behavior, adding a bundler, or touching the backend.
---

# HTML Monolith Refactor

Safely split a single-file HTML frontend (inline CSS + inline vanilla JS, no
framework, no build step) into separate static assets, keeping the app fully
runnable and deployable after every step.

## Scope

- Modify ONLY the template and static assets. NEVER modify backend
  routes/handlers. Sole exception: injecting an asset version string for
  cache busting — and only with explicit user approval.
- Do not introduce npm, bundlers, transpilers, or frameworks.
- Do not proceed to any "optional cleanup" step without explicit user opt-in.

## Non-Negotiable Rules

### 1. Classic scripts only
Extracted JS files are CLASSIC scripts loaded with `defer`, in explicit
numbered order:

```
00-config.js   constants, endpoint paths
01-state.js    central App.state
02-utils.js    fetch wrapper, DOM helpers
10..79-*.js    feature modules (auth, data, media, canvas, render, export...)
90-main.js     ALL top-level executable statements / init
```

NEVER use `type="module"`. Inline handlers (`onclick="fn()"`) require
top-level functions to be global; modules break that silently.

### 2. DOM contract is frozen
Existing element IDs, class names, and inline event-handler attributes are a
public API. Never rename or remove them. Every function referenced by an
inline handler stays global. `90-main.js` must assert them at load:

```js
["startPractice", "toggleMic" /* every inline-handler fn */].forEach(f =>
  console.assert(typeof window[f] === "function", `missing global: ${f}`));
```

### 3. Jinja safety
BEFORE extracting any `<style>` or `<script>` block, grep it for `{{` and
`{%`. Templated fragments must NOT move to `/static` (Flask does not render
static files — they will be served literally and fail silently).

- Route dynamic values through ONE inline bootstrap script:
  `window.APP_BOOT = { ... }` — the only inline JS that remains.
- Jinja-dependent CSS stays in a small inline `<style>` block.
- All asset URLs in the template use `url_for('static', filename=...)`.

### 4. Cache busting
Every `<link>` and `<script src>` gets a `?v=` version string. Warn the user:
deploying split assets WITHOUT cache busting will break returning users who
load new HTML with stale cached JS.

## Migration Order

Each step = one commit = app fully runnable = smoke checklist passes.
Copy CHECKLIST.md from this skill folder into the target repo and log each
step there.

- **Step 0 — Baseline.** Commit current state. Write a smoke checklist
  covering every major user flow (auth, data loading, media recording,
  canvas, rendering, export — whatever the app has). Record any
  PRE-EXISTING console errors so later regressions are distinguishable.
- **Step 1 — Extract CSS.** Move the `<style>` block verbatim to
  `static/css/app.css`; add the `<link>`. Grep for Jinja first (Rule 3).
- **Step 2 — Split JS verbatim.** Cut the monolithic `<script>` into the
  numbered files IN THE ORIGINAL SOURCE ORDER. Zero logic changes. Load
  with `defer` in order. (Classic deferred scripts share one global scope
  and execute in document order — behaviorally identical to one block.)
- **Step 3 — Reorganize.** Move functions into their logical modules.
  Rule: numbered module files may only DEFINE things; every top-level
  executable statement moves to `90-main.js` (single init point). This is
  the only step where hoisting/load-order bugs can appear — smoke test
  thoroughly. As each module takes shape, add a `log()` call at its key
  entry points (see Step 3.5).
- **Step 3.5 — Add logging (inline with the refactor, not after).** Add a
  single `log()` helper in `02-utils.js` and emit logs as you migrate each
  module — do NOT add logging upfront (Step 0–2) or defer it to the end.
  This keeps logs next to the code that owns them and avoids logging code
  that is about to move.

  Define exactly one helper, debug-gated so it is silent for end users:

  ```js
  // 02-utils.js
  function log(...args) {
    if (window.APP_BOOT && window.APP_BOOT.debug) {
      console.debug("[loop]", ...args);
    }
  }
  ```

  - **Per-module entry points:** sprinkle `log(...)` at each module's key
    transitions as you touch it in Step 3 — e.g. `20-scenario.js` logs when
    a question loads, `30-recording.js` logs mic start/stop + transcribe
    result, `50-coach.js` logs judge/coaching render. One module per commit,
    so logs land with the code that owns them.
  - **Every fetch, automatically:** the `api()` wrapper (Step 4) is the
    highest-value logging spot. Log `method path status ms` in one place so
    all network calls are visible without touching call sites:

    ```js
    // 02-utils.js
    async function api(path, opts = {}) {
      const t0 = performance.now();
      const res = await fetch(path, opts);
      log(opts.method || "GET", path, res.status, Math.round(performance.now() - t0) + "ms");
      return res;
    }
    ```

  - **Gate it:** logs fire only when `window.APP_BOOT.debug` is true, so
    production stays silent. Set `APP_BOOT.debug = true` during local
    testing (see Risk 5 in the plan); remove or leave false before deploy.
  - **Separate concern:** frontend `log()` is for local debugging only.
    Durable request history lives on the backend (its `after_request`
    logger) and the host's log stream — do not build a frontend logging
    pipeline.
- **Step 4 — Fetch wrapper.** Add one `api(path, opts)` helper in
  `02-utils.js` (with the auto-log from Step 3.5). Migrate call sites ONE
  ENDPOINT AT A TIME, one commit each. Because `api()` logs centrally, every
  migrated endpoint gains visibility for free.
- **Step 5 — Centralize state.** Move magic globals into `App.state`.
  Keep old names alive during migration via aliases:

  ```js
  Object.defineProperty(window, "__compareData", {
    get: () => App.state.compareData,
    set: v => { App.state.compareData = v; }
  });
  ```

  Delete each alias only after grep shows zero remaining direct uses.
  One commit per global.
- **Step 6 — OPTIONAL (explicit user opt-in required).** Convert inline
  handlers to `addEventListener`. Default: STOP before this step. It is
  the highest-risk, lowest-value change.

## Risks — surface these to the user BEFORE starting

1. **Stale cache on deploy** — new HTML + cached old JS for returning
   users. Mitigation: `?v=` versioning (Rule 4).
2. **Jinja inside CSS/JS** — silent `undefined` at runtime if moved to
   static. Mitigation: grep + APP_BOOT bridge (Rule 3).
3. **Hoisting/load-order coupling** — in one file, function declarations
   hoist across 5000 lines; after splitting, only file order preserves
   this. Mitigation: verbatim order in Step 2; definitions-only rule in
   Step 3.
4. **Double initialization** — init code left in a module AND in
   90-main.js causes double listeners/fetches. Mitigation: grep for stray
   top-level calls before each commit.
5. **Media/permission flows** — getUserMedia/MediaRecorder behave
   differently off HTTPS. Test on the deployed HTTPS URL, not just
   localhost.
6. **Logging is silent by default.** The `log()` helper (Step 3.5) is
   gated behind `window.APP_BOOT.debug`. If you add logs but forget to set
   `APP_BOOT.debug = true` locally, you will see nothing — that is intended,
   not a bug. Never make `log()` always-on in production; it is a local
   debugging aid, not telemetry.

## Verification (after EVERY step)

- Run the smoke checklist end to end.
- Browser console: no NEW errors vs the Step-0 baseline.
- `git diff` on the template shows markup unchanged except removed
  `<style>`/`<script>` bodies and added `<link>`/`<script src>` tags.
- During local testing, add `window.onerror = e => alert(e)` temporarily
  so nothing fails silently; remove before commit.
