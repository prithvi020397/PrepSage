---
name: flask-monolith-refactor
description: >
  Use this skill whenever the user asks to refactor, split, restructure, or
  clean up a single-file Flask (or similar WSGI) backend — one large app.py
  with many @app.route definitions, module-level state, and no blueprints or
  package structure. Covers adding failure observability first, removing
  duplicate routes, characterization tests, extracting pure helpers and
  services, and converting routes to blueprints — all WITHOUT changing
  behavior, response shapes, or route contracts, and without touching the
  frontend.
---

# Flask Monolith Refactor

Safely restructure a single-file Flask backend (one giant `app.py`) into
`core/` + `services/` + `routes/` blueprints, keeping the app fully runnable
and deployable after every phase. Structure + observability only — never a
behavior change.

## Scope

- Backend only. NEVER touch frontend assets, templates' markup, or static
  files.
- Keep every JSON response shape byte-compatible. Clients depend on them;
  "cleaner" response formats are a behavior change, not a refactor.
- No new third-party dependencies without explicit user approval. Logging
  uses stdlib (`logging`, `logging.handlers`) only.
- Env-var-driven modes (feature flags, auth toggles, legacy modes) keep
  identical semantics. If the app runs single-worker because module-level
  state is not concurrency-safe, do NOT raise the worker count.
- Persistence changes (JSON files → DB) are OUT of scope unless explicitly
  requested, and only after the structure phases are done.

## Non-Negotiable Rules

### 1. Read the whole file first
Read all of `app.py` before editing anything. Map: routes, helpers, shared
module-level state, and which functions each route calls. Fragile fixes live
in monoliths (truncation repair, schema-agnostic helpers, retry wrappers) —
identify them BEFORE moving code and preserve them intact. Ask the user
which functions are known-fragile if the history isn't visible.

### 2. Observability before restructuring
`except Exception as e: return jsonify({"error": str(e)})` with no logging
means production failures are invisible — and invisible failures make a
refactor unverifiable. Phase 0 is always logging, never code movement.

### 3. One phase = one commit = green tests
Run the full test suite after every phase. Do not proceed on red. Never push
without explicit user approval.

### 4. Characterize before you move
No function moves files until a test pins its current behavior — including
its weird cases (both input schemas, malformed JSON, boundary values).
The tests must pass unchanged before AND after the move.

### 5. Moves are verbatim
Extraction = cut, paste, import. Zero logic edits in a move commit. Any
"while I'm here" improvement goes in its own later commit, flagged to the
user first. If a behavior change is unavoidable, STOP and flag it before
doing it.

## Migration Order

Copy CHECKLIST.md from this skill folder into the target repo and log each
phase there.

- **Phase 0 — Logging / failure observability (DO FIRST).**
  - One module logger with `RotatingFileHandler` (size-capped + backups)
    plus stderr. Format includes timestamp,
    `%(levelname)s %(name)s %(module)s:%(lineno)d`.
  - Every `except` block calls `log.exception("context: <what failed>")`
    BEFORE returning the error response. Prioritize routes that call LLMs,
    parsers, external APIs, and auth.
  - Convert raw `print()` debug dumps to `log.debug(...)`.
  - Info-level entry logging on the riskiest routes: method, path,
    provider/model, duration.
  - Verify: trigger a real error → full traceback in log file + stderr;
    rotation works at the size cap; `import app` loads clean.
- **Phase 1 — Kill duplicate routes.** Flask silently keeps only one
  handler per rule; find duplicates
  (`grep -n '@app.route' app.py | sort` by path), determine which is live,
  delete the dead one. Add a test asserting each rule maps to exactly one
  endpoint.
- **Phase 2 — Characterization tests (no refactor).** Pin current behavior
  of every pure helper that will move: schema-handling functions with ALL
  schemas they accept, scoring/banding boundaries, scheduling predicates,
  JSON-repair functions with truncated input. These tests must stay green
  through every later phase.
- **Phase 3 — Extract pure helpers into `core/`.** Group by domain
  (e.g. `core/questions.py`, `core/schedule.py`, `core/concepts.py`).
  Pure functions only — no Flask imports, no module state. Verbatim moves,
  covered entirely by Phase 2 tests.
- **Phase 4 — Extract services into `services/`.** Side-effectful
  collaborators: LLM client + prompt builders (keep existing timeout/retry
  values), grading/judging, code execution, document extraction + fallback
  chains, persistence (save functions, atomic-write helper, the
  module-level dicts — a single `Store` object is acceptable if it changes
  nothing observable).
- **Phase 5 — Blueprints in `routes/`.** Group routes by domain (auth,
  practice, documents, analytics, pages, ...). `app.py` becomes a thin
  entrypoint: app factory + blueprint registration + logging setup. URL
  rules must be identical — no url_prefix that changes any path.
- **Phase 6 — OPTIONAL (explicit user opt-in required).** Persistence
  upgrade (files → DB) to lift the single-worker cap. Default: STOP before
  this phase.

## Risks — surface these to the user BEFORE starting

1. **Invisible failures** — swallowed exceptions mean you can't tell a
   refactor regression from a pre-existing bug. Mitigation: Phase 0 first;
   record pre-existing errors as a baseline.
2. **Import-time side effects** — module-level code (client init, file
   loads, dict population) runs on import; splitting files reorders it.
   Mitigation: keep initialization explicit in the entrypoint/factory.
3. **Circular imports** — routes ↔ services ↔ state. Mitigation: strict
   dependency direction `routes → services → core`; state lives in one
   module.
4. **Shared mutable state by reference** — `from app import PROGRESS` in a
   new module can rebind instead of share, or duplicate the dict.
   Mitigation: import the module (or Store), never the bare dict.
5. **Fragile fixes silently dropped** — hand-tuned constants
   (max_tokens, timeouts, retry counts) and repair functions look like
   cruft and get "cleaned up". Mitigation: Rule 1 inventory + Phase 2 tests.

## Verification (after EVERY phase)

- Full test suite green (`python -m pytest`).
- App boots; hit 2–3 representative endpoints with curl and diff the JSON
  against a pre-refactor capture.
- Route inventory unchanged: dump `app.url_map` before Phase 0 and diff it
  after every phase (same rules, same methods, same endpoints count).
- Grep for leftover top-level executable statements in extracted modules —
  extracted files should only define.
