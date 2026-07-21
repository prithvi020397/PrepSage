# Concept Learning Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Learn" tab to `/practice` that presents system design concepts as interactive lessons: concept name → war story → linked questions with precomputed traces → "Try this question" button.

**Architecture:** Server-rendered Jinja templates, no JS framework. A new `templates/learn.html` template served by a route in `routes/pages.py`. Concept→question mapping built as a lookup dict in `core/concepts.py`. Questions tagged with `concept_tags` in `questions.json`.

**Tech Stack:** Flask, Jinja2, Python 3.10+

## Global Constraints

- No new JS dependencies — all UI is server-rendered HTML/CSS
- War stories and concept taxonomies already exist in `core/constants.py` — don't duplicate
- Precomputed traces/solutions already exist in `app.py` state — reference via existing dicts
- All 80 existing tests must stay green
- Follow existing template conventions (dark theme CSS vars, same layout patterns as taxonomy.html)

---

### Task 1: Tag all design questions with concept_tags

**Files:**
- Modify: `questions.json`

**Interfaces:**
- Consumes: existing `CONCEPT_TAXONOMY`, `CONCEPT_TAXONOMY_AI`, `CONCEPT_TAXONOMY_FDE` keys from `core/constants.py`
- Produces: each design question (design-1 through design-23, ai-design-1 through ai-design-4, tradeoff-1 through tradeoff-13) has a `concept_tags` list

- [ ] **Step 1: Add `concept_tags` to all 27 design questions**

For each `design-N` and `ai-design-N` question, add a `concept_tags` field. For each `tradeoff-N` question, replace the existing single `concept_tag` string with a `concept_tags` list.

The `concept_tags` for each question should be derived from the rubric and concepts the question tests. Below is the complete mapping:

**design-1 (Clickstream Event Pipeline):** `["batch_vs_stream_choice", "partitioning_hot_key_skew", "storage_format_choice", "data_quality_observability"]`
**design-2 (Sharding a Multi-Tenant SaaS Database):** `["partitioning_hot_key_skew", "domain_alignment"]`
**design-3 (Event Streaming Platform with Schema Evolution):** `["schema_evolution_compat", "batch_vs_stream_choice"]`
**design-4 (Analytical Store for a Growing OLTP Workload):** `["storage_format_choice", "grain_awareness", "entity_enumeration"]`
**design-5 (Change Data Capture Pipeline):** `["idempotency_dedup", "backfill_reprocessing", "late_data_watermarks"]`
**design-6 (Lakehouse Ingestion):** `["late_data_watermarks", "batch_vs_stream_choice", "storage_format_choice"]`
**design-7 (Backfilling a Multi-Stage Pipeline):** `["backfill_reprocessing", "idempotency_dedup"]`
**design-8 (Real-Time Fraud Detection):** `["batch_vs_stream_choice", "partitioning_hot_key_skew", "data_quality_observability"]`
**design-9 (IoT Sensor Data Platform):** `["batch_vs_stream_choice", "late_data_watermarks", "storage_format_choice"]`
**design-10 (Server Log Aggregation):** `["storage_format_choice", "partitioning_hot_key_skew", "domain_alignment"]`
**design-11 (Food Delivery Order Processing):** `["entity_enumeration", "grain_awareness", "scd_strategy"]`
**design-12 (Feature Store):** `["batch_vs_stream_choice", "domain_alignment", "data_quality_observability"]`
**design-13 (Ride-Sharing Data Model for Analytics):** `["entity_enumeration", "grain_awareness", "scd_strategy", "domain_alignment"]`
**design-14 (Identity Resolution Pipeline):** `["idempotency_dedup", "missing_dimension_audit", "data_quality_observability"]`
**design-15 (GDPR-Compliant Data Deletion):** `["backfill_reprocessing", "data_quality_observability"]`
**design-16 (Data Lake Access Control):** `["domain_alignment", "data_quality_observability"]`
**design-17 (Write Sharding for Hot NoSQL Keys):** `["partitioning_hot_key_skew", "storage_format_choice"]`
**design-18 (Reliable Event Publication with Outbox):** `["idempotency_dedup", "replication_consistency"]`
**design-19 (Read-Model Projection Pipeline):** `["batch_vs_stream_choice", "late_data_watermarks", "storage_format_choice", "schema_evolution_compat", "data_quality_observability", "domain_alignment"]`
**design-20 (Conversation Log Ingestion Pipeline):** `["batch_vs_stream_choice", "schema_evolution_compat", "late_data_watermarks", "storage_format_choice", "data_quality_observability", "partitioning_hot_key_skew"]`
**design-21 (Bad Pod Detection and Alert Pipeline):** `["idempotency_dedup", "late_data_watermarks", "partitioning_hot_key_skew", "data_quality_observability"]`
**design-22 (GPU Telemetry Collection and Analytics):** `["batch_vs_stream_choice", "partitioning_hot_key_skew", "storage_format_choice", "data_quality_observability"]`
**design-23 (Emoji Reactions OLAP Pipeline):** `["domain_alignment", "schema_evolution_compat", "late_data_watermarks", "storage_format_choice", "data_quality_observability", "scd_strategy", "entity_enumeration", "grain_awareness"]`
**ai-design-1 (RAG Pipeline):** `["retrieval_relevance_chunking", "embedding_index_choice", "hallucination_grounding", "context_window_budget"]`
**ai-design-2 (Tool-Use Loop):** `["tool_use_safety", "agent_loop_termination", "latency_cost_tradeoff"]`
**ai-design-3 (LLM Serving Layer):** `["latency_cost_tradeoff", "prompt_versioning_regression", "eval_observability"]`
**ai-design-4 (Eval Pipeline):** `["eval_observability", "prompt_versioning_regression", "hallucination_grounding"]`

