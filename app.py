import json
import os
import random
import re
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template
from openai import OpenAI

load_dotenv()

app = Flask(__name__)
HEADROOM_ENABLED = os.environ.get("HEADROOM_ENABLED", "").lower() in ("1", "true", "yes")
API_BASE = "http://localhost:9090/v1" if HEADROOM_ENABLED else "https://openrouter.ai/api/v1"
client = OpenAI(base_url=API_BASE, api_key=os.environ["OPENROUTER_API_KEY"])
MODEL = "deepseek/deepseek-v4-flash"
# ponytail: separate client — OpenRouter doesn't proxy Whisper transcription, needs a real OpenAI key
whisper_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "")) if os.environ.get("OPENAI_API_KEY") else None

QUESTIONS = {q["id"]: q for q in json.load(open("questions.json"))}

# ponytail: in-memory, single-user, resets on restart — fine for a local tutor
ATTEMPTS = {}
STRUGGLES = {}  # qid -> {"title", "concept", "fails"} — for cross-question pattern callouts
PENDING_RECALL = set()  # qids where the tutor just asked a recall-check question, awaiting the student's answer
PENDING_DRYRUN = set()  # qids where the tutor just posed a dry-run challenge, awaiting the student's trace

PROGRESS_FILE = "progress.json"
# qid -> {"solved_at": iso, "fails": int, "due_at": iso} — this one DOES persist to disk,
# spaced-repetition scheduling is pointless if it resets every time Flask autoreloads.
PROGRESS = json.load(open(PROGRESS_FILE)) if os.path.exists(PROGRESS_FILE) else {}

HISTORY_FILE = "history.json"
# append-only list of {ts, event: "submit"|"debrief", ...} — powers the trend dashboard.
# Kept separate from PROGRESS (current-state-only) because trends need a timeline.
HISTORY = json.load(open(HISTORY_FILE)) if os.path.exists(HISTORY_FILE) else []

CHATS_FILE = "chats.json"
# chat_key -> [{"role", "content"}, ...] — persisted so a shareable replay link still
# works after a dyno restart, not just within the same running process.
CHATS = json.load(open(CHATS_FILE)) if os.path.exists(CHATS_FILE) else {}

REPLAY_COMMENTS_FILE = "replay_comments.json"
# chat_key -> [{"turn_idx", "author", "text", "ts"}, ...] — same persistence shape as
# CHATS, so a shared replay link's comments survive a restart too.
REPLAY_COMMENTS = json.load(open(REPLAY_COMMENTS_FILE)) if os.path.exists(REPLAY_COMMENTS_FILE) else {}

