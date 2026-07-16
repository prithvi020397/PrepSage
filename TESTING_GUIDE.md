# Testing Guide

PrepSage has no automated UI test suite (see [CONTRIBUTING.md](CONTRIBUTING.md)) — this is a manual
click-through checklist covering every feature, plus a running log of the latest full test pass.
If you change a feature a section covers, walk through that section before opening a PR. If you
add a new feature, add a section for it.

Backend scoring logic (`hire_verdict`, `split_wrap_up_reply`, rubric parsing) *does* have automated
coverage — run `python3 -m unittest test_scoring` before you touch anything in that area.

## Setup

```bash
pip install -r requirements.txt
# .env needs OPENROUTER_API_KEY (required) and optionally OPENAI_API_KEY (only for /api/transcribe)
python3 app.py   # http://127.0.0.1:5050
```

Before hand-testing, back up `progress.json` / `history.json` / `chats.json` /
`replay_comments.json` if you have real practice data you care about — every checklist item below
writes to them for real (there's no test/mock mode), and there's no undo.

## Checklist

### Onboarding (`/onboarding`)
- [ ] Fresh install (no `progress.json`) — visiting `/` redirects here instead of `/dashboard`.
- [ ] Fill deadline date + strongest/weakest selects, click **Get started** → redirects to
      `/dashboard`, and the deadline banner on `/practice` reflects the date.
- [ ] **Skip** link goes straight to `/dashboard` without saving anything.

### Dashboard (`/dashboard`)
- [ ] Solved / due-for-review / debriefs-completed counters match reality.
- [ ] Interview-readiness bars, weak-areas-by-topic, and concept mastery map render without
      throwing when there's zero history (new user) and with history (after solving a few).
- [ ] System-design "concepts to revisit" list links (`→`) jump to the right question.
- [ ] Postmortem journal: log an entry, confirm it appears in the list immediately.
- [ ] **← back to practice** goes to `/practice` (not `/`, which would bounce you right back here).

### Practice shell (`/practice`)
- [ ] Sidebar category headers (SQL / Python / System Design / Tradeoff Drills / Napkin Math)
      collapse/expand independently; solved items show a checkmark, due-for-review items are
      visually marked.
- [ ] Filter box narrows the list by question **title** — note it filters titles only, so typing
      a language/category name (e.g. "design") won't match unless a title happens to contain it.
- [ ] Solved counter and deadline countdown in the top bar stay accurate as you solve things.

### SQL / Python questions
- [ ] Selecting a question loads the prompt, sample data/example output, and a **read-only**
      editor — this is intentional, not a bug: the editor stays locked until you clear the
      "clarify first" gate.
- [ ] Type an approach in the plan box, **Check approach** unlocks the editor (Run/Submit go
      live) and shows a pass/fail verdict on your approach + complexity claim.
- [ ] **Run** executes your code against the sample case and shows real output (SQL runs against
      an actual SQLite instance; Python against a real interpreter/subprocess).
- [ ] **Submit** grades against the full hidden test set, updates the solved counter, reveals the
      "key idea" panel, and kicks off the tutor's post-submit thread (recall-check question +
      an automatic code review) — reply in the chat box and confirm the tutor responds in
      context.
- [ ] **Hint**, **Spot the bug**, **Curveball**, **Twist**, **Be the interviewer** each produce a
      distinct tutor interaction — spot-check at least one per PR that touches tutor prompts.
- [ ] Concept-map / trace panel (where present) renders and "check" grades your trace correctly.

### System Design questions
- [ ] Canvas tools: **Box** (drag to draw), **Arrow** (connect two boxes), **Note**, **Select**,
      **Delete**, **Clear** all work; double-click a box to rename it.
- [ ] Picking an interviewer persona (Standard/Skeptical/Friendly/Silent) starts a real tutor
      turn — confirm the opening question matches the persona.
- [ ] Narrower drill modes (**Clarify-only drill**, **Break this design**, **3am stress test**,
      **Scaling pressure**, **Framework mode**) each load a distinct flow.
- [ ] **Wrap up interview** produces a debrief with a hire/no-hire verdict and rubric breakdown.
- [ ] **Replay session** re-opens a past transcript read-only, and posting a replay comment
      attaches it to the right turn.

### Tradeoff Drills
- [ ] Scenario loads with two named options to defend.
- [ ] Type an answer, **Grade my answer** returns substantive tradeoff-specific feedback (not a
      generic template) and marks the question solved on a reasonable answer.
- [ ] **Spar with tutor** and **New scenario** (regenerates a fresh prompt for the same concept)
      both work; note a regenerated scenario is in-memory only and resets on server restart.

### Napkin Math
- [ ] Assumptions box is optional — leaving it blank still lets you submit a numeric estimate.
- [ ] **Check answer** grades deterministically (no LLM latency) against a tolerance band and
      explains the expected order of magnitude either way.
- [ ] ⚠️ Known papercut: the input rejects a leading `~` (e.g. `~211` → "Enter a number.") even
      though the question prompts themselves use `~` for approximation — type the bare number.
      See `napkin_grade()` in `app.py`. Low severity, not yet fixed.
- [ ] **New numbers** regenerates the scenario with fresh figures (also in-memory only).

### Mock interview loop
- [ ] **Mock interview** button in the top bar starts a loop across multiple questions and
      **Mock interview report** summarizes it at the end.

## Latest full pass — 2026-07-15

Ran against a live local server (real OpenRouter key, real LLM calls — not mocked) covering
all 41 routes and a hands-on browser walkthrough of onboarding, dashboard, and one question of
each type (SQL, System Design, Tradeoff, Napkin Math). Runtime state files were backed up first
and restored after; no real practice data was affected.

**Backend (all 41 routes reachable, correct response shapes):**
- One real bug found: **intermittent 502 with a leaked Python exception**
  (`'NoneType' object has no attribute 'strip'`) on `/api/adversarial-design` and, by the same
  root cause, potentially any of the ~20 other LLM-calling routes that don't guard against the
  model returning empty content. Only `/api/interview` and `/api/hint` currently check for this
  (`if not reply: return jsonify({"error": "model returned an empty response — try again"}), 502`);
  every other route calls `resp.choices[0].message.content.strip()` unguarded. Confirmed
  reproducible: identical request succeeded on retry, so it's a real intermittent model-response
  case, not a payload issue. Fix shape: one shared helper used at each call site rather than
  duplicating the guard by hand — see call sites via `grep -n "message.content.strip()" app.py`.
- `/api/transcribe` correctly short-circuits with a clean error when `OPENAI_API_KEY` isn't set
  (by design — OpenRouter doesn't proxy Whisper).

**Frontend (hands-on in a real browser):**
- Onboarding → dashboard → practice flow works end to end, including the deadline banner and
  solved counters staying in sync.
- SQL question: full loop verified (approach gate → editor unlock → Run against real SQLite →
  Submit → grading → recall-check chat reply).
- System Design: canvas draw/label and persona-picker-triggered interview turn both verified.
- Tradeoff Drills: grading returns genuinely scenario-specific feedback, not boilerplate.
- Napkin Math: deterministic grading works; found the `~` input papercut noted above.
- Minor, not a defect: `replay_comments.json` (the same category of per-user runtime file as
  `progress.json`/`history.json`/`chats.json`) was missing from `.gitignore` — added.
