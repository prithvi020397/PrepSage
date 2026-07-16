# The Loop

An interactive interview-prep tutor that *adapts to you, with a tutor watching your back*. The Loop
covers SQL, Python, System Design, Tradeoff Drills, and Napkin Math. Unlike a static question bank,
it runs an LLM tutor alongside every question that gives hints, injects curveballs, challenges your
assumptions, and debriefs your solution afterward — plus a **Command Center** home screen that
surfaces the right drill at the right time instead of dumping a giant list on you.

> The repo's old name was `PrepSage`; the product brand is **The Loop**. URLs, the git remote, and
> some docs may still say `PrepSage` — that's the same project.

## What's inside

- **202 questions** across five tracks: SQL (96), Python (66), System Design (20), Tradeoff Drills
  (13), and Napkin Math (7).
- **The Command Center** (`/practice` when nothing is selected) — your home screen:
  - **Three lanes** act as the primary entry points: *Focused rep* (one smart-picked question),
    *Mock loop* (a chained SQL → design → tradeoff interview), and *Weak-area drill* (your
    recurring misses).
  - **Feature Compass** — every drill type grouped into 5 families (Practice, Pressure, Step-through,
    System Design, Reflection) with hover tooltips. Collapsed by default behind a *See all tools*
    toggle so the screen stays calm; expand it to explore the full toolkit (our USP).
  - Live momentum pills (streak / due / solved) and a compact standings strip.
- **Adaptive tutor** — hints, "spot the bug," clarify-first mode, curveballs/twists, adversarial
  design challenges, and a dry run.
- **Spaced repetition** — questions resurface on a due-date scheduler; the dashboard shows a mastery
  map, weak-area breakdown, and postmortem journal.
- **Chained mock interviews** — combine a coding question, a system design question, and a tradeoff
  drill into one continuous session with a wrap-up report.
- **Narration & voice** — talk through your approach out loud (browser mic, zero cost) and hear the
  tutor's replies (TTS).
- **Replay** — step back through a past interview turn-by-turn and leave timestamped comments.
- **System design canvas** — a rough.js whiteboard (boxes, arrows, sticky notes) that syncs to the
  tutor automatically, with layer tagging and persona-driven interview modes.

## Tech stack

- **Flask** backend + server-rendered templates. No JS build step — `templates/*.html` are plain
  HTML/CSS/JS, edited in place.
- **OpenRouter** (via the OpenAI SDK) for the LLM tutor; **Gunicorn** in production.
- **Flat JSON files** for persistence (`questions.json` + precomputed `traces.json`,
  `concept_maps.json`, `solutions.json`, `question_contexts.json`) and per-user runtime state
  (`history.json`, `progress.json`, `chats.json`, `replay_comments.json`).
- **rough.js** (CDN) for the system-design canvas; **CodeMirror** (CDN) for the SQL/Python editor.

## Getting started

### Prerequisites

- Python 3.10+
- An [OpenRouter](https://openrouter.ai/) API key (required — the tutor is the product)
- Optionally an [OpenAI](https://platform.openai.com/) key for `/api/transcribe` (Whisper). OpenRouter
  doesn't proxy Whisper, so transcription silently no-ops without it.

### Setup

```bash
git clone https://github.com/prithvi020397/PrepSage.git
cd PrepSage
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
OPENROUTER_API_KEY=your-key-here
# optional:
OPENAI_API_KEY=your-openai-key
# optional: point the tutor at a local OpenAI-compatible proxy (e.g. Headroom)
HEADROOM_ENABLED=false
```

Run the app:

```bash
python3 app.py
```

The app starts at `http://127.0.0.1:5050` with debug/auto-reload enabled.

### First run / onboarding

On a fresh install (no `progress.json`) visiting `/` redirects to `/onboarding` — set your interview
deadline and strongest/weakest areas, then land on the dashboard. Skipping goes straight to the
dashboard. The deadline compresses review intervals as the date approaches.

### Persistence note

`questions.json` and the four precomputed data files ship with the repo (the question bank + cached
LLM framing). `history.json`, `chats.json`, `progress.json`, and `replay_comments.json` are per-user
runtime state — they're created automatically on first run and are gitignored, so your local practice
history never gets committed.

## Deployment

The repo includes a `Procfile` and `render.yaml` for [Render](https://render.com/): set
`OPENROUTER_API_KEY` as an environment variable in the Render dashboard (it's marked `sync: false` so
it's never stored in the repo). `gunicorn app:app` is the start command.

## Project structure

```
app.py                      Flask routes + logic: tutor prompts, grading, spaced repetition, mock loop
precompute.py               One-off generator that fills traces.json / concept_maps.json /
                            solutions.json / question_contexts.json from questions.json (run once)
test_scoring.py             unittest suite for backend scoring (hire_verdict, rubric parsing, etc.)
templates/
  index.html                Practice UI: editor, tutor chat, design canvas, Command Center
  dashboard.html            Progress dashboard: mastery map, weak areas, streak, postmortem journal
  onboarding.html           First-run setup (deadline + strengths/weaknesses)
static/                     Static assets (currently unused — assets load from CDN)
questions.json             Question bank (5 tracks) — ships with the repo
traces.json                 Per-question worked traces (precomputed)
concept_maps.json          Per-question concept maps (precomputed)
solutions.json             Reference solutions (precomputed)
question_contexts.json     Realistic scenario framing per question (precomputed)
history.json               Per-user attempt history (runtime, gitignored)
progress.json              Per-user spaced-repetition schedule + solved state (runtime, gitignored)
chats.json                 Per-user tutor transcripts (runtime, gitignored)
replay_comments.json        Per-user replay annotations (runtime, gitignored)
```

## Architecture notes

- **Entry points.** `/` redirects to `/onboarding` (fresh) or `/dashboard` (returning). `/dashboard`
  links to `/practice`. `/practice` is the full shell; with no question selected it renders the
  **Command Center**.
- **LLM safety.** Every chat-completions call goes through `chat_content(resp)`, which safely returns
  `None` on an empty/`None` model response instead of crashing with a 502. Routes check for `None`
  and return a clean "try again" error. Previously an empty response at any of ~24 routes threw
  `'NoneType' object has no attribute 'strip'`.
- **No build step.** Frontend is vanilla HTML/CSS/JS in `templates/`. Keep it that way unless there's
  a real reason to add tooling.
- **Editing JSON while running.** Flask's reloader watches `.py` files, not `.json`. After hand-editing
  a data file while `app.py` is running, `touch app.py` to force a restart, or the running process can
  overwrite your edit on its next write.

## Testing

- **Backend scoring:** `python3 -m unittest test_scoring` (run before touching grading logic).
- **Manual UI checklist:** see [TESTING_GUIDE.md](TESTING_GUIDE.md) — there is no automated UI suite
  by design. Walk the relevant section before opening a PR.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