Tradeoff questions map their existing single `concept_tag`:
- **tradeoff-1 (Lambda or Kappa):** `["batch_vs_stream_choice"]`
- **tradeoff-2 (Hash vs Range Sharding):** `["partitioning_hot_key_skew"]`
- **tradeoff-3 (Avro vs Parquet):** `["storage_format_choice"]`
- **tradeoff-4 (Sync vs Async Replication):** `["replication_consistency"]`
- **tradeoff-5 (Batch ETL vs CDC):** `["batch_vs_stream_choice"]`
- **tradeoff-6 (Dedup at Consumer or Broker):** `["idempotency_dedup"]`
- **tradeoff-7 (Schema Registry Enforce at Write or Read):** `["schema_evolution_compat"]`
- **tradeoff-8 (Data Quality: Block or Alert):** `["data_quality_observability"]`
- **tradeoff-9 (Sync Dual-Write vs Log-Based):** `["idempotency_dedup", "batch_vs_stream_choice"]`
- **tradeoff-10 (Fail-Open vs Fail-Closed):** `["data_quality_observability"]`
- **tradeoff-11 (Per-Device vs Aggregated Timers):** `["batch_vs_stream_choice", "storage_format_choice"]`
- **tradeoff-12 (Airflow Executor):** `["batch_vs_stream_choice"]`
- **tradeoff-13 (COPY vs MERGE):** `["batch_vs_stream_choice", "storage_format_choice"]`

- [ ] **Step 2: Verify JSON is valid**

```bash
python3 -c "import json; qs=json.load(open('questions.json')); print(f'OK: {len(qs)} questions')"
```
Expected: prints "OK: 208 questions" (no error)

- [ ] **Step 3: Verify all concept_tags reference valid taxonomy keys**

