---
name: pawscode
type: skill
---

# pawscode — The Loop (Domain-Specific Coding Interview Tutor)

## Project
pawscode is a Flask-based domain-specific coding interview tutor ("The Loop") with:
- Graded solve loop with Socratic reinforcement
- Spaced repetition for question scheduling
- Concept-mapper pipeline for JD-to-resume matching
- LLM-powered question generation via OpenRouter/DeepSeek
- Optional Firecrawl fresh-angle layer (with ScrapeGraphAI fallback)
- Dashboard with role-readiness scoring
- JD-aware tool-to-concept resume matching

## Key Files
- `app.py` — Main Flask application
- `precompute.py` — Offline precompute: traces, solutions, concept-links
- `firecrawl_layer.py` — Fresh-angle search (Firecrawl + ScrapeGraphAI fallback to DeepSeek)
- `questions.json` — Question bank (195 questions)
- `question_concept_links.json` — LLM-derived concept-to-question links
- `templates/dashboard.html` — Dashboard UI
- `test_scoring.py` — Scoring tests
- `test_concept_normalization.py` — Concept normalization tests
- `progress.json` — Private state (gitignored)

## Config & Secrets
- `.env` — API keys: OPENROUTER_API_KEY, FIRECRAWL_API_KEY
- Other keys: DEEPSEEK_API_KEY (for ScrapeGraphAI fallback), STIRLING_PDF_URL (OCR fallback)

## Common Tasks
- Run precompute: `python3 precompute.py`
- Run tests: `python3 -m unittest discover`
- Start server: `bash restart.sh` (port 5050)
- Generate concept links: `python3 -c "from precompute import gen_concept_links; gen_concept_links()"`

## Conventions
- Coverage = proven ÷ total (self-reported shown as footnote, never blended)
- Matching labeled "tool-to-concept mapping" (never "concept-level")
- Self-attestation is user-owned (system is a mirror, not a gatekeeper)

## Automation Notes
- Nightly precompute regenerates question_concept_links.json, traces, and solutions
- After precompute, commit and push if output changed
- Always run tests after any code change
