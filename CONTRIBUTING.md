# Contributing to PrepSage

Thanks for taking a look. This is a small, single-file-backend Flask app — the goal here is to
keep it easy to run and easy to change, not to add process for its own sake.

## Local setup

See the [README](README.md#getting-started) for install steps. In short: `pip install -r
requirements.txt`, add `OPENROUTER_API_KEY` to a `.env` file, run `python3 app.py`.

## Project layout

- `app.py` — all backend routes, tutor prompts, and grading/spaced-repetition logic
- `questions.json` — the question bank (SQL / Python / System Design / Tradeoff / Napkin Math)
- `templates/index.html` — the practice UI (editor, tutor chat, canvas) — vanilla JS, no build step
- `templates/dashboard.html` — the progress dashboard
- `history.json` / `chats.json` / `progress.json` — per-user runtime state, gitignored, created automatically

There's no frontend build tooling on purpose — `templates/*.html` are plain HTML/CSS/JS served
directly by Flask. Keep it that way unless there's a real reason to add a build step.

## Important gotcha: editing JSON files while the app is running

Flask's debug reloader watches `.py` files, not `.json` files. If you hand-edit `questions.json`,
`history.json`, etc. while `app.py` is running, the running process keeps its stale in-memory copy
and can silently overwrite your edit on its next write. After editing a JSON file directly, run:

```bash
touch app.py
```

to force the reloader to restart and pick up the change.

## Adding a question

Add an entry to `questions.json` matching the shape of existing questions for its `lang`
(`sql`, `python`, `design`, `tradeoff`, `napkin`). Design questions additionally take a `track`
field (`"data"` or `"ai"`) that selects which concept taxonomy/rubric the tutor uses — see
`taxonomy_for()` / `war_stories_for()` / `baseline_rubric_for()` in `app.py` for how that's wired.

## Testing

There's no automated test suite for the UI — [`TESTING_GUIDE.md`](TESTING_GUIDE.md) is a manual
click-through checklist covering every feature. If you change a feature it covers, walk through
its section before opening a PR. If you add a new feature, add a section for it.

## Pull requests

- Keep diffs focused — one feature or fix per PR.
- Describe what you tested manually (screenshots/GIFs welcome for UI changes).
- Don't commit `.env`, or anything under `history.json` / `chats.json` / `progress.json` — these
  are gitignored for a reason (they're your personal practice data, not app state).