```bash
python3 -c "
from core.constants import CONCEPT_TAXONOMY, CONCEPT_TAXONOMY_AI, CONCEPT_TAXONOMY_FDE
import json
ALL = set(CONCEPT_TAXONOMY + CONCEPT_TAXONOMY_AI + CONCEPT_TAXONOMY_FDE)
qs = json.load(open('questions.json'))
errors = []
for q in qs:
    tags = q.get('concept_tags', []) or [q.get('concept_tag', [])]
    if isinstance(tags, str): tags = [tags]
    for t in tags:
        if t not in ALL:
            errors.append(f'{q[\"id\"]}: unknown tag \"{t}\"')
if errors:
    for e in errors: print(e)
else:
    print(f'All tags valid ({len(ALL)} unique concepts)')
"
```
Expected: prints "All tags valid"

- [ ] **Step 4: Run tests to confirm nothing broke**

```bash
python3 -m pytest -q
```
Expected: 80 passed

- [ ] **Step 5: Commit**

```bash
git add questions.json
git commit -m "feat: add concept_tags to all design/tradeoff/ai questions"
```

---

### Task 2: Build concept-to-questions lookup in core/concepts.py

**Files:**
- Modify: `core/concepts.py`
- Test: `test_concept_normalization.py` (or add a new test file)

**Interfaces:**
- Consumes: `questions.json` (via `services.state.QUESTIONS` at runtime), `CONCEPT_TAXONOMY*` from `core/constants.py`
- Produces: `CONCEPT_QUESTION_INDEX: dict[str, list[dict]]` — each concept maps to a list of question metadata dicts `{id, title, lang, track, difficulty}`

- [ ] **Step 1: Write the failing test**

Add to `test_concept_normalization.py` or create a new test. Since test_concept_normalization.py already exists and tests concept functions, add there:

```python
def test_concept_question_index_has_all_concepts():
    """Every concept in at least one taxonomy has at least one question."""
    from core.concepts import CONCEPT_QUESTION_INDEX
    from core.constants import CONCEPT_TAXONOMY, CONCEPT_TAXONOMY_AI, CONCEPT_TAXONOMY_FDE
    all_concepts = set(CONCEPT_TAXONOMY + CONCEPT_TAXONOMY_AI + CONCEPT_TAXONOMY_FDE)
    indexed = set(CONCEPT_QUESTION_INDEX.keys())
    # Every concept should have at least one question (no orphaned concepts)
    missing = all_concepts - indexed
    assert not missing, f"Concepts with no questions: {missing}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_concept_normalization.py::test_concept_question_index_has_all_concepts -v
```
Expected: FAIL with ImportError or AttributeError

- [ ] **Step 3: Build the lookup**

Add to `core/concepts.py`:

```python
import json, os

CONCEPT_QUESTION_INDEX = {}

def _build_concept_index():
    index = {}
    questions_path = os.path.join(os.path.dirname(__file__), "..", "questions.json")
    with open(questions_path) as f:
        questions = json.load(f)
    for q in questions:
        tags = q.get("concept_tags", []) or q.get("concept_tag", [])
        if isinstance(tags, str):
            tags = [tags]
        if not tags:
            continue
        entry = {
            "id": q["id"],
            "title": q["title"],
            "lang": q.get("lang", ""),
            "track": q.get("track", ""),
            "difficulty": q.get("difficulty", ""),
        }
        for tag in tags:
            index.setdefault(tag, []).append(entry)
    return index

CONCEPT_QUESTION_INDEX = _build_concept_index()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_concept_normalization.py::test_concept_question_index_has_all_concepts -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/concepts.py tests/test_concept_normalization.py
git commit -m "feat: add CONCEPT_QUESTION_INDEX lookup in core/concepts.py"
```

---

### Task 3: Create the Learn template

**Files:**
- Create: `templates/learn.html`

**Interfaces:**
- Consumes: template variables `concepts_by_track` (dict of track_name → list of concept dicts), `war_stories_by_track` (dict), `CONCEPT_QUESTION_INDEX` lookup
- Produces: rendered HTML with two views (concept browser, lesson detail)

- [ ] **Step 1: Create `templates/learn.html`**

