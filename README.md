# PrepSage

An interactive interview-prep tutor covering SQL, Python, System Design, and AI-engineering
(RAG, agents, LLM serving, evals). Unlike a static question bank, PrepSage runs an LLM tutor
alongside every question that gives hints, injects curveballs, challenges your assumptions,
and debriefs your solution afterward.

## Features

- **180+ questions** across SQL, Python, System Design, Tradeoff Drills, and Napkin Math
- **Adaptive tutor** — hints, "spot the bug," clarify-first mode, curveballs/twists, and adversarial design challenges
- **Spaced repetition** — questions resurface based on a due-date scheduler, with a mastery map and weak-area breakdown on the dashboard
- **Chained mock interviews** — combine a coding question, a system design question, and a tradeoff drill into one continuous session
- **Narration & voice** — talk through your approach out loud (mic input) and hear the tutor's replies (TTS)
- **Replay** — step back through a past interview turn-by-turn

## Tech stack

- Flask (backend + templated frontend, no JS build step)
- OpenRouter (via the OpenAI SDK) for the LLM tutor
- Flat JSON files for persistence (`questions.json`, `history.json`, `progress.json`, `chats.json`)

## Getting started

### Prerequisites

- Python 3.10+
- An [OpenRouter](https://openrouter.ai/) API key

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
```

Run the app:

```bash
python3 app.py
```

The app starts at `http://127.0.0.1:5050` with debug/auto-reload enabled.

### Persistence note

`questions.json` ships with the repo (the question bank). `history.json`, `chats.json`, and
`progress.json` are per-user runtime state — they're created automatically on first run and are
gitignored, so your local practice history never gets committed.

## Deployment

The repo includes a `Procfile` and `render.yaml` for deploying to [Render](https://render.com/):
set `OPENROUTER_API_KEY` as an environment variable in the Render dashboard (it's marked
`sync: false` so it's never stored in the repo).

## Project structure

```
app.py                   Flask routes, tutor prompts, spaced-repetition logic
questions.json           Question bank (SQL / Python / System Design / Tradeoff / Napkin Math)
templates/index.html     Main practice UI (editor, tutor chat, canvas)
templates/dashboard.html Progress dashboard (mastery map, weak areas, streak)
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
