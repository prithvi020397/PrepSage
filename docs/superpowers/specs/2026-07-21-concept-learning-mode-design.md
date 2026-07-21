# Concept Learning Mode

## Scope

Add a "Learn" tab to `/practice` that presents system design concepts as interactive lessons: concept name → war story → linked questions with precomputed traces/solutions → "Try this question" button that switches to Practice mode.

**In scope:** Learn/Practice tab toggle, concept→question lookup, war story display, linked example questions with precomputed traces, concept tagging on design questions.
**Out of scope:** Study paths (composing concepts into a curriculum), flashcard mode, video content, offline mode, spaced repetition for concepts.

## UX Flow

### Tab toggle on `/practice`

The practice page gets a two-tab header at the top:

```
[ Learn ]  [ Practice ]
```

- **Learn tab** — concept browser → lesson detail view
- **Practice tab** — the existing Command Center / question interface (unchanged)

### Learn tab: concept browser

Lists concepts grouped by track:

```
Data Engineering (15 concepts)
├── Clarifying Requirements
├── Batch vs Stream Choice
├── Partitioning / Hot Key Skew
├── Idempotency / Dedup
├── Backfill / Reprocessing
├── Schema Evolution / Compatibility
├── Replication / Consistency
├── Data Quality / Observability
├── Storage Format Choice
├── Late Data / Watermarks
├── Domain Alignment
├── Entity Enumeration
├── Grain Awareness
├── SCD Strategy
├── Missing Dimension Audit

AI System Design (9 concepts)
├── Retrieval Relevance / Chunking
├── Embedding Index Choice
├── Context Window Budget
├── Hallucination Grounding
├── Prompt Versioning / Regression
├── Eval Observability
├── Latency / Cost Tradeoff
├── Tool Use Safety
├── Agent Loop Termination

FDE / Decomposition (7 concepts)
├── Ambiguous Problem Scoping
├── Stakeholder Mapping / Alignment
├── Production Deployment Strategy
├── Legacy Enterprise Integration
├── Failure Mode / Risk Analysis
├── Iterative Delivery / MVP
├── Data Integration Quality
```

Concepts are grouped by their taxonomy (`CONCEPT_TAXONOMY` → Data Engineering, `CONCEPT_TAXONOMY_AI` → AI System Design, `CONCEPT_TAXONOMY_FDE` → FDE/Decomposition). A question tagged with a concept inherits that concept's track for grouping.

Each concept entry shows:
- Concept name
- One-line description (first sentence of the war story)
- Question count (how many questions in the bank map to this concept)

### Learn tab: lesson detail

Clicking a concept expands or navigates to a detail view:

1. **Concept name** — bold header
2. **War story** — the real-world anecdote from `WAR_STORIES`, `WAR_STORIES_AI`, or `WAR_STORIES_FDE`
3. **Linked questions** — list of questions tagged with this concept, each showing:
   - Question title
   - Difficulty (where available)
   - Solved/attempted status from `PROGRESS`
   - **"View walkthrough"** button → shows the precomputed trace/solution
   - **"Try this question"** button → switches to Practice tab with that question loaded

4. **Walkthrough view** (inline or modal):
   - Shows the precomputed trace (`traces.json`) or solution (`solutions.json`) for that question
   - If the user already attempted the question, also shows their past attempt and tutor feedback

### Handling missing data

- **No walkthrough available:** If a question has no precomputed trace or solution (`PRECOMPUTED_TRACES` or `PRECOMPUTED_SOLUTIONS` lacks a key), the "View walkthrough" button is hidden. The "Try this question" button is still shown.
- **No test cases:** Design questions don't have test cases. The "Try this question" button loads the question in Practice mode for free-form LLM tutor interaction (same as current behavior).
- **Tradeoff questions:** These already have a single `concept_tag` field. The learn view treats `concept_tag` the same as `concept_tags` — if only one tag exists, the question appears under that concept.

### Back navigation

- Browser back button or an explicit "← Back to concepts" link returns to the concept browser

## Data Changes

### `questions.json` — concept_tags field

Every design question (design-1 through design-23, ai-design-1 through ai-design-4) gets a `concept_tags` list:

```json
{
  "id": "design-1",
  "lang": "design",
  "title": "Clickstream Event Pipeline",
  "concept_tags": ["batch_vs_stream_choice", "partitioning_hot_key_skew", "storage_format_choice", "data_quality_observability"],
  ...
}
```

Tradeoff questions already have `concept_tag` (single value) — convert to list or keep as-is for the learn view.

### `core/concepts.py` — concept lookup

New function:

```python
def concept_to_questions(concept_key: str) -> list[dict]:
    """Return all questions that have concept_key in their concept_tags."""
```

Or a pre-built dict:

```python
CONCEPT_QUESTION_INDEX: dict[str, list[str]] = {
    "batch_vs_stream_choice": ["design-1", "design-6", "design-8", ...],
    ...
}
```

### `services/state.py` — no changes needed

The existing `QUESTIONS`, `PRECOMPUTED_TRACES`, `PRECOMPUTED_SOLUTIONS`, `PRECOMPUTED_CONCEPTS` dicts already provide the data the learn view needs.

## Route Changes

### `routes/pages.py`

Add or extend the `/practice` route to accept a `?tab=learn` or `?tab=practice` query parameter, and serve a `learn.html` template with the concept data.

Alternatively, add a separate `/learn` route that renders `learn.html`. The tab toggle on the frontend navigates between `/practice` and `/learn`.

## Template Changes

### New: `templates/learn.html`

Two views:
1. **Concept browser** — grouped list with expandable sections per track
2. **Lesson detail** — war story + linked questions + walkthrough

Both rendered from template data passed by the route (no client-side JS framework). The "Try this question" button is a link to `/practice?question_id=design-17` which switches to the Practice tab and loads the question.

## Verification

1. Visit `/practice?tab=learn` — see concept browser grouped by track
2. Click a concept — see war story + linked questions
3. Click "View walkthrough" — see precomputed trace/solution
4. Click "Try this question" — switches to Practice tab with question loaded
5. All 80 existing tests still pass