```html
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>The Loop — Learn</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0e1015; --panel: #14161d; --card: #1b1e27; --card-2: #20232e;
    --border: rgba(255,255,255,0.08); --text: #e7e9ee; --text-dim: #9299ab;
    --text-faint: #656c7e; --accent: #7c6cf6; --accent-2: #5ee6d8;
    --accent-soft: rgba(124,108,246,0.14); --success: #3ddc97;
    --success-soft: rgba(61,220,151,0.12); --error: #ff6b6b;
  }
  * { box-sizing: border-box; }
  body { font-family: 'Inter', sans-serif; margin: 0; background: var(--bg); color: var(--text); font-size: 14px; }
  #topbar {
    display: flex; align-items: baseline; gap: 14px;
    padding: 16px 24px;
    background: linear-gradient(180deg, var(--panel), var(--bg));
    border-bottom: 1px solid var(--border);
  }
  #topbar h1 { font-size: 16px; margin: 0; letter-spacing: 0.02em; }
  #topbar a { color: var(--text-dim); text-decoration: none; font-size: 13px; }
  #topbar a:hover { color: var(--text); }
  #topbar .tab { color: var(--text-dim); font-size: 13px; cursor: pointer; padding: 4px 10px; border-radius: 6px; }
  #topbar .tab.active { color: var(--accent); background: var(--accent-soft); }
  main { max-width: 1100px; margin: 0 auto; padding: 24px; }
  .track-group { margin-bottom: 28px; }
  .track-group h2 { font-size: 15px; font-weight: 600; margin: 0 0 10px; color: var(--accent-2); letter-spacing: 0.01em; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; cursor: pointer; transition: border-color 0.15s; }
  .card:hover { border-color: var(--accent); }
  .card h3 { font-size: 14px; font-weight: 600; margin: 0 0 4px; }
  .card .key { font-size: 11px; color: var(--text-faint); font-family: 'JetBrains Mono', monospace; margin-bottom: 5px; }
  .card .story { font-size: 12.5px; color: var(--text-dim); line-height: 1.5; margin-bottom: 6px; }
  .card .qcount { font-size: 11px; color: var(--accent); }
  /* Lesson detail view */
  #lesson-view { display: none; }
  #browser-view { display: block; }
  .show-lesson #lesson-view { display: block; }
  .show-lesson #browser-view { display: none; }
  .back-link { color: var(--accent); cursor: pointer; font-size: 13px; margin-bottom: 16px; display: inline-block; }
  .war-story { background: var(--card-2); border-radius: 8px; padding: 14px 16px; margin: 12px 0 20px; font-size: 13.5px; line-height: 1.6; color: var(--text-dim); border-left: 3px solid var(--accent); }
  .qlist { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
  .qitem { display: flex; align-items: center; justify-content: space-between; background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; }
  .qitem .qinfo { display: flex; flex-direction: column; }
  .qitem .qtitle { font-size: 13px; font-weight: 500; }
  .qitem .qmeta { font-size: 11px; color: var(--text-faint); margin-top: 2px; }
  .qitem .qactions { display: flex; gap: 8px; }
  .btn { padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 500; cursor: pointer; border: none; text-decoration: none; display: inline-block; }
  .btn-primary { background: var(--accent); color: #fff; }
  .btn-primary:hover { background: #8a7af7; }
  .btn-ghost { background: var(--card-2); color: var(--text-dim); }
  .btn-ghost:hover { background: var(--border); color: var(--text); }
  .walkthrough { background: var(--card-2); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-top: 8px; font-size: 13px; line-height: 1.5; white-space: pre-wrap; }
</style>
</head>
<body>
<div id="topbar">
  <h1>The Loop</h1>
  <a href="/dashboard">Dashboard</a>
  <span class="tab active">Learn</span>
  <a class="tab" href="/practice">Practice</a>
  <a href="/taxonomy">Taxonomy</a>
</div>
<main>
<div id="browser-view">
  {% for track_name, concepts in concepts_by_track.items() %}
  <div class="track-group">
    <h2>{{ track_name }}</h2>
    <div class="grid">
      {% for c in concepts %}
      <div class="card" onclick="showLesson('{{ c.key }}')">
        <div class="key">{{ c.key }}</div>
        <h3>{{ c.name }}</h3>
        <div class="story">{{ c.story_preview }}</div>
        <div class="qcount">{{ c.question_count }} question{% if c.question_count != 1 %}s{% endif %}</div>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endfor %}
</div>

<div id="lesson-view">
  <span class="back-link" onclick="showBrowser()">&larr; Back to concepts</span>
  <h2 id="lesson-title"></h2>
  <div id="lesson-war-story" class="war-story"></div>
  <h3 style="font-size:14px;font-weight:600;margin:16px 0 8px;">Related Questions</h3>
  <div id="lesson-questions" class="qlist"></div>
</div>
</main>

<script>
const conceptData = {{ concept_data | tojson | safe }};

function showLesson(key) {
  const d = conceptData[key];
  if (!d) return;
  document.body.classList.add('show-lesson');
  document.getElementById('lesson-title').textContent = d.name;
  document.getElementById('lesson-war-story').textContent = d.war_story;
  const qlist = document.getElementById('lesson-questions');
  qlist.innerHTML = d.questions.map(q => `
    <div class="qitem">
      <div class="qinfo">
        <div class="qtitle">${q.title}</div>
        <div class="qmeta">${q.lang}${q.difficulty ? ' &middot; ' + q.difficulty : ''}</div>
      </div>
      <div class="qactions">
        ${q.has_walkthrough ? `<a class="btn btn-ghost" href="/practice?question_id=${q.id}&show_trace=1">Walkthrough</a>` : ''}
        <a class="btn btn-primary" href="/practice?question_id=${q.id}">Try this</a>
      </div>
    </div>
  `).join('');
}

function showBrowser() {
  document.body.classList.remove('show-lesson');
}
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/learn.html
git commit -m "feat: add learn.html template with concept browser and lesson detail views"
```