# ponytail: static keyword map, not an LLM call — topic tagging doesn't need to cost anything.
PATTERN_SKELETONS = {
    "two pointers": ("Two-pointer", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">left, right = 0, len(arr) - 1
while left &lt; right:
    if condition:
        left += 1
    else:
        right -= 1
return result</pre>"""),
    "sliding window": ("Sliding Window", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">window_start, window_sum = 0, 0
for window_end in range(len(arr)):
    window_sum += arr[window_end]
    while window_sum &gt; target:
        window_sum -= arr[window_start]
        window_start += 1
    if window_sum == target:
        update result</pre>"""),
    "hashing": ("Hashmap", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">seen = {}
for i, val in enumerate(arr):
    complement = target - val
    if complement in seen:
        return [seen[complement], i]
    seen[val] = i</pre>"""),
    "stacks / queues": ("Stack", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">stack = []
for char in s:
    if char in '({[':
        stack.append(char)
    else:
        if not stack or not matching:
            return False
        stack.pop()
return len(stack) == 0</pre>"""),
    "dynamic programming": ("Dynamic Programming", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">dp = [0] * (n + 1)
dp[0], dp[1] = base_case_0, base_case_1
for i in range(2, n + 1):
    dp[i] = recurrence(dp[i-1], dp[i-2])
return dp[n]</pre>"""),
    "backtracking": ("Backtracking", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">def backtrack(path, remaining):
    if goal_reached:
        result.append(path.copy())
        return
    for choice in choices:
        make_choice
        backtrack(path, remaining)
        undo_choice</pre>"""),
    "graphs / BFS-DFS": ("BFS/DFS", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">from collections import deque
queue = deque([start])
visited = {start}
while queue:
    node = queue.popleft()
    for neighbor in graph[node]:
        if neighbor not in visited:
            visited.add(neighbor)
            queue.append(neighbor)</pre>"""),
    "trees": ("Tree Traversal", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">def dfs(node):
    if not node:
        return 0
    left = dfs(node.left)
    right = dfs(node.right)
    return combine(left, right, node.val)</pre>"""),
    "linked lists": ("Linked List", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">prev, curr = None, head
while curr:
    nxt = curr.next
    curr.next = prev
    prev, curr = curr, nxt
return prev</pre>"""),
    "sorting": ("Sorting", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">arr.sort()
for i in range(len(arr)):
    if condition:
        # process</pre>"""),
    "greedy": ("Greedy", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">items.sort(key=fn)
result = []
for item in items:
    if condition:
        result.append(item)
        update_state</pre>"""),
    "heaps": ("Heap", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">import heapq
heap = []
for item in items:
    heapq.heappush(heap, item)
    if len(heap) &gt; k:
        heapq.heappop(heap)
return heap[0]</pre>"""),
    "string manipulation": ("String", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">result = []
for char in s:
    if condition:
        result.append(char)
return ''.join(result)</pre>"""),
    "intervals": ("Intervals", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">intervals.sort(key=lambda x: x[0])
merged = []
for interval in intervals:
    if not merged or interval[0] &gt; merged[-1][1]:
        merged.append(interval)
    else:
        merged[-1][1] = max(merged[-1][1], interval[1])
return merged</pre>"""),
    "matrices": ("Matrix", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">rows, cols = len(matrix), len(matrix[0])
for r in range(rows):
    for c in range(cols):
        if condition:
            process(matrix[r][c])</pre>"""),
    "recursion": ("Recursion", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">def solve(state):
    if base_case(state):
        return base_result
    return combine(solve(smaller_state))</pre>"""),
    "_default": ("General Problem-Solving", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">for item in input:
    if condition:
        # update result based on item
result = ...
return result</pre>"""),
}

SQL_PATTERN_SKELETONS = {
    "window functions": ("Window Function", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">SELECT col,
       RANK() OVER (PARTITION BY group_col ORDER BY order_col DESC) AS rnk
FROM table_name</pre>"""),
    "group by / aggregation": ("Group By / Aggregation", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">SELECT group_col, AGG_FUNC(value_col) AS result
FROM table_name
GROUP BY group_col
HAVING condition</pre>"""),
    "joins": ("Join", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">SELECT a.col, b.col
FROM table_a a
JOIN table_b b ON a.key = b.key
WHERE condition</pre>"""),
    "subqueries": ("Subquery", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">SELECT col
FROM table_name
WHERE col = (
    SELECT AGG_FUNC(col)
    FROM table_name
)</pre>"""),
    "_default": ("Query Structure", """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">SELECT col
FROM table_name
WHERE condition
ORDER BY col</pre>"""),
}

TOPIC_KEYWORDS = [
    ("window function", "window functions"), ("over (partition", "window functions"),
    ("rank", "window functions"), ("running total", "window functions"),
    ("group by", "group by / aggregation"), ("having", "group by / aggregation"),
    ("join", "joins"), ("subquery", "subqueries"), ("self join", "joins"),
    ("recursion", "recursion"), ("recursive", "recursion"),
    ("dynamic programming", "dynamic programming"), ("dp", "dynamic programming"),
    ("graph", "graphs / BFS-DFS"), ("bfs", "graphs / BFS-DFS"), ("dfs", "graphs / BFS-DFS"),
    ("tree", "trees"), ("binary search tree", "trees"),
    ("linked list", "linked lists"),
    ("two pointer", "two pointers"), ("sliding window", "sliding window"),
    ("hash", "hashing"), ("dictionary", "hashing"), ("hashmap", "hashing"),
    ("sort", "sorting"), ("heap", "heaps"), ("priority queue", "heaps"),
    ("backtrack", "backtracking"), ("greedi", "greedy"), ("fibonacci", "dynamic programming"),
    ("kadane", "dynamic programming"), ("memo", "dynamic programming"),
    ("string", "string manipulation"), ("palindrome", "string manipulation"),
    ("interval", "intervals"), ("matrix", "matrices"), ("bit", "bit manipulation"),
    ("stack", "stacks / queues"), ("queue", "stacks / queues"),
    ("date", "date / time"), ("null", "NULL handling"),
]


PATTERN_MAP = {
    "dynamic programming": "dynamic programming", "graphs / BFS-DFS": "graphs / BFS-DFS",
    "trees": "trees", "linked lists": "linked lists",
    "two pointers": "two pointers", "sliding window": "sliding window",
    "hashing": "hashing", "sorting": "sorting",
    "heaps": "heaps", "backtracking": "backtracking",
    "greedy": "greedy", "string manipulation": "string manipulation",
    "intervals": "intervals", "matrices": "matrices",
    "stacks / queues": "stacks / queues", "bit manipulation": "hashing",
    "recursion": "recursion",
}

# ponytail: cross-cutting DE system-design concepts — shared taxonomy for baseline
# rubric items, war-stories bank, and wrap-up debrief concept classification below
CONCEPT_TAXONOMY = [
    "clarifying_requirements", "batch_vs_stream_choice", "partitioning_hot_key_skew",
    "idempotency_dedup", "backfill_reprocessing", "schema_evolution_compat",
    "replication_consistency", "data_quality_observability", "storage_format_choice",
]

WAR_STORIES = {
    "clarifying_requirements": "a team built a 'real-time' dashboard assuming sub-second latency was required, then spent months over-engineering a streaming pipeline before anyone checked — the actual ask was a 15-minute SLA",
    "batch_vs_stream_choice": "a streaming-only billing pipeline with no reprocessing path meant that when a bug corrupted two days of records, replaying history risked double-charging every customer",
    "partitioning_hot_key_skew": "a viral launch sent 40% of traffic to one partition key — that partition fell over while fifteen others sat idle",
    "idempotency_dedup": "a duplicate delivery during a consumer rebalance processed one payment twice, double-counting a day of revenue",
    "backfill_reprocessing": "a schema bug was found three weeks after ingestion, and without idempotent writes, replaying three weeks of events doubled every downstream aggregate",
    "schema_evolution_compat": "a producer team added a required field without coordinating with consumers, and every downstream deserializer crashed at 2am",
    "replication_consistency": "a leader failover during a write burst promoted a stale follower, silently rolling back several seconds of already-committed writes",
    "data_quality_observability": "a silent null-rate spike in an upstream table went unnoticed for two weeks because nothing monitored data quality, and it fed straight into an exec-facing revenue dashboard",
    "storage_format_choice": "row-oriented JSON storage for high-cardinality clickstream data meant a report scanning one column had to read the entire dataset",
}

# ponytail: SQL/Python's version of WAR_STORIES, keyed by topic_for()'s output instead of
# a hand-authored concept tag — one line, only pulled in when it matches the current question's topic.
WAR_STORIES_CODE = {
    "window functions": "an analytics query used ROW_NUMBER() without a fully-specified ORDER BY tiebreaker — on a rerun, ties landed in a different order and 'the top referrer' silently changed report to report",
    "NULL handling": "a churn query used `WHERE last_login != last_purchase` and silently dropped every customer who'd never purchased at all, because NULL != NULL is NULL, not true",
    "joins": "a reporting join fanned out on a one-to-many relationship no one noticed, quietly multiplying revenue in a dashboard for two release cycles before someone reconciled it against the ledger",
    "subqueries": "a correlated subquery that looked correct returned right answers on a 500-row staging table and then ran for 40 minutes in production because it re-scanned the outer table per row",
    "group by / aggregation": "an aggregation used AVG() over a column with nulls sprinkled in and nobody realized nulls are excluded from the denominator, quietly inflating every average",
    "recursion": "a recursive CTE walking an org chart had no depth guard, and a single accidental self-reference (a manager set as their own report) spun the query until it hit the database's stack limit",
    "dynamic programming": "a brute-force recursive solution shipped to prod because it passed on small test fixtures, then timed out in production the first time a real customer's dataset was 10x larger",
    "hashing": "a cache key built from a dict's string representation broke silently once dict ordering changed across a Python version bump, because the same logical key started hashing differently",
    "date / time": "a 'daily' aggregation job compared naive datetimes across a DST transition and double-counted an hour of events twice a year, for years, before anyone noticed",
    "sorting": "an in-place sort mutated a list that another part of the pipeline still held a reference to, corrupting a report that ran concurrently against 'the same' data",
}

BASELINE_RUBRIC = [
    "Idempotency: the design handles re-delivery/replay without double-processing (duplicate messages, retried writes)",
    "Backfill/reprocessing: there's a concrete story for replaying historical data (a bug fix, a schema change, a late correction) without corrupting or duplicating downstream results",
    "Schema evolution: producers and consumers can evolve independently without a synchronized deploy, and breaking vs non-breaking changes are distinguished",
    "Data quality/observability: some mechanism exists to catch bad data before it reaches consumers, not just after",
]

# ponytail: AI-engineering counterpart to the three DE globals above, same shape/length,
# selected via q["track"] == "ai" instead of building a second gated curriculum system.
CONCEPT_TAXONOMY_AI = [
    "retrieval_relevance_chunking", "embedding_index_choice", "context_window_budget",
    "hallucination_grounding", "prompt_versioning_regression", "eval_observability",
    "latency_cost_tradeoff", "tool_use_safety", "agent_loop_termination",
]

WAR_STORIES_AI = {
    "retrieval_relevance_chunking": "docs were chunked by fixed character count with no overlap, so the one paragraph that answered the question got split across two chunks and neither scored high enough to be retrieved",
    "embedding_index_choice": "a team swapped embedding models during a 'quick upgrade' without re-embedding the existing index, so new queries were compared against vectors from a different embedding space and retrieval quality silently collapsed",
    "context_window_budget": "a prompt kept appending full conversation history with no trimming, and once a session got long enough the most relevant retrieved context got pushed out of the window entirely",
    "hallucination_grounding": "a support bot with no 'say I don't know' path confidently invented a refund policy that didn't exist, and a customer screenshotted it",
    "prompt_versioning_regression": "a one-line prompt tweak to fix one complaint shipped straight to prod with no eval run, and silently broke a different intent category that had been working fine for months",
    "eval_observability": "a model provider pushed a silent update behind the same API version string, and accuracy on one internal eval category dropped 15% before anyone noticed because nothing was tracking it in production",
    "latency_cost_tradeoff": "every request re-ran the full retrieval + generation pipeline against the largest model available, and the bill for answering 'what are your hours' cost as much as a complex multi-step query",
    "tool_use_safety": "an agent with an unguarded shell/file tool was asked to 'clean up temp files' and, reasoning from an ambiguous instruction, deleted files outside the intended directory",
    "agent_loop_termination": "a multi-step agent had no max-iteration or progress check, so when one tool call kept returning an error it hadn't seen before, it retried the same failing action in a loop until the session timed out",
}

BASELINE_RUBRIC_AI = [
    "Grounding: answers are grounded in retrieved/cited sources, with a defined behavior when there isn't enough context (say unsure/refuse vs hallucinate)",
    "Evals: there's a concrete offline eval set or regression harness that catches quality regressions before a prompt or model change ships",
    "Cost/latency: the design accounts for cost and latency at expected scale (caching, model tiering, batching), not just correctness",
    "Observability: production quality is monitored on an ongoing basis (e.g. logging retrieved context, tracking hallucination/refusal rates) rather than tested once offline",
]


def taxonomy_for(q):
    return CONCEPT_TAXONOMY_AI if q.get("track") == "ai" else CONCEPT_TAXONOMY


def war_stories_for(q):
    return WAR_STORIES_AI if q.get("track") == "ai" else WAR_STORIES


def baseline_rubric_for(q):
    return BASELINE_RUBRIC_AI if q.get("track") == "ai" else BASELINE_RUBRIC


def persona_for(q):
    return "senior AI/ML engineering interviewer" if q.get("track") == "ai" else "senior data engineering interviewer"


def pattern_for(q):
    t = topic_for(q)
    if q["lang"] == "sql":
        return SQL_PATTERN_SKELETONS.get(t, SQL_PATTERN_SKELETONS["_default"])
    key = PATTERN_MAP.get(t, "_default")
    return PATTERN_SKELETONS.get(key, PATTERN_SKELETONS["_default"])


def topic_for(q):
    text = (q["title"] + " " + q["prompt"] + " " + q.get("concept", "")).lower()
    for keyword, topic in TOPIC_KEYWORDS:
        if keyword in text:
            return topic
    return "other-" + q["lang"]


def save_progress():
    json.dump(PROGRESS, open(PROGRESS_FILE, "w"))


def log_history(entry):
    entry["ts"] = datetime.now().isoformat()
    HISTORY.append(entry)
    json.dump(HISTORY, open(HISTORY_FILE, "w"))


def save_chats():
    json.dump(CHATS, open(CHATS_FILE, "w"))


def save_replay_comments():
    json.dump(REPLAY_COMMENTS, open(REPLAY_COMMENTS_FILE, "w"))


def split_wrap_up_reply(reply, taxonomy=CONCEPT_TAXONOMY):
    """Split an interview wrap-up reply into (prose, missed_concepts, rushed_to_design,
    communication_score, communication_note) — the trailing ```json fence is a grading
    artifact and never shown to the candidate."""
    if "```json" not in reply:
        return reply.strip(), [], False, None, ""
    prose, _, tail = reply.partition("```json")
    try:
        raw = tail.split("```")[0]
        parsed = json.loads(raw)
        concepts = [c for c in parsed.get("missed_concepts", []) if c in taxonomy]
        rushed = bool(parsed.get("rushed_to_design"))
        score = parsed.get("communication_score")
        score = int(score) if isinstance(score, (int, float)) and 1 <= score <= 5 else None
        note = parsed.get("communication_note") or ""
    except Exception:
        concepts, rushed, score, note = [], False, None, ""
    return prose.strip(), concepts, rushed, score, note


def recurring_missed_concepts():
    recent = [h for h in HISTORY if h.get("event") == "design_debrief"][-3:]
    counts = {}
    for h in recent:
        for c in h.get("missed_concepts", []):
            counts[c] = counts.get(c, 0) + 1
    return [c for c, n in counts.items() if n >= 2]


def recurring_missed_topics():
    # ponytail: SQL/Python's version of recurring_missed_concepts — same "seen >=2 times
    # recently" rule, but over topic_for()'s auto-derived topics instead of a hand-authored
    # taxonomy, since submit fails + debrief misses already carry a topic.
    recent = [h for h in HISTORY
              if (h.get("event") == "submit" and not h.get("passed"))
              or (h.get("event") == "debrief" and (not h.get("complexity_ok", True) or not h.get("edge_ok", True)))][-15:]
    counts = {}
    for h in recent:
        t = h.get("topic")
        if t:
            counts[t] = counts.get(t, 0) + 1
    return [t for t, n in counts.items() if n >= 2]


def schedule_review(qid, fails):
    # ponytail: fixed interval by fails-at-solve-time, not a real Leitner box ladder.
    # Upgrade to per-question box progression if a single fixed interval stops feeling right.
    interval_days = 7 if fails == 0 else 3 if fails <= 2 else 1
    deadline = PROGRESS.get("_deadline")
    if isinstance(deadline, dict) and deadline.get("date"):
        days_left = (datetime.fromisoformat(deadline["date"]) - datetime.now()).days
        # ponytail: compress toward the deadline (half of what's left) instead of a real
        # deadline-aware scheduler that redistributes ALL due questions across the remaining days
        interval_days = 1 if days_left <= 0 else max(1, min(interval_days, days_left // 2))
    now = datetime.now()
    entry = PROGRESS.get(qid) if isinstance(PROGRESS.get(qid), dict) else {}
    entry.update({
        "solved_at": now.isoformat(),
        "fails": fails,
        "due_at": (now + timedelta(days=interval_days)).isoformat(),
    })
    PROGRESS[qid] = entry
    save_progress()


def is_solved(qid):
    # ponytail: PROGRESS also holds trace-only cache entries (no solved_at) — don't treat those as solved.
    p = PROGRESS.get(qid)
    return isinstance(p, dict) and "solved_at" in p


def is_due(qid):
    p = PROGRESS.get(qid)
    if not p or "due_at" not in p:
        return False
    return datetime.now() >= datetime.fromisoformat(p["due_at"])


def run_sql_case(schema_sql, code):
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_sql)
    try:
        cur = conn.execute(code)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchall()]
    except sqlite3.Error as e:
        return None, None, str(e)
    return cols, rows, None


def get_sample_tables(schema_sql):
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_sql)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    out = {}
    for t in tables:
        cur = conn.execute(f"SELECT * FROM {t}")
        out[t] = {"columns": [d[0] for d in cur.description], "rows": [list(r) for r in cur.fetchall()]}
    return out


def run_python_case(harness, code):
    full_code = code + "\n\n" + harness
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(full_code)
        path = f.name
    try:
        result = subprocess.run(["python3", path], capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return None, "Timed out (5s) — check for an infinite loop."
    finally:
        os.unlink(path)
    if result.returncode != 0:
        return None, result.stderr.strip()
    return result.stdout, None


@app.route("/")
def index():
    return render_template("index.html", concept_taxonomies={"data": CONCEPT_TAXONOMY, "ai": CONCEPT_TAXONOMY_AI})


@app.route("/dashboard")
def dashboard():
    total_by_lang = {"sql": 0, "python": 0}
    for q in QUESTIONS.values():
        total_by_lang[q["lang"]] = total_by_lang.get(q["lang"], 0) + 1

    solved_by_lang = {"sql": 0, "python": 0}
    for qid in PROGRESS:
        q = QUESTIONS.get(qid)
        if q and is_solved(qid):
            solved_by_lang[q["lang"]] = solved_by_lang.get(q["lang"], 0) + 1

    due_count = sum(1 for qid in PROGRESS if is_due(qid))

    def rate(events, key):
        return round(100 * sum(1 for e in events if e[key]) / len(events)) if events else None

    debriefs = [h for h in HISTORY if h["event"] == "debrief"]
    recent_debriefs = debriefs[-10:]
    narrated_debriefs = [h for h in debriefs if "narration_ok" in h]
    recent_narrated = narrated_debriefs[-10:]

    fails = [h for h in HISTORY if h["event"] == "submit" and not h["passed"]]
    debrief_misses = [h for h in debriefs if not h.get("complexity_ok", True) or not h.get("edge_ok", True)]
    topic_counts = {}
    for f in fails:
        topic_counts[f["topic"]] = topic_counts.get(f["topic"], 0) + 1
    for h in debrief_misses:
        if h.get("topic"):
            topic_counts[h["topic"]] = topic_counts.get(h["topic"], 0) + 1

    postmortems = [h for h in HISTORY if h.get("event") == "postmortem"]
    for h in postmortems:
        if h["qtype"] in ("sql", "python") and not h["ok"] and h.get("topic"):
            topic_counts[h["topic"]] = topic_counts.get(h["topic"], 0) + 1
    weak_areas = sorted(topic_counts.items(), key=lambda kv: -kv[1])[:8]
    max_weak = max((c for _, c in weak_areas), default=1)

    design_debriefs = [h for h in HISTORY if h.get("event") == "design_debrief"]
    concept_counts = {}
    for h in design_debriefs:
        for c in h.get("missed_concepts", []):
            concept_counts[c] = concept_counts.get(c, 0) + 1
    for h in postmortems:
        if h["qtype"] == "design" and not h["ok"] and h.get("concept"):
            concept_counts[h["concept"]] = concept_counts.get(h["concept"], 0) + 1
    concept_misses = sorted(concept_counts.items(), key=lambda kv: -kv[1])[:8]
    max_concept_miss = max((c for _, c in concept_misses), default=1)
    rushed_count = sum(1 for h in design_debriefs if h.get("rushed_to_design"))
    rushed_pct = round(100 * rushed_count / len(design_debriefs)) if design_debriefs else None

    # ponytail: concept_tag -> tradeoff qid, powers the "practice this" deep link on the dashboard
    concept_to_tradeoff = {q["concept_tag"]: qid for qid, q in QUESTIONS.items()
                            if q["lang"] == "tradeoff" and q.get("concept_tag")}

    # Mastery map: per-topic pass rate across every SQL/Python submit (pass+fail), weakest first.
    # ponytail: SQL/Python is the only mode with clean per-attempt pass/fail data — design's
    # concept_misses only counts misses (no attempt total), so a blended cross-mode % would be
    # misleading. Add design/tradeoff into this if they grow attempt-level tracking.
    topic_attempts, topic_fails = {}, {}
    for h in HISTORY:
        if h.get("event") == "submit" and h.get("topic"):
            t = h["topic"]
            topic_attempts[t] = topic_attempts.get(t, 0) + 1
            if not h["passed"]:
                topic_fails[t] = topic_fails.get(t, 0) + 1
    mastery_map = sorted(
        ((t, round(100 * (n - topic_fails.get(t, 0)) / n), n) for t, n in topic_attempts.items()),
        key=lambda row: row[1],
    )

    return render_template(
        "dashboard.html",
        total_by_lang=total_by_lang, solved_by_lang=solved_by_lang,
        total_solved=sum(1 for qid in PROGRESS if is_solved(qid)), total_questions=len(QUESTIONS),
        due_count=due_count, debrief_count=len(debriefs),
        complexity_recent=rate(recent_debriefs, "complexity_ok"),
        complexity_alltime=rate(debriefs, "complexity_ok"),
        edge_recent=rate(recent_debriefs, "edge_ok"),
        edge_alltime=rate(debriefs, "edge_ok"),
        narrated_count=len(narrated_debriefs),
        narration_recent=rate(recent_narrated, "narration_ok"),
        narration_alltime=rate(narrated_debriefs, "narration_ok"),
        weak_areas=weak_areas, max_weak=max_weak,
        concept_misses=concept_misses, max_concept_miss=max_concept_miss,
        concept_to_tradeoff=concept_to_tradeoff,
        design_debrief_count=len(design_debriefs), rushed_pct=rushed_pct,
        mastery_map=mastery_map,
        postmortems=list(reversed(postmortems))[:15],
    )


@app.route("/api/deadline", methods=["GET", "POST"])
def deadline():
    # ponytail: reuses PROGRESS's flat dict with a reserved "_deadline" key instead of a new file —
    # every PROGRESS.items() loop elsewhere already guards with `oid in QUESTIONS`, so this is safe.
    if request.method == "POST":
        date_str = (request.json or {}).get("deadline", "").strip()
        if date_str:
            datetime.fromisoformat(date_str)  # raises ValueError -> 500 on bad input, fine for a solo local tool
            PROGRESS["_deadline"] = {"date": date_str}
        else:
            PROGRESS.pop("_deadline", None)
        save_progress()
    d = PROGRESS.get("_deadline")
    return jsonify({"deadline": d["date"] if isinstance(d, dict) else None})


@app.route("/api/questions")
def list_questions():
    return jsonify([{"id": q["id"], "title": q["title"], "lang": q["lang"], "difficulty": q.get("difficulty"),
                      "solved": is_solved(q["id"]), "due": is_due(q["id"])}
                     for q in QUESTIONS.values()])


@app.route("/api/mock-loop/start")
def mock_loop_start():
    """Picks one SQL-or-Python + one design + one tradeoff question for a chained mock
    interview — biased toward unsolved ones, falling back to the full pool if everything
    in that category is already solved."""
    def pick(lang):
        candidates = [q for q in QUESTIONS.values() if q["lang"] == lang]
        if not candidates:
            return None
        unsolved = [q for q in candidates if not is_solved(q["id"])]
        return random.choice(unsolved or candidates)["id"]

    ids = [pick(random.choice(["sql", "python"])), pick("design"), pick("tradeoff")]
    return jsonify({"ids": [i for i in ids if i]})


@app.route("/api/mock-loop/report")
def mock_loop_report():
    """Final report for a mock-loop run — reuses PROGRESS + HISTORY as-is rather than
    tracking loop state server-side; the frontend already knows how to render each
    event type's payload since it renders the same shape live during solving."""
    ids = [i for i in request.args.get("ids", "").split(",") if i]
    event_types = {"sql": "submit", "python": "submit", "design": "design_debrief", "tradeoff": "tradeoff"}
    report = []
    for qid in ids:
        q = QUESTIONS.get(qid)
        if not q:
            continue
        want = event_types.get(q["lang"])
        last = next((h for h in reversed(HISTORY) if h.get("qid") == qid and h.get("event") == want), None)
        report.append({"id": qid, "title": q["title"], "lang": q["lang"],
                        "solved": is_solved(qid), "last_event": last})
    return jsonify({"report": report})


@app.route("/api/questions/<qid>")
def get_question(qid):
    q = QUESTIONS.get(qid)
    if not q:
        return jsonify({"error": "not found"}), 404
    if q["lang"] in ("design", "tradeoff", "napkin"):
        # ponytail: no test_cases/starter_code for design/tradeoff/napkin questions, and the
        # rubric/key_points/answer range are graded server-side only — never sent to the client
        resp = {"id": q["id"], "lang": q["lang"], "title": q["title"], "prompt": q["prompt"]}
        if q["lang"] == "design":
            resp["track"] = q.get("track", "data")
        if q["lang"] == "napkin":
            roll = NAPKIN_ROLLS.get(q["id"])
            resp["prompt"] = roll["prompt"] if roll else q["prompt"]
            resp["unit"] = roll["unit"] if roll else q.get("unit", "")
        if q["lang"] == "tradeoff":
            roll = TRADEOFF_ROLLS.get(q["id"])
            resp["title"] = roll["title"] if roll else q["title"]
            resp["prompt"] = roll["prompt"] if roll else q["prompt"]
        return jsonify(resp)
    first_case = q["test_cases"][0]
    p = PROGRESS.get(qid, {})
    saved_code = p.get("code", "") if isinstance(p, dict) else ""
    resp = {"id": q["id"], "lang": q["lang"], "title": q["title"], "prompt": q["prompt"],
            "starter_code": q["starter_code"], "code": saved_code, "concept": q["concept"]}
    if q["lang"] == "sql":
        resp["sample_tables"] = get_sample_tables(first_case["schema_sql"])
        resp["sample_output"] = {"columns": first_case["expected_columns"], "rows": first_case["expected"]}
    else:
        # ponytail: show only the call line, not helper defs (build_list/build_tree etc.)
        # that would hand the user the exact traversal/construction idiom they're being tested on
        harness_lines = [l for l in first_case.get("harness", "").strip().split("\n") if l.strip()]
        resp["sample_call"] = harness_lines[-1] if harness_lines else ""
        resp["sample_output"] = first_case.get("expected_stdout")
    return jsonify(resp)


def _exec_case(q, code, case):
    if q["lang"] == "sql":
        cols, actual, err = run_sql_case(case["schema_sql"], code)
        expected = case["expected"]
    else:
        cols, actual, err = None, *run_python_case(case["harness"], code)
        expected = case["expected_stdout"]
    return cols, actual, expected, err


@app.route("/api/run", methods=["POST"])
def run():
    """Sample-only check: no grading, no attempt/struggle tracking."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q:
        return jsonify({"error": "not found"}), 404
    case = q["test_cases"][0]
    cols, actual, expected, err = _exec_case(q, data["code"], case)
    return jsonify({"passed": err is None and actual == expected,
                     "actual": actual, "actual_columns": cols,
                     "expected": expected, "expected_columns": case.get("expected_columns"), "error": err})


@app.route("/api/submit", methods=["POST"])
def submit():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q:
        return jsonify({"error": "not found"}), 404
    code = data["code"]
    # save code
    p = PROGRESS.get(q["id"], {})
    if isinstance(p, dict):
        PROGRESS[q["id"]] = p
        p["code"] = code
        save_progress()

    for i, case in enumerate(q["test_cases"]):
        cols, actual, expected, err = _exec_case(q, code, case)

        if err is not None or actual != expected:
            ATTEMPTS[q["id"]] = ATTEMPTS.get(q["id"], 0) + 1
            s = STRUGGLES.setdefault(q["id"], {"title": q["title"], "concept": q["concept"], "fails": 0})
            s["fails"] += 1
            log_history({"event": "submit", "qid": q["id"], "lang": q["lang"], "difficulty": q.get("difficulty"),
                         "passed": False, "topic": topic_for(q)})
            return jsonify({"passed": False, "case": i + 1, "total_cases": len(q["test_cases"]),
                             "actual": actual, "actual_columns": cols,
                             "expected": expected, "expected_columns": case.get("expected_columns"), "error": err})

    schedule_review(q["id"], ATTEMPTS.get(q["id"], 0))
    log_history({"event": "submit", "qid": q["id"], "lang": q["lang"], "difficulty": q.get("difficulty"),
                 "passed": True, "topic": topic_for(q)})
    return jsonify({"passed": True, "total_cases": len(q["test_cases"]),
                     "actual": actual, "actual_columns": cols})


@app.route("/api/check-approach", methods=["POST"])
def check_approach():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q:
        return jsonify({"error": "not found"}), 404
    plan = (data.get("plan") or "").strip()
    if not plan:
        return jsonify({"ok": False, "feedback": "Write your approach first."})

    prompt = f"""You are a terse technical interviewer grading a candidate's STATED approach before they've written any code — you are grading their plan, not code.

Problem: {q['title']}
{q['prompt']}

Ground-truth approach and common pitfall (for your judgment only — NEVER reveal, quote, or paraphrase this to the candidate): {q['concept']}

Candidate's stated approach: "{plan}"

Judge whether the approach is roughly on the right track — correct general algorithm/data-structure idea and a plausible time complexity. It does not need to match the ground truth's exact wording or catch every edge case.

Respond with ONLY strict JSON, no markdown fences, no commentary:
{{"ok": true or false, "feedback": "one short sentence — encouraging if ok, a nudge toward the right direction if not. Never reveal the ground-truth solution."}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        return jsonify({"ok": bool(result.get("ok")), "feedback": result.get("feedback", "")})
    except Exception:
        # ponytail: a grading hiccup shouldn't block practice — let them through with a note
        return jsonify({"ok": True, "feedback": "(couldn't auto-grade that — proceeding anyway)"})


@app.route("/api/spot-bug", methods=["POST"])
def spot_bug():
    """SQL/Python's version of adversarial-design: generates plausible-but-buggy code with
    one deliberate concept-tagged bug baked in, for a 'find the bug' drill instead of write-from-scratch.
    Mirrors adversarial_design's pattern of round-tripping the ground truth through the client, hidden
    from display, rather than stashing server-side session state."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] not in ("sql", "python"):
        return jsonify({"error": "not found"}), 404

    prompt = f"""You are a senior interviewer preparing a code-review drill for this problem.

Problem: {q['title']}
{q['prompt']}
Known idiomatic approach and common pitfall: {q['concept']}

Write a plausible-looking {q['lang']} solution a mediocre candidate might submit, with exactly ONE deliberate,
subtle bug that breaks on a specific edge case (nulls, ties, duplicates, empty input, off-by-one, mutable
default argument, etc.) — not a syntax error, not something a linter would catch. It should look correct at a glance.

Respond ONLY strict JSON, no markdown fences, no commentary:
{{"code": "the buggy {q['lang']} code as a single string with \\n line breaks", "bug_note": "one sentence describing the specific bug and what input would expose it"}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=500, temperature=0.4, extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        return jsonify({"code": result.get("code", ""), "bug_note": result.get("bug_note", "")})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/spot-bug-grade", methods=["POST"])
def spot_bug_grade():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] not in ("sql", "python"):
        return jsonify({"error": "not found"}), 404
    bug_note = (data.get("bug_note") or "").strip()
    answer = (data.get("answer") or "").strip()
    if not bug_note or not answer:
        return jsonify({"ok": False, "feedback": "Write what you think is wrong first."})

    prompt = f"""A candidate was shown deliberately buggy code for this problem and asked what's wrong with it.

Problem: {q['title']}
Ground-truth bug (for your judgment only — NEVER reveal, quote, or paraphrase this to the candidate): {bug_note}

Candidate's answer: "{answer}"

Judge whether they identified the actual bug (the real mechanism, not just any plausible-sounding nitpick).
They don't need to propose the exact fix, just correctly diagnose what's wrong and roughly why.

Respond with ONLY strict JSON, no markdown fences, no commentary:
{{"ok": true or false, "feedback": "one short sentence — confirm what they caught if ok, a nudge toward the actual bug if not. Never reveal the ground-truth bug verbatim if they missed it."}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=200, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        log_history({"event": "spot_bug", "qid": q["id"], "ok": bool(result.get("ok")), "topic": topic_for(q)})
        return jsonify({"ok": bool(result.get("ok")), "feedback": result.get("feedback", "")})
    except Exception:
        return jsonify({"ok": True, "feedback": "(couldn't auto-grade that — proceeding anyway)"})


CURVEBALLS = {}  # qid -> twist text, so grading judges against the same twist that was shown


@app.route("/api/curveball", methods=["POST"])
def curveball():
    """Mid-solve requirement change: interviewer changes the ask while the candidate is still coding,
    instead of a fresh problem. Reuses the check-approach LLM-judge pattern, applied to code instead of a plan."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] not in ("sql", "python"):
        return jsonify({"error": "not found"}), 404

    prompt = f"""You are a senior interviewer. The candidate is mid-solve on this problem and hasn't submitted yet.

Problem: {q['title']}
{q['prompt']}

Pose ONE realistic mid-interview requirement change — reuse the same schema/function signature, but change a
constraint (e.g. a uniqueness assumption no longer holds, an extra filter is added, ties must now be handled a
specific way, nulls can now appear). Don't restate the original problem.

Respond ONLY strict JSON, no markdown fences, no commentary:
{{"twist": "1-2 sentences stating the new requirement, in the interviewer's voice"}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=150, temperature=0.5, extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        twist = json.loads(raw).get("twist", "").strip()
        if not twist:
            raise ValueError("empty twist")
        CURVEBALLS[q["id"]] = twist
        return jsonify({"twist": twist})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/curveball-grade", methods=["POST"])
def curveball_grade():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] not in ("sql", "python"):
        return jsonify({"error": "not found"}), 404
    twist = CURVEBALLS.get(q["id"])
    code = (data.get("code") or "").strip()
    if not twist:
        return jsonify({"ok": False, "feedback": "Ask for a curveball first."})
    if not code:
        return jsonify({"ok": False, "feedback": "Update your code first."})

    prompt = f"""A candidate was solving this problem, then given a mid-solve requirement change.

Problem: {q['title']}
{q['prompt']}

Requirement change given: "{twist}"

Candidate's updated {q['lang']} code:
```{q['lang']}
{code}
```

Judge whether the updated code actually handles the new requirement (not just the original problem). Don't
run it mentally line-by-line for syntax — judge the logic/approach.

Respond with ONLY strict JSON, no markdown fences, no commentary:
{{"ok": true or false, "feedback": "one short sentence — confirm what changed if ok, point at what's still missing if not."}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=200, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        log_history({"event": "curveball", "qid": q["id"], "ok": bool(result.get("ok")), "topic": topic_for(q)})
        return jsonify({"ok": bool(result.get("ok")), "feedback": result.get("feedback", "")})
    except Exception:
        return jsonify({"ok": True, "feedback": "(couldn't auto-grade that — proceeding anyway)"})


@app.route("/api/debrief", methods=["POST"])
def debrief():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q:
        return jsonify({"error": "not found"}), 404
    complexity = (data.get("complexity") or "").strip()
    edge_cases = (data.get("edge_cases") or "").strip()
    narration = (data.get("narration") or "").strip()
    if not complexity or not edge_cases:
        return jsonify({"complexity_ok": False, "complexity_feedback": "Answer both fields.",
                         "edge_ok": False, "edge_feedback": "Answer both fields."})

    narration_block = f"""

Candidate's spoken narration of their approach (transcribed from voice, verbatim — judge as speech, not writing): "{narration}"
Additionally judge:
- narration_ok: would this narration, said out loud in an interview, clearly communicate their approach, the complexity, and why it's correct? Filler words are fine; missing structure or hand-waving over the actual logic is not.
Add "narration_ok": true or false and "narration_feedback": "one short sentence" to the JSON.""" if narration else ""

    prompt = f"""You are a terse technical interviewer debriefing a candidate right after their code PASSED all tests — this is the "what's the complexity, what would you test" follow-up every interview asks after working code.

Problem: {q['title']}
{q['prompt']}

Candidate's passing code:
```{q['lang']}
{data.get('code', '')}
```

Candidate's stated time/space complexity: "{complexity}"
Candidate's stated edge cases they'd test: "{edge_cases}"
{narration_block}

Judge each independently against the ACTUAL code (not against an ideal solution):
- complexity_ok: is their stated complexity actually correct for the code they wrote?
- edge_ok: are the edge cases they named actually relevant and non-trivial for this code (not just restating the given examples)?

Respond with ONLY strict JSON, no markdown fences, no commentary:
{{"complexity_ok": true or false, "complexity_feedback": "one short sentence", "edge_ok": true or false, "edge_feedback": "one short sentence"{', "narration_ok": true or false, "narration_feedback": "one short sentence"' if narration else ''}}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        complexity_ok = bool(result.get("complexity_ok"))
        edge_ok = bool(result.get("edge_ok"))
        history_entry = {"event": "debrief", "qid": q["id"], "complexity_ok": complexity_ok, "edge_ok": edge_ok,
                          "topic": topic_for(q)}
        response = {"complexity_ok": complexity_ok, "complexity_feedback": result.get("complexity_feedback", ""),
                    "edge_ok": edge_ok, "edge_feedback": result.get("edge_feedback", "")}
        if narration:
            narration_ok = bool(result.get("narration_ok"))
            history_entry["narration_ok"] = narration_ok
            response["narration_ok"] = narration_ok
            response["narration_feedback"] = result.get("narration_feedback", "")
        log_history(history_entry)
        return jsonify(response)
    except Exception:
        # ponytail: a grading hiccup shouldn't block practice — let them through with a note
        fallback = {"complexity_ok": True, "complexity_feedback": "(couldn't auto-grade — proceeding anyway)",
                    "edge_ok": True, "edge_feedback": "(couldn't auto-grade — proceeding anyway)"}
        if narration:
            fallback["narration_ok"] = True
            fallback["narration_feedback"] = "(couldn't auto-grade — proceeding anyway)"
        return jsonify(fallback)


@app.route("/api/trace", methods=["POST"])
def gen_trace():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q:
        return jsonify({"error": "not found"}), 404
    # save code unconditionally so it persists across restarts
    if data.get("code"):
        if q["id"] not in PROGRESS:
            PROGRESS[q["id"]] = {}
        if isinstance(PROGRESS[q["id"]], dict):
            PROGRESS[q["id"]]["code"] = data["code"]
            save_progress()
    # check cache
    p = PROGRESS.get(q["id"], {})
    if isinstance(p, dict) and p.get("trace"):
        return jsonify({"trace": p["trace"], "pattern": p.get("pattern", ""), "skeleton": p.get("skeleton", ""), "solved": is_solved(q["id"])})

    pattern_info = pattern_for(q)
    tc = q["test_cases"][0]
    sample_data = tc.get("harness", "") if q["lang"] == "python" else tc.get("schema_sql", "")
    sample_output = tc.get("expected_stdout", "") if q["lang"] == "python" else json.dumps(tc.get("expected", []))

    if q["lang"] == "sql":
        code_noun = "SQL clause/keyword"
        example = """Example of a good full trace for 'Second Highest Salary':
[
  {"q": "What keyword removes duplicate salaries before ranking?", "a": "SELECT DISTINCT salary"},
  {"q": "How do you sort salaries from highest to lowest?", "a": "ORDER BY salary DESC"},
  {"q": "How do you skip the first row and limit to one row to land on the second highest?", "a": "LIMIT 1 OFFSET 1"}
]"""
    else:
        code_noun = "Python method"
        example = """Example of a good full trace for 'Valid Palindrome':
[
  {"q": "What method converts a character to lowercase?", "a": "char.lower()"},
  {"q": "What method keeps only letters and numbers?", "a": "char.isalnum()"},
  {"q": "How do we combine filtered chars back into a string?", "a": "''.join(filtered)"},
  {"q": "How do we check if a string equals its reverse?", "a": "cleaned == cleaned[::-1]"}
]"""

    prompt = f"""You are a coding tutor that teaches CODE TRANSLATION. The student knows the theory but struggles to write specific code lines. Generate trace steps that teach them WHICH CODE to write.

Problem: {q['title']}
{q['prompt']}
Concept: {q['concept']}
Pattern skeleton:
{pattern_info[1] if pattern_info[1] else 'N/A'}

Sample call/harness: {sample_data}
Expected output: {sample_output}
Starter code:
{q.get("starter_code", "")}

Generate 3-5 steps. Each step must ask about a SPECIFIC, DISTINCT line or code construct the student needs to write, in {q["lang"].upper()}. The answer is the ACTUAL CODE (not a description).

Do NOT add a final "put it all together" / "write the complete query/function" step — that's just retyping the concatenation of earlier answers and tests nothing new. Every step must teach a translation point the earlier steps didn't already cover.

Bad (conceptual):
  Q: "What do we do after filtering?"  A: "Compare the string to its reverse."

Bad (redundant assembly):
  Q: "What is the complete query/function to solve this?"  A: "<everything from the previous steps combined>"

Good (code-focused):
  Q: "What {code_noun} checks if a character is alphanumeric?"
  A: "char.isalnum()"

{example}

Respond with ONLY JSON:
{{"steps": [{{"q": "what line of code to write?", "a": "the actual code"}}]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=2000, temperature=0,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        start = raw.find("{")
        end = raw.rfind("}")
        raw = raw[start:end+1]
        result = json.loads(raw)
        steps = result.get("steps", [])
    except Exception:
        steps = [{"q": "What's the first step to solve this?", "a": "Identify the core operation and apply the pattern."}]

    if q["id"] not in PROGRESS:
        PROGRESS[q["id"]] = {}
    if isinstance(PROGRESS[q["id"]], dict):
        PROGRESS[q["id"]]["trace"] = steps
        PROGRESS[q["id"]]["pattern"] = pattern_info[0]
        PROGRESS[q["id"]]["skeleton"] = pattern_info[1]
        if data.get("code"):
            PROGRESS[q["id"]]["code"] = data["code"]
    save_progress()

    return jsonify({"trace": steps, "pattern": pattern_info[0], "skeleton": pattern_info[1], "solved": is_solved(q["id"])})


@app.route("/api/trace-check", methods=["POST"])
def trace_check():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q:
        return jsonify({"error": "not found"}), 404
    p = PROGRESS.get(q["id"], {})
    steps = p.get("trace") if isinstance(p, dict) else None
    if not steps:
        return jsonify({"error": "no trace generated for this question yet"}), 400

    submitted = data.get("answers", [])  # [{index, guess}]
    if not submitted:
        return jsonify({"results": []})

    lines = []
    for a in submitted:
        i = a["index"]
        if not isinstance(i, int) or not (0 <= i < len(steps)):
            continue
        lines.append(f"{i}. Q: {steps[i]['q']}\n   Canonical answer: {steps[i]['a']}\n   Student's guess: {a.get('guess', '')}")
    if not lines:
        return jsonify({"results": []})

    prompt = f"""You are grading a student's guesses for specific lines of code in a code-translation drill (they know the theory, this checks if they can write the actual code).

Problem: {q['title']}
{q['prompt']}

For each numbered item below, judge whether the student's guess is FUNCTIONALLY EQUIVALENT code to the canonical answer — allow different variable names, equivalent method calls, and minor syntax variants. Don't require an exact string match.

{chr(10).join(lines)}

Respond with ONLY strict JSON, no markdown fences, no commentary:
{{"results": [{{"index": 0, "correct": true or false}}]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        return jsonify({"results": result.get("results", [])})
    except Exception:
        # ponytail: a grading hiccup shouldn't block practice — call everything submitted correct
        return jsonify({"results": [{"index": a["index"], "correct": True} for a in submitted]})


@app.route("/api/hint", methods=["POST"])
def hint():
    data = request.json
    qid = data["question_id"]
    q = QUESTIONS.get(qid)
    if not q:
        return jsonify({"error": "not found"}), 404

    attempt = ATTEMPTS.get(qid, 1)
    escalation = (
        "Give only a small conceptual nudge — do not name the specific fix."
        if attempt <= 1
        else "They've tried a couple times — you can be more specific about what's wrong, but still don't hand them full working code."
        if attempt <= 3
        else "They're stuck — walk through the key insight clearly, code sketch is fine, but let them write the final version themselves."
    )

    other_struggles = {oid: s for oid, s in STRUGGLES.items() if oid != qid and s["fails"] >= 2}
    # ponytail: STRUGGLES resets on restart (this session only) — also pull qids that took
    # >=2 fails to solve in a PAST session from persisted PROGRESS, so pattern callbacks span days,
    # not just today. Reuses PROGRESS/schedule_review's existing "fails at solve time" field.
    for oid, p in PROGRESS.items():
        if oid != qid and oid not in other_struggles and isinstance(p, dict) and p.get("fails", 0) >= 2 and oid in QUESTIONS:
            other_struggles[oid] = {"title": QUESTIONS[oid]["title"], "concept": QUESTIONS[oid]["concept"]}
    other_struggles = list(other_struggles.values())
    struggles_note = ""
    if other_struggles:
        lines = "\n".join(f"- {s['title']}: {s['concept']}" for s in other_struggles)
        struggles_note = (
            f"\n\nIMPORTANT — pattern callback required:\n"
            f"The student struggled with these OTHER problems this session (already filtered to real repeats, "
            f"not noise):\n{lines}\n"
            "If today's mistake shares the same underlying pattern as one of these, your reply MUST end with a "
            "separate final sentence starting exactly with \"Pattern check:\" naming the shared underlying idea. "
            "If none of them genuinely share a pattern with today's mistake, skip that sentence entirely."
        )

    topic = topic_for(q)
    resurfacing_note = ""
    if topic in recurring_missed_topics():
        resurfacing_note = (
            f"\n\nThis student has repeatedly missed questions tagged '{topic}' across recent sessions "
            "(not just today). If that pattern applies here, name it plainly — don't just treat this as an isolated slip."
        )

    war_story = WAR_STORIES_CODE.get(topic, "")
    war_story_note = (
        f"\n\nA real production war story for this concept (use sparingly — only if it strengthens the hint, "
        f"don't force it in every time): {war_story}"
        if war_story else ""
    )

    system_prompt = f"""You are a terse, encouraging interview-prep coding tutor, not a solution-giver.

Problem: {q['title']}
{q['prompt']}
The concept this problem tests: {q['concept']}{struggles_note}{resurfacing_note}{war_story_note}

Rules:
- Never hand over full working code.
- Ground hints in the concept above — explain *why* their approach does or doesn't fit, not just surface syntax.
- This may be a continuation of an earlier conversation on this problem — don't repeat a hint you already gave, build on it.
- If their code doesn't actually attempt the problem's core logic yet (e.g. `SELECT *`, unchanged starter code, or something unrelated to the concept), say so plainly and ask a guiding question to get them started — don't hunt for a subtle bug in code that was never a real attempt.
- If their message is vague ("it's not working", "look at my code") without saying what they expected or what they think is wrong, ask one clarifying question before explaining anything.
- {escalation}
- Reply in 2-4 sentences, no preamble."""

    history = CHATS.setdefault(qid, [])

    code_context = (
        f"Their current code:\n```{q['lang']}\n{data.get('code', '')}\n```\n"
        f"Actual output: {data.get('actual')}\n"
        f"Error (if any): {data.get('error')}\n"
    )

    if data.get("proactive"):
        user_turn = (
            code_context +
            "(The student has gone quiet after a failed attempt — they didn't ask for this. "
            "Proactively check in with a short, warm nudge grounded in the concept above. "
            "Ask a guiding question rather than stating the fix outright. Don't repeat a hint you already gave.)"
        )
    elif data.get("reinforce"):
        user_turn = (
            code_context +
            "(The student just passed all test cases. Give a short congratulatory reinforcement: "
            "restate *why* their solution satisfies the concept above, in 1-2 sentences. Then ask ONE short "
            "question that makes them explain the key idea back in their own words — don't just restate it "
            "for them. This is a recap plus a quick check, not a critique.)"
        )
        PENDING_RECALL.add(qid)
    elif data.get("twist"):
        user_turn = (
            code_context +
            "(The student already solved this problem correctly. Pose ONE realistic interview-style follow-up "
            "variation on this exact problem — reuse the same schema/function signature, but change a constraint "
            "or requirement (e.g. a uniqueness assumption no longer holds, an extra condition is added). Don't "
            "restate the original problem. 1-3 sentences: state the twist clearly, then ask how their solution "
            "would need to change. Do not solve it for them.)"
        )
    elif data.get("dry_run"):
        user_turn = (
            code_context +
            "(The student already solved this problem correctly. Pick ONE small concrete sample input for their "
            "function (reuse or adapt the sample input above) and ask them to trace through their own code by "
            "hand: how do the key variables change at each step, and what's the final return value? State the "
            "input clearly. Do not trace it yourself — wait for their answer. 2-3 sentences.)"
        )
        PENDING_DRYRUN.add(qid)
    else:
        recall_note = ""
        if qid in PENDING_RECALL and data.get("message"):
            PENDING_RECALL.discard(qid)
            recall_note = (
                "(The student is now answering the recall-check question you just asked after passing. "
                "Assess whether their answer shows real understanding. If yes, confirm briefly and warmly. "
                "If it's off or vague, gently correct it — don't just agree to be nice. 1-2 sentences.)\n"
            )
        elif qid in PENDING_DRYRUN and data.get("message"):
            PENDING_DRYRUN.discard(qid)
            recall_note = (
                "(The student is now giving their dry-run trace for the input you just asked about. Actually "
                "check whether their stated variable states and final result are correct for their own code — "
                "don't just take their word for it. If correct, confirm briefly. If they made a tracing error or "
                "skipped a step, point out exactly where it goes wrong without just handing them the fix. "
                "2-3 sentences.)\n"
            )
        user_turn = recall_note + code_context + (data.get("message") or "I'm stuck — give me a hint.")
    history.append({"role": "user", "content": user_turn})

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system_prompt}] + history,
            max_tokens=300,
            extra_body={"reasoning": {"enabled": False}},
        )
    except Exception as e:
        history.pop()  # don't leave a dangling user turn with no reply
        return jsonify({"error": str(e)}), 502
    reply = resp.choices[0].message.content
    if not reply:
        history.pop()  # don't leave a dangling user turn with no reply
        return jsonify({"error": "model returned an empty response — try again"}), 502
    history.append({"role": "assistant", "content": reply})
    save_chats()

    return jsonify({"hint": reply})


REQUIREMENTS_ONLY_RULES = """You are running a focused clarifying-questions-only drill, not a full interview — the candidate is NOT allowed to design anything yet, only ask questions to scope the problem.

Rules:
1. If they try to propose any design, storage, or architecture, redirect them: tell them to hold that thought and keep asking clarifying questions instead.
2. Encourage a broad sweep of clarifying-question categories relevant to the scenario (scale/volume, latency/freshness needs, existing systems/constraints, consistency/failure requirements, budget/team constraints) — don't spoon-feed which ones are missing, just note if they're going deep on one category while ignoring others.
3. Keep replies to 1-3 sentences, interviewer voice.
4. When they say they're ready to end the drill, give a short debrief (2-4 sentences): which categories they covered well, which they never touched, and whether their questions were specific enough to actually inform a design."""

# ponytail: temperament variants only — same 4 scenarios, same rubric, just how the
# interviewer carries themselves. Not job-track/seniority variants.
PERSONAS = {
    "skeptical": "Adopt a skeptical, terse temperament: give minimal encouragement, question claims before accepting them, make the candidate justify choices, keep replies clipped.",
    "friendly": "Adopt a collaborative, friendly temperament: warm tone, build on the candidate's ideas out loud, use encouraging phrasing even while pushing back — but stay just as rigorous on substance.",
    "silent": "Adopt a silent, minimal temperament: say as little as possible, favor one-line prompts ('why?', 'and at 10x?') over full sentences, force the candidate to drive and fill the silences themselves.",
}

ADVERSARIAL_RULES = """You already sketched a design for this scenario and it's sitting on the candidate's whiteboard — don't re-explain it, they can see it. Their job now is to critique it: find what breaks at scale, under failure, or at the edges.

Rules:
1. Don't volunteer the flaws. Open with something like "what worries you about this at scale?" and let them lead.
2. When they correctly name a real weakness, confirm it plainly and ask one follow-up (how would they fix it, what's the blast radius).
3. If they claim something is broken that genuinely isn't, push back and ask them to justify it — don't just agree.
4. If they seem to be running out of ideas, nudge toward an unexplored area of the design (ingestion, processing, storage, consumers) without naming the flaw outright.
5. Reply in 2-4 sentences, interviewer voice, no preamble."""


@app.route("/api/interview", methods=["POST"])
def interview():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "design":
        return jsonify({"error": "not found"}), 404

    requirements_only = bool(data.get("requirements_only"))
    adversarial = bool(data.get("adversarial"))
    chat_key = data["question_id"] + (":clarify" if requirements_only else (":adversarial" if adversarial else ""))

    if requirements_only:
        system_prompt = f"""You are a {persona_for(q)} running a requirements-gathering drill. Stay in character.

Scenario: {q['title']}
{q['prompt']}

{REQUIREMENTS_ONLY_RULES}"""
    elif adversarial:
        flaws = data.get("flaws") or []
        flaws_block = "\n".join(f"- {f.get('concept', '')}: {f.get('note', '')}" for f in flaws if f.get("concept"))
        system_prompt = f"""You are a {persona_for(q)} running an adversarial "break this design" drill.

Scenario: {q['title']}
{q['prompt']}

The design currently on the candidate's whiteboard has these deliberate flaws (never reveal this list directly — only confirm or push back as they investigate):
{flaws_block}

{ADVERSARIAL_RULES}"""
    else:
        rubric_lines = "\n".join(f"- {r}" for r in baseline_rubric_for(q) + q.get("rubric", []))
        war_stories_block = "\n".join(f"- {concept}: {story}" for concept, story in war_stories_for(q).items())

        resurfacing_note = ""
        if data.get("start"):
            recurring = recurring_missed_concepts()
            if recurring:
                resurfacing_note = (
                    f"\n\nThis candidate has repeatedly missed these concepts across recent design interviews: "
                    f"{', '.join(recurring)}. If either is relevant to this question, make sure to probe it."
                )

        persona_note = ""
        persona_key = data.get("persona")
        if persona_key in PERSONAS:
            persona_note = f"\n\nInterviewer persona for this session: {PERSONAS[persona_key]}"

        system_prompt = f"""You are a {persona_for(q)} conducting a system design interview. Stay in character as the interviewer throughout.

Scenario: {q['title']}
{q['prompt']}

What a strong answer eventually covers (your private rubric — NEVER read this list back to the candidate or hint that it exists):
{rubric_lines}

Concrete failure scenarios you can draw on when probing or pushing back — cite the consequence, not just the pattern name, and only bring up the ones relevant to what's missing (don't dump this list):
{war_stories_block}

Rules:
1. Don't volunteer requirements the candidate hasn't asked about yet.
2. If the candidate starts proposing a design before asking about scale, latency, data volume, existing systems, or budget, stop them and ask what they'd want to clarify first.
3. Once they've asked reasonable clarifying questions (or explicitly state assumptions and move on), let them sketch a design across all layers (sources, processing, storage, consumers, tooling) before pushing deep on any one part.
4. Only probe a layer they actually mentioned or conspicuously skipped, and ground the probe in a concrete failure mode or scale consideration specific to their choice — not a generic "what about scale?" question.
5. Push back, don't just note it and move on: if they propose streaming-only or batch-only with no reprocessing/replay story, or never mention idempotency, backfills, schema evolution, or data quality once the design is otherwise taking shape, ask one pointed question grounded in the matching failure scenario above before letting them move to the next layer.
6. Never design it for them and never state the "correct" answer, even if asked directly.
7. Keep replies to 2-4 sentences, interviewer voice, no bullet lists.
8. The candidate has a whiteboard. Before their message you'll see its current contents as boxes/arrows/notes — treat it like glancing at a real whiteboard. React to mismatches: things they said but never drew, or drew but never explained.{resurfacing_note}{persona_note}"""

    if data.get("wrap_up"):
        concept_list = ", ".join(taxonomy_for(q))
        user_turn = ("(The candidate wants to end the interview now. Give a structured debrief in 4-6 sentences total: "
                     "which rubric points they addressed well, which were missing or shallow, and one concrete concept to "
                     "go read up on. This is the only time you may reveal rubric-style structure. Comment on the "
                     "whiteboard too if it's empty or contradicts what they said, but keep it brief — the json block "
                     "below is where the missing concepts get itemized, don't also list them at length in prose. "
                     "After your prose debrief, on a new line, append a fenced json block classifying which "
                     f"concepts from this fixed list were missing or shallow: [{concept_list}]. Use ONLY concepts "
                     "from that list, only the ones actually missing or shallow. Also include rushed_to_design: true "
                     "if the candidate proposed concrete storage/architecture choices before asking any meaningful "
                     "clarifying questions about scale, latency, or requirements, false if they clarified first. Also "
                     "include communication_score: an integer 1-5 rating how well they signposted their thinking, "
                     "checked in before committing to a direction, and paced the conversation (5 = clearly narrated "
                     "reasoning and checked in at decision points, 1 = silent info-dumping or jumping around with no "
                     "narration), plus communication_note: one short sentence justifying that score. e.g.:\n"
                     "```json\n{\"missed_concepts\": [\"idempotency_dedup\", \"backfill_reprocessing\"], "
                     "\"rushed_to_design\": false, \"communication_score\": 4, \"communication_note\": "
                     "\"Narrated tradeoffs clearly but didn't check in before committing to Kafka.\"}\n```)")
    elif data.get("end_drill"):
        user_turn = ("(The candidate wants to end the drill now. Give the short debrief described in your "
                     "instructions: which clarifying-question categories they covered, which they missed, and "
                     "whether their questions were specific enough.)")
    elif data.get("start"):
        if requirements_only:
            user_turn = ("(The drill is starting. Give a brief one-sentence opening telling the candidate this "
                         "round is clarifying questions only — no design yet.)")
        elif adversarial:
            user_turn = ("(The drill is starting and a flawed design is already on the candidate's whiteboard. "
                         "Give a brief one-sentence opening asking what worries them about it at scale.)")
        else:
            user_turn = ("(The interview is starting. Give a brief one-sentence opening inviting the candidate to "
                         "ask clarifying questions before they begin designing. Don't restate the scenario.)")
    else:
        user_turn = data.get("message") or "I'm ready to start."

    diagram = (data.get("diagram") or "").strip()
    if diagram:
        user_turn = f"[Candidate's current whiteboard]\n{diagram}\n\n[Candidate says]\n{user_turn}"

    history = CHATS.setdefault(chat_key, [])
    history.append({"role": "user", "content": user_turn})

    # ponytail: wrap-up replies need room for prose debrief + trailing json tail
    reply_max_tokens = 700 if (data.get("wrap_up") or data.get("end_drill")) else 400
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "system", "content": system_prompt}] + history,
            max_tokens=reply_max_tokens, extra_body={"reasoning": {"enabled": False}},
        )
    except Exception as e:
        history.pop()
        return jsonify({"error": str(e)}), 502
    reply = resp.choices[0].message.content
    if not reply:
        history.pop()
        return jsonify({"error": "model returned an empty response — try again"}), 502
    history.append({"role": "assistant", "content": reply})
    save_chats()

    prose_reply = reply
    if data.get("wrap_up"):
        prose_reply, missed_concepts, rushed_to_design, communication_score, communication_note = split_wrap_up_reply(reply, taxonomy_for(q))
        self_rated = [c for c in (data.get("self_rated") or []) if c in taxonomy_for(q)]
        log_history({"event": "design_debrief", "qid": data["question_id"], "missed_concepts": missed_concepts,
                     "rushed_to_design": rushed_to_design, "self_rated": self_rated,
                     "communication_score": communication_score})
        return jsonify({"reply": prose_reply, "wrap_up": True, "missed_concepts": missed_concepts,
                         "concept_taxonomy": taxonomy_for(q), "self_rated": self_rated,
                         "rushed_to_design": rushed_to_design, "communication_score": communication_score,
                         "communication_note": communication_note})

    return jsonify({"reply": prose_reply, "wrap_up": bool(data.get("wrap_up"))})


WHITEBOARD_WRAP_RE = re.compile(r"^\[Candidate's current whiteboard\]\n(.*?)\n\n\[Candidate says\]\n(.*)$", re.S)


@app.route("/api/interview-history")
def interview_history():
    """Replays a design interview's chat turns paired with the whiteboard state as it stood at
    each turn — reuses CHATS as-is (the diagram is already embedded in each user turn's stored
    content), no separate snapshot storage needed."""
    qid = request.args.get("question_id", "")
    adversarial = request.args.get("adversarial") == "1"
    requirements_only = request.args.get("requirements_only") == "1"
    chat_key = qid + (":clarify" if requirements_only else (":adversarial" if adversarial else ""))

    turns = []
    diagram = ""
    for msg in CHATS.get(chat_key, []):
        content = msg["content"]
        if msg["role"] == "user":
            m = WHITEBOARD_WRAP_RE.match(content)
            if m:
                diagram, text = m.group(1), m.group(2)
            else:
                text = content
        else:
            text = split_wrap_up_reply(content)[0] if "```json" in content else content
        turns.append({"role": msg["role"], "text": text, "diagram": diagram})
    return jsonify({"turns": turns})


def _replay_chat_key(args):
    qid = args.get("question_id", "")
    adversarial = args.get("adversarial") == "1"
    requirements_only = args.get("requirements_only") == "1"
    return qid + (":clarify" if requirements_only else (":adversarial" if adversarial else ""))


@app.route("/api/replay-comments")
def replay_comments():
    """Comments anchored to a turn index in a shared replay link — same chat_key as
    interview-history, so no separate lookup/auth needed to find the right thread."""
    chat_key = _replay_chat_key(request.args)
    return jsonify({"comments": REPLAY_COMMENTS.get(chat_key, [])})


@app.route("/api/replay-comment", methods=["POST"])
def replay_comment():
    data = request.json
    chat_key = _replay_chat_key(data)
    text = (data.get("text") or "").strip()
    author = (data.get("author") or "").strip() or "anonymous"
    turn_idx = data.get("turn_idx")
    if not text or not isinstance(turn_idx, int):
        return jsonify({"error": "text and turn_idx required"}), 400
    comment = {"turn_idx": turn_idx, "author": author, "text": text, "ts": datetime.now().isoformat()}
    REPLAY_COMMENTS.setdefault(chat_key, []).append(comment)
    save_replay_comments()
    return jsonify({"comment": comment})


@app.route("/api/postmortem", methods=["POST"])
def postmortem():
    """Log a question from a REAL interview (not this app), classify it against the same taxonomy
    used for practice questions, and fold it into HISTORY so it counts toward weak-areas/mastery
    tracking exactly like a practice miss would."""
    data = request.json
    question = (data.get("question") or "").strip()
    qtype = data.get("qtype")
    ok = bool(data.get("ok"))
    if not question or qtype not in ("sql", "python", "design"):
        return jsonify({"error": "question and qtype (sql/python/design) required"}), 400

    if qtype == "design":
        vocab = CONCEPT_TAXONOMY
        label_field = "concept"
    else:
        vocab = sorted(set(topic for _, topic in TOPIC_KEYWORDS))
        label_field = "topic"

    prompt = f"""Classify this real interview question into exactly ONE label from the list below — pick the
closest match even if imperfect, never invent a new label.

Labels: {", ".join(vocab)}

Question: "{question}"

Respond ONLY strict JSON, no markdown fences, no commentary:
{{"label": "one label from the list, verbatim"}}"""

    label = vocab[0]
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=50, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        candidate = json.loads(raw).get("label", "")
        if candidate in vocab:
            label = candidate
    except Exception:
        pass  # falls back to vocab[0] — still logs the postmortem, just under a rough label

    entry = {"event": "postmortem", "question": question, "qtype": qtype, "ok": ok, label_field: label}
    log_history(entry)
    return jsonify({label_field: label})


@app.route("/api/reference-design", methods=["POST"])
def reference_design():
    """Post-hoc only — called after wrap-up, never during the live interview."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "design":
        return jsonify({"error": "not found"}), 404

    coverage = ("pipeline shape (batch/stream/hybrid), key storage choices, and how it handles idempotency, "
                "backfills, schema evolution, and data quality" if q.get("track") != "ai" else
                "retrieval/context strategy, model and serving choices, and how it handles grounding/hallucination, "
                "evals, cost/latency, and production monitoring")
    prompt = f"""You are a {persona_for(q)}. The candidate just finished a mock interview and its debrief for the scenario below and asked to see a reference design to compare against — this is now a learning aid, not part of the live interview, so you may reveal a concrete answer.

Scenario: {q['title']}
{q['prompt']}

Give a concise reference design covering: {coverage}.

Also express the same design as a simple box-and-arrow diagram using this exact schema (one line per shape):
Box: <short component label> [<layer>]
Arrow: <from label> -> <to label>
where <layer> is one of: source, processing, storage, consumer. Reuse the exact same labels between boxes and arrows. Keep it to 5-9 boxes.

Respond ONLY strict JSON, no markdown fences, no commentary:
{{"bullets": ["one design point per bullet, 6-9 bullets total, no leading dash"], "diagram": ["Box: ... [layer]", "Arrow: A -> B", ...]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=600, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        return jsonify({"bullets": result.get("bullets", []), "diagram": result.get("diagram", [])})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/adversarial-design", methods=["POST"])
def adversarial_design():
    """Generates a flawed reference design + its flaw list to seed the whiteboard before an
    adversarial 'break this design' drill starts. The flaw list never reaches the client verbatim
    as text — the frontend only uses it to prime /api/interview's system prompt server-side."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "design":
        return jsonify({"error": "not found"}), 404

    concept_list = ", ".join(taxonomy_for(q))
    prompt = f"""You are a {persona_for(q)} preparing an adversarial "break this design" drill for the scenario below.

Scenario: {q['title']}
{q['prompt']}

Design a plausible-looking but flawed architecture for this scenario — something a mediocre candidate might propose, with 2-4 deliberate weaknesses a strong candidate should be able to spot. Each flaw must map to one of these concepts: [{concept_list}].

Express the design as a simple box-and-arrow diagram using this exact schema (one line per shape):
Box: <short component label> [<layer>]
Arrow: <from label> -> <to label>
where <layer> is one of: source, processing, storage, consumer. Reuse the exact same labels between boxes and arrows. Keep it to 5-9 boxes.

Respond ONLY strict JSON, no markdown fences, no commentary:
{{"diagram": ["Box: ... [layer]", "Arrow: A -> B", ...], "flaws": [{{"concept": "one of the fixed concepts above", "note": "one sentence describing the specific weakness in this design"}}]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=600, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        flaws = [f for f in result.get("flaws", []) if f.get("concept") in taxonomy_for(q)]
        return jsonify({"diagram": result.get("diagram", []), "flaws": flaws})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# qid -> {title, prompt, key_points} — session-only re-rolled tradeoff scenarios targeting the
# same concept_tag, so practicing a weak concept isn't capped at the 5 fixed bank scenarios.
# Falls back to the static bank entry whenever a question hasn't been re-rolled.
TRADEOFF_ROLLS = {}


@app.route("/api/tradeoff-regenerate", methods=["POST"])
def tradeoff_regenerate():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "tradeoff":
        return jsonify({"error": "not found"}), 404

    prompt = f"""You are writing a forced-choice system-design tradeoff drill for interview practice, targeting the
same underlying concept as the example below, but with a different concrete scenario (different domain,
numbers, and framing) so it can't be memorized.

Concept: {q['concept_tag'].replace('_', ' ')}
Existing example (for concept reference only — don't reuse its scenario): {q['title']} — {q['prompt']}

Respond ONLY strict JSON, no markdown fences, no commentary:
{{"title": "short scenario title, under 8 words", "prompt": "2-4 sentences posing a forced choice between two concrete options for a new scenario", "key_points": ["3-4 bullets, private grading key, what a strong justification must touch on"]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=400, temperature=0.6, extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        title, new_prompt, key_points = result.get("title", ""), result.get("prompt", ""), result.get("key_points", [])
        if not (title and new_prompt and key_points):
            raise ValueError("incomplete regeneration")
        TRADEOFF_ROLLS[q["id"]] = {"title": title, "prompt": new_prompt, "key_points": key_points}
        return jsonify({"title": title, "prompt": new_prompt})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/tradeoff-grade", methods=["POST"])
def tradeoff_grade():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "tradeoff":
        return jsonify({"error": "not found"}), 404
    answer = (data.get("answer") or "").strip()
    if not answer:
        return jsonify({"ok": False, "feedback": "Write your choice and reasoning first."})

    roll = TRADEOFF_ROLLS.get(q["id"])
    title = roll["title"] if roll else q["title"]
    scenario_prompt = roll["prompt"] if roll else q["prompt"]
    points = roll["key_points"] if roll else q.get("key_points", [])
    key_points = "\n".join(f"- {k}" for k in points)
    prompt = f"""You are a terse senior data engineering interviewer grading a candidate's tradeoff justification in a forced-choice drill.

Scenario: {title}
{scenario_prompt}

What a strong justification touches on (private grading key — NEVER reveal this to the candidate):
{key_points}

Candidate's answer: "{answer}"

Judge whether their choice is defensible and their reasoning actually engages with the real tradeoff driving it — they don't need to hit every point above, but the core tradeoff should be present, not just the pattern name.

Respond with ONLY strict JSON, no markdown fences, no commentary:
{{"ok": true or false, "feedback": "2-3 sentences: what they got right, what's missing or wrong. Never reveal the grading key verbatim."}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=250, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        ok = bool(result.get("ok"))
        feedback = result.get("feedback", "")
    except Exception:
        return jsonify({"ok": True, "feedback": "(couldn't auto-grade — proceeding anyway)"})

    if ok:
        schedule_review(q["id"], ATTEMPTS.get(q["id"], 0))
    else:
        ATTEMPTS[q["id"]] = ATTEMPTS.get(q["id"], 0) + 1
    log_history({"event": "tradeoff", "qid": q["id"], "concept": q.get("concept_tag", ""), "ok": ok})
    return jsonify({"ok": ok, "feedback": feedback})


@app.route("/api/tradeoff-spar", methods=["POST"])
def tradeoff_spar():
    """Back-and-forth debate on a tradeoff drill — reuses the CHATS persistence pattern with a
    ':spar' chat_key, same as the design chat's ':clarify'/':adversarial' suffixes."""
    data = request.json
    q = QUESTIONS.get(data.get("question_id", ""))
    if not q or q["lang"] != "tradeoff":
        return jsonify({"error": "not found"}), 404
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "say something first"}), 400

    roll = TRADEOFF_ROLLS.get(q["id"])
    title = roll["title"] if roll else q["title"]
    scenario_prompt = roll["prompt"] if roll else q["prompt"]

    system_prompt = f"""You are a sharp system-design interviewer sparring live with a candidate on a forced-choice tradeoff.

Scenario: {title}
{scenario_prompt}

Rules:
- Always argue AGAINST whatever position the candidate is currently defending — never simply agree.
- If their latest argument is weak, hand-wavy, or ignores a real cost, press on that specific gap.
- If their latest argument is genuinely strong and engages the real tradeoff, explicitly concede that point, then pivot: start arguing the OTHER side yourself (steelman the position they just abandoned), so they now have to defend it in turn.
- Stay concrete and scenario-specific, never generic. 2-4 sentences, no preamble."""

    chat_key = q["id"] + ":spar"
    history = CHATS.setdefault(chat_key, [])
    history.append({"role": "user", "content": message})
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system_prompt}] + history,
            max_tokens=250,
            extra_body={"reasoning": {"enabled": False}},
        )
        reply = resp.choices[0].message.content
        if not reply:
            raise ValueError("model returned an empty response")
    except Exception as e:
        history.pop()
        return jsonify({"error": str(e)}), 502
    history.append({"role": "assistant", "content": reply})
    save_chats()
    return jsonify({"reply": reply})


# qid -> {prompt, answer_low, answer_high, unit, explanation} — session-only re-rolled napkin
# scenarios, so the same underlying skill can't just be memorized after one pass. Falls back to
# the static bank entry whenever a question hasn't been re-rolled (or after a server restart).
NAPKIN_ROLLS = {}


@app.route("/api/napkin-regenerate", methods=["POST"])
def napkin_regenerate():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "napkin":
        return jsonify({"error": "not found"}), 404

    prompt = f"""Write a fresh back-of-envelope estimation scenario testing the exact same underlying
skill/formula as this one, but with different concrete inputs (different user counts, rates, sizes, etc.)
so the numeric answer differs and the scenario can't just be memorized.

Title: {q['title']}
Original scenario: {q['prompt']}

Respond ONLY strict JSON, no markdown fences:
{{"prompt": "the new scenario text", "answer_low": <number>, "answer_high": <number>, "unit": "{q.get('unit', '')}", "explanation": "one sentence walking through the estimate"}}"""
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=400, temperature=0.6, extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        NAPKIN_ROLLS[q["id"]] = {
            "prompt": result.get("prompt") or q["prompt"],
            "answer_low": float(result.get("answer_low", q["answer_low"])),
            "answer_high": float(result.get("answer_high", q["answer_high"])),
            "unit": result.get("unit") or q.get("unit", ""),
            "explanation": result.get("explanation") or q.get("explanation", ""),
        }
        return jsonify(NAPKIN_ROLLS[q["id"]])
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/napkin-grade", methods=["POST"])
def napkin_grade():
    """Numeric tolerance-band check stays deterministic, no LLM call. An optional free-text
    'assumptions' field gets a best-effort LLM aside — never blocks the objective pass/fail."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "napkin":
        return jsonify({"error": "not found"}), 404
    raw_answer = (data.get("answer") or "").strip().replace(",", "")
    try:
        value = float(raw_answer)
    except ValueError:
        return jsonify({"ok": False, "feedback": "Enter a number."})

    roll = NAPKIN_ROLLS.get(q["id"])
    low, high, unit = (roll["answer_low"], roll["answer_high"], roll["unit"]) if roll else (
        q["answer_low"], q["answer_high"], q.get("unit", ""))
    explanation = roll["explanation"] if roll else q.get("explanation", "")
    scenario = roll["prompt"] if roll else q["prompt"]
    ok = low <= value <= high
    feedback = (f"Within the expected range ({low:g}-{high:g} {unit})."
                if ok else f"Outside the expected range — aim for roughly {low:g}-{high:g} {unit}.")

    if ok:
        schedule_review(q["id"], ATTEMPTS.get(q["id"], 0))
    else:
        ATTEMPTS[q["id"]] = ATTEMPTS.get(q["id"], 0) + 1
    log_history({"event": "napkin", "qid": q["id"], "ok": ok})

    assumption_feedback = ""
    assumptions = (data.get("assumptions") or "").strip()
    if assumptions:
        try:
            aprompt = (f"A candidate is doing a back-of-envelope estimation problem.\n"
                       f"Scenario: {scenario}\nTheir stated assumptions: \"{assumptions}\"\n"
                       f"In one short, terse sentence (like a quick interviewer aside), note whether "
                       f"their assumptions are reasonable, or flag the shakiest one.")
            aresp = client.chat.completions.create(
                model=MODEL, messages=[{"role": "user", "content": aprompt}],
                max_tokens=80, temperature=0, extra_body={"reasoning": {"enabled": False}},
            )
            assumption_feedback = aresp.choices[0].message.content.strip()
        except Exception:
            pass

    return jsonify({"ok": ok, "feedback": feedback, "explanation": explanation,
                     "assumption_feedback": assumption_feedback})


@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    if whisper_client is None:
        return jsonify({"error": "OPENAI_API_KEY not configured on the server"}), 500
    audio = request.files.get("audio")
    if not audio:
        return jsonify({"error": "no audio uploaded"}), 400
    try:
        result = whisper_client.audio.transcriptions.create(
            model="whisper-1", file=(audio.filename or "note.webm", audio.read(), audio.mimetype or "audio/webm"),
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"text": result.text})


@app.route("/api/review", methods=["POST"])
def review():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q:
        return jsonify({"error": "not found"}), 404

    prompt = f"""You are a terse senior interviewer reviewing a candidate's PASSING solution — they already got it correct, this is a quality review, not a hint.

Problem: {q['title']}
{q['prompt']}
Known idiomatic approach and pitfall: {q['concept']}

Candidate's passing solution:
```{q['lang']}
{data.get('code', '')}
```

Give a short, blunt code review covering only what's actually notable (skip categories with nothing worth saying):
- Readability/style issues, if any
- Edge cases their solution might not handle that weren't covered by the test cases
- Whether this would survive a follow-up twist on the same problem in a real interview
- One alternate approach and its complexity tradeoff, if there's a genuinely different one worth knowing

4-6 sentences max, plain prose, no markdown, no headers, no "great job" preamble."""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=350,
            extra_body={"reasoning": {"enabled": False}},
        )
        return jsonify({"review": resp.choices[0].message.content.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


if __name__ == "__main__":
    app.run(debug=True, port=5050)
