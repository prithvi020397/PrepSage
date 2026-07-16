# Testing Guide

The Loop has no automated UI test suite (see [CONTRIBUTING.md](CONTRIBUTING.md)) — this is a manual
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
- [ ] With no question selected, the **Command Center** renders full-width (left panel hidden):
      greeting + momentum pills, **Start Practice** button, three **lanes** (Focused rep / Mock loop
      / Weak-area drill) as the primary entry points, a **See all tools** toggle that expands the
      **Feature Compass** (5 families, hover tooltips), and a compact standings strip.
- [ ] Clicking a lane starts the matching mode; clicking a sidebar question restores the two-pane
      layout (left panel + resizer reappear).
- [ ] Expanding the Feature Compass and hovering a tool shows its tooltip; collapsing hides it again.
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
- [ ] A leading approximation marker is accepted — e.g. `~211` or `≈211` grades the same as `211`
      (fixed in `napkin_grade()` via `raw_answer.lstrip("~≈ ")`).
- [ ] **New numbers** regenerates the scenario with fresh figures (also in-memory only).

### Mock interview loop
- [ ] **Mock interview** button in the top bar starts a loop across multiple questions and
      **Mock interview report** summarizes it at the end.

## Latest full pass — 2026-07-15

Ran against a live local server (real OpenRouter key, real LLM calls — not mocked) covering
all 41 routes and a hands-on browser walkthrough of onboarding, dashboard, and one question of
each type (SQL, System Design, Tradeoff, Napkin Math). Runtime state files were backed up first
and restored after; no real practice data was affected.

**Backend (all 44 routes reachable, correct response shapes):**
- **Fixed: intermittent empty-response crash.** Previously ~24 LLM-calling routes did
  `resp.choices[0].message.content.strip()` unguarded and 502'd with a leaked
  `'NoneType' object has no attribute 'strip'` when the model returned empty content. All call
  sites now route through `chat_content(resp)`, which returns `None` on an empty/`None` response;
  routes check for `None` and return a clean "try again" 502 instead of crashing. Verified no
  remaining unguarded `content.strip()` outside the two already-guarded interview/hint routes.
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