---

### Task 4: Add learn route in pages.py

**Files:**
- Modify: `routes/pages.py`

**Interfaces:**
- Consumes: `CONCEPT_QUESTION_INDEX` from `core/concepts.py`, `CONCEPT_TAXONOMY*` and `WAR_STORIES*` from `core/constants.py`, `QUESTIONS`, `PRECOMPUTED_TRACES`, `PRECOMPUTED_SOLUTIONS` from `services/state.py`
- Produces: `/learn` GET route that renders `learn.html` with all concept data

- [ ] **Step 1: Add the import and route**

Add to the imports in `routes/pages.py`:

```python
from core.concepts import CONCEPT_QUESTION_INDEX
```

Add after the `practice()` route:

```python
@bp.route("/learn")
def learn():
    from core.constants import (
        CONCEPT_TAXONOMY, CONCEPT_TAXONOMY_AI, CONCEPT_TAXONOMY_FDE,
        WAR_STORIES, WAR_STORIES_AI, WAR_STORIES_FDE,
    )
    from services.state import PRECOMPUTED_TRACES, PRECOMPUTED_SOLUTIONS

    taxonomies = {
        "Data Engineering": (CONCEPT_TAXONOMY, WAR_STORIES),
        "AI System Design": (CONCEPT_TAXONOMY_AI, WAR_STORIES_AI),
        "FDE / Decomposition": (CONCEPT_TAXONOMY_FDE, WAR_STORIES_FDE),
    }

    concepts_by_track = {}
    concept_data = {}

    for track_name, (taxonomy, war_stories) in taxonomies.items():
        concepts = []
        for key in taxonomy:
            name = key.replace("_", " ").title()
            story = war_stories.get(key, "")
            questions = CONCEPT_QUESTION_INDEX.get(key, [])
            concepts.append({
                "key": key,
                "name": name,
                "story_preview": story[:120] + "..." if len(story) > 120 else story,
                "question_count": len(questions),
            })
            concept_data[key] = {
                "name": name,
                "war_story": story,
                "questions": [
                    {
                        "id": q["id"],
                        "title": q["title"],
                        "lang": q["lang"],
                        "difficulty": q.get("difficulty", ""),
                        "has_walkthrough": q["id"] in PRECOMPUTED_TRACES or q["id"] in PRECOMPUTED_SOLUTIONS,
                    }
                    for q in questions
                ],
            }
        concepts_by_track[track_name] = concepts

    return render_template("learn.html",
                           concepts_by_track=concepts_by_track,
                           concept_data=concept_data)
```

- [ ] **Step 2: Test that the route works**

```bash
python3 -c "
from app import app
with app.test_client() as c:
    r = c.get('/learn')
    assert r.status_code == 200, f'Got {r.status_code}'
    assert b'Learn' in r.data
    assert b'Back to concepts' in r.data
    print('OK: /learn returns 200 with learn template')
"
```
Expected: prints "OK: /learn returns 200 with learn template"

- [ ] **Step 3: Run full test suite**

```bash
python3 -m pytest -q
```
Expected: 80 passed

- [ ] **Step 4: Commit**

```bash
git add routes/pages.py
git commit -m "feat: add /learn route serving concept lesson browser"
```

---

### Task 5: Wire tab toggle from practice to learn and vice versa

**Files:**
- Modify: `templates/index.html` (add Learn tab in topbar)
- Modify: `routes/pages.py` (accept `?question_id=` param to auto-load a question)

**Interfaces:**
- Consumes: existing `/practice` route
- Produces: tab navigation between `/learn` and `/practice`

- [ ] **Step 1: Add Learn tab to the practice page topbar**

In `templates/index.html`, find the topbar section (around line where Dashboard link is) and add a Learn tab link. Look for existing navigation links in the template and add:

```html
<a class="tab" href="/learn">Learn</a>
```

Add appropriate CSS for `.tab` class styling similar to learn.html.

- [ ] **Step 2: Wire the `?question_id=` query param in the practice route**

Modify the `practice()` route in `routes/pages.py` to accept a `question_id` query param that gets passed to the template so the practice UI auto-loads that question:

```python
@bp.route("/practice")
def practice():
    jd = PROGRESS.get("_jd", {})
    role = jd.get("role_title", "")
    domain = jd.get("domain", "")
    if role and domain:
        jd_context = f"{role} at a {domain} company"
    elif role:
        jd_context = role
    else:
        jd_context = ""
    preselected = request.args.get("question_id", "")
    return render_template("index.html",
                           concept_taxonomies={"data": CONCEPT_TAXONOMY, "ai": CONCEPT_TAXONOMY_AI, "fde": CONCEPT_TAXONOMY_FDE},
                           jd_context=jd_context,
                           jd_loaded=bool(jd),
                           preselected_question=preselected)
```

Find the existing question-loading mechanism in `templates/index.html`. Look for a function like `selectQuestion(id)`, `loadQuestion(qid)`, or a URL hash handler that reads `location.hash` and loads a question. Then add a small JS snippet at the bottom of `index.html` after that function definition to auto-trigger it on page load when `preselected_question` is set:

```html
{% if preselected_question %}
<script>
document.addEventListener('DOMContentLoaded', function() {
  var qid = '{{ preselected_question }}';
  setTimeout(function() {
    // Call the existing question-loading function discovered above
    if (typeof selectQuestion === 'function') {
      selectQuestion(qid);
    } else if (typeof window.loadQuestion === 'function') {
      window.loadQuestion(qid);
    } else {
      // Fallback: set location.hash and trigger any hash listener
      location.hash = '#q-' + qid;
    }
  }, 300);
});
</script>
{% endif %}
```

- [ ] **Step 3: Run full test suite**

```bash
python3 -m pytest -q
```
Expected: 80 passed

- [ ] **Step 4: Commit**

```bash
git add templates/index.html routes/pages.py
git commit -m "feat: add learn/practice tab navigation and ?question_id= auto-load"
```
