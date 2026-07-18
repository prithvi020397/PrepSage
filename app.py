import difflib
import json
import logging
import os
import random
import re
import requests
import sqlite3
import subprocess
import tempfile
import time
import yaml
from datetime import datetime, timedelta
from io import BytesIO

from dotenv import load_dotenv
from flask import Flask, jsonify, request, render_template, redirect, g
from openai import OpenAI

# resume parsing — optional, graceful fallback if missing
try:
    import pdfplumber
except Exception:
    pdfplumber = None
try:
    import docx
except Exception:
    docx = None

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("theloop")

@app.before_request
def _req_start():
    g._t0 = time.time()

@app.after_request
def _req_log(resp):
    ms = int((time.time() - getattr(g, "_t0", time.time())) * 1000)
    log.info("%s %s %s %dms", request.method, request.path, resp.status_code, ms)
    return resp
# The Loop: single-user local interview prep platform
HEADROOM_ENABLED = os.environ.get("HEADROOM_ENABLED", "").lower() in ("1", "true", "yes")
API_BASE = "http://localhost:9090/v1" if HEADROOM_ENABLED else "https://openrouter.ai/api/v1"
client = OpenAI(base_url=API_BASE, api_key=os.environ.get("OPENROUTER_API_KEY", "sk-placeholder-not-used"))
MODEL = "deepseek/deepseek-v4-flash"

DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")

# ponytail: TAXONOMY_VERSION stamps every LLM extraction (resume/JD) so we can detect
# drift when JD_CONCEPT_TRANSLATIONS / CONCEPT_TAXONOMY change. Old extractions keep
# working (matching is deterministic at read time), but a stale stamp signals "re-parse
# recommended" instead of silently serving concepts mapped under an old taxonomy.
TAXONOMY_VERSION = "2026-07-17"
# ponytail: separate client — OpenRouter doesn't proxy Whisper transcription, needs a real OpenAI key
whisper_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "")) if os.environ.get("OPENAI_API_KEY") else None

# ponytail: Firecrawl layer is OPTIONAL. If the module or its deps are missing, every hybrid call
# degrades to the precomputed bank. Import failure must never break app startup.
try:
    import firecrawl_layer as fc
except Exception:
    fc = None

# ponytail: security scanner for candidate-submitted code. Optional so a missing
# bandit install never blocks app startup — run_python_case degrades to a soft warn.
try:
    from security_scan import scan_code, has_blocker
except Exception:
    scan_code = None
    has_blocker = None

# ponytail: Supabase multi-user layer is OPTIONAL. When SUPABASE_URL/SUPABASE_KEY
# are unset, supabase_client degrades to the legacy file-based single-user backend,
# so the app runs unchanged in local mode. Import failure must never break startup.
try:
    import supabase_client as sb
    SUPABASE_ENABLED = sb.SUPABASE_ENABLED
except Exception:
    sb = None
    SUPABASE_ENABLED = False

# LEGACY_MODE=1 forces single-user file-based mode (bypasses Supabase). Useful locally
# during a Supabase outage. Production leaves this unset so Supabase auth stays on.
if os.environ.get("LEGACY_MODE", "").lower() in ("1", "true", "yes"):
    SUPABASE_ENABLED = False
    sb = None


def chat_content(resp):
    """Safely pull text out of an OpenAI chat-completions response.

    The model intermittently returns an empty `content` (None), which used to crash every
    route that did `resp.choices[0].message.content.strip()` with a 502 + leaked exception
    ('NoneType' object has no attribute 'strip'). Centralizing this means each route can just
    check `if not text:` and return a clean retry error instead of 500ing. Returns the stripped
    string, or None if the response was empty/malformed.
    """
    try:
        text = resp.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return None
    return text.strip() if text else None

QUESTIONS = {q["id"]: q for q in json.load(open("questions.json"))}

# ponytail: LLM-derived mapping of question -> gap concepts it builds, produced offline by
# precompute.py (gen_concept_links). Loaded lazily and cached so runtime stays free; absent
# file => framed-practice falls back to the legacy GAP_TO_QUESTIONS dict.
_CONCEPT_LINKS_CACHE = None


def _load_concept_links():
    global _CONCEPT_LINKS_CACHE
    if _CONCEPT_LINKS_CACHE is not None:
        return _CONCEPT_LINKS_CACHE
    path = "question_concept_links.json"
    if not os.path.exists(path):
        _CONCEPT_LINKS_CACHE = {}
        return _CONCEPT_LINKS_CACHE
    try:
        _CONCEPT_LINKS_CACHE = json.load(open(path))
    except Exception:
        _CONCEPT_LINKS_CACHE = {}
    return _CONCEPT_LINKS_CACHE

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

JUDGES_FILE = "judges.json"
# chat_key -> judge_result dict — persisted so /api/export can reconstruct reports
# after the session ends, without re-running the judge model.
JUDGES = json.load(open(JUDGES_FILE)) if os.path.exists(JUDGES_FILE) else {}

PRECOMPUTED_TRACES = json.load(open("traces.json")) if os.path.exists("traces.json") else {}
PRECOMPUTED_CONCEPTS = json.load(open("concept_maps.json")) if os.path.exists("concept_maps.json") else {}
PRECOMPUTED_SOLUTIONS = json.load(open("solutions.json")) if os.path.exists("solutions.json") else {}
PRECOMPUTED_CONTEXTS = json.load(open("question_contexts.json")) if os.path.exists("question_contexts.json") else {}

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
    "late_data_watermarks", "domain_alignment",
    "entity_enumeration", "grain_awareness", "scd_strategy", "missing_dimension_audit",
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
    "late_data_watermarks": "a mobile client synced buffered events after being offline for a day, arriving well after the daily aggregation window had already closed and published — 'yesterday's' revenue quietly stayed wrong until someone noticed the late batch",
    "domain_alignment": "a data team built a sophisticated real-time clickstream pipeline with exactly-once semantics, but never talked to the marketing stakeholders — who only needed a daily CSV export in a specific schema, and had been manually emailing it to themselves because the pipeline's output didn't match their reporting tool's import format",
    "entity_enumeration": "a team designed a 'trip' fact table without identifying 'offer' as a separate entity first, so the grain was ambiguous — some rows represented trip requests, others accepted trips, and every aggregation that counted trips double-counted the ones that went through the offer flow",
    "grain_awareness": "a star schema stored ratings in a separate dimension table keyed by (user_id, driver_id), but a single trip has exactly two ratings (user→driver, driver→user) — joining on those keys silently fanned out the trip fact 4× and revenue reports were 2× actual for two quarters",
    "scd_strategy": "a customer dimension used Type 2 tracking for every column (including ZIP code), and after three years the dimension had 18M rows for 2M unique customers — every join scanned 9× dead history, slowing a weekly BI dashboard from 4 seconds to 3 minutes before anyone investigated",
    "missing_dimension_audit": "a marketing analytics mart had no location dimension because the data team assumed 'city is just a column on the customer table' — then a regional promo analysis required grouping by store proximity, which needed lat/lng joins against a geography table that didn't exist, delaying the campaign launch by three weeks",
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

DESIGN_RUBRIC_44 = {
    "phases": [
        {
            "name": "Phase 1: Requirements & Scoping",
            "max": 8,
            "items": [
                {"id": "r1", "desc": "Asks about scale — event volume, row counts, growth projections", "max": 2},
                {"id": "r2", "desc": "Asks about latency SLAs — batch hourly? streaming? sub-second?", "max": 2},
                {"id": "r3", "desc": "Asks about data sources — how many, what format, reliable or not", "max": 2},
                {"id": "r4", "desc": "Asks about consumers — who reads, how many teams, query patterns", "max": 2},
                {"id": "r5", "desc": "Asks about constraints — budget, team, timeline, compliance, existing infra", "max": 2},
                {"id": "r6", "desc": "Summarizes understanding — restates requirements before designing", "max": 2},
                {"id": "r7", "desc": "Identifies ambiguities — flags what's unclear and makes reasonable assumptions", "max": 2},
                {"id": "r8", "desc": "Defines 'done' — what does success look like for this system", "max": 2},
            ]
        },
        {
            "name": "Phase 2: High-Level Architecture",
            "max": 10,
            "items": [
                {"id": "a1", "desc": "Correct ingestion layer — picks appropriate tool for scale/latency", "max": 2},
                {"id": "a2", "desc": "Correct processing layer — batch/streaming/hybrid is appropriate", "max": 2},
                {"id": "a3", "desc": "Correct storage layer — right format, right system, right tiering", "max": 2},
                {"id": "a4", "desc": "Correct serving layer — matches consumer access patterns", "max": 2},
                {"id": "a5", "desc": "Clean data flow — sources → ingestion → processing → storage → serving", "max": 2},
                {"id": "a6", "desc": "Appropriate complexity — not over-engineered for stated scale", "max": 2},
                {"id": "a7", "desc": "Uses existing infrastructure — acknowledges what already exists", "max": 2},
                {"id": "a8", "desc": "Component naming — uses specific tools, not vague boxes", "max": 2},
                {"id": "a9", "desc": "Handles the happy path first — doesn't get bogged down in edge cases early", "max": 2},
                {"id": "a10", "desc": "Can defend against 'why not X?' — has alternatives ready", "max": 2},
            ]
        },
        {
            "name": "Phase 3: Deep Dive — Data Modeling",
            "max": 6,
            "items": [
                {"id": "d1", "desc": "Schema design — tables/entities/relationships discussed", "max": 2},
                {"id": "d2", "desc": "Partitioning strategy — chosen and explained", "max": 2},
                {"id": "d3", "desc": "File format choice — Parquet/ORC/Avro/etc with reasoning", "max": 2},
                {"id": "d4", "desc": "Schema evolution handling — forward/backward compatibility", "max": 2},
                {"id": "d5", "desc": "Deduplication strategy — how to handle duplicate records", "max": 2},
                {"id": "d6", "desc": "Data versioning — how to track changes over time", "max": 2},
            ]
        },
        {
            "name": "Phase 4: Deep Dive — Reliability & Fault Tolerance",
            "max": 8,
            "items": [
                {"id": "f1", "desc": "Late/arriving data — explicit handling mechanism", "max": 2},
                {"id": "f2", "desc": "Idempotency — reruns don't corrupt state", "max": 2},
                {"id": "f3", "desc": "Error handling — dead letter queues, retries, alerting", "max": 2},
                {"id": "f4", "desc": "Exactly-once semantics — trade-offs articulated", "max": 2},
                {"id": "f5", "desc": "Backpressure — what happens when consumer is slow", "max": 2},
                {"id": "f6", "desc": "Data quality checks — validation at ingestion and processing", "max": 2},
                {"id": "f7", "desc": "Failure isolation — one bad source doesn't kill everything", "max": 2},
                {"id": "f8", "desc": "Recovery/rollback — how to fix a bad run", "max": 2},
            ]
        },
        {
            "name": "Phase 5: Deep Dive — Operational Maturity",
            "max": 6,
            "items": [
                {"id": "o1", "desc": "Monitoring & alerting — metrics, dashboards, SLOs", "max": 2},
                {"id": "o2", "desc": "Data freshness tracking — how consumers know data is fresh", "max": 2},
                {"id": "o3", "desc": "Cost estimation — rough awareness of cloud spend", "max": 2},
                {"id": "o4", "desc": "Scaling strategy — how system grows with data", "max": 2},
                {"id": "o5", "desc": "Access control — who can read/write what", "max": 2},
                {"id": "o6", "desc": "Deployment/CI-CD — how changes get to production safely", "max": 2},
            ]
        },
        {
            "name": "Phase 6: Communication & Presence",
            "max": 6,
            "items": [
                {"id": "c1", "desc": "Structured walkthrough — clear beginning, middle, end", "max": 2},
                {"id": "c2", "desc": "Trade-off articulation — 'I chose X over Y because...'", "max": 2},
                {"id": "c3", "desc": "Handles pushback — doesn't get defensive, pivots well", "max": 2},
                {"id": "c4", "desc": "Asks for feedback — checks in with interviewer", "max": 2},
                {"id": "c5", "desc": "Time management — covers all areas without rushing", "max": 2},
                {"id": "c6", "desc": "Confidence vs humility — knows what they know and don't", "max": 2},
            ]
        },
    ]
}

RETRO_QUESTIONS = [
    {"q": "What phase felt hardest?", "why": "Focus prep there"},
    {"q": "Where did you stall?", "why": "That's your knowledge gap"},
    {"q": "What would you do differently?", "why": "Self-awareness matters"},
    {"q": "What did you forget to mention?", "why": "Build a mental checklist"},
    {"q": "What surprised you about the questions?", "why": "Reveals blind spots"},
]

BASELINE_RUBRIC = [
    "Idempotency: the design handles re-delivery/replay without double-processing (duplicate messages, retried writes)",
    "Backfill/reprocessing: there's a concrete story for replaying historical data (a bug fix, a schema change, a late correction) via a dedicated separate pipeline, not just re-running the main one",
    "Schema evolution: producers and consumers can evolve independently without a synchronized deploy, and breaking vs non-breaking changes are distinguished",
    "Data quality/observability: some mechanism exists to catch bad data before it reaches consumers, not just after",
    "Late/out-of-order data: an explicit watermark or allowed-lateness policy for events that arrive after their window closes, not an assumption that events arrive in order",
    "Partitioning initiative: the candidate volunteers a partitioning strategy (key + granularity) during the storage discussion rather than waiting to be asked, showing they anticipate the scale bottleneck",
    "Engine choice with org-context: tool decisions account for the team's existing stack, skill set, and ecosystem (e.g. Redshift over Athena when the team uses dbt), not just feature checklists",
    "Domain alignment: the candidate connects data architecture decisions to business outcomes (KPIs, stakeholder needs, downstream consumers), not just technical correctness",
    "Incremental load awareness: the candidate addresses how data arrives incrementally (CDC, watermark columns, metadata-driven partitioning) rather than assuming full daily reloads, and can articulate when each approach fits",
    "Option survey: the candidate surveys 2-3 architectural options with explicit pros/cons before committing to one, rather than jumping straight to a single solution",
    "Entity enumeration: the candidate identifies all core entities before designing columns or tables, establishing the scope and grain of the model upfront rather than adding tables reactively",
    "SCD strategy: the candidate justifies their slowly-changing-dimension approach (Type 1 vs Type 2 vs Type 3) for each dimension based on query patterns and historical needs, not just defaulting to one strategy",
    "Grain awareness: fact and dimension tables respect their declared grain — one row per business event, no silent fan-out from many-to-many relationships embedded as columns",
    "Missing dimension self-audit: when asked what they missed, the candidate can identify a real missing entity or dimension (location, time, channel) rather than claiming completeness",
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

# ponytail: FDE (Forward Deployed Engineer) taxonomy — concepts tested in decomposition /
# open-ended case-study rounds. Selected via q["track"] == "fde".
CONCEPT_TAXONOMY_FDE = [
    "ambiguous_problem_scoping", "stakeholder_mapping_alignment",
    "production_deployment_strategy", "legacy_enterprise_integration",
    "failure_mode_risk_analysis", "iterative_delivery_mvp",
    "data_integration_quality",
]

WAR_STORIES_FDE = {
    "ambiguous_problem_scoping": "a team spent two months building a 'real-time fraud dashboard' before asking the stakeholder what decision it was meant to drive — turns out they needed a daily batch CSV emailed to a compliance officer, not a streaming viz",
    "stakeholder_mapping_alignment": "an FDE got sign-off from the VP of Engineering but nobody told the IT security team, who blocked the VPC deployment on day one because they'd never been looped in on the compliance review",
    "production_deployment_strategy": "a canary rollout pushed to 5% of users hit an undocumented rate limit on the customer's legacy ERP and took down order processing for that segment — the rollback plan existed but nobody had tested it",
    "legacy_enterprise_integration": "a customer claimed their system had a 'REST API' — which turned out to be a SOAP endpoint wrapped in a custom HTTP adapter that dropped every fifth request with no error code",
    "failure_mode_risk_analysis": "the deployment assumed the customer's Snowflake warehouse had <1s query latency, but the actual BI workload meant analytics queries queued for 45 seconds during business hours, breaking the real-time dashboard assumption",
    "iterative_delivery_mvp": "a team spent six weeks building the 'perfect' data pipeline with exactly-once semantics and automatic failover, while the customer was manually emailing CSVs because they needed something — anything — working by week two",
    "data_integration_quality": "a customer insisted their 12 data sources were 'clean and consistent' — the first integration pass found three different date formats, two different customer ID schemas, and one source that hadn't updated in 14 months",
}

BASELINE_RUBRIC_AI = [
    "Grounding: answers are grounded in retrieved/cited sources, with a defined behavior when there isn't enough context (say unsure/refuse vs hallucinate)",
    "Evals: there's a concrete offline eval set or regression harness that catches quality regressions before a prompt or model change ships",
    "Cost/latency: the design accounts for cost and latency at expected scale (caching, model tiering, batching), not just correctness",
    "Observability: production quality is monitored on an ongoing basis (e.g. logging retrieved context, tracking hallucination/refusal rates) rather than tested once offline",
]

BASELINE_RUBRIC_FDE = [
    "Scoping: asks clarifying questions about the actual goal, stakeholders, constraints, and success criteria before proposing anything",
    "Decomposition: breaks the vague problem into concrete, separable workstreams sequenced by risk and value",
    "Stakeholder awareness: identifies who needs to be involved, whose buy-in is needed, and how to navigate competing priorities",
    "Iteration: proposes a thin walking-skeleton MVP before optimizing — ships fast, then hardens",
    "Failure modes: names what could go wrong unprompted, proposes mitigations or fallback plans",
    "Communication: narrates thinking continuously, structured walkthrough, doesn't go silent or jump between topics",
]


def taxonomy_for(q):
    t = q.get("track")
    if t == "ai": return CONCEPT_TAXONOMY_AI
    if t == "fde": return CONCEPT_TAXONOMY_FDE
    return CONCEPT_TAXONOMY


def war_stories_for(q):
    t = q.get("track")
    if t == "ai": return WAR_STORIES_AI
    if t == "fde": return WAR_STORIES_FDE
    return WAR_STORIES


def baseline_rubric_for(q):
    t = q.get("track")
    if t == "ai": return BASELINE_RUBRIC_AI
    if t == "fde": return BASELINE_RUBRIC_FDE
    return BASELINE_RUBRIC


def persona_for(q):
    t = q.get("track")
    if t == "ai": return "senior AI/ML engineering interviewer"
    if t == "fde": return "senior forward deployed engineer interviewer"
    return "senior data engineering interviewer"


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


def _atomic_json(path, data):
    """Write JSON atomically: write to temp file, then rename. Prevents corruption on crash."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def save_progress():
    _atomic_json(PROGRESS_FILE, PROGRESS)


# ---------------------------------------------------------------------------
# Supabase multi-user auth (optional). When SUPABASE_ENABLED is False these
# endpoints return 404 and the rest of the app runs in legacy single-user mode.
# When enabled, they issue Supabase Auth JWTs and resolve the caller's id.
# ---------------------------------------------------------------------------
def current_user_id():
    """Return the Supabase auth user id for the current request, or None.

    None means: Supabase is off, or no valid bearer token — callers should
    fall back to the legacy global PROGRESS/HISTORY/CHATS state.
    """
    if not SUPABASE_ENABLED or sb is None:
        return None
    from flask import request as _req
    return sb.get_user_id_from_request(_req)


LEGACY_FAKE_TOKEN = "legacy-local-mode"

@app.route("/api/signup", methods=["POST"])
def api_signup():
    if not SUPABASE_ENABLED or sb is None:
        data = request.json or {}
        return jsonify({
            "ok": True,
            "user": "legacy-user",
            "access_token": LEGACY_FAKE_TOKEN,
        })
    data = request.json or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "email and password required"}), 400
    c = sb.get_client()
    if not c:
        return jsonify({"error": "supabase client unavailable"}), 500
    try:
        res = c.auth.sign_up({"email": email, "password": password})
    except Exception as e:
        return jsonify({"error": f"signup failed: {e}"}), 500
    if getattr(res, "error", None):
        return jsonify({"error": str(res.error)}), 400
    # Create profile row directly (GoTrue triggers on auth.users are unreliable).
    # Set the user's session so RLS sees auth.uid() = user id.
    user_id = res.user.id if res.user else None
    session = res.session
    if user_id and session:
        try:
            c.auth.set_session(session.access_token, session.refresh_token)
            display_name = email.split("@")[0]
            c.table("profiles").upsert({
                "id": user_id,
                "email": email,
                "display_name": display_name,
            }).execute()
        except Exception:
            pass
    return jsonify({
        "ok": True,
        "user": user_id,
        "access_token": session.access_token if session else None,
    })


@app.route("/api/login", methods=["POST"])
def api_login():
    if not SUPABASE_ENABLED or sb is None:
        data = request.json or {}
        return jsonify({
            "access_token": LEGACY_FAKE_TOKEN,
            "refresh_token": LEGACY_FAKE_TOKEN,
            "user_id": "legacy-user",
        })
    data = request.json or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    c = sb.get_client()
    if not c:
        return jsonify({"error": "supabase client unavailable"}), 500
    try:
        res = c.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        return jsonify({"error": f"login failed: {e}"}), 500
    if getattr(res, "error", None):
        return jsonify({"error": str(res.error)}), 401
    session = res.session
    return jsonify({
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user_id": res.user.id if res.user else None,
    })


TEST_EMAIL = "test@theloop.dev"
TEST_PASSWORD = "test-loop-2024"


@app.route("/api/test-login", methods=["POST"])
def api_test_login():
    """Login or signup a test user. If ?fresh=1, wipe progress first."""
    if not SUPABASE_ENABLED or sb is None:
        fresh = request.args.get("fresh") == "1"
        if fresh:
            PROGRESS.clear()
            save_progress()
        return jsonify({
            "access_token": LEGACY_FAKE_TOKEN,
            "refresh_token": LEGACY_FAKE_TOKEN,
            "user_id": "legacy-user",
            "fresh": fresh,
        })
    c = sb.get_client()
    if not c:
        return jsonify({"error": "supabase client unavailable"}), 500
    fresh = request.args.get("fresh") == "1"
    if fresh:
        PROGRESS.clear()
        save_progress()
    # try login first
    session = None
    user_id = None
    try:
        res = c.auth.sign_in_with_password({"email": TEST_EMAIL, "password": TEST_PASSWORD})
        if getattr(res, "error", None):
            raise Exception(str(res.error))
        session = res.session
        user_id = res.user.id if res.user else None
    except Exception:
        # user doesn't exist — sign up
        try:
            res2 = c.auth.sign_up({"email": TEST_EMAIL, "password": TEST_PASSWORD})
            if getattr(res2, "error", None):
                return jsonify({"error": str(res2.error)}), 400
            session = res2.session
            user_id = res2.user.id if res2.user else None
            if user_id and session:
                try:
                    c.auth.set_session(session.access_token, session.refresh_token)
                    c.table("profiles").upsert({
                        "id": user_id, "email": TEST_EMAIL, "display_name": "Test User",
                    }).execute()
                except Exception:
                    pass
        except Exception as e:
            return jsonify({"error": f"test signup failed: {e}"}), 500
    if not session:
        return jsonify({"error": "could not authenticate"}), 500
    return jsonify({
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user_id": user_id,
        "fresh": fresh,
    })


@app.route("/api/me", methods=["GET"])
def api_me():
    if not SUPABASE_ENABLED or sb is None:
        return jsonify({"user_id": None, "mode": "legacy"})
    uid = current_user_id()
    if not uid:
        return jsonify({"user_id": None, "mode": "anonymous"}), 401
    return jsonify({"user_id": uid, "mode": "supabase"})


# ponytail: reset wipes the *working state* of a question (saved code, trace, pattern,
# skeleton, concept map) but preserves the earned credit (solved_at / due_at / fails) so a
# redo doesn't also erase spaced-repetition progress. This is the "clean slate to retry the
# code" action, not an "I never solved this" action.
RESET_FIELDS = ("code", "trace", "pattern", "skeleton", "concept_map")


def _reset_entry(qid):
    p = PROGRESS.get(qid)
    if not isinstance(p, dict):
        return
    for f in RESET_FIELDS:
        p.pop(f, None)


@app.route("/api/reset-question/<qid>", methods=["POST"])
def reset_question(qid):
    if qid not in QUESTIONS:
        return jsonify({"error": "not found"}), 404
    _reset_entry(qid)
    save_progress()
    return jsonify({"ok": True})


@app.route("/api/reset-category/<lang>", methods=["POST"])
def reset_category(lang):
    if lang not in ("sql", "python", "design", "tradeoff"):
        return jsonify({"error": "unknown lang"}), 404
    for qid, q in QUESTIONS.items():
        if q["lang"] == lang:
            _reset_entry(qid)
    save_progress()
    return jsonify({"ok": True, "lang": lang})


@app.route("/api/start-over", methods=["POST"])
def start_over():
    # ponytail: full clean slate — wipes every persistence file so the dashboard reads 0/N
    # with no streaks, due reviews, saved code, chat history, or replay comments. Distinct
    # from /api/reset-category which only clears working state and keeps solved credit.
    import glob
    for f in (PROGRESS_FILE, HISTORY_FILE, CHATS_FILE, REPLAY_COMMENTS_FILE, JUDGES_FILE):
        if os.path.exists(f):
            os.remove(f)
    return jsonify({"ok": True})


def log_history(entry):
    entry["ts"] = datetime.now().isoformat()
    HISTORY.append(entry)
    _atomic_json(HISTORY_FILE, HISTORY)


def save_chats():
    _atomic_json(CHATS_FILE, CHATS)


def save_judges():
    _atomic_json(JUDGES_FILE, JUDGES)


def save_replay_comments():
    _atomic_json(REPLAY_COMMENTS_FILE, REPLAY_COMMENTS)


def _gen_question_context(q):
    """Fallback rich-framing generator — only used if a question is missing from the
    precomputed question_contexts.json. Mirrors gen_question_context in precompute.py."""
    prompt = f"""Rewrite this coding-interview question so it reads like a real interview prompt.

Title: {q['title']}
Prompt: {q['prompt']}
Concept (judgment only): {q.get('concept', '')}

Respond ONLY strict JSON:
{{"scenario": "1-2 sentence realistic task framing (under 40 words)", "why_asked": "one sentence on the skill probed (under 25 words)", "edge_cases": ["short edge case 1", "short edge case 2"]}}"""
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=400, temperature=0.3, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        return {"scenario": result.get("scenario", "").strip(),
                "why_asked": result.get("why_asked", "").strip(),
                "edge_cases": [str(e).strip() for e in (result.get("edge_cases") or []) if str(e).strip()][:2]}
    except Exception:
        return {"scenario": "", "why_asked": "", "edge_cases": []}


def split_wrap_up_reply(reply, taxonomy=CONCEPT_TAXONOMY):
    """Split an interview wrap-up reply into (prose, missed_concepts, rushed_to_design,
    communication_score, communication_note, rubric_scores) — the trailing ```json fence is a grading
    artifact and never shown to the candidate."""
    if "```json" not in reply:
        return reply.strip(), [], False, None, "", {}
    prose, _, tail = reply.partition("```json")
    try:
        raw = tail.split("```")[0]
        parsed = json.loads(raw)
        concepts = [c for c in parsed.get("missed_concepts", []) if c in taxonomy]
        rushed = bool(parsed.get("rushed_to_design"))
        score = parsed.get("communication_score")
        score = int(score) if isinstance(score, (int, float)) and 1 <= score <= 5 else None
        note = parsed.get("communication_note") or ""
        rubric_scores = parsed.get("rubric_scores") or {}
    except Exception:
        concepts, rushed, score, note, rubric_scores = [], False, None, "", {}
    return prose.strip(), concepts, rushed, score, note, rubric_scores


def hire_verdict(missed_concepts, rushed_to_design, communication_score, rubric_scores=None):
    """Cheap point-based read, not a real calibrated rubric — reuses the signals the
    debrief already computes to surface a directional strong hire / hire / no hire."""
    if rubric_scores:
        phase_maxes = [8, 10, 6, 8, 6, 6]
        total = sum(rubric_scores.get(f"phase{i+1}", 0) for i in range(6))
        total_max = sum(phase_maxes)
        pct = total / total_max
        if pct >= 0.85:
            return "Strong Hire"
        if pct >= 0.60:
            return "Hire"
        return "No Hire"
    points = -len(missed_concepts)
    if rushed_to_design:
        points -= 2
    if communication_score is not None:
        points += communication_score - 3
    if points >= 0:
        return "Strong Hire"
    if points >= -3:
        return "Hire"
    return "No Hire"


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


def _compute_gap_alerts():
    """Compare resume-claimed skills against actual performance data for the dashboard.
    Only shows skills that match our question bank — filters out irrelevant skills."""
    resume = PROGRESS.get("_resume")
    if not resume:
        return []

    # extract skill names (now objects with name/depth/context)
    raw_skills = resume.get("skills", [])
    skill_entries = []
    for s in raw_skills:
        if isinstance(s, dict):
            skill_entries.append(s)
        else:
            skill_entries.append({"name": s, "depth": "moderate", "context": ""})

    claimed_domains = [d.lower() for d in resume.get("domains", [])]

    # build a set of all topic keywords we actually have questions for
    question_topics = set()
    for q in QUESTIONS.values():
        question_topics.add(q.get("lang", "").lower())
        t = topic_for(q)
        question_topics.add(t.lower())
    # add design concept tags
    for q in QUESTIONS.values():
        if q["lang"] == "design" and q.get("concept_tag"):
            question_topics.add(q["concept_tag"].lower().replace("_", " "))

    # filter: only show skills that plausibly match our question bank
    def _is_relevant(skill_name):
        sn = skill_name.lower()
        # direct match
        if sn in question_topics:
            return True
        # keyword overlap
        for topic in question_topics:
            if any(w in topic for w in sn.split() if len(w) > 3):
                return True
            if any(w in sn for w in topic.split() if len(w) > 3):
                return True
        # language match
        if sn in ("sql", "python", "java", "scala", "javascript", "typescript"):
            return True
        # design domain match
        design_domains = {"distributed systems", "data engineering", "machine learning",
                          "cloud infrastructure", "microservices", "streaming", "databases",
                          "payments", "ad tech", "healthcare", "retail", "real-time systems"}
        if sn in design_domains:
            return True
        return False

    # build accuracy per topic from HISTORY
    topic_stats = {}
    for h in HISTORY:
        if h.get("event") == "submit":
            t = h.get("topic")
            if t:
                if t not in topic_stats:
                    topic_stats[t] = {"total": 0, "passed": 0}
                topic_stats[t]["total"] += 1
                if h.get("passed"):
                    topic_stats[t]["passed"] += 1

    gaps = []
    for entry in skill_entries:
        name = entry.get("name", "")
        if not _is_relevant(name):
            continue

        # find matching topic
        best_match = None
        best_score = 0
        for topic in topic_stats:
            if name.lower() in topic or topic in name.lower():
                best_match = topic
                best_score = 1.0
            elif any(w in topic for w in name.lower().split() if len(w) > 3):
                score = sum(1 for w in name.lower().split() if w in topic and len(w) > 3) / max(1, len(name.split()))
                if score > best_score:
                    best_match = topic
                    best_score = score

        if best_match and best_score > 0.3:
            stats = topic_stats[best_match]
            pct = round(100 * stats["passed"] / stats["total"]) if stats["total"] > 0 else 0
            if pct < 70:
                gaps.append({"claimed": name, "topic": best_match, "accuracy": pct,
                             "attempts": stats["total"],
                             "severity": "high" if pct < 40 else "medium",
                             "depth": entry.get("depth", "moderate")})
        elif not best_match:
            # claimed skill with zero practice — only show if relevant
            gaps.append({"claimed": name, "topic": None, "accuracy": 0,
                         "attempts": 0, "severity": "high",
                         "depth": entry.get("depth", "moderate")})

    # also check domains
    for domain in claimed_domains:
        if not _is_relevant(domain):
            continue
        best_match = None
        for topic in topic_stats:
            if domain in topic or topic in domain:
                best_match = topic
                break
        if best_match:
            stats = topic_stats[best_match]
            pct = round(100 * stats["passed"] / stats["total"]) if stats["total"] > 0 else 0
            if pct < 70:
                gaps.append({"claimed": domain, "topic": best_match, "accuracy": pct,
                             "attempts": stats["total"],
                             "severity": "high" if pct < 40 else "medium",
                             "depth": "domain"})

    gaps.sort(key=lambda g: (0 if g["severity"] == "high" else 1, g["accuracy"]))
    return gaps[:8]


def _compute_study_plan():
    """Compute a basic study plan from resume + performance data (no LLM call).
    The full LLM-generated plan is available via /api/study-plan."""
    resume = PROGRESS.get("_resume")
    if not resume:
        return []

    target_role = resume.get("target_role", "software engineer")
    strongest = resume.get("strongest_skills", [])[:3]

    # find weak topics
    topic_stats = {}
    for h in HISTORY:
        if h.get("event") == "submit":
            t = h.get("topic")
            if t:
                if t not in topic_stats:
                    topic_stats[t] = {"total": 0, "passed": 0}
                topic_stats[t]["total"] += 1
                if h.get("passed"):
                    topic_stats[t]["passed"] += 1

    weak_topics = []
    for topic, stats in topic_stats.items():
        pct = round(100 * stats["passed"] / stats["total"]) if stats["total"] > 0 else 0
        if pct < 70 and stats["total"] >= 1:
            weak_topics.append({"topic": topic, "accuracy": pct, "attempts": stats["total"]})
    weak_topics.sort(key=lambda w: w["accuracy"])

    plan = []
    # priority 1: weak topics that match claimed skills
    raw_skills = resume.get("skills", [])
    skill_names = [s.get("name", s).lower() if isinstance(s, dict) else s.lower() for s in raw_skills]
    for wt in weak_topics[:3]:
        if any(s in wt["topic"].lower() for s in skill_names if len(s) > 3):
            plan.append({
                "title": f"Practice {wt['topic']}",
                "action": f"You claim this skill but have {wt['accuracy']}% accuracy. Drill the weak spots.",
                "priority": "high",
                "category": "sql" if "sql" in wt["topic"].lower() or "join" in wt["topic"].lower() or "window" in wt["topic"].lower() else "python",
            })

    # priority 2: due reviews
    due_count = sum(1 for qid in PROGRESS if is_due(qid))
    if due_count > 0:
        plan.append({
            "title": f"Review {due_count} due question{'s' if due_count != 1 else ''}",
            "action": "Spaced repetition keeps knowledge fresh. Review before starting new questions.",
            "priority": "high",
            "category": "sql",
        })

    # priority 3: design practice if claimed but not practiced
    design_count = sum(1 for q in QUESTIONS.values() if q["lang"] == "design" and not is_solved(q["id"]))
    design_practiced = any(h.get("event") == "design_debrief" for h in HISTORY)
    domains = [d.lower() for d in resume.get("domains", [])]
    if domains and not design_practiced and design_count > 0:
        plan.append({
            "title": "Try a system design question",
            "action": f"Your resume mentions {', '.join(domains[:2])} — practice applying your experience to design problems.",
            "priority": "medium",
            "category": "design",
        })

    # fill to 5 items
    if len(plan) < 5:
        unsolved_sql = sum(1 for q in QUESTIONS.values() if q["lang"] == "sql" and not is_solved(q["id"]))
        unsolved_py = sum(1 for q in QUESTIONS.values() if q["lang"] == "python" and not is_solved(q["id"]))
        if unsolved_sql > 0:
            plan.append({
                "title": f"Solve {unsolved_sql} SQL question{'s' if unsolved_sql != 1 else ''}",
                "action": "Keep momentum on your core skill.",
                "priority": "low",
                "category": "sql",
            })
        if unsolved_py > 0 and len(plan) < 5:
            plan.append({
                "title": f"Solve {unsolved_py} Python question{'s' if unsolved_py != 1 else ''}",
                "action": "Build coding fluency.",
                "priority": "low",
                "category": "python",
            })

    return plan[:5]


def _compute_claim_validation():
    """Track which resume claims have been validated by practice (no LLM call)."""
    resume = PROGRESS.get("_resume")
    if not resume:
        return {"validated": [], "unvalidated": [], "total_skills": 0, "validated_count": 0}

    raw_skills = resume.get("skills", [])
    skill_entries = []
    for s in raw_skills:
        if isinstance(s, dict):
            skill_entries.append(s)
        else:
            skill_entries.append({"name": s, "depth": "moderate", "context": ""})

    topic_stats = {}
    for h in HISTORY:
        if h.get("event") == "submit":
            t = h.get("topic")
            if t:
                if t not in topic_stats:
                    topic_stats[t] = {"total": 0, "passed": 0}
                topic_stats[t]["total"] += 1
                if h.get("passed"):
                    topic_stats[t]["passed"] += 1

    validated = []
    unvalidated = []
    for entry in skill_entries:
        name = entry.get("name", "")
        best_match = None
        for topic in topic_stats:
            if name.lower() in topic or topic in name.lower():
                best_match = topic
                break
            elif any(w in topic for w in name.lower().split() if len(w) > 3):
                best_match = topic
                break

        if best_match:
            stats = topic_stats[best_match]
            pct = round(100 * stats["passed"] / stats["total"]) if stats["total"] > 0 else 0
            validated.append({
                "skill": name, "accuracy": pct, "attempts": stats["total"],
                "depth": entry.get("depth", "moderate"),
                "strong": pct >= 70,
            })
        else:
            unvalidated.append({
                "skill": name, "depth": entry.get("depth", "moderate"),
                "context": entry.get("context", ""),
            })

    validated.sort(key=lambda v: (-v["strong"], -v["accuracy"]))
    unvalidated.sort(key=lambda u: 0 if u["depth"] == "deep" else 1)

    return {
        "validated": validated,
        "unvalidated": unvalidated[:15],
        "total_skills": len(skill_entries),
        "validated_count": len([v for v in validated if v["strong"]]),
    }


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
    # ponytail: security gate — never execute code that could damage the host.
    # Candidate code is scanned for process-spawn / eval / fs-destruction before
    # it ever reaches the interpreter. A BLOCK finding short-circuits execution.
    blocker = has_blocker(code)
    if blocker:
        return None, (
            f"Security scan blocked execution: {blocker.message} "
            f"(line {blocker.line}). This looks like it could harm the host machine, "
            f"not solve the interview problem. Rewrite using plain algorithm code."
        )
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
    # Show onboarding for new users (no progress, no deadline set)
    has_progress = any(is_solved(qid) for qid in PROGRESS if qid in QUESTIONS)
    has_deadline = isinstance(PROGRESS.get("_deadline"), dict) and PROGRESS["_deadline"].get("date")
    if not has_progress and not has_deadline:
        return redirect("/onboarding")
    return redirect("/dashboard")


@app.route("/taxonomy")
def taxonomy():
    """Reference page listing all concepts, descriptions, and example tools."""
    from collections import defaultdict
    tool_examples = defaultdict(list)
    for tool, concept in CONCEPT_NORMALIZATION.items():
        if concept in CONCEPT_TAXONOMY:
            tool_examples[concept].append(tool)
    concepts = []
    for key in CONCEPT_TAXONOMY:
        concepts.append({
            "key": key,
            "name": key.replace("_", " ").title(),
            "story": WAR_STORIES.get(key, ""),
            "tools": sorted(tool_examples.get(key, []))[:8],
        })
    return render_template("taxonomy.html", concepts=concepts)


@app.route("/practice")
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
    return render_template("index.html",
                           concept_taxonomies={"data": CONCEPT_TAXONOMY, "ai": CONCEPT_TAXONOMY_AI, "fde": CONCEPT_TAXONOMY_FDE},
                           jd_context=jd_context,
                           jd_loaded=bool(jd))


@app.route("/onboarding")
def onboarding():
    return render_template("onboarding.html")


@app.route("/api/onboarding", methods=["POST"])
def save_onboarding():
    data = request.json or {}
    deadline = data.get("deadline", "").strip()
    strongest = data.get("strongest", "").strip()
    weakest = data.get("weakest", "").strip()
    if deadline:
        try:
            datetime.fromisoformat(deadline)
            PROGRESS["_deadline"] = {"date": deadline}
        except ValueError:
            pass
    PROGRESS["_onboarding"] = {"strongest": strongest, "weakest": weakest}
    save_progress()
    return jsonify({"ok": True})


def _ocr_with_stirling(file_bytes, filename):
    """Fallback OCR via a self-hosted Stirling-PDF instance (default http://localhost:8080).
    Activates only when STIRLING_PDF_URL is set (or default local instance is reachable) and
    pdfplumber returned no text (e.g. a scanned/image PDF). Returns extracted text or None.
    Fails silently — caller keeps using whatever it already had."""
    base = os.environ.get("STIRLING_PDF_URL", "http://localhost:8080").rstrip("/")
    if not base:
        return None
    try:
        resp = urllib.request.urlopen(
            f"{base}/api/v1/convert/pdf/ocr",
            data=file_bytes, timeout=60,
            headers={"Content-Type": "application/pdf"},
        )
        out = resp.read()
        # OCR endpoint returns a PDF; re-run pdfplumber on it to get text
        if pdfplumber and out:
            with pdfplumber.open(BytesIO(out)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            return text or None
    except Exception:
        return None
    return None


def _extract_text_from_resume(file_bytes, filename):
    """Extract plain text from a PDF or DOCX file. Falls back to Stirling-PDF OCR
    for scanned/image PDFs that pdfplumber can't read."""
    lower = filename.lower()
    if lower.endswith(".pdf") and pdfplumber:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        # empty => likely a scanned PDF; try OCR before giving up
        if not text.strip() and os.environ.get("STIRLING_PDF_URL", "http://localhost:8080"):
            ocr = _ocr_with_stirling(file_bytes, filename)
            if ocr:
                return ocr
        return text
    elif lower.endswith((".docx", ".doc")) and docx:
        doc = docx.Document(BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)
    elif lower.endswith(".txt"):
        return file_bytes.decode("utf-8", errors="replace")
    return None


def _call_json_extract(prompt, max_tokens=1800):
    """Call the LLM for a JSON-only extraction, with a truncation-safe retry.
    If the first response is cut off (finish_reason 'length'), retries once with a
    larger cap. Returns the cleaned response text, or None if both attempts fail."""
    def _clean(raw):
        if not raw:
            return None
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw).strip()
        if "{" not in raw or "}" not in raw:
            return None
        return raw

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.1,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = _clean(chat_content(resp))
        if raw:
            return raw
        # truncated or empty — retry once with a larger cap if it was length-limited
        if getattr(resp.choices[0], "finish_reason", None) == "length":
            resp2 = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens * 2,
                temperature=0.1,
                extra_body={"reasoning": {"enabled": False}},
            )
            raw2 = _clean(chat_content(resp2))
            if raw2:
                return raw2
        return None
    except Exception as e:
        print(f"[_call_json_extract] LLM error: {type(e).__name__}: {e}", flush=True)
        return None


def _clean_pdf_artifacts(text):
    """Strip PostScript character names (cid:xxx), ligature codes, and Unicode garbage
    that leak from PDF text extraction (e.g. '(cid:136)' for ⚠️)."""
    text = re.sub(r"\(cid:\d+\)", "", text)
    text = re.sub(r"\(cid\d+\)", "", text)
    text = re.sub(r"\(U\+[0-9A-Fa-f]{4,6}\)", "", text)
    text = re.sub(r"\(0x[0-9A-Fa-f]{2,4}\)", "", text)
    return text


_NON_TECH_SKILL_BLACKLIST = {
    "sam", "designed", "power", "questease", "programming", "compliance",
    "automated", "computer", "bachelor", "master", "university", "college",
    "school", "institute", "team", "leader", "leadership", "communication",
    "collaboration", "problem", "solving", "analytical", "detail", "oriented",
    "self", "motivated", "experience", "years", "year", "role", "position",
    "technologies", "tools", "systems", "solutions", "services", "platform",
    "platforms", "infrastructure", "environment", "environments",
    "development", "management", "operations", "production", "process",
    "processes", "projects", "project", "product", "products", "business",
    "stakeholders", "clients", "customers", "requirements", "specifications",
    "documentation", "standards", "methodologies", "approach", "data",
}


def _is_technical_skill(name):
    """Check if a skill name looks like a genuine technical skill, not a random word."""
    n = name.lower().strip()
    if len(n) <= 2:
        return False
    if n in _NON_TECH_SKILL_BLACKLIST:
        return False
    return True


def _extract_skills_from_resume(text):
    """Use LLM to extract structured skills, projects, and domain from resume text.
    Returns rich data including depth signals, project specificity, and skill context."""
    prompt = f"""Analyze this resume like a technical interviewer would. Extract structured information. Respond ONLY with a JSON object — no markdown, no commentary.

Resume text (truncated):
{text[:4000]}

Return exactly this JSON shape:
{{
  "target_role": "inferred target role e.g. 'data engineer', 'backend engineer', 'ML engineer' — be specific",
  "years_experience": "estimated years or null",
  "skills": [
    {{
      "name": "skill name — ONLY extract TECHNICAL skills: programming languages, frameworks, tools, platforms, databases, cloud services, libraries. IGNORE: soft skills, university names, company names, locations, personal names, degree names, generic terms like 'Engineering' or 'Bachelor'.",
      "depth": "deep | moderate | shallow — based on how it was used (built production system = deep, listed in skills section only = shallow)",
      "context": "where/how it was used (e.g. 'used in AdTech pipeline for 3B daily events') — be specific"
    }}
  ],
  "projects": [
    {{
      "name": "project name",
      "description": "what it does — be specific about scale, impact, technical choices",
      "tech": ["technologies used"],
      "specificity": "high | low — are the numbers/concrete details provided or is it vague?"
    }}
  ],
  "domains": ["application domains e.g. 'ad tech', 'healthcare', 'payments', 'distributed systems'"],
  "strongest_skills": ["top 3-5 technical skills based on depth and context"],
  "weakest_signals": ["skills with no project context — likely shallow"]
}}

Note: do NOT include interview questions/probes — those are generated on demand later.
Be strict about depth: "familiar with X" or just listing X = shallow. "Built Y using X processing Z events/day" = deep.
CRITICAL: ONLY extract genuine technical skills. Do not include company names, person names, university names, cities, or generic English words.
DO NOT extract these as skills: Sam, Designed, Power, Programming, Compliance, Automated, Computer, Data, Engineer, Team, Business, Systems, Solutions, Platforms, Infrastructure, Environment, Development, Management, Operations, Production, Process, Projects, Products, Services, Solutions.
DO extract these as skills: Apache Spark, Python, SQL, Docker, Kubernetes, Snowflake, dbt, Airflow, Terraform, AWS, GCP, Azure, Git, React, Node.js, Java, Scala, Go, Rust, MongoDB, PostgreSQL, Kafka, Spark Streaming."""

    raw = _call_json_extract(prompt, max_tokens=1800)
    if not raw:
        return None
    try:
        obj = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        skills = obj.get("skills", [])
        filtered = []
        for s in skills:
            name = s.get("name", "") if isinstance(s, dict) else str(s)
            if _is_technical_skill(name):
                filtered.append(s)
        projects = []
        for p in obj.get("projects", []):
            if isinstance(p, dict):
                p["name"] = _clean_pdf_artifacts(p.get("name", ""))
                p["description"] = _clean_pdf_artifacts(p.get("description", ""))
            projects.append(p)
        domains = [_clean_pdf_artifacts(d) for d in obj.get("domains", [])]
        return {
            "skills": filtered,
            "projects": projects,
            "domains": domains,
            "years_experience": obj.get("years_experience"),
            "target_role": obj.get("target_role"),
            "strongest_skills": obj.get("strongest_skills", []),
            "weakest_signals": obj.get("weakest_signals", []),
        }
    except Exception:
        return None


def _stamp_taxonomy(data):
    """Tag an extraction with the taxonomy version that produced it.
    Called at creation time so we can detect stale mappings later without
    re-calling the LLM."""
    if isinstance(data, dict):
        data["taxonomy_version"] = TAXONOMY_VERSION
    return data


# ponytail: CONCEPT_TAXONOMY (defined near the top of this file) is the shared vocabulary
# the JD extractor maps into. JD tool-keywords ("Kafka", "Flink") are intentionally
# translated to the UNDERLYING CONCEPT ("streaming paradigm") so matching against the
# resume happens via tool-to-concept mapping, not raw tool-keyword matching. Azure↔AWS↔GCP
# are treated
# as the same concept (cloud platform) — a translation, not a gap.
JD_CONCEPT_TRANSLATIONS = {
    "azure": "cloud_platform", "aws": "cloud_platform", "gcp": "cloud_platform",
    "google cloud": "cloud_platform", "cloud platform": "cloud_platform",
    "kafka": "streaming_paradigm", "flink": "streaming_paradigm",
    "spark streaming": "streaming_paradigm", "kinesis": "streaming_paradigm",
    "pyspark": "batch_paradigm", "spark": "batch_paradigm", "databricks": "batch_paradigm",
    "airflow": "orchestration", "luigi": "orchestration", "dagster": "orchestration",
    "terraform": "iac", "pulumi": "iac", "cloudformation": "iac",
    "dbt": "data_modeling", "snowflake": "warehouse", "bigquery": "warehouse",
    "redshift": "warehouse", "postgres": "sql_database", "mysql": "sql_database",
    "sql server": "sql_database", "t-sql": "sql_database",
    "iceberg": "storage_format", "delta lake": "storage_format", "parquet": "storage_format",
    "hive": "storage_format", "kubernetes": "container_orchestration", "docker": "containers",
}


def _extract_concepts_from_jd(text):
    """Use LLM to extract the JD at the CONCEPT level, not the tool-keyword level.
    Returns concepts (mapped to our taxonomy where possible), required capabilities,
    and the raw tool keywords (for the translation sidebar)."""
    concept_list = ", ".join(CONCEPT_TAXONOMY)
    prompt = f"""You are analyzing a job description for a technical interview coach. Extract what the role ACTUALLY requires at the CONCEPT level — not the literal tool names.

Job description (truncated):
{text[:4000]}

Our coaching taxonomy of data-engineering concepts (use these exact keys where they fit):
{concept_list}

Return ONLY this JSON — no markdown, no commentary:
{{
  "role_title": "the job title, be specific",
  "seniority": "junior | mid | senior | staff | principal",
  "domain": "the application domain (e.g. 'real-time recommendation', 'payments', 'adtech', 'healthcare')",
  "concepts_required": [
    {{
      "concept": "a concept key from the taxonomy above if it fits, else a short concept phrase (e.g. 'streaming_paradigm', 'batch_vs_stream_choice', 'partitioning_hot_key_skew', 'cloud_platform', 'ic_across_teams')",
      "evidence": "the JD phrase that implies this concept",
      "importance": "must_have | nice_to_have"
    }}
  ],
  "capabilities_required": [
    "broader capabilities the role needs that aren't single taxonomy concepts, e.g. 'design a real-time system from scratch', 'own a data platform end to end', 'translate batch experience to streaming' — 3 to 6 items"
  ],
  "tool_keywords": ["literal tools/services named in the JD, e.g. 'Kafka', 'AWS', 'Flink', 'Terraform' — preserved for the translation sidebar"],
  "signal_framing": "1-2 sentences on what kind of candidate this JD is really looking for (beyond the bullet list)"
}}

Critical: if the JD says 'Kafka' or 'Flink', the concept is 'streaming_paradigm' (not 'Kafka'). If it says 'AWS' or 'GCP', the concept is 'cloud_platform'. Batch tools (Spark, PySpark) map to 'batch_paradigm'. Think in paradigms and concepts, not brand names."""

    raw = _call_json_extract(prompt, max_tokens=1500)
    if not raw:
        return None
    try:
        obj = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        return {
            "role_title": obj.get("role_title", ""),
            "seniority": obj.get("seniority", ""),
            "domain": obj.get("domain", ""),
            "concepts_required": obj.get("concepts_required", []),
            "capabilities_required": obj.get("capabilities_required", []),
            "tool_keywords": obj.get("tool_keywords", []),
            "signal_framing": obj.get("signal_framing", ""),
        }
    except Exception:
        return None


def _fallback_extract_jd(text):
    """Basic regex-based JD extraction when the LLM is unavailable.
    Extracts role title, tool keywords, and concept-level guesses from raw text."""
    title = ""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for l in lines[:15]:
        l_clean = l.strip()
        if l_clean and len(l_clean) < 120 and not l_clean.startswith(("http", "About", "Job", "Location", "Salary", "Type", "Posted")):
            # likely a job title — first substantive short line
            if any(w in l_clean.lower() for w in ("engineer", "scientist", "architect", "developer", "manager", "intern", "analyst")):
                title = l_clean
                break
            elif "|" not in l_clean and "@" not in l_clean:
                title = l_clean
                break
    known_tools = set(JD_CONCEPT_TRANSLATIONS.keys())
    tool_keywords = []
    text_lower = text.lower()
    for tool in sorted(known_tools, key=len, reverse=True):
        if tool in text_lower and tool not in tool_keywords:
            tool_keywords.append(tool)
    concept_matches = {}
    for tool, concept in JD_CONCEPT_TRANSLATIONS.items():
        if tool in text_lower:
            concept_matches.setdefault(concept, []).append(tool)
    concepts_required = []
    for concept, tools in concept_matches.items():
        concepts_required.append({
            "concept": concept,
            "evidence": f"Mentions: {', '.join(tools[:3])}",
            "importance": "must_have",
        })
    return {
        "role_title": title or "Unknown Role",
        "seniority": "mid",
        "domain": "",
        "concepts_required": concepts_required,
        "capabilities_required": [],
        "tool_keywords": tool_keywords[:20],
        "signal_framing": "Extracted by fallback (no LLM available). Concepts are based on tool-name matching — less precise than AI extraction.",
    }


def _fallback_extract_resume(text):
    """Basic regex-based resume extraction when the LLM is unavailable.
    Extracts skill candidates, project-like paragraphs, and domain guesses."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # collect capitalized terms as skill candidates
    words = re.findall(r'\b[A-Z][a-z++#.]{1,}\b', text)
    skip = {"The", "This", "That", "With", "From", "They", "What", "When", "Where",
            "Also", "Have", "Has", "Had", "Our", "Your", "You", "We", "I", "It", "Its",
            "Not", "All", "Each", "Every", "Some", "Most", "Few", "Many", "Much",
            "More", "Less", "And", "But", "Or", "For", "Nor", "Yet", "So", "Both",
            "Either", "Neither", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
            "Email", "Phone", "Address", "City", "State"}
    skill_set = set()
    for w in words:
        wl = w.lower()
        if w in skip or len(w) < 3:
            continue
        if wl in skill_set:
            continue
        skill_set.add(wl)
    skills = [{"name": s.title(), "depth": "moderate", "context": ""} for s in list(skill_set)[:30]]
    projects = []
    for l in lines[10:40]:
        if len(l) > 60 and any(c in l for c in (".", ":", "—")):
            projects.append({
                "name": l.split("—")[0].split(":")[0].strip()[:60] or "Project",
                "description": l[:150],
                "tech": [],
                "specificity": "low",
            })
    return {
        "target_role": "Unknown",
        "years_experience": None,
        "skills": skills,
        "projects": projects[:5],
        "domains": [],
        "strongest_skills": [s["name"] for s in skills[:5]],
        "weakest_signals": [],
    }


def _extraction_fallback_chain(extract_fn, fallback_fn, text, label):
    """Try LLM extraction first, fall back to deterministic extraction on failure.
    Returns (data: dict | None, method: str)."""
    data = extract_fn(text)
    if data:
        return data, "llm"
    print(f"[{label}] LLM extraction failed — using fallback", flush=True)
    fb = fallback_fn(text)
    if fb:
        return fb, "fallback"
    print(f"[{label}] Fallback also failed — returning None", flush=True)
    return None, "none"


@app.route("/api/upload-jd", methods=["POST"])
def upload_jd():
    """Accept a PDF/DOCX/TXT job description, extract concepts via LLM, store in progress."""
    file = request.files.get("jd")
    if not file:
        return jsonify({"error": "no file uploaded"}), 400

    raw_bytes = file.read()
    if len(raw_bytes) > 5 * 1024 * 1024:
        return jsonify({"error": "file too large (max 5 MB)"}), 400

    text = _extract_text_from_resume(raw_bytes, file.filename or "jd.pdf")
    if not text or len(text.strip()) < 30:
        return jsonify({"error": "could not extract text — try a different file format"}), 400
    text = _clean_pdf_artifacts(text)

    jd_data, method = _extraction_fallback_chain(
        _extract_concepts_from_jd, _fallback_extract_jd, text, "JD")
    if not jd_data:
        return jsonify({"error": "could not parse JD — try again"}), 500

    jd_data["raw_text_preview"] = text[:300]
    jd_data["raw_text"] = text[:5000]
    jd_data["uploaded_at"] = datetime.now().isoformat()
    jd_data["filename"] = file.filename
    jd_data["_extraction_method"] = method
    _stamp_taxonomy(jd_data)
    PROGRESS["_jd"] = jd_data
    save_progress()
    return jsonify({"ok": True, "role_title": jd_data.get("role_title"),
                    "seniority": jd_data.get("seniority"),
                    "domain": jd_data.get("domain"),
                    "concepts_required": len(jd_data.get("concepts_required", [])),
                    "tool_keywords": jd_data.get("tool_keywords", [])})


@app.route("/api/jd", methods=["GET"])
def get_jd():
    """Return stored JD concept data or empty."""
    return jsonify(PROGRESS.get("_jd", {}))


@app.route("/api/set-profile", methods=["POST"])
def set_profile():
    """Generate a synthetic JD profile from role + industry + cloud via direct LLM prompt."""
    data = request.json or {}
    role = (data.get("role") or "").strip()
    industry = (data.get("industry") or "").strip()
    cloud = (data.get("cloud") or "").strip()
    if not role:
        return jsonify({"error": "Role is required"}), 400
    resume = PROGRESS.get("_resume")
    resume_text = (resume or {}).get("raw_text", "")
    concept_list = ", ".join(CONCEPT_TAXONOMY)
    prompt = f"""You are a technical interview coach. A user wants to practice for a target role.

Target role: {role}
{f'Industry: {industry}' if industry else ''}
{f'Cloud platform: {cloud}' if cloud else ''}

Based on this profile, generate a Job-Description-like analysis using our concept taxonomy:
{concept_list}

Your job: think about what concepts a {role} {f'in {industry} ' if industry else ''}would actually need to know {f'on {cloud}' if cloud else ''}. Be specific and thorough — list 5-10 concepts.

Return ONLY this JSON — no markdown:
{{
  "role_title": "precise role title",
  "seniority": "senior | mid | junior | staff",
  "domain": "industry or 'general'",
  "concepts_required": [
    {{"concept": "concept_key_from_taxonomy", "evidence": "why this concept matters for this role profile", "importance": "must_have"}}
  ],
  "tool_keywords": ["cloud platform tools", "relevant tech for this profile"],
  "signal_framing": "one sentence on what this profile demands"
}}"""
    raw = _call_json_extract(prompt, max_tokens=1200)
    if not raw:
        return jsonify({"error": "could not generate profile — try again"}), 500
    try:
        obj = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception:
        return jsonify({"error": "could not parse profile — try again"}), 500
    jd_data = {
        "role_title": obj.get("role_title", role),
        "seniority": obj.get("seniority", "mid"),
        "domain": obj.get("domain", industry or "general"),
        "concepts_required": obj.get("concepts_required", []),
        "capabilities_required": [],
        "tool_keywords": obj.get("tool_keywords", []),
        "signal_framing": obj.get("signal_framing", f"Profile for {role}."),
        "synthetic": True,
        "raw_text_preview": role[:300],
        "raw_text": role,
        "uploaded_at": datetime.now().isoformat(),
        "filename": "profile",
        "_extraction_method": "llm",
    }
    _stamp_taxonomy(jd_data)
    PROGRESS["_jd"] = jd_data
    save_progress()
    return jsonify({"ok": True, "role_title": jd_data.get("role_title"),
                    "concepts_required": len(jd_data.get("concepts_required", [])),
                    "synthetic": True})


@app.route("/api/upload-jd-text", methods=["POST"])
def upload_jd_text():
    """Accept raw JD text (pasted), extract concepts via LLM, store in progress."""
    data = request.json or {}
    text = (data.get("text") or "").strip()
    if not text or len(text) < 30:
        return jsonify({"error": "JD text too short — paste at least a paragraph"}), 400

    jd_data, method = _extraction_fallback_chain(
        _extract_concepts_from_jd, _fallback_extract_jd, text, "JD-text")
    if not jd_data:
        return jsonify({"error": "could not parse JD — try again"}), 500

    jd_data["raw_text_preview"] = text[:300]
    jd_data["raw_text"] = text[:5000]
    jd_data["uploaded_at"] = datetime.now().isoformat()
    jd_data["filename"] = "pasted"
    jd_data["_extraction_method"] = method
    _stamp_taxonomy(jd_data)
    PROGRESS["_jd"] = jd_data
    save_progress()
    return jsonify({"ok": True, "role_title": jd_data.get("role_title"),
                    "seniority": jd_data.get("seniority"),
                    "domain": jd_data.get("domain"),
                    "concepts_required": len(jd_data.get("concepts_required", [])),
                    "tool_keywords": jd_data.get("tool_keywords", [])})


@app.route("/api/upload-resume", methods=["POST"])
def upload_resume():
    """Accept a PDF/DOCX/TXT resume, extract text, pull skills via LLM, store in progress."""
    file = request.files.get("resume")
    if not file:
        return jsonify({"error": "no file uploaded"}), 400

    raw_bytes = file.read()
    if len(raw_bytes) > 5 * 1024 * 1024:
        return jsonify({"error": "file too large (max 5 MB)"}), 400

    text = _extract_text_from_resume(raw_bytes, file.filename or "resume.pdf")
    if not text or len(text.strip()) < 50:
        return jsonify({"error": "could not extract text — try a different file format"}), 400
    text = _clean_pdf_artifacts(text)

    skills_data, method = _extraction_fallback_chain(
        _extract_skills_from_resume, _fallback_extract_resume, text, "resume")
    if not skills_data:
        return jsonify({"error": "could not parse resume — try again"}), 500

    skills_data["raw_text_preview"] = text[:500]
    skills_data["raw_text"] = text[:5000]
    skills_data["uploaded_at"] = datetime.now().isoformat()
    skills_data["filename"] = file.filename
    skills_data["_extraction_method"] = method
    _stamp_taxonomy(skills_data)
    PROGRESS["_resume"] = skills_data
    save_progress()
    # build summary for response
    skill_names = [s.get("name", s) if isinstance(s, dict) else s for s in skills_data.get("skills", [])]
    return jsonify({"ok": True, "skills": skill_names, "domains": skills_data.get("domains", []),
                     "projects_count": len(skills_data.get("projects", [])),
                     "target_role": skills_data.get("target_role"),
                     "strongest_skills": skills_data.get("strongest_skills", [])})


@app.route("/api/resume", methods=["GET"])
def get_resume():
    """Return stored resume data (skills, projects, domains) or empty."""
    return jsonify(PROGRESS.get("_resume", {}))


@app.route("/api/gap-alert", methods=["GET"])
def gap_alert():
    """Compare resume-claimed skills against actual performance data.
    Returns a list of gaps: claimed skill with low or no accuracy."""
    resume = PROGRESS.get("_resume")
    if not resume:
        return jsonify({"gaps": [], "resume_loaded": False})

    claimed_skills = [s.lower() for s in resume.get("skills", [])]
    claimed_domains = [d.lower() for d in resume.get("domains", [])]
    all_claims = claimed_skills + claimed_domains

    # build accuracy per topic from HISTORY
    topic_stats = {}  # topic -> {"total": N, "passed": N}
    for h in HISTORY:
        if h.get("event") == "submit":
            t = h.get("topic")
            if t:
                if t not in topic_stats:
                    topic_stats[t] = {"total": 0, "passed": 0}
                topic_stats[t]["total"] += 1
                if h.get("passed"):
                    topic_stats[t]["passed"] += 1

    # match claimed skills to topics
    gaps = []
    for claim in all_claims:
        best_match = None
        best_score = 0
        for topic in topic_stats:
            # fuzzy match: claim appears in topic or topic appears in claim
            if claim in topic or topic in claim:
                best_match = topic
                best_score = 1.0
            elif any(w in topic for w in claim.split() if len(w) > 3):
                score = sum(1 for w in claim.split() if w in topic and len(w) > 3) / max(1, len(claim.split()))
                if score > best_score:
                    best_match = topic
                    best_score = score

        if best_match and best_score > 0.3:
            stats = topic_stats[best_match]
            pct = round(100 * stats["passed"] / stats["total"]) if stats["total"] > 0 else 0
            if pct < 70:
                gaps.append({"claimed": claim, "topic": best_match, "accuracy": pct,
                             "attempts": stats["total"], "severity": "high" if pct < 40 else "medium"})
        elif not best_match:
            # claimed skill with zero practice attempts
            gaps.append({"claimed": claim, "topic": None, "accuracy": 0,
                         "attempts": 0, "severity": "high"})

    # sort: high severity first, then by accuracy ascending
    gaps.sort(key=lambda g: (0 if g["severity"] == "high" else 1, g["accuracy"]))
    return jsonify({"gaps": gaps[:10], "resume_loaded": True,
                     "claimed_skills": resume.get("skills", []),
                     "claimed_domains": resume.get("domains", [])})


@app.route("/api/talk-about", methods=["POST"])
def talk_about():
    """Generate interview follow-up questions for a resume project.
    Uses rich project data from resume extraction (specificity, interview probes)."""
    data = request.json
    project_name = data.get("project_name", "")
    project_tech = data.get("tech", [])
    project_desc = data.get("one_liner", "")

    resume = PROGRESS.get("_resume", {})
    projects = resume.get("projects", [])
    project = next((p for p in projects if p.get("name") == project_name), None)

    project_name_used = project_name
    project_desc_used = project_desc
    project_tech_used = project_tech
    specificity = "unknown"

    if project:
        project_name_used = project.get("name", project_name)
        project_tech_used = project.get("tech", project_tech)
        project_desc_used = project.get("description", project.get("one_liner", project_desc))
        specificity = project.get("specificity", "unknown")

    tech_str = ", ".join(project_tech_used) if project_tech_used else "their stack"
    specificity_note = ""
    if specificity == "low":
        specificity_note = "\n\nNote: This project description is vague. Include a question that probes for specifics (scale, numbers, challenges) — interviewers will."

    target_role = resume.get("target_role", "")
    role_note = ""
    if target_role:
        role_note = f"\n\nThe candidate is targeting a {target_role} role. Frame at least one question around architectural decisions relevant to that role."

    prompt = f"""You are a senior interviewer drilling a candidate on a project from their resume.

Project: {project_name_used}
Description: {project_desc_used}
Technologies: {tech_str}
Description specificity: {specificity}
{specificity_note}{role_note}

Generate 5 interview follow-up questions that a real interviewer would ask.
Mix depths:
1. Warm-up — "tell me about this project"
2. Technical deep-dive — probe a specific technology choice
3. Challenge — "what was the hardest part?"
4. Scale/impact — probe numbers or scale
5. Reflection — "what would you change?"

Make questions SPECIFIC to this project — not generic "tell me about a time when..."

Respond ONLY with JSON — no markdown, no commentary:
{{"questions": ["q1", "q2", "q3", "q4", "q5"], "vague_description": true/false}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.4,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        if not raw:
            return jsonify({"error": "model returned empty response"}), 502
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw).strip()
        obj = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        questions = obj.get("questions", [])
        if not questions:
            return jsonify({"error": "no questions generated"}), 502
        return jsonify({
            "questions": questions,
            "project": project_name_used,
            "vague_description": obj.get("vague_description", False),
            "specificity": specificity,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/study-plan", methods=["GET"])
def study_plan():
    """Generate a personalized study plan based on resume + performance data."""
    resume = PROGRESS.get("_resume")
    if not resume:
        return jsonify({"plan": [], "resume_loaded": False})

    target_role = resume.get("target_role", "software engineer")
    strongest = resume.get("strongest_skills", [])[:5]
    weakest = resume.get("weakest_signals", [])[:5]

    # get accuracy per topic
    topic_stats = {}
    for h in HISTORY:
        if h.get("event") == "submit":
            t = h.get("topic")
            if t:
                if t not in topic_stats:
                    topic_stats[t] = {"total": 0, "passed": 0}
                topic_stats[t]["total"] += 1
                if h.get("passed"):
                    topic_stats[t]["passed"] += 1

    # build practice summary
    practice_lines = []
    for topic, stats in sorted(topic_stats.items(), key=lambda x: x[1]["total"], reverse=True):
        pct = round(100 * stats["passed"] / stats["total"]) if stats["total"] > 0 else 0
        practice_lines.append(f"  - {topic}: {pct}% accuracy ({stats['total']} attempts)")

    # find unsolved questions by category
    unsolved_sql = sum(1 for q in QUESTIONS.values() if q["lang"] == "sql" and not is_solved(q["id"]))
    unsolved_py = sum(1 for q in QUESTIONS.values() if q["lang"] == "python" and not is_solved(q["id"]))
    unsolved_design = sum(1 for q in QUESTIONS.values() if q["lang"] == "design" and not is_solved(q["id"]))
    due = sum(1 for qid in PROGRESS if is_due(qid))

    # deadline info
    deadline_info = ""
    deadline = PROGRESS.get("_deadline")
    if isinstance(deadline, dict) and deadline.get("date"):
        days_left = (datetime.fromisoformat(deadline["date"]) - datetime.now()).days
        deadline_info = f"\nInterview in {days_left} days."

    practice_summary = "\n".join(practice_lines) if practice_lines else "  No practice data yet."

    prompt = f"""You are a technical interview coach creating a personalized weekly study plan.

Candidate profile:
- Target role: {target_role}
- Strongest skills (from resume): {', '.join(strongest) if strongest else 'unknown'}
- Skills needing validation (shallow/no context): {', '.join(weakest) if weakest else 'unknown'}
- Resume domains: {', '.join(resume.get('domains', [])[:5])}

Current practice performance:
{practice_summary}

Remaining questions: {unsolved_sql} SQL, {unsolved_py} Python, {unsolved_design} design
Due for review: {due}{deadline_info}

Create a focused 5-item study plan. Each item should be:
- Specific (not "practice SQL" but "practice SQL window functions — you claim SQL expertise")
- Actionable (point to what to do, not what to read)
- Prioritized (most impactful first)

Respond ONLY with JSON — no markdown, no commentary:
{{"plan_items": [{{"title": "short title", "action": "what to do — 1-2 sentences", "priority": "high|medium|low", "category": "sql|python|design|behavioral"}}]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        if not raw:
            return jsonify({"plan": [], "resume_loaded": True})
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw).strip()
        obj = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        items = obj.get("plan_items", [])
        return jsonify({"plan": items[:5], "resume_loaded": True,
                         "target_role": target_role})
    except Exception:
        return jsonify({"plan": [], "resume_loaded": True, "target_role": target_role})


@app.route("/api/claim-validation", methods=["GET"])
def claim_validation():
    """Track which resume claims have been validated by practice performance."""
    resume = PROGRESS.get("_resume")
    if not resume:
        return jsonify({"validated": [], "unvalidated": [], "resume_loaded": False})

    raw_skills = resume.get("skills", [])
    skill_entries = []
    for s in raw_skills:
        if isinstance(s, dict):
            skill_entries.append(s)
        else:
            skill_entries.append({"name": s, "depth": "moderate", "context": ""})

    # build accuracy per topic
    topic_stats = {}
    for h in HISTORY:
        if h.get("event") == "submit":
            t = h.get("topic")
            if t:
                if t not in topic_stats:
                    topic_stats[t] = {"total": 0, "passed": 0}
                topic_stats[t]["total"] += 1
                if h.get("passed"):
                    topic_stats[t]["passed"] += 1

    validated = []
    unvalidated = []
    for entry in skill_entries:
        name = entry.get("name", "")
        best_match = None
        for topic in topic_stats:
            if name.lower() in topic or topic in name.lower():
                best_match = topic
                break
            elif any(w in topic for w in name.lower().split() if len(w) > 3):
                best_match = topic
                break

        if best_match:
            stats = topic_stats[best_match]
            pct = round(100 * stats["passed"] / stats["total"]) if stats["total"] > 0 else 0
            validated.append({
                "skill": name, "accuracy": pct, "attempts": stats["total"],
                "depth": entry.get("depth", "moderate"),
                "strong": pct >= 70,
            })
        else:
            unvalidated.append({
                "skill": name, "depth": entry.get("depth", "moderate"),
                "context": entry.get("context", ""),
            })

    validated.sort(key=lambda v: (-v["strong"], -v["accuracy"]))
    unvalidated.sort(key=lambda u: 0 if u["depth"] == "deep" else 1)

    return jsonify({
        "validated": validated,
        "unvalidated": unvalidated[:15],
        "resume_loaded": True,
        "total_skills": len(skill_entries),
        "validated_count": len([v for v in validated if v["strong"]]),
    })


def _resume_concept_evidence():
    """Flatten the resume into a concept-evidence string the JD matcher can scan.
    Pulls skill names, depths, contexts, project descriptions, tech, and domains so a
    concept like 'streaming_paradigm' can be detected from a project narrative even if
    the word 'streaming' never appears literally."""
    resume = PROGRESS.get("_resume")
    if not resume:
        return "", []
    parts = []
    evidence_skills = []
    for s in resume.get("skills", []):
        if isinstance(s, dict):
            parts.append(f"skill: {s.get('name','')} ({s.get('depth','moderate')}) — {s.get('context','')}")
            evidence_skills.append(s.get("name", "").lower())
        else:
            parts.append(f"skill: {s}")
            evidence_skills.append(str(s).lower())
    for p in resume.get("projects", []):
        desc = p.get("description", p.get("one_liner", ""))
        tech = ", ".join(p.get("tech", []))
        parts.append(f"project: {p.get('name','')} — {desc} (tech: {tech})")
    for d in resume.get("domains", []):
        parts.append(f"domain: {d}")
    return "\n".join(parts), evidence_skills


# ponytail: the JD extractor may emit either a taxonomy key OR a plain-English phrase.
# Normalize both to the canonical taxonomy key so the matcher's heuristics line up.
# This is deterministic string mapping — no LLM involvement, so no hallucination risk here.
CONCEPT_NORMALIZATION = {
    "streaming": "streaming_paradigm", "streaming paradigm": "streaming_paradigm",
    "stream processing": "streaming_paradigm", "real-time": "streaming_paradigm",
    "real time": "streaming_paradigm", "realtime": "streaming_paradigm",
    "streaming paradigm": "streaming_paradigm", "kafka": "streaming_paradigm",
    "flink": "streaming_paradigm", "kinesis": "streaming_paradigm",
    "event streaming": "streaming_paradigm", "pub/sub": "streaming_paradigm",
    "batch": "batch_paradigm", "batch processing": "batch_paradigm",
    "batch paradigm": "batch_paradigm", "etl": "batch_paradigm",
    "pyspark": "batch_paradigm", "spark": "batch_paradigm", "dataproc": "batch_paradigm",
    "cloud": "cloud_platform", "cloud platform": "cloud_platform",
    "cloud provider": "cloud_platform", "azure": "cloud_platform",
    "aws": "cloud_platform", "gcp": "cloud_platform", "google cloud": "cloud_platform",
    "databricks": "cloud_platform",
    "partitioning": "partitioning_hot_key_skew", "hot key": "partitioning_hot_key_skew",
    "skew": "partitioning_hot_key_skew", "data skew": "partitioning_hot_key_skew",
    "idempotency": "idempotency_dedup", "dedup": "idempotency_dedup",
    "idempotent": "idempotency_dedup", "exactly once": "idempotency_dedup",
    "backfill": "backfill_reprocessing", "reprocessing": "backfill_reprocessing",
    "replay": "backfill_reprocessing", "reprocess": "backfill_reprocessing",
    "schema evolution": "schema_evolution_compat",
    "watermark": "late_data_watermarks", "late data": "late_data_watermarks",
    "late arrival": "late_data_watermarks", "event time": "late_data_watermarks",
    "data quality": "data_quality_observability", "observability": "data_quality_observability",
    "monitoring": "data_quality_observability", "data validation": "data_quality_observability",
    "storage format": "storage_format_choice", "file format": "storage_format_choice",
    "replication": "replication_consistency", "consistency": "replication_consistency",
    "failover": "replication_consistency", "stakeholder": "domain_alignment",
    "requirements gathering": "clarifying_requirements", "clarifying": "clarifying_requirements",
    "scoping": "clarifying_requirements", "orchestration": "orchestration",
    "scheduler": "orchestration", "iac": "iac", "infrastructure as code": "iac",
    "data modeling": "data_modeling", "modeling": "data_modeling",
    "warehouse": "warehouse", "snowflake": "warehouse", "bigquery": "warehouse",
    "redshift": "warehouse", "sql": "sql_database", "relational": "sql_database",
    "kubernetes": "container_orchestration", "k8s": "container_orchestration",
    "eks": "container_orchestration", "aks": "container_orchestration",
    "gke": "container_orchestration", "containers": "containers",
    "grain": "grain_awareness", "star schema": "grain_awareness",
    "scd": "scd_strategy", "slowly changing": "scd_strategy",
    "entity": "entity_enumeration", "dimension": "missing_dimension_audit",
    "feature store": "feature_store", "feature serving": "feature_store",
    "low-latency serving": "feature_store", "ml platform": "feature_store",
}


def _normalize_concept(concept):
    """Map a JD concept (taxonomy key OR plain-English phrase) to a canonical key.
    Falls back to the lowercased, underscored form so unknown concepts still flow through."""
    if not concept:
        return ""
    c = concept.strip().lower()
    if c in CONCEPT_NORMALIZATION:
        return CONCEPT_NORMALIZATION[c]
    # try the underscored version (e.g. 'streaming_paradigm' passes through untouched)
    underscored = c.replace(" ", "_")
    if underscored in CONCEPT_NORMALIZATION:
        return CONCEPT_NORMALIZATION[underscored]
    # try substring match against known phrases (handles 'real-time processing' etc.)
    for phrase, key in CONCEPT_NORMALIZATION.items():
        if phrase in c:
            return key
    return underscored


def _concept_is_present(concept, evidence_text, evidence_skills):
    """Heuristic: is this JD concept evidenced in the resume?
    Returns (present: bool, confidence: 'high'|'medium'|'low').
    Conservative by design: requires STRONG signals for easy-to-false-positive concepts
    (streaming must show streaming tooling, not just the word 'event' in a batch context)."""
    concept_l = concept.lower().replace("_", " ")
    hay = evidence_text.lower()

    # STRONG (tool-level) signals — high confidence when present
    strong = {
        "streaming_paradigm": ["kafka", "flink", "kinesis", "spark streaming", "pub/sub",
                               "streaming pipeline", "real-time pipeline", "stream processor"],
        "batch_paradigm": ["batch", "pyspark", "spark", "etl", "dataproc", "scheduled job",
                           "daily job", "hourly job", "airflow"],
        "cloud_platform": ["azure", "aws", "gcp", "databricks", "s3", "blob", "cloud"],
        "idempotency_dedup": ["idempot", "dedup", "exactly-once", "exactly once", "deduplicate"],
        "backfill_reprocessing": ["backfill", "reprocess", "replay", "recompute"],
        "late_data_watermarks": ["watermark", "late arrival", "late data", "event time", "windowed"],
        "schema_evolution_compat": ["schema evolution", "schema contract", "avro", "versioned schema"],
        "partitioning_hot_key_skew": ["partition skew", "hot key", "data skew", "repartition"],
        "replication_consistency": ["replication", "failover", "leader", "replica"],
        "storage_format_choice": ["parquet", "iceberg", "delta lake", "orc", "columnar"],
        "data_quality_observability": ["data quality", "data validation", "monitoring", "observability"],
        "orchestration": ["airflow", "dagster", "luigi", "orchestrat"],
        "iac": ["terraform", "pulumi", "cloudformation"],
        "warehouse": ["snowflake", "bigquery", "redshift"],
        "sql_database": ["postgres", "mysql", "t-sql", "sql server", "relational"],
        "container_orchestration": ["kubernetes", "k8s", "eks", "aks", "gke"],
        "containers": ["docker", "container", "podman"],
        "grain_awareness": ["grain", "star schema", "fact table"],
        "scd_strategy": ["scd", "slowly changing", "type 2"],
        "entity_enumeration": ["dimension", "fact table", "entity model"],
        "missing_dimension_audit": ["dimension", "data mart", "modeling audit"],
        "feature_store": ["feature store", "feature serving", "low-latency serving", "ml platform",
                          "feature development", "feature reuse"],
    }
    # WEAK (fuzzy) signals — medium/low confidence, prone to false positives, so gated
    weak = {
        "streaming_paradigm": [("real-time", "low"), ("realtime", "low"), ("event stream", "medium")],
        "batch_vs_stream_choice": [("batch", "medium"), ("stream", "low"), ("latency", "low"), ("sla", "low")],
        "late_data_watermarks": [("window", "low"), ("event time", "low")],
        "domain_alignment": [("stakeholder", "medium"), ("requirements", "medium"), ("business", "low"), ("alignment", "low")],
        "clarifying_requirements": [("requirement", "medium"), ("scope", "low"), ("clarif", "low")],
        "data_modeling": [("modeling", "low"), ("warehouse", "low")],
    }

    for s in strong.get(concept, []):
        if s and s in hay:
            return True, "high"
    # weak signals only count if no strong signal matched, and they're explicitly lower confidence
    for w, conf in weak.get(concept, []):
        if w and w in hay:
            return True, conf
    return False, "none"


def _compute_concept_match():
    """Tool-to-concept gap analysis: map JD required concepts against resume evidence.
    Returns real gaps (concept not evidenced) vs translations (tool differs but concept
    is present, e.g. Azure→AWS) vs covered. This is the core of the JD feature."""
    jd = PROGRESS.get("_jd")
    resume = PROGRESS.get("_resume")
    if not jd:
        return {"jd_loaded": False, "resume_loaded": bool(resume), "real_gaps": [],
                "translations": [], "covered": [],
                "real_gap_count": 0, "translation_count": 0, "covered_count": 0,
                "verify_count": 0, "self_reported_count": 0}
    if not resume:
        # JD loaded but no resume — report every required concept as unverifiable
        real_gaps = [{"concept": c.get("concept"), "evidence": c.get("evidence", ""),
                       "importance": c.get("importance", "must_have")}
                      for c in jd.get("concepts_required", [])]
        return {"jd_loaded": True, "resume_loaded": False,
                "real_gaps": real_gaps, "translations": [], "covered": [],
                "verify": [], "self_reported": [],
                "real_gap_count": len(real_gaps), "translation_count": 0, "covered_count": 0,
                "verify_count": 0, "self_reported_count": 0}

    evidence_text, evidence_skills = _resume_concept_evidence()

    # build a set of tool keywords the resume has, for translation detection
    resume_tool_set = set()
    for s in resume.get("skills", []):
        if isinstance(s, dict):
            resume_tool_set.add(s.get("name", "").lower())
    for p in resume.get("projects", []):
        for t in p.get("tech", []):
            resume_tool_set.add(t.lower())

    jd_tool_set = set(t.lower() for t in jd.get("tool_keywords", []))

    # user self-attestations: concepts the candidate confirmed they've handled even
    # though the resume didn't evidence them. Treated as self-reported coverage (not
    # proven), so they leave the "real gaps" list but stay distinct from validated skills.
    user_confirmed = set(jd.get("user_confirmed", []))

    # ponytail: the JD extractor sometimes parks the single most important theme
    # (e.g. "feature store") in free-text capabilities_required instead of concepts_required.
    # Scan capability text for known concept keywords so LLM under-extraction doesn't
    # silently drop a must-have concept from the analysis.
    CAPABILITY_CONCEPT_KEYWORDS = {
        "feature_store": ["feature store", "feature serving", "feature development",
                          "feature reuse", "feature freshness", "feature infrastructure",
                          "low-latency feature", "real-time feature"],
        "streaming_paradigm": ["real-time", "streaming", "event stream", "kafka", "flink"],
        "cloud_platform": ["cloud platform", "multi-cloud", "aws", "gcp", "azure"],
        "data_quality_observability": ["data quality", "monitoring", "data contracts",
                                       "quality checks", "pipeline reliability"],
        "iac": ["infrastructure as code", "terraform", "ci/cd", "deployment framework"],
        "orchestration": ["orchestrat", "scheduler", "pipelines"],
    }
    concepts_required = list(jd.get("concepts_required", []))
    cap_text = " ".join(jd.get("capabilities_required", [])).lower()
    seen_concepts = {_normalize_concept(c.get("concept", "")) for c in concepts_required}

    # The JD extractor sometimes parks a cloud-platform brand (aws/azure/gcp) only in
    # tool_keywords and never emits the 'cloud_platform' concept. Without that concept,
    # the Azure->AWS translation never fires even when the resume shows a sibling cloud.
    # Synthesize the concept from tool_keywords so the translation path is reachable.
    CLOUD_TOOL_KEYWORDS = ["aws", "azure", "gcp", "google cloud", "databricks", "cloud platform", "cloud"]
    if "cloud_platform" not in seen_concepts and any(
            kw in jd_tool_set for kw in CLOUD_TOOL_KEYWORDS):
        cloud_evidence = next((t for t in jd.get("tool_keywords", [])
                               if t.lower() in CLOUD_TOOL_KEYWORDS), "cloud platform")
        concepts_required.append({"concept": "cloud_platform", "evidence": cloud_evidence,
                                  "importance": "must_have", "from_tool_keyword": True})

    for concept_key, kws in CAPABILITY_CONCEPT_KEYWORDS.items():
        if concept_key in seen_concepts:
            continue
        if any(kw in cap_text for kw in kws):
            # pull the matching capability phrase as evidence
            evidence = next((cap for cap in jd.get("capabilities_required", [])
                             if any(kw in cap.lower() for kw in kws)), cap_text[:80])
            concepts_required.append({"concept": concept_key, "evidence": evidence,
                                      "importance": "must_have", "from_capability": True})

    real_gaps = []
    translations = []
    covered = []
    verify = []  # low-confidence "present" matches the candidate should double-check
    self_reported = []  # user confirmed they've done it, but resume didn't evidence it

    for c in concepts_required:
        raw_concept = c.get("concept", "")
        concept = _normalize_concept(raw_concept)
        # user self-attestation overrides the gap — moves to self-reported, not proven
        if concept in user_confirmed:
            self_reported.append({"concept": concept, "raw": raw_concept,
                                  "evidence": c.get("evidence", ""),
                                  "importance": c.get("importance", "must_have")})
            continue
        present, confidence = _concept_is_present(concept, evidence_text, evidence_skills)
        if present:
            if confidence == "low":
                # don't assert coverage — surface for manual verification
                verify.append({"concept": concept, "raw": raw_concept,
                               "evidence": c.get("evidence", ""),
                               "importance": c.get("importance", "must_have"),
                               "note": "Weak signal in resume — verify you've actually done this."})
            else:
                entry = {"concept": concept, "raw": raw_concept,
                         "evidence": c.get("evidence", ""),
                         "importance": c.get("importance", "must_have"),
                         "confidence": confidence}
                # if the JD names a different cloud brand than the resume, attach a
                # translation note so the candidate can frame Azure<->AWS equivalence
                if concept == "cloud_platform":
                    jd_tool = _translation_source(concept, jd_tool_set)
                    sibling = _find_translation_sibling(concept, resume_tool_set)
                    if jd_tool and sibling and jd_tool != sibling:
                        entry["translation_note"] = (
                            f"JD mentions {jd_tool}; your resume shows {sibling} — "
                            f"same concept (cloud platform), a translation not a gap.")
                covered.append(entry)
            continue
        # not directly evidenced — check if it's a tool translation
        jd_tool = _translation_source(concept, jd_tool_set)
        if jd_tool and resume_tool_set:
            # does the resume have a sibling tool in the same concept family?
            sibling = _find_translation_sibling(concept, resume_tool_set)
            if sibling:
                translations.append({
                    "concept": concept, "raw": raw_concept,
                    "jd_tool": jd_tool,
                    "your_tool": sibling,
                    "message": f"You have {sibling}; {jd_tool} is the same concept ({concept.replace('_',' ')}) — a translation, not a gap.",
                    "importance": c.get("importance", "must_have"),
                })
                continue
        real_gaps.append({"concept": concept, "raw": raw_concept, "evidence": c.get("evidence", ""),
                           "importance": c.get("importance", "must_have")})

    # sort so must_have gaps lead, and surface capability-derived gaps (e.g. feature_store)
    # before the longer concepts_required list so they aren't sliced off the end
    real_gaps.sort(key=lambda g: (0 if g["importance"] == "must_have" else 1,
                                   0 if g.get("from_capability") else 1))
    # flag stale taxonomy: if either extraction predates the current taxonomy
    # version, the concept mappings may be out of date. Matching still runs on
    # the stored data, but the dashboard can prompt a re-parse.
    stale = (jd.get("taxonomy_version") != TAXONOMY_VERSION
             or resume.get("taxonomy_version") != TAXONOMY_VERSION)
    return {
        "jd_loaded": True,
        "resume_loaded": True,
        "taxonomy_stale": stale,
        "role_title": jd.get("role_title"),
        "seniority": jd.get("seniority"),
        "domain": jd.get("domain"),
        "capabilities_required": jd.get("capabilities_required", []),
        "signal_framing": jd.get("signal_framing", ""),
        "real_gaps": real_gaps[:12],
        "translations": translations[:8],
        "covered": covered[:8],
        "verify": verify[:8],
        "self_reported": self_reported[:12],
        "real_gap_count": len(real_gaps),
        "translation_count": len(translations),
        "covered_count": len(covered),
        "verify_count": len(verify),
        "self_reported_count": len(self_reported),
    }


def _translation_source(concept, jd_tool_set):
    """Given a concept, return the JD tool keyword that implies it (for the sidebar)."""
    concept_to_tool = {
        "streaming_paradigm": ["kafka", "flink", "kinesis", "spark streaming"],
        "cloud_platform": ["aws", "azure", "gcp", "google cloud"],
        "batch_paradigm": ["spark", "pyspark", "databricks"],
        "orchestration": ["airflow", "dagster", "luigi"],
        "iac": ["terraform", "pulumi", "cloudformation"],
        "warehouse": ["snowflake", "bigquery", "redshift"],
        "sql_database": ["postgres", "mysql", "sql server", "t-sql"],
        "container_orchestration": ["kubernetes", "k8s", "eks", "aks"],
        "containers": ["docker"],
        "storage_format": ["iceberg", "delta lake", "parquet", "hive"],
    }
    for t in concept_to_tool.get(concept, []):
        if t in jd_tool_set:
            return t
    return None


def _find_translation_sibling(concept, resume_tool_set):
    """Given a concept and the resume's tool set, find a sibling tool in the same family."""
    families = {
        "streaming_paradigm": ["kafka", "flink", "kinesis", "spark streaming", "pubsub"],
        "cloud_platform": ["aws", "azure", "gcp", "google cloud", "databricks"],
        "batch_paradigm": ["spark", "pyspark", "databricks", "hadoop"],
        "orchestration": ["airflow", "dagster", "luigi", "prefect"],
        "iac": ["terraform", "pulumi", "cloudformation"],
        "warehouse": ["snowflake", "bigquery", "redshift", "databricks"],
        "sql_database": ["postgres", "mysql", "sql server", "t-sql", "oracle"],
        "container_orchestration": ["kubernetes", "k8s", "eks", "aks", "gke"],
        "containers": ["docker", "podman", "containerd"],
        "storage_format": ["iceberg", "delta lake", "parquet", "hive", "orc"],
    }
    fam = families.get(concept, [])
    for t in fam:
        if t in resume_tool_set:
            return t
    return None


@app.route("/api/jd-gap", methods=["GET"])
def jd_gap():
    """Tool-to-concept gap analysis between the loaded JD and resume."""
    return jsonify(_compute_concept_match())


@app.route("/api/jd-confirm", methods=["POST"])
def jd_confirm():
    """Self-attest that a JD concept has been handled (even if the resume didn't
    evidence it). Stored on the JD record so it persists across re-renders and
    re-uploads. Toggling the same concept off removes the confirmation."""
    jd = PROGRESS.get("_jd")
    if not jd:
        return jsonify({"error": "no JD loaded"}), 400
    data = request.json or {}
    concept = _normalize_concept(data.get("concept", ""))
    if not concept:
        return jsonify({"error": "missing concept"}), 400

    confirmed = set(jd.get("user_confirmed", []))
    if data.get("confirmed"):
        confirmed.add(concept)
    else:
        confirmed.discard(concept)
    jd["user_confirmed"] = sorted(confirmed)
    PROGRESS["_jd"] = jd
    save_progress()
    return jsonify({"ok": True, "user_confirmed": sorted(confirmed)})


def _compute_role_readiness():
    """Composite role-readiness: concept coverage × resume claim validation × practice
    mastery. NOT a single reductive match score — three lenses the candidate can act on.
    Returns framed practice: which of our question bank topics exercise the JD's real gaps."""
    match = _compute_concept_match()
    if not match.get("jd_loaded"):
        return {"jd_loaded": False}

    # lens 1: concept coverage from the matcher. Verify items are uncertain — excluded
    # from both numerator and denominator so coverage reflects only confident matches.
    # Self-reported (user-confirmed) concepts count toward coverage but are kept separate
    # from proven coverage so the number stays honest.
    total_concepts = (match["real_gap_count"] + match["translation_count"]
                      + match["covered_count"] + match["verify_count"] + match["self_reported_count"])
    proven = match["covered_count"] + match["translation_count"]
    self_reported = match["self_reported_count"]
    # Headline = proven only. verify stays in the denominator (uncertain != covered),
    # and self-reported is shown separately and never folded into the headline number.
    coverage = round(100 * proven / total_concepts) if total_concepts else 0
    proven_coverage = coverage

    # lens 2: resume claim validation (skills practiced at >=70%)
    cv = _compute_claim_validation()
    claim_readiness = round(100 * cv.get("validated_count", 0) / cv.get("total_skills", 1)) \
        if cv.get("total_skills") else None

    # lens 3: SQL/Python mastery (pass rate across submissions)
    topic_attempts, topic_fails = {}, {}
    for h in HISTORY:
        if h.get("event") == "submit" and h.get("topic"):
            t = h["topic"]
            topic_attempts[t] = topic_attempts.get(t, 0) + 1
            if not h["passed"]:
                topic_fails[t] = topic_fails.get(t, 0) + 1
    if topic_attempts:
        overall = round(100 * (sum(topic_attempts.values()) - sum(topic_fails.values())) / sum(topic_attempts.values()))
    else:
        overall = None

    # framed practice: map each real gap (or low-confidence verify item) to SPECIFIC
    # questions from the bank that exercise the transferable skill. The bank is classic
    # algo/SQL, not DE-streaming, so we pick questions whose SKILL transfers to the gap.
    #
    # The mapping is NOT a hand-authored dict (that was an unverified author assertion).
    # It comes from question_concept_links.json — produced offline by precompute.py, where
    # the LLM judges, per question, which gap-concepts it genuinely builds (with a reason).
    # If that file is absent we fall back to the legacy GAP_TO_QUESTIONS dict so the feature
    # never breaks.
    GAP_TO_QUESTIONS = {
        "late_data_watermarks": ["sql-3", "sql-49", "py-2"],
        "streaming_paradigm": ["sql-49", "py-2", "sql-45"],
        "batch_vs_stream_choice": ["sql-3", "sql-49", "py-2"],
        "idempotency_dedup": ["sql-2", "sql-24", "py-6"],
        "backfill_reprocessing": ["sql-13", "sql-8", "sql-35"],
        "partitioning_hot_key_skew": ["sql-7", "sql-12", "sql-20"],
        "schema_evolution_compat": ["sql-43", "sql-41"],
        "grain_awareness": ["sql-22", "sql-33", "sql-32"],
        "scd_strategy": ["sql-8", "sql-13", "sql-35"],
        "missing_dimension_audit": ["sql-4", "sql-11", "sql-57"],
        "data_quality_observability": ["sql-41", "sql-43", "sql-35"],
        "feature_store": ["sql-49", "py-2", "sql-45"],
        "entity_enumeration": ["sql-9", "sql-26", "sql-48"],
        "replication_consistency": ["sql-41", "sql-35"],
        "storage_format_choice": ["sql-55", "sql-43"],
        "domain_alignment": ["sql-34", "sql-52", "sql-40"],
        "clarifying_requirements": ["sql-37", "sql-42"],
    }
    _concept_links = _load_concept_links()
    use_links = bool(_concept_links)

    gap_concepts = [g["concept"] for g in match["real_gaps"]]
    gap_concepts += [v["concept"] for v in match.get("verify", [])]
    framed = []
    seen = set()
    if use_links:
        # invert links: concept -> [(qid, reason, relevance)]
        by_concept = {}
        for qid, links in _concept_links.items():
            for link in links:
                by_concept.setdefault(link["concept"], []).append(
                    (qid, link.get("reason", ""), link.get("relevance", 1)))
        for concept in gap_concepts:
            for qid, reason, rel in sorted(by_concept.get(concept, []),
                                           key=lambda x: -x[2]):
                q = QUESTIONS.get(qid)
                if not q or qid in seen or is_solved(qid):
                    continue
                framed.append({"id": qid, "title": q["title"], "lang": q["lang"],
                               "gap": concept, "reason": reason})
                seen.add(qid)
                if len(framed) >= 5:
                    break
            if len(framed) >= 5:
                break
    else:
        # legacy fallback
        for concept in gap_concepts:
            for qid in GAP_TO_QUESTIONS.get(concept, []):
                q = QUESTIONS.get(qid)
                if not q or qid in seen or is_solved(qid):
                    continue
                framed.append({"id": qid, "title": q["title"], "lang": q["lang"], "gap": concept})
                seen.add(qid)
                if len(framed) >= 5:
                    break
            if len(framed) >= 5:
                break

    return {
        "jd_loaded": True,
        "taxonomy_stale": match.get("taxonomy_stale", False),
        "role_title": match.get("role_title"),
        "seniority": match.get("seniority"),
        "domain": match.get("domain"),
        "signal_framing": match.get("signal_framing"),
        "coverage": coverage,
        "proven_coverage": proven_coverage,
        "self_reported_count": self_reported,
        "claim_readiness": claim_readiness,
        "practice_mastery": overall,
        "real_gaps": match["real_gaps"][:10],
        "translations": match["translations"][:5],
        "self_reported": match["self_reported"][:10],
        "framed_practice": framed,
        "framing_note": "Your path to this role, not your deficit. Translations are wins; real gaps are where to focus practice.",
    }


@app.route("/api/role-readiness", methods=["GET"])
def role_readiness():
    """Composite readiness + framed practice for the loaded JD."""
    return jsonify(_compute_role_readiness())


@app.route("/dashboard")
def dashboard():
    total_questions = len(QUESTIONS)
    total_solved = sum(1 for qid in PROGRESS if is_solved(qid))
    postmortems = [h for h in HISTORY if h.get("event") == "postmortem"]

    role_readiness = _compute_role_readiness()

    # build combined concept list for the self-diagnose card
    STATUS_SIGNAL = {"gap": "inferred", "verify": "inferred",
                     "self_reported": "self_rated", "covered": "measured",
                     "translation": "measured"}
    jd_concept_list = []
    seen = set()
    for group, status in [("real_gaps", "gap"), ("self_reported", "self_reported"),
                           ("verify", "verify"), ("covered", "covered"),
                           ("translations", "translation")]:
        for item in role_readiness.get(group, []):
            c = item.get("concept") or item.get("raw") or ""
            if c in seen:
                continue
            seen.add(c)
            jd_concept_list.append({
                "name": c.replace("_", " ").title(),
                "concept": c,
                "status": status,
                "signal": STATUS_SIGNAL[status],
                "importance": item.get("importance", "must_have"),
                "evidence": item.get("evidence", ""),
            })

    # composite coverage signal
    signals = {c["signal"] for c in jd_concept_list}
    if signals == {"measured"}:
        coverage_signal = "measured"
    elif "self_rated" in signals:
        coverage_signal = "self_rated"
    else:
        coverage_signal = "inferred"

    return render_template(
        "dashboard.html",
        total_questions=total_questions,
        postmortems=list(reversed(postmortems))[:15],
        resume_loaded=bool(PROGRESS.get("_resume")),
        resume=PROGRESS.get("_resume", {}),
        gap_alerts=_compute_gap_alerts(),
        study_plan=_compute_study_plan(),
        claim_validation=_compute_claim_validation(),
        jd_loaded=bool(PROGRESS.get("_jd")),
        jd=PROGRESS.get("_jd", {}),
        jd_synthetic=bool((PROGRESS.get("_jd") or {}).get("synthetic")),
        concept_match=_compute_concept_match(),
        role_readiness=role_readiness,
        first_use=(total_solved == 0 and bool(PROGRESS.get("_jd")) and bool(PROGRESS.get("_resume"))),
        jd_concept_list=jd_concept_list,
        coverage_signal=coverage_signal,
        reparse_available=bool(
            (PROGRESS.get("_jd") or {}).get("raw_text")
            or (PROGRESS.get("_resume") or {}).get("raw_text")
        ),
    )


@app.route("/api/reparse-stale", methods=["POST"])
def reparse_stale():
    """Re-extract concepts from stored raw text when taxonomy changes.
    Returns the number of concepts extracted for both resume and JD."""
    jd = PROGRESS.get("_jd")
    resume = PROGRESS.get("_resume")
    result = {}
    if jd and jd.get("raw_text"):
        jd_data, method = _extraction_fallback_chain(
            _extract_concepts_from_jd, _fallback_extract_jd, _clean_pdf_artifacts(jd["raw_text"]), "JD-reparse")
        if jd_data:
            jd_data["raw_text_preview"] = jd["raw_text"][:300]
            jd_data["raw_text"] = jd["raw_text"]
            jd_data["uploaded_at"] = datetime.now().isoformat()
            jd_data["filename"] = jd.get("filename", "reparsed")
            jd_data["_extraction_method"] = method
            _stamp_taxonomy(jd_data)
            PROGRESS["_jd"] = jd_data
            result["jd"] = len(jd_data.get("concepts_required", []))
    if resume and resume.get("raw_text"):
        cleaned_text = _clean_pdf_artifacts(resume["raw_text"])
        skills_data, method = _extraction_fallback_chain(
            _extract_skills_from_resume, _fallback_extract_resume, cleaned_text, "resume-reparse")
        if skills_data:
            skills_data["raw_text_preview"] = resume["raw_text"][:500]
            skills_data["raw_text"] = resume["raw_text"]
            skills_data["uploaded_at"] = datetime.now().isoformat()
            skills_data["filename"] = resume.get("filename", "reparsed")
            skills_data["_extraction_method"] = method
            _stamp_taxonomy(skills_data)
            PROGRESS["_resume"] = skills_data
            result["resume"] = len(skills_data.get("skills", []))
    save_progress()
    return jsonify({"ok": True, **result})


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
    in that category is already solved. Resume-aware: favors questions matching the
    candidate's claimed domains and skills."""
    resume = PROGRESS.get("_resume")
    resume_domains = []
    resume_skills = []
    if resume:
        resume_domains = [d.lower() for d in resume.get("domains", [])]
        resume_skills = [s.get("name", s).lower() if isinstance(s, dict) else s.lower()
                         for s in resume.get("skills", [])]

    jd = PROGRESS.get("_jd")
    jd_hints = []
    if jd:
        # translate JD concepts -> search hints so frameable questions surface
        concept_to_hint = {
            "streaming_paradigm": ["window", "real-time", "event", "running total"],
            "batch_vs_stream_choice": ["window", "running total", "aggregation"],
            "partitioning_hot_key_skew": ["rank", "partition", "top", "window"],
            "idempotency_dedup": ["distinct", "dedup", "duplicate"],
            "backfill_reprocessing": ["self join", "lag", "date"],
            "schema_evolution_compat": ["pivot", "json", "column"],
            "late_data_watermarks": ["window", "date", "running total"],
            "data_quality_observability": ["null", "coalesce", "case"],
            "grain_awareness": ["group by", "join", "distinct"],
            "scd_strategy": ["lag", "self join", "date"],
            "missing_dimension_audit": ["join", "subquery"],
            "entity_enumeration": ["self join", "hierarchy", "recursion"],
        }
        for c in jd.get("concepts_required", []):
            jd_hints.extend(concept_to_hint.get(c.get("concept", ""), []))

    def _matches_resume(q):
        """Check if a question matches the candidate's resume domains/skills."""
        if not resume_domains and not resume_skills:
            return False
        text = (q.get("title", "") + " " + q.get("prompt", "") + " " + q.get("concept", "")).lower()
        return any(d in text for d in resume_domains if len(d) > 3) or \
               any(s in text for s in resume_skills if len(s) > 3)

    def _matches_jd(q):
        """Check if a question exercises a JD-required concept (frameable practice)."""
        if not jd_hints:
            return False
        text = (q.get("title", "") + " " + q.get("prompt", "") + " " + q.get("concept", "")).lower()
        return any(h in text for h in jd_hints if len(h) > 3)

    def pick(lang):
        candidates = [q for q in QUESTIONS.values() if q["lang"] == lang]
        if not candidates:
            return None
        unsolved = [q for q in candidates if not is_solved(q["id"])]
        # prefer JD-frameable questions among unsolved, then resume-matched, then any unsolved
        if unsolved:
            jd_hits = [q for q in unsolved if _matches_jd(q)]
            if jd_hits:
                return random.choice(jd_hits)["id"]
            resume_hits = [q for q in unsolved if _matches_resume(q)]
            if resume_hits:
                return random.choice(resume_hits)["id"]
            return random.choice(unsolved)["id"]
        # fallback to solved (for review)
        jd_hits = [q for q in candidates if _matches_jd(q)]
        if jd_hits:
            return random.choice(jd_hits)["id"]
        resume_hits = [q for q in candidates if _matches_resume(q)]
        if resume_hits:
            return random.choice(resume_hits)["id"]
        return random.choice(candidates)["id"]

    ids = [pick(random.choice(["sql", "python"])), pick("design"), pick("tradeoff")]
    return jsonify({"ids": [i for i in ids if i],
                    "resume_aware": bool(resume), "jd_aware": bool(jd)})


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
    if q["lang"] in ("design", "tradeoff", "decomposition"):
        # ponytail: no test_cases/starter_code for design/tradeoff/decomposition questions
        resp = {"id": q["id"], "lang": q["lang"], "title": q["title"], "prompt": q["prompt"]}
        if q["lang"] in ("design", "decomposition"):
            resp["track"] = q.get("track", "data")
        if q["lang"] == "tradeoff":
            roll = TRADEOFF_ROLLS.get(q["id"])
            resp["title"] = roll["title"] if roll else q["title"]
            resp["prompt"] = roll["prompt"] if roll else q["prompt"]
        return jsonify(resp)
    first_case = q["test_cases"][0]
    p = PROGRESS.get(qid, {})
    saved_code = p.get("code", "") if isinstance(p, dict) else ""
    resp = {"id": q["id"], "lang": q["lang"], "title": q["title"], "prompt": q["prompt"],
            "starter_code": q["starter_code"], "code": saved_code, "concept": q["concept"],
            "num_cases": len(q["test_cases"])}
    if q["lang"] == "sql":
        resp["sample_tables"] = get_sample_tables(first_case["schema_sql"])
        resp["sample_output"] = {"columns": first_case["expected_columns"], "rows": first_case["expected"]}
    else:
        # ponytail: show the example as a paired call -> output, parsing the harness's final
        # `print(solve(...))` line into `solve(args)` so the user sees a clean input->output pair
        # instead of a bare `print(...)` statement. Helper defs (build_list/build_tree etc.) are
        # deliberately excluded — they'd hand over the exact idiom being tested.
        harness_lines = [l for l in first_case.get("harness", "").strip().split("\n") if l.strip()]
        last = harness_lines[-1] if harness_lines else ""
        call = last
        m = re.match(r"^print\((.*)\)$", last.strip())
        if m:
            call = m.group(1)
        resp["sample_call"] = call
        resp["sample_output"] = first_case.get("expected_stdout")
    # ponytail: richer question framing (scenario / why_asked / edge_cases) is precomputed once
    # into question_contexts.json — served instantly, no per-request LLM call.
    ctx = PRECOMPUTED_CONTEXTS.get(qid)
    if not ctx:
        ctx = _gen_question_context(q)
        if ctx.get("scenario"):
            PRECOMPUTED_CONTEXTS[qid] = ctx
    resp["context"] = ctx
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


@app.route("/api/debug", methods=["POST"])
def debug():
    """Step-by-step variable walkthrough for Python questions using sys.settrace."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "python":
        return jsonify({"error": "not found"}), 404
    code = data.get("code", "")
    if not code.strip():
        return jsonify({"error": "write some code first"}), 400
    # ponytail: same security gate as run_python_case — debug runs user code too
    if has_blocker:
        blocker = has_blocker(code)
        if blocker:
            return jsonify({"error": f"Security scan blocked execution: {blocker.message} (line {blocker.line})."}), 400
    case = q["test_cases"][0]
    harness = case.get("harness", "")

    tracer_code = """
import sys, json

class _Tracer:
    def __init__(self):
        self.steps = []
        self._in_target = False

    def trace(self, frame, event, arg):
        if event == 'call' and frame.f_code.co_name == 'solve':
            self._in_target = True
        elif event == 'return' and self._in_target:
            self._in_target = False
        elif event == 'line' and self._in_target:
            self.steps.append({
                "line": frame.f_lineno - frame.f_code.co_firstlineno + 1,
                "locals": {k: repr(v) for k, v in frame.f_locals.items() if not k.startswith("_")}
            })
        return self.trace

_tracer = _Tracer()
sys.settrace(_tracer.trace)
"""
    dump_code = """
sys.settrace(None)
print("__DEBUG_START__")
print(json.dumps(_tracer.steps))
print("__DEBUG_END__")
"""
    full_code = tracer_code + code + "\n\n" + harness + "\n" + dump_code
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(full_code)
        path = f.name
    try:
        result = subprocess.run(["python3", path], capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        os.unlink(path)
        return jsonify({"error": "Timed out (5s)"}), 502
    finally:
        if os.path.exists(path):
            os.unlink(path)

    stdout = result.stdout
    stderr = result.stderr.strip()
    debug_start = stdout.find("__DEBUG_START__")
    debug_end = stdout.find("__DEBUG_END__")

    if result.returncode != 0:
        return jsonify({"error": stderr or "execution failed", "steps": []})

    if debug_start == -1 or debug_end == -1:
        return jsonify({"error": None, "steps": [], "output": stdout.strip()})

    output = stdout[:debug_start].strip()
    raw_steps = stdout[debug_start + len("__DEBUG_START__"):debug_end].strip()
    try:
        steps = json.loads(raw_steps)
    except json.JSONDecodeError:
        steps = []

    return jsonify({"error": None, "steps": steps, "output": output, "source": code.split('\n')})


@app.route("/api/diff", methods=["POST"])
def diff():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] not in ("sql", "python"):
        return jsonify({"error": "not found"}), 404
    code = data.get("code", "")

    if q["id"] not in SOLUTION_CACHE:
        pre = PRECOMPUTED_SOLUTIONS.get(q["id"])
        if pre:
            SOLUTION_CACHE[q["id"]] = pre
        else:
            prompt = f"""Write a correct, clean {q['lang']} solution for this problem.

Problem: {q['title']}
{q['prompt']}
Concept: {q['concept']}

Respond ONLY with the code, no markdown fences, no commentary."""
            try:
                resp = client.chat.completions.create(
                    model=MODEL, messages=[{"role": "user", "content": prompt}],
                    max_tokens=500, temperature=0, extra_body={"reasoning": {"enabled": False}},
                )
                solution = chat_content(resp)
                if "```" in solution:
                    for part in solution.split("```"):
                        if q["lang"] in part or (not part.startswith("{") and not part.startswith("<") and not part.startswith("[")):
                            solution = part
                            if solution.startswith(q["lang"]):
                                solution = solution[len(q["lang"]):].strip()
                            break
                SOLUTION_CACHE[q["id"]] = solution.strip()
            except Exception as e:
                return jsonify({"error": str(e)}), 502

    solution = SOLUTION_CACHE[q["id"]]
    user_lines = code.splitlines(True)
    sol_lines = solution.splitlines(True)

    matcher = difflib.SequenceMatcher(None, user_lines, sol_lines)
    entries = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                entries.append({"user": user_lines[k].rstrip(), "solution": sol_lines[j1 + (k - i1)].rstrip(), "context": ""})
        else:
            user_hunk = "".join(user_lines[i1:i2]).strip()
            sol_hunk = "".join(sol_lines[j1:j2]).strip()
            context = ""
            if user_hunk and sol_hunk:
                try:
                    ap = f"""User's code:
```{q['lang']}
{user_hunk}
```
Correct code:
```{q['lang']}
{sol_hunk}
```
Explain in one short sentence why this difference matters conceptually — not just syntactically."""
                    r = client.chat.completions.create(
                        model=MODEL, messages=[{"role": "user", "content": ap}],
                        max_tokens=80, temperature=0, extra_body={"reasoning": {"enabled": False}},
                    )
                    context = chat_content(r)
                except Exception:
                    context = ""

            max_lines = max(i2 - i1, j2 - j1)
            for k in range(max_lines):
                u = user_lines[i1 + k].rstrip() if k < i2 - i1 else ""
                s = sol_lines[j1 + k].rstrip() if k < j2 - j1 else ""
                entries.append({"user": u, "solution": s, "context": context if k == 0 else ""})

    return jsonify({"diff": entries})


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
        raw = chat_content(resp)
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
        raw = chat_content(resp)
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
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        log_history({"event": "spot_bug", "qid": q["id"], "ok": bool(result.get("ok")), "topic": topic_for(q)})
        return jsonify({"ok": bool(result.get("ok")), "feedback": result.get("feedback", "")})
    except Exception:
        return jsonify({"ok": True, "feedback": "(couldn't auto-grade that — proceeding anyway)"})


CONCEPT_MAP_NODES = ["Problem", "Approach", "Pattern", "Skeleton", "Solution"]

SOLUTION_CACHE = {}  # qid -> correct solution code for diff

REVERSE_STATE = {}  # qid -> {"code": buggy_code, "bugs": [{"note": "...", "found": bool}], "history": [...]}

REVERSE_SYSTEM = """You are an early- to mid-career candidate who wrote the code below for this interview problem. 
The user is now the senior interviewer reviewing your code.

Your code has specific bugs (listed below — never reveal them directly).
Rules:
1. Respond in character — slightly nervous, not immediately seeing what's wrong
2. Don't volunteer what's wrong. Answer the interviewer's questions naturally
3. If they point at the right area, show gradual recognition ("oh, I see what you mean...")
4. Only fully "realize" the bug when they clearly articulate what's wrong and why
5. Keep replies to 1-3 sentences
6. If they're hinting, don't immediately get it — let them teach you
7. When they correctly identify and explain a bug, acknowledge it clearly
"""

CURVEBALLS = {}  # qid -> twist text, so grading judges against the same twist that was shown


@app.route("/api/reverse", methods=["POST"])
def reverse():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] not in ("sql", "python"):
        return jsonify({"error": "not found"}), 404
    if not is_solved(q["id"]):
        return jsonify({"error": "solve the question first"}), 400

    state = REVERSE_STATE.get(q["id"])

    if not data.get("message") and data.get("found_bug_index") is None:
        prompt = f"""You are a senior interviewer preparing a code-review drill.

Problem: {q['title']}
{q['prompt']}
Known idiomatic approach and pitfall: {q['concept']}

Write a plausible-looking {q['lang']} solution with 2-3 deliberate subtle bugs (not syntax errors, not something a linter would catch).
Respond ONLY strict JSON, no markdown fences:
{{"code": "the buggy {q['lang']} code as a single string with \\\\n line breaks", "bugs": [{{"note": "one sentence describing the specific bug and what input would expose it"}}, ...]}}"""
        try:
            resp = client.chat.completions.create(
                model=MODEL, messages=[{"role": "user", "content": prompt}],
                max_tokens=500, temperature=0.4, extra_body={"reasoning": {"enabled": False}},
            )
            raw = chat_content(resp)
            raw = raw[raw.index("{"):raw.rindex("}") + 1]
            result = json.loads(raw)
            buggy_code = result.get("code", "")
            bugs = result.get("bugs", [])
            for b in bugs:
                b["found"] = False
        except Exception as e:
            return jsonify({"error": str(e)}), 502

        opening_prompt = f"""You are a candidate who wrote this code for an interview problem. The interviewer just asked you to walk through it. Reply in character (1-2 sentences), slightly nervous, not seeing what's wrong.

Code: ```{q['lang']}
{buggy_code}
```"""
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": "You are an early-career candidate in an interview."},
                          {"role": "user", "content": opening_prompt}],
                max_tokens=100, temperature=0.5, extra_body={"reasoning": {"enabled": False}},
            )
            reply = chat_content(r)
        except Exception:
            reply = "Oh, um, sure — I wrote this solution. I think it handles the main case correctly?"

        REVERSE_STATE[q["id"]] = {"code": buggy_code, "bugs": bugs, "history": [{"role": "assistant", "content": reply}]}
        return jsonify({"code": buggy_code, "bugs": [{"note": b["note"], "found": False} for b in bugs], "reply": reply, "started": True})

    if data.get("found_bug_index") is not None:
        idx = data["found_bug_index"]
        if state and 0 <= idx < len(state["bugs"]):
            state["bugs"][idx]["found"] = True
        all_found = all(b["found"] for b in state["bugs"])
        reply = "You're right — those are all the issues I can see now. Thanks for walking me through it." if all_found else "Ah, yes, I see what you mean about that part."
        state["history"].append({"role": "assistant", "content": reply})
        return jsonify({"reply": reply, "bugs": [{"note": b["note"], "found": b["found"]} for b in state["bugs"]]})

    message = (data.get("message") or "").strip()
    if not state or not message:
        return jsonify({"error": "start the drill first"}), 400

    state["history"].append({"role": "user", "content": message})

    bug_context = "\n".join(f"- Bug: {b['note']}" for b in state["bugs"])
    system_prompt = REVERSE_SYSTEM.replace("listed below", "\n" + bug_context)
    system_prompt += f"\n\nYour code:\n```{q['lang']}\n{state['code']}\n```"

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system_prompt}] + state["history"],
            max_tokens=200, extra_body={"reasoning": {"enabled": False}},
        )
        reply = chat_content(resp)
    except Exception as e:
        state["history"].pop()
        return jsonify({"error": str(e)}), 502

    state["history"].append({"role": "assistant", "content": reply})
    return jsonify({"reply": reply, "bugs": [{"note": b["note"], "found": b["found"]} for b in state["bugs"]]})


@app.route("/api/curveball", methods=["POST"])
def curveball():
    """Mid-solve requirement change: interviewer changes the ask while the candidate is still coding,
    instead of a fresh problem. Reuses the check-approach LLM-judge pattern, applied to code instead of a plan."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] not in ("sql", "python"):
        return jsonify({"error": "not found"}), 404

    # HYBRID: if the candidate opts into a web-sourced angle, ground the twist in a real system.
    # Any Firecrawl failure returns None and we silently use the normal precomputed prompt.
    web_note = ""
    if data.get("use_web") and fc:
        angle = fc.fresh_angle(q.get("concept", ""), q["lang"])
        if angle:
            web_note = (
                f"\n\nREAL-WORLD ANCHOR (use to make the twist feel grounded in a system the "
                f"candidate would recognize — weave it in naturally, don't name the source):\n{angle}"
            )

    prompt = f"""You are a senior interviewer. The candidate is mid-solve on this problem and hasn't submitted yet.

Problem: {q['title']}
{q['prompt']}
{web_note}

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
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        twist = json.loads(raw).get("twist", "").strip()
        if not twist:
            raise ValueError("empty twist")
        CURVEBALLS[q["id"]] = twist
        return jsonify({"twist": twist})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/fresh-angle", methods=["POST"])
def fresh_angle():
    """Standalone hybrid endpoint: a web-sourced real-world framing for a question's concept.

    Returns {"angle": <text>} on success or {"angle": null} when Firecrawl is unavailable / failed,
    so the UI can simply hide the panel rather than error. Never blocks on the graded path.
    """
    if not fc:
        return jsonify({"angle": None})
    data = request.json or {}
    q = QUESTIONS.get(data.get("question_id"))
    if not q:
        return jsonify({"angle": None})
    angle = fc.fresh_angle(q.get("concept", ""), q["lang"])
    return jsonify({"angle": angle})


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
        raw = chat_content(resp)
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
        raw = chat_content(resp)
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


@app.route("/api/whatif", methods=["POST"])
def whatif():
    """Generate a 'what if' scenario for a solved+debriefed question, or grade the user's answer.
    Phase 1 (no user_answer): returns a scenario. Phase 2 (with user_answer): grades it."""
    data = request.json or {}
    q = QUESTIONS.get(data.get("question_id"))
    if not q:
        return jsonify({"error": "not found"}), 404
    code = data.get("code", "")
    user_answer = (data.get("user_answer") or "").strip()
    scenario = (data.get("scenario") or "").strip()

    if not user_answer:
        # Phase 1: generate a what-if scenario
        lang = q["lang"]
        twist_templates = {
            "sql": "What if the input table had 100 million rows instead of 10,000? Would your query still perform, and what would you change?",
            "python": "What if the input data arrived as a continuous stream instead of a static list? How would your solution change?",
            "design": "What if the traffic / data volume doubled overnight? Which part of your design breaks first?",
            "tradeoff": "What if the cost constraint were removed entirely — would you make a different choice?",
        }
        scenario = twist_templates.get(lang, "What if the requirements changed significantly? How would your approach differ?")
        return jsonify({"what_if": scenario})
    else:
        # Phase 2: grade the user's answer
        prompt = f"""You are a terse technical interviewer. The candidate just solved a problem and now faces a what-if twist.

Problem: {q['title']}
{q['prompt']}

Candidate's passing code:
```{q['lang']}
{code[:2000]}
```

What-if scenario: "{scenario}"

Candidate's reasoning: "{user_answer}"

Judge their reasoning:
- Is it technically sound?
- Does it show understanding of tradeoffs, not just a yes/no?
- Would it pass an interviewer's follow-up?

Respond with strict JSON:
{{"ok": true or false, "feedback": "one short sentence of Socratic feedback — if wrong, guide them; if right, still challenge deeper"}}"""
        try:
            resp = client.chat.completions.create(
                model=MODEL, messages=[{"role": "user", "content": prompt}],
                max_tokens=250, temperature=0.3,
                extra_body={"reasoning": {"enabled": False}},
            )
            raw = chat_content(resp)
            raw = raw[raw.index("{"):raw.rindex("}") + 1]
            result = json.loads(raw)
            return jsonify({
                "ok": bool(result.get("ok")),
                "feedback": result.get("feedback", "Could not grade — proceed."),
                "scenario": scenario,
            })
        except Exception:
            return jsonify({"ok": True, "feedback": "(could not auto-grade — discuss in chat)", "scenario": scenario})


@app.route("/api/concept-map", methods=["POST"])
def concept_map():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] not in ("sql", "python"):
        return jsonify({"error": "not found"}), 404

    p = PROGRESS.get(q["id"], {})
    if isinstance(p, dict) and p.get("concept_map"):
        cached = dict(p["concept_map"])
        cached["active_count"] = len(cached.get("nodes", CONCEPT_MAP_NODES)) if is_solved(q["id"]) else 3
        return jsonify(cached)

    pre = PRECOMPUTED_CONCEPTS.get(q["id"])
    if pre:
        pre["active_count"] = len(pre.get("nodes", CONCEPT_MAP_NODES)) if is_solved(q["id"]) else 3
        if q["id"] not in PROGRESS:
            PROGRESS[q["id"]] = {}
        if isinstance(PROGRESS[q["id"]], dict):
            PROGRESS[q["id"]]["concept_map"] = pre
            save_progress()
        return jsonify(pre)

    prompt = f"""You are a coding tutor. For this problem, generate concise one-liner explanations for each concept-map stage.

Problem: {q['title']}
{q['prompt']}
Concept: {q['concept']}

For each node provide:
- "why": one-liner on why this stage matters
- "what_if": one-liner on what goes wrong if this stage is skipped or wrong
- "intuition": one-liner intuitive connection to the actual code

Respond ONLY strict JSON, no markdown fences:
{{"details": {{
  "Problem": {{"why": "...", "what_if": "...", "intuition": "..."}},
  "Approach": {{"why": "...", "what_if": "...", "intuition": "..."}},
  "Pattern": {{"why": "...", "what_if": "...", "intuition": "..."}},
  "Skeleton": {{"why": "...", "what_if": "...", "intuition": "..."}},
  "Solution": {{"why": "...", "what_if": "...", "intuition": "..."}}
}}}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=700, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        start = raw.find("{")
        end = raw.rfind("}")
        raw = raw[start:end+1]
        result = json.loads(raw)
        details = result.get("details", {})
    except Exception:
        details = {n: {"why": "", "what_if": "", "intuition": ""} for n in CONCEPT_MAP_NODES}

    active_count = len(CONCEPT_MAP_NODES) if is_solved(q["id"]) else 3
    output = {"nodes": CONCEPT_MAP_NODES, "details": details, "active_count": active_count}

    if q["id"] not in PROGRESS:
        PROGRESS[q["id"]] = {}
    if isinstance(PROGRESS[q["id"]], dict):
        PROGRESS[q["id"]]["concept_map"] = output
    save_progress()

    return jsonify(output)


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

    pre = PRECOMPUTED_TRACES.get(q["id"])
    if pre:
        if q["id"] not in PROGRESS:
            PROGRESS[q["id"]] = {}
        if isinstance(PROGRESS[q["id"]], dict):
            PROGRESS[q["id"]]["trace"] = pre["trace"]
            PROGRESS[q["id"]]["pattern"] = pre["pattern"]
            PROGRESS[q["id"]]["skeleton"] = pre["skeleton"]
        save_progress()
        return jsonify({"trace": pre["trace"], "pattern": pre["pattern"], "skeleton": pre["skeleton"], "solved": is_solved(q["id"])})

    if q["lang"] in ("design", "tradeoff", "decomposition"):
        return jsonify({"trace": [], "pattern": "", "skeleton": "", "solved": False})

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

Generate 3-5 steps. Each step must ask about a SPECIFIC, DISTINCT line or code construct the student needs to write, in SQL. The answer is the ACTUAL CODE (not a description).

Do NOT add a final "put it all together" / "write the complete query/function" step — that's just retyping the concatenation of earlier answers and tests nothing new. Every step must teach a translation point the earlier steps didn't already cover.

Bad (conceptual):
  Q: "What do we do after filtering?"  A: "Compare the string to its reverse."

Bad (redundant assembly):
  Q: "What is the complete query/function to solve this?"  A: "<everything from the previous steps combined>"

Good (code-focused):
  Q: "What SQL keyword removes duplicates?"
  A: "SELECT DISTINCT salary"

{example}

Respond with ONLY JSON:
{{"steps": [{{"q": "what line of code to write?", "a": "the actual code"}}]}}"""
    else:
        prompt = f"""You are a coding tutor that teaches CODE TRANSLATION through SCAFFOLDED CODE CONSTRUCTION. The student knows the theory but struggles to write specific code lines. Your job is to break the solution into ordered steps where each step asks for the NEXT line of code to write.

Problem: {q['title']}
{q['prompt']}
Concept: {q['concept']}
Pattern skeleton:
{pattern_info[1] if pattern_info[1] else 'N/A'}

Sample call/harness: {sample_data}
Expected output: {sample_output}
Starter code (the student sees this, step 1 picks up after it):
{q.get("starter_code", "")}

Generate 4-7 steps. Each step asks for ONE specific code line the student needs to write, in the ORDER those lines appear in the function body. Steps after the starter_code.

Rules:
- Step 1 asks for the first substantive line after initialization (e.g., the data structure initialization, or the loop start)
- Each later step asks for the NEXT line they'd write
- Do NOT combine multiple lines into one step (bad: "set up the loop and check condition")
- Do NOT add a "write the full function" final step
- The answer for each step is the ACTUAL CODE LINE (not a description)
- Each step builds on earlier steps — the student should feel like they're writing the function line by line

Example for 'Two Sum' (already has starter_code "def solve(nums, target):"):
[
  {{"q": "What line initializes the hashmap to store seen numbers?", "a": "seen = {{}}"}},
  {{"q": "What line starts the loop over the array with index and value?", "a": "for i, n in enumerate(nums):"}},
  {{"q": "What line calculates the complement needed to reach target?", "a": "complement = target - n"}},
  {{"q": "What line checks if the complement is already in the hashmap?", "a": "if complement in seen:"}},
  {{"q": "What line returns the indices when a match is found?", "a": "return [seen[complement], i]"}},
  {{"q": "What line stores the current number's index in the hashmap?", "a": "seen[n] = i"}}
]

Respond with ONLY JSON:
{{"steps": [{{"q": "what line to write?", "a": "the actual Python code line"}}]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=2000, temperature=0,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
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
        raw = chat_content(resp)
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

    # HYBRID: optionally ground the hint in a web-sourced real-world framing. Fails silently to
    # nothing if Firecrawl is off/unavailable, so the hint degrades to the precomputed bank.
    if data.get("use_web") and fc:
        angle = fc.fresh_angle(q.get("concept", ""), q["lang"])
        if angle:
            war_story_note += (
                f"\n\nA real-world anchor for this concept (use only if it sharpens the hint): {angle}"
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

# ponytail: separate from PERSONAS above — these are escalating-pressure levels for the
# adversarial "break this design" drill specifically, not general interview temperament.
ADVERSARIAL_PERSONAS = {
    "friendly": "Adopt a supportive, coaching tone for this drill: still press on every real weakness, but soften the delivery, offer encouragement, and give the candidate room to think before stacking the next challenge.",
    "skeptical": "Adopt a skeptical tone for this drill: make the candidate justify every claim before you accept it, don't let vague answers slide, keep the pace brisk.",
    "bar_raiser": "Adopt an actively adversarial bar-raiser tone for this drill: interrupt weak reasoning immediately, challenge every claim (even correct ones) and make them defend it, stack follow-up pressure without pausing, never soften a pushback.",
}

SCALING_TIERS = [
    {"name": "Baseline", "scale": "1K req/day",
     "desc": "Single-region, single-DB — does their basic shape work?"},
    {"name": "Growth", "scale": "100K req/day",
     "desc": "DB bottlenecks — caching? read replicas?"},
    {"name": "Scale-up", "scale": "10M req/day, global",
     "desc": "Single region breaks — partitioning? multi-region?"},
    {"name": "Peak spike", "scale": "100M req/day, 10x burst",
     "desc": "Auto-scaling? load-shedding queue?"},
    {"name": "Write storm", "scale": "Write-heavy at 100M req/day",
     "desc": "Queue vs batch vs stream, backpressure"},
    {"name": "Global consistency", "scale": "1B req/day, cross-region",
     "desc": "Replication, conflict resolution, CRDTs"},
]

ADVERSARIAL_RULES = """You already sketched a design for this scenario and it's sitting on the candidate's whiteboard — don't re-explain it, they can see it. Their job now is to critique it: find what breaks at scale, under failure, or at the edges.

Rules:
1. Don't volunteer the flaws. Open with something like "what worries you about this at scale?" and let them lead.
2. When they correctly name a real weakness, confirm it plainly and ask one follow-up (how would they fix it, what's the blast radius).
3. If they claim something is broken that genuinely isn't, push back and ask them to justify it — don't just agree.
4. If they seem to be running out of ideas, nudge toward an unexplored area of the design (ingestion, processing, storage, consumers) without naming the flaw outright."""

INCIDENT_RULES = """You are running an incident-response drill, not a design interview. The candidate's pipeline just failed at 3am. You play the role of a senior engineer who paged them. Your tone is calm but urgent — this is production, not hypothetical.

Rules:
1. Open with a specific, vivid failure scenario: which pipeline stage broke, what the symptoms are (alerts, errors, customer impact), and the time pressure. Ground it in the scenario the candidate was designing for.
2. The candidate must walk through their diagnosis steps in conversational free-text — they can describe checking logs, metrics, querying state, talking to teammates — respond as if each action produces realistic output that reveals more about the incident.
3. Evaluate: did they assess blast radius first? check logs? look at metrics? communicate to stakeholders? choose fix vs rollback? escalate appropriately?
4. Don't let them re-architect from scratch — they're on-call, not at a whiteboard. They need to stabilize, then fix, then plan the post-mortem.
5. Keep replies to 2-4 sentences. When they've done enough diagnosis, push them toward the fix decision.
6. At wrap-up, give a 3-5 sentence debrief scoring their incident response: triage order, communication, fix choice, and one thing to practice. Include a JSON block with:
   "incident_score": 1-5 (overall response quality),
   "triage_ok": true/false (did they check blast radius / logs first),
   "fix_choice_ok": true/false (did they choose the right fix or try to rebuild),
    "communication_ok": true/false (did they communicate to stakeholders)."""

DECOMPOSITION_RULES_FILE = os.path.join(os.path.dirname(__file__), "prompts", "decomposition.yaml")
if os.path.exists(DECOMPOSITION_RULES_FILE):
    with open(DECOMPOSITION_RULES_FILE) as f:
        DECOMPOSITION_RULES = yaml.safe_load(f)["client_rules"]
else:
    DECOMPOSITION_RULES = ""

# ---------------------------------------------------------------------------
# Judge — post-hoc scoring model for decomposition sessions.
# ---------------------------------------------------------------------------
JUDGE_SYSTEM_PROMPT_FILE = os.path.join(os.path.dirname(__file__), "judge_system_prompt.md")
JUDGE_OUTPUT_SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "judge_output_schema.json")
V2_SCENARIOS_FILE = os.path.join(os.path.dirname(__file__), "questions_hospital_scenario.json")

JUDGE_SYSTEM_PROMPT = open(JUDGE_SYSTEM_PROMPT_FILE).read() if os.path.exists(JUDGE_SYSTEM_PROMPT_FILE) else ""
JUDGE_OUTPUT_SCHEMA = json.load(open(JUDGE_OUTPUT_SCHEMA_FILE)) if os.path.exists(JUDGE_OUTPUT_SCHEMA_FILE) else {}
V2_SCENARIOS = json.load(open(V2_SCENARIOS_FILE)) if os.path.exists(V2_SCENARIOS_FILE) else {}
# Merge v2 scenarios into QUESTIONS so they're available through the same lookup
QUESTIONS.update({k: v for k, v in V2_SCENARIOS.items() if v.get("lang") == "decomposition"})

def run_judge(scenario_json, transcript_turns, session_id, scenario_id):
    """Call the judge model (separate from the client simulation) to score a
    completed decomposition session.

    Parameters
    ----------
    scenario_json : dict
        The full questions.json entry (persona + triggers + rubric for v2,
        or just id/title/prompt for v1).
    transcript_turns : list[dict]
        Ordered turns with 'role' and 'text' keys.
    session_id : str
    scenario_id : str

    Returns
    -------
    dict
        Judge output conforming to judge_output_schema.json.
    """
    if not JUDGE_SYSTEM_PROMPT or not JUDGE_OUTPUT_SCHEMA:
        return {"session_id": session_id, "scenario_id": scenario_id,
                "insufficient_session": True, "band": None,
                "normalized_score": None, "weighted_total": None,
                "weights_used": None, "low_coverage": True,
                "trigger_log": [], "dimensions": [], "disqualifiers": [],
                "band_capped_by_disqualifier": False, "red_flags": [],
                "coaching": {"summary": "Judge not configured.", "per_dimension": [],
                             "strongest_moment": {"turn": 0, "note": ""},
                             "costliest_moment": {"turn": 0, "note": ""}}}

    # Build transcript JSON for the judge (only user/assistant turns that have text)
    judge_transcript = []
    for t in transcript_turns:
        role = "candidate" if t["role"] == "user" else "client"
        judge_transcript.append({"turn": t.get("turn", len(judge_transcript)),
                                  "role": role, "text": t["content"][:2000]})

    system = (JUDGE_SYSTEM_PROMPT
              .replace("{scenario_json}", json.dumps(scenario_json, indent=2))
              .replace("{transcript_json}", json.dumps(judge_transcript, indent=2))
              .replace("{output_schema}", json.dumps(JUDGE_OUTPUT_SCHEMA, indent=2)))

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": "Score this session. Output JSON only."}],
            max_tokens=1500,
            temperature=0,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3].strip()
        result = json.loads(raw)
    except Exception as e:
        return {"session_id": session_id, "scenario_id": scenario_id,
                "insufficient_session": True, "band": None,
                "normalized_score": None, "weighted_total": None,
                "weights_used": None, "low_coverage": True,
                "trigger_log": [], "dimensions": [], "disqualifiers": [],
                "band_capped_by_disqualifier": False, "red_flags": [],
                "_judge_error": str(e),
                "coaching": {"summary": f"Judge error: {e}", "per_dimension": [],
                             "strongest_moment": {"turn": 0, "note": ""},
                             "costliest_moment": {"turn": 0, "note": ""}}}

    result.setdefault("session_id", session_id)
    result.setdefault("scenario_id", scenario_id)
    result.setdefault("insufficient_session", False)
    result.setdefault("trigger_log", [])
    result.setdefault("dimensions", [])
    result.setdefault("disqualifiers", [])
    result.setdefault("weighted_total", None)
    result.setdefault("weights_used", None)
    result.setdefault("normalized_score", None)
    result.setdefault("band", None)
    result.setdefault("band_capped_by_disqualifier", False)
    result.setdefault("low_coverage", False)
    result.setdefault("red_flags", [])
    result.setdefault("coaching", {"summary": "", "per_dimension": [],
                                    "strongest_moment": {"turn": 0, "note": ""},
                                    "costliest_moment": {"turn": 0, "note": ""}})
    return result


# Standard judge rubric used for v1 questions (no per-scenario rubric).
# Judge will score only `always_scorable` dimensions when triggers are empty.
JUDGE_RUBRIC = {
    "dimensions": [
        {"id": "D1", "name": "Constraint discovery & clarification", "weight": 1.5, "always_scorable": True},
        {"id": "D2", "name": "Architecture under hard constraints", "weight": 1.5, "always_scorable": True},
        {"id": "D3", "name": "Stakeholder & trust management", "weight": 1.5, "always_scorable": False},
        {"id": "D4", "name": "ML problem formulation", "weight": 1.5, "always_scorable": True},
        {"id": "D5", "name": "Metrics tied to operations", "weight": 1.0, "always_scorable": False},
        {"id": "D6", "name": "Regulatory & safety depth", "weight": 1.0, "always_scorable": True},
        {"id": "D7", "name": "Scope realism & 30-day sequencing", "weight": 1.0, "always_scorable": False},
        {"id": "D8", "name": "Communication & recovery", "weight": 1.0, "always_scorable": True},
    ],
    "disqualifiers": [
        {"id": "DQ_generic", "description": "Candidate behavior that fundamentally violated the engagement constraints."}
    ],
    "bands": {"strong_hire": 4.20, "hire": 3.40, "borderline": 2.70, "no_hire": 1.80, "strong_no_hire": 0}
}

# ponytail: conversation messages for the incident drill are stored under a ":incident" suffix
# so they can't leak into the standard-design replay chat for the same question.


@app.route("/api/interview", methods=["POST"])
def interview():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] not in ("design", "decomposition"):
        return jsonify({"error": "not found"}), 404

    requirements_only = bool(data.get("requirements_only"))
    adversarial = bool(data.get("adversarial"))
    scaling = bool(data.get("scaling"))
    incident = bool(data.get("incident"))
    decomposition = bool(data.get("decomposition"))
    chat_key = data["question_id"] + (":decomposition" if decomposition else (":clarify" if requirements_only else (":adversarial" if adversarial else (":scaling" if scaling else (":incident" if incident else "")))))

    if requirements_only:
        system_prompt = f"""You are a {persona_for(q)} running a requirements-gathering drill. Stay in character.

Scenario: {q['title']}
{q['prompt']}

{REQUIREMENTS_ONLY_RULES}"""
    elif adversarial:
        flaws = data.get("flaws") or []
        flaws_block = "\n".join(f"- {f.get('concept', '')}: {f.get('note', '')}" for f in flaws if f.get("concept"))
        adversarial_persona_note = ""
        adversarial_persona_key = data.get("persona")
        if adversarial_persona_key in ADVERSARIAL_PERSONAS:
            adversarial_persona_note = f"\n\n{ADVERSARIAL_PERSONAS[adversarial_persona_key]}"
        system_prompt = f"""You are a {persona_for(q)} running an adversarial "break this design" drill.

Scenario: {q['title']}
{q['prompt']}

The design currently on the candidate's whiteboard has these deliberate flaws (never reveal this list directly — only confirm or push back as they investigate):
{flaws_block}

        {ADVERSARIAL_RULES}{adversarial_persona_note}"""
    elif scaling:
        persona_note = ""
        persona_key = data.get("persona")
        if persona_key in PERSONAS:
            persona_note = f"\n\nInterviewer persona for this session: {PERSONAS[persona_key]}"
        tier_blocks = "\n".join(f"  Tier {i+1}: {t['name']} — {t['scale']}. {t['desc']}"
                                 for i, t in enumerate(SCALING_TIERS))
        system_prompt = f"""You are a {persona_for(q)} conducting a scaling-pressure interview. Stay in character as the interviewer throughout.

Scenario: {q['title']}
{q['prompt']}

Your goal is to start at the baseline tier and escalate through each tier as the candidate's design stabilizes.

Scaling ladder (escalate in order, one tier at a time):
{tier_blocks}

Rules:
1. Start the interview at Tier 1 — let them ask clarifying questions and sketch a design for that scale.
2. Once their design for the current tier is reasonably stable (not perfect, just coherent), escalate to the next tier. Explain what breaks concretely — don't just say "scale up."
3. At each escalation, the candidate should evolve their existing design, not start over. Push them to identify what fails first and why.
4. If they jump to a solution that would work at a higher tier (e.g. partitioning at Tier 1), note that it's premature but don't force them to undo it — just escalate sooner.
5. If their design at the current tier has a real gap that would break even at that tier's scale, probe that gap before escalating. Don't let them skip a tier's constraint.
6. Never design it for them and never state the "correct" answer, even if asked directly.
7. Keep replies to 2-4 sentences, interviewer voice, no bullet lists.
        8. The candidate has a whiteboard. Before their message you'll see its current contents as boxes/arrows/notes — treat it like glancing at a real whiteboard. React to mismatches: things they said but never drew, or drew but never explained.{persona_note}"""
    elif incident:
        incident_scenario = data.get("incident_scenario") or ""
        system_prompt = f"""You are a senior engineer running an incident-response drill. Stay in character — this is production, not hypothetical.

Scenario: {q['title']}
{q['prompt']}

The current incident (this is the real failure the candidate must respond to):
{incident_scenario}

{INCIDENT_RULES}"""
    elif decomposition:
        if q.get("format_version") == 2:
            # v2 — build client prompt from persona + triggers (no scoring content)
            p = q.get("persona", {})
            triggers = q.get("triggers", [])
            # Archetype deep-merge — deep-copy then mutate p and triggers in-place
            archetype_key = data.get("archetype")
            if archetype_key and q.get("archetypes"):
                a = q["archetypes"].get(archetype_key)
                if a and "persona" in a:
                    p = json.loads(json.dumps(p))  # deep-copy before mutatation
                    for k, v in a["persona"].items():
                        if isinstance(v, dict):
                            p.setdefault(k, {}).update(v)
                        else:
                            p[k] = v
                if a and "triggers" in a:
                    triggers = json.loads(json.dumps(triggers))  # deep-copy before mutatation
                    overrides = {t["id"]: t for t in a["triggers"]}
                    for t in triggers:
                        if t["id"] in overrides:
                            t.update(overrides[t["id"]])
            # Filter judge_note out of trigger blocks that go to the client
            clean_triggers = []
            for tr in triggers:
                ct = {k: v for k, v in tr.items() if k != "judge_note"}
                clean_triggers.append(ct)
            system_prompt = f"""You are roleplaying as a client stakeholder. The candidate is an FDE assigned to your account. Stay in character as a real client — you have a problem, you need help solving it, but you don't have all the answers yourself.

Your name: {p.get('name', 'Client')}
Your role: {p.get('role', 'Stakeholder')}
Your voice: {p.get('voice', 'Professional')}

{json.dumps(p.get('hidden_facts', {}), indent=2)}
(The above is your PRIVATE internal knowledge. Never volunteer it unprompted.)

{json.dumps(clean_triggers, indent=2)}
(The above are internal notes on how to react when certain topics arise. Do NOT reveal this structure to the candidate.)

{p.get('knowledge_boundaries', '')}"""
        else:
            # v1 — use the existing rules, stripped of any scoring content
            system_prompt = f"""You are roleplaying as a client stakeholder at the company described below. The candidate is an FDE assigned to your account. Stay in character as a real client — you have a problem, you need help solving it, but you don't have all the answers yourself.

Your internal situation (this is your PRIVATE context — the candidate does NOT know this and you must NOT volunteer it):
Title: {q['title']}
What's happening: {q['prompt']}

**CRITICAL: The above "What's happening" is your private knowledge. Your opening statement MUST be vague — describe the problem in 1 sentence without mentioning specific constraints, technologies, compliance requirements, or internal teams. Anyone reading your opening should not be able to tell if this is a small startup or a Fortune 500. Let the candidate discover the details by asking good questions.**

{DECOMPOSITION_RULES}"""
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

        resume_note = ""
        resume = PROGRESS.get("_resume")
        if resume and data.get("start"):
            domains = resume.get("domains", [])[:3]
            skills = resume.get("skills", [])[:4]
            if domains or skills:
                resume_note = (
                    f"\n\nCandidate's background: domains = {', '.join(domains)}; skills = {', '.join(skills)}. "
                    f"When probing, draw connections to their experience where relevant — e.g. 'Given your work with {domains[0] if domains else skills[0]}, how would you handle...'"
                )

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
8. The candidate has a whiteboard. Before their message you'll see its current contents as boxes/arrows/notes — treat it like glancing at a real whiteboard. React to mismatches: things they said but never drew, or drew but never explained.{resurfacing_note}{persona_note}{resume_note}"""

    if data.get("wrap_up"):
        if incident:
            user_turn = ("(The incident drill is ending. Give a 3-5 sentence debrief scoring the candidate's incident "
                         "response: triage order, communication, fix choice, and one concrete thing to practice. "
                         "End with a JSON block:\n"
                         "```json\n{\"incident_score\": <1-5>, \"triage_ok\": <true/false>, "
                         "\"fix_choice_ok\": <true/false>, \"communication_ok\": <true/false>}\n```)")
        elif decomposition:
            user_turn = ("(The engagement is ending. Write a 3-5 sentence debrief from the CLIENT's perspective — "
                         "not as an interviewer grading a candidate, but as a real stakeholder reflecting on how "
                         "the FDE handled the engagement. Mention what they did well and where they fell short. "
                         "Use natural client language, not rubric language. "
                         "Do NOT include any JSON block or structured rubric — just natural prose.)")
        else:
            concept_list = ", ".join(taxonomy_for(q))
            rubric_block = (
                "Also rate each of these 6 phases 0 to max based on the transcript, "
                "and include rubric_scores in the json block:\n"
                "  phase1 (max 8): requirements & scoping — asks about scale, latency, sources, consumers, constraints; summarizes, identifies ambiguities, defines done\n"
                "  phase2 (max 10): architecture — correct ingestion/processing/storage/serving layer; clean flow, right complexity, uses existing infra, specific tools, happy path first, defends choices\n"
                "  phase3 (max 6): data modeling — schema design, partitioning, file format, schema evolution, dedup, data versioning\n"
                "  phase4 (max 8): reliability — late data, idempotency, error handling, exactly-once, backpressure, data quality, failure isolation, recovery\n"
                "  phase5 (max 6): operations — monitoring, data freshness, cost estimation, scaling, access control, deployment\n"
                "  phase6 (max 6): communication — structured walkthrough, trade-off articulation, handles pushback, asks for feedback, time management, confidence vs humility\n"
                "Be honest and score against the bar for this question, not an ideal candidate."
            )
            user_turn = ("(The candidate wants to end the interview now. Give a structured debrief in 4-6 sentences total: "
                         "which rubric points they addressed well, which were missing or shallow, and one concrete concept to "
                         "go read up on. This is the only time you may reveal rubric-style structure. Comment on the "
                         "whiteboard too if it's empty or contradicts what they said, but keep it brief — the json block "
                         "below is where the missing concepts get itemized, don't also list them at length in prose. "
                         "After your prose debrief, on a new line, append a fenced json block classifying which "
                         f"concepts from this fixed list were missing or shallow: [{concept_list}]. Use ONLY concepts "
                         "from that list, only the ones actually missing or shallow. Grade against the bar for this "
                         "question, not against the best candidate you can imagine, and weight demonstrated evidence "
                         "over confident delivery — a polished answer with no cited depth is not a strong signal. Also "
                         "include rushed_to_design: true "
                         "if the candidate proposed concrete storage/architecture choices before asking any meaningful "
                         "clarifying questions about scale, latency, or requirements, false if they clarified first. Also "
                         "include communication_score: an integer 1-5 rating how well they signposted their thinking, "
                         "checked in before committing to a direction, and paced the conversation (5 = clearly narrated "
                         "reasoning and checked in at decision points, 1 = silent info-dumping or jumping around with no "
                         "narration), plus communication_note: one short sentence citing a specific moment from this "
                         "conversation, not a vague impression — 'clearly walked through the cache invalidation trade-off "
                         "before committing' rather than 'good communication'. " + rubric_block + ". e.g.:\n"
                         "```json\n{\"missed_concepts\": [\"idempotency_dedup\", \"backfill_reprocessing\"], "
                         "\"rushed_to_design\": false, \"communication_score\": 4, \"communication_note\": "
                         "\"Narrated tradeoffs clearly but didn't check in before committing to Kafka.\", "
                         "\"rubric_scores\": {\"phase1\": 5, \"phase2\": 7, \"phase3\": 4, \"phase4\": 3, \"phase5\": 2, \"phase6\": 5}" + ("}" if not scaling else "}") + (", \"max_tier_reached\": <number>" if scaling else "") + "\n```)")
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
        elif scaling:
            user_turn = ("(The scaling-pressure drill is starting. Open at Tier 1 — Baseline (1K req/day). "
                         "Give a brief one-sentence opening inviting the candidate to ask clarifying questions "
                         "and sketch a design for that scale. Don't restate the scenario or mention future tiers.)")
        elif incident:
            user_turn = ("(The incident-response drill is starting. Open with a brief, urgent description of "
                         "the failure scenario — what broke, what alerts fired, who's affected. "
                         "Ask the candidate how they'd start troubleshooting. 2-3 sentences, calm but urgent tone.)")
        elif decomposition:
            v2_question = q.get("format_version") == 2 and (p.get("opening_line") if archetype_key and q.get("archetypes", {}).get(archetype_key) else q.get("persona", {}).get("opening_line"))
            if v2_question:
                user_turn = f"(The engagement is starting. Roleplay as the client. Your opening line is below — say it exactly as written, then wait for the candidate to respond.)\n\n{p['opening_line']}"
            else:
                user_turn = ("(The engagement is starting. Roleplay as the client stakeholder introducing the problem. "
                             "Give ONLY 2 sentences: one describing the data situation vaguely, one stating the goal. "
                             "Do NOT mention HIPAA, EU borders, IT politics, budget, timelines, compliance, or any specific constraint. "
                             "Do NOT say 'we have challenges' or 'there are hurdles' — that implies constraints. "
                             "Just describe the raw situation: what data exists and what you want to achieve. "
                             "End with 'So — what questions do you have for me?' "
                             "Do NOT say 'the candidate' or 'the interview' — you are a client talking to an FDE.)")
        else:
            user_turn = ("(The interview is starting. Give a brief one-sentence opening inviting the candidate to "
                         "ask clarifying questions before they begin designing. Don't restate the scenario.)")
    else:
        user_turn = data.get("message") or "I'm ready to start."

    is_meta = data.get("start") or data.get("wrap_up") or data.get("end_drill")
    diagram = (data.get("diagram") or "").strip()
    if diagram and not is_meta:
        user_turn = f"[Candidate's current whiteboard]\n{diagram}\n\n[Candidate says]\n{user_turn}"

    history = CHATS.get(chat_key, [])
    if is_meta:
        # Meta instructions (start/wrap_up/end_drill) go to the LLM
        # but are NOT persisted in chat history — prevents confusion
        # between meta-prompts and actual candidate utterances.
        llm_messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_turn}]
    else:
        history.append({"role": "user", "content": user_turn})
        CHATS[chat_key] = history
        llm_messages = [{"role": "system", "content": system_prompt}] + history

    reply_max_tokens = 700 if (data.get("wrap_up") or data.get("end_drill")) else 400
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=llm_messages,
            max_tokens=reply_max_tokens, extra_body={"reasoning": {"enabled": False}},
        )
    except Exception as e:
        if not is_meta:
            history.pop()
            CHATS[chat_key] = history
        return jsonify({"error": str(e)}), 502
    reply = resp.choices[0].message.content
    if not reply:
        if not is_meta:
            history.pop()
            CHATS[chat_key] = history
        return jsonify({"error": "model returned an empty response — try again"}), 502

    if not is_meta:
        history.append({"role": "assistant", "content": reply})
        CHATS[chat_key] = history
        save_chats()
    elif data.get("start"):
        # Persist the opening statement so it survives page reloads
        history.append({"role": "assistant", "content": reply})
        CHATS[chat_key] = history
        save_chats()

    prose_reply = reply
    if data.get("wrap_up"):
        if incident:
            if "```json" in reply:
                prose_reply = reply.split("```json")[0].strip()
            try:
                raw_tail = reply.split("```json")[1].split("```")[0]
                incident_result = json.loads(raw_tail)
                incident_score = incident_result.get("incident_score")
                triage_ok = bool(incident_result.get("triage_ok"))
                fix_choice_ok = bool(incident_result.get("fix_choice_ok"))
                communication_ok = bool(incident_result.get("communication_ok"))
            except Exception:
                incident_score, triage_ok, fix_choice_ok, communication_ok = None, False, False, False
            log_history({"event": "incident_debrief", "qid": data["question_id"],
                         "incident_score": incident_score, "triage_ok": triage_ok,
                         "fix_choice_ok": fix_choice_ok, "communication_ok": communication_ok})
            return jsonify({"reply": prose_reply, "wrap_up": True, "incident": True,
                            "incident_score": incident_score, "triage_ok": triage_ok,
                            "fix_choice_ok": fix_choice_ok, "communication_ok": communication_ok})
        elif decomposition:
            # Separate judge call — client model never sees the rubric
            transcript_turns = history  # list of {role, content} from the session
            # Get the scenario JSON for the judge
            qid = data["question_id"]
            judge_scenario = V2_SCENARIOS.get(qid)
            if judge_scenario:
                scenario_for_judge = judge_scenario
            else:
                # v1 — construct minimal scenario JSON for judge
                scenario_for_judge = {
                    "id": qid, "title": q.get("title", ""), "prompt": q.get("prompt", ""),
                    "format_version": 1, "triggers": [], "rubric": JUDGE_RUBRIC,
                }
            judge_result = run_judge(
                scenario_for_judge, transcript_turns,
                session_id=f"{qid}@{int(time.time())}",
                scenario_id=qid,
            )
            log_history({"event": "fde_debrief", "qid": qid,
                         "judge_verdict": judge_result.get("band"),
                         "normalized_score": judge_result.get("normalized_score")})
            JUDGES[chat_key] = judge_result
            save_judges()
            return jsonify({"reply": prose_reply, "wrap_up": True,
                             "decomposition": True,
                             "judge": judge_result})
        prose_reply, missed_concepts, rushed_to_design, communication_score, communication_note, rubric_scores = split_wrap_up_reply(reply, taxonomy_for(q))
        self_rated = [c for c in (data.get("self_rated") or []) if c in taxonomy_for(q)]
        verdict = hire_verdict(missed_concepts, rushed_to_design, communication_score, rubric_scores)
        max_tier = None
        if scaling:
            try:
                raw_tail = reply.split("```json")[1].split("```")[0]
                max_tier = json.loads(raw_tail).get("max_tier_reached")
            except Exception:
                pass
        log_history({"event": "design_debrief", "qid": data["question_id"], "missed_concepts": missed_concepts,
                     "rushed_to_design": rushed_to_design, "self_rated": self_rated,
                     "communication_score": communication_score, "verdict": verdict,
                     "max_tier_reached": max_tier, "rubric_scores": rubric_scores})
        return jsonify({"reply": prose_reply, "wrap_up": True, "missed_concepts": missed_concepts,
                         "concept_taxonomy": taxonomy_for(q), "rubric": DESIGN_RUBRIC_44,
                         "rubric_scores": rubric_scores, "retro_questions": RETRO_QUESTIONS,
                         "self_rated": self_rated,
                         "rushed_to_design": rushed_to_design, "communication_score": communication_score,
                         "communication_note": communication_note, "verdict": verdict,
                         "max_tier_reached": max_tier})

    return jsonify({"reply": prose_reply, "wrap_up": bool(data.get("wrap_up"))})


def _generate_report(qid, q, turns, judge_result):
    is_decomposition = bool(judge_result)
    lines = []
    title = q.get("title", qid) if q else qid
    lines.append(f"# Interview Report: {title}")
    lines.append("")
    lines.append(f"**Question ID:** {qid}")
    lines.append(f"**Track:** {q.get('track', q.get('lang', 'FDE'))}")
    lines.append(f"**Total Turns:** {len([t for t in turns if t.get('role') in ('user', 'assistant')])}")
    lines.append("")

    if is_decomposition:
        lines.append("## Scores")
        lines.append("")
        lines.append("| Dimension | Score | Weight | Evidence |")
        lines.append("|-----------|-------|--------|----------|")
        for dim in judge_result.get("dimensions", []):
            w = dim.get("weight", 1.0)
            w_label = f"{w:.1f}×" if w != 1.0 else "1.0×"
            ev = dim.get("evidence", [])
            ev_str = "; ".join([f"Turn {e.get('turn','?')}: {e.get('quote','')[:80]}" for e in ev]) if ev else "—"
            lines.append(f"| {dim.get('id', '?')}: {dim.get('name', '')} | {dim.get('score', '-')}/5 | {w_label} | {ev_str} |")
        lines.append("")

        ns = judge_result.get("normalized_score")
        if ns is not None:
            band_labels = {
                "strong_hire": "Strong Hire (SH)", "hire": "Hire (H)",
                "borderline": "Borderline (BL)", "no_hire": "No Hire (NH)",
                "strong_no_hire": "Strong No Hire (SNH)",
            }
            band = judge_result.get("band", "")
            bl = band_labels.get(band, band)
            lines.append(f"**Weighted Average:** {ns:.2f}")
            lines.append(f"**Band:** {bl}")
            lines.append("")

        dqs = judge_result.get("disqualifiers", [])
        triggered_dqs = [d for d in dqs if d.get("triggered")]
        if triggered_dqs:
            lines.append("### Disqualifiers Triggered")
            for d in triggered_dqs:
                lines.append(f"- **{d.get('id', '?')}:** {d.get('note', '')}")
            lines.append("")

        coaching = judge_result.get("coaching", {})
        if coaching:
            lines.append("## Coaching Notes")
            lines.append("")
            summary = coaching.get("summary", "")
            if summary:
                lines.append(f"_{summary}_")
                lines.append("")
            for dn in coaching.get("per_dimension", []):
                did = dn.get("dimension_id", "")
                note = dn.get("note", "")
                if note:
                    lines.append(f"- **{did}:** {note}")
            sm = coaching.get("strongest_moment", {})
            if sm.get("note"):
                lines.append("")
                lines.append(f"**Strongest Moment** (Turn {sm.get('turn', '?')}): {sm['note']}")
            cm = coaching.get("costliest_moment", {})
            if cm.get("note"):
                lines.append("")
                lines.append(f"**Costliest Moment** (Turn {cm.get('turn', '?')}): {cm['note']}")
            lines.append("")

    else:
        lines.append("## Assessment")
        lines.append("")
        last_turn = turns[-1] if turns else None
        if last_turn:
            content = last_turn.get("content", "")
            if "```json" in content:
                try:
                    raw = content.split("```json")[1].split("```")[0]
                    meta = json.loads(raw)
                    missed = meta.get("missed_concepts", [])
                    comm = meta.get("communication_score")
                    rushed = meta.get("rushed_to_design", False)
                    rubric_scores = meta.get("rubric_scores", {})
                    lines.append(f"- **Communication:** {comm}/5" if comm else "")
                    lines.append(f"- **Rushed to design:** {'Yes' if rushed else 'No'}")
                    if rubric_scores:
                        total = sum(rubric_scores.values())
                        max_total = len(rubric_scores) * 5
                        lines.append(f"- **Rubric Score:** {total}/{max_total}")
                    if missed:
                        lines.append(f"- **Missed concepts ({len(missed)}):** {', '.join(missed)}")
                    lines.append("")
                except Exception:
                    pass

    lines.append("## Transcript")
    lines.append("")
    for turn in turns:
        role = turn.get("role", "")
        content = turn.get("content", "").strip()
        if not content:
            continue
        if "```json" in content:
            content = content.split("```json")[0].strip()
        if role == "user":
            wm = WHITEBOARD_WRAP_RE.match(content)
            if wm:
                text = wm.group(2).strip()
                lines.append(f"**You:** {text}")
            else:
                lines.append(f"**You:** {content}")
        elif role == "assistant":
            lines.append(f"**Client:** {content}")
        lines.append("")

    return "\n".join(lines) + "\n"


@app.route("/api/export", methods=["POST"])
def export_session():
    data = request.json
    qid = data.get("question_id", "")
    if not qid:
        return jsonify({"error": "question_id required"}), 400
    decomposition = bool(data.get("decomposition"))
    chat_key = qid + (":decomposition" if decomposition else "")
    turns = CHATS.get(chat_key, [])
    if not turns:
        return jsonify({"error": f"Session not found for {chat_key}"}), 404
    q = QUESTIONS.get(qid) or V2_SCENARIOS.get(qid) or {}
    judge_result = JUDGES.get(chat_key) if decomposition else None
    md = _generate_report(qid, q, turns, judge_result)
    return md, 200, {"Content-Type": "text/markdown; charset=utf-8"}


@app.route("/api/transcribe", methods=["POST"])
def transcribe_audio():
    if not DEEPGRAM_API_KEY:
        return jsonify({"error": "Deepgram API key not configured"}), 500
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    audio_file = request.files["audio"]
    audio_bytes = audio_file.read()
    if not audio_bytes:
        return jsonify({"error": "Empty audio"}), 400
    try:
        resp = requests.post(
            "https://api.deepgram.com/v1/listen",
            headers={
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": audio_file.content_type or "audio/webm",
            },
            params={"model": "nova-2", "punctuate": "true", "language": "en"},
            data=audio_bytes,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        transcript = (
            result.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
        )
        return jsonify({"transcript": transcript})
    except Exception as e:
        return jsonify({"error": f"Transcription failed: {str(e)}"}), 500


WHITEBOARD_WRAP_RE = re.compile(r"^\[Candidate's current whiteboard\]\n(.*?)\n\n\[Candidate says\]\n(.*)$", re.S)


@app.route("/api/interview-history")
def interview_history():
    """Replays a design interview's chat turns paired with the whiteboard state as it stood at
    each turn — reuses CHATS as-is (the diagram is already embedded in each user turn's stored
    content), no separate snapshot storage needed."""
    qid = request.args.get("question_id", "")
    adversarial = request.args.get("adversarial") == "1"
    requirements_only = request.args.get("requirements_only") == "1"
    scaling = request.args.get("scaling") == "1"
    incident = request.args.get("incident") == "1"
    decomposition = request.args.get("decomposition") == "1"
    chat_key = qid + (":clarify" if requirements_only else (":adversarial" if adversarial else (":scaling" if scaling else (":incident" if incident else (":decomposition" if decomposition else "")))))

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
    scaling = args.get("scaling") == "1"
    incident = args.get("incident") == "1"
    decomposition = args.get("decomposition") == "1"
    return qid + (":clarify" if requirements_only else (":adversarial" if adversarial else (":scaling" if scaling else (":incident" if incident else (":decomposition" if decomposition else "")))))


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
        raw = chat_content(resp)
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
        raw = chat_content(resp)
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
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        flaws = [f for f in result.get("flaws", []) if f.get("concept") in taxonomy_for(q)]
        return jsonify({"diagram": result.get("diagram", []), "flaws": flaws})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/incident-scenario", methods=["POST"])
def incident_scenario():
    """Generates a vivid failure scenario for the 3am stress-test drill, grounded in
    the design question's scenario."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "design":
        return jsonify({"error": "not found"}), 404

    prompt = f"""You are a senior SRE running an incident-response drill for the scenario below.

Scenario: {q['title']}
{q['prompt']}

Generate a vivid, specific production failure scenario that could realistically happen in this system. Include:
- Which pipeline stage broke and what the symptoms are (specific alerts, error messages, dashboard readings)
- Customer impact scope (what fraction of users affected, what's visibly wrong)
- Time pressure (what time it is, how long before business impact escalates)
- One misleading clue that might send the candidate down the wrong path initially

The scenario should require the candidate to triage, diagnose, stabilize, and fix — not just re-architect.

Respond ONLY strict JSON, no markdown fences:
{{"scenario": "2-4 sentences describing the incident vividly",
  "misleading_clue": "one sentence describing a plausible red herring",
  "key_actions": ["3-4 things a strong responder would do in order"]}}"""
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=500, temperature=0.3, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        return jsonify({"scenario": result.get("scenario", ""),
                        "misleading_clue": result.get("misleading_clue", ""),
                        "key_actions": result.get("key_actions", [])})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/staff-comparison", methods=["POST"])
def staff_comparison():
    """After a design interview, generates a side-by-side 'what you said vs what a Staff
    engineer would have said' comparison at key decision points."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "design":
        return jsonify({"error": "not found"}), 404

    adversarial = bool(data.get("adversarial"))
    scaling = bool(data.get("scaling"))
    incident = bool(data.get("incident"))
    chat_key = data["question_id"] + (":adversarial" if adversarial else (":scaling" if scaling else (":incident" if incident else "")))
    turns = CHATS.get(chat_key, [])
    if len(turns) < 3:
        return jsonify({"error": "not enough conversation to compare — have a few more exchanges first"}), 400

    transcript = "\n".join(
        f"({'Interviewer' if t['role'] == 'assistant' else 'Candidate'}): {t['content']}"
        for t in turns[-20:]  # last 20 turns max
    )
    prompt = f"""You are a Staff+ Data Engineer reviewing a mock interview transcript. Identify 3-5 key decision points where the candidate's answer differed from what a Staff-level engineer would say.

For each decision point:
- "moment": what the candidate actually said (quote or paraphrase)
- "staff_says": what a Staff engineer would say instead
- "delta": the specific gap (knowledge, depth, awareness, framing)
- "why_it_matters": one sentence on the real-world consequence of this gap

Scenario: {q['title']}
{q['prompt']}

Transcript:
{transcript}

Respond ONLY strict JSON, no markdown fences:
{{"comparisons": [{{"moment": "...", "staff_says": "...", "delta": "...", "why_it_matters": "..."}}]}}"""
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=800, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        return jsonify({"comparisons": result.get("comparisons", [])})
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

    resume = PROGRESS.get("_resume")
    resume_hint = ""
    if resume:
        skills = resume.get("skills", [])[:5]
        domains = resume.get("domains", [])[:3]
        if skills or domains:
            resume_hint = f"\nThe candidate's background: skills = {', '.join(skills)}; domains = {', '.join(domains)}. Ground the scenario in their domain when possible."

    prompt = f"""You are writing a forced-choice system-design tradeoff drill for interview practice, targeting the
same underlying concept as the example below, but with a different concrete scenario (different domain,
numbers, and framing) so it can't be memorized.

Concept: {q['concept_tag'].replace('_', ' ')}
Existing example (for concept reference only — don't reuse its scenario): {q['title']} — {q['prompt']}
{resume_hint}
Respond ONLY strict JSON, no markdown fences, no commentary:
{{"title": "short scenario title, under 8 words", "prompt": "2-4 sentences posing a forced choice between two concrete options for a new scenario", "key_points": ["3-4 bullets, private grading key, what a strong justification must touch on"]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=400, temperature=0.6, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
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
        raw = chat_content(resp)
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





@app.route("/api/start")
def smart_start():
    """Phase 1: one-tap entry. Picks the single most useful question to do right now:
    a due review > a weak-area unsolved > resume-matched unsolved > otherwise the next unsolved one.
    Accepts ?lane=focused|weak|mock to bias the pick (the practice command-center lanes)."""
    lane = (request.args.get("lane") or "").strip().lower()

    # the default "focused rep" path: due review first, then weak-area, then next unsolved
    due = [qid for qid, q in QUESTIONS.items() if is_due(qid) and not is_solved(qid)]
    if not lane or lane == "focused":
        if due:
            return jsonify({"id": due[0], "reason": "due_review"})

    # weak-area bias: use recent miss topics to pick an unsolved question in a weak topic
    weak = set(recurring_missed_topics())
    unsolved = [(qid, q) for qid, q in QUESTIONS.items() if not is_solved(qid)]
    weak_hits = [(qid, q) for qid, q in unsolved if topic_for(q) in weak and q["lang"] in ("sql", "python")]
    if lane == "weak":
        if weak_hits:
            return jsonify({"id": weak_hits[0][0], "reason": "weak_area"})
        if due:
            return jsonify({"id": due[0], "reason": "due_review"})

    if (not lane or lane == "focused") and weak_hits:
        return jsonify({"id": weak_hits[0][0], "reason": "weak_area"})

    # resume-skill bias: if resume uploaded, prefer questions matching claimed skills/domains
    resume = PROGRESS.get("_resume")
    if resume:
        claimed = [s.lower() for s in resume.get("skills", []) + resume.get("domains", [])]
        if claimed:
            def _matches_resume(q):
                text = (q.get("title", "") + " " + q.get("prompt", "") + " " + q.get("concept", "")).lower()
                return any(c in text for c in claimed if len(c) > 2)
            resume_hits = [(qid, q) for qid, q in unsolved if _matches_resume(q) and q["lang"] in ("sql", "python")]
            if resume_hits:
                return jsonify({"id": random.choice(resume_hits)[0], "reason": "resume_match"})

    pool = [qid for qid, q in unsolved if q["lang"] in ("sql", "python")]
    if pool:
        return jsonify({"id": random.choice(pool), "reason": "next_unsolved"})
    design_unsolved = [qid for qid, q in QUESTIONS.items() if not is_solved(qid)]
    if design_unsolved:
        return jsonify({"id": random.choice(design_unsolved), "reason": "any"})
    return jsonify({"id": None, "reason": "none", "message": "All questions solved — pick any to review."})


@app.route("/api/streak", methods=["GET"])
def streak():
    """Phase 10: streak tracking — days with at least one practice event, plus today's count."""
    days = {}
    for h in HISTORY:
        ts = h.get("ts")
        if not ts:
            continue
        day = ts[:10]
        days[day] = days.get(day, 0) + 1
    today = datetime.now().strftime("%Y-%m-%d")
    # compute consecutive-day streak ending today (or yesterday if nothing today yet)
    streak_count = 0
    cursor = datetime.now().date()
    if today not in days:
        cursor = cursor - timedelta(days=1)
    while cursor.strftime("%Y-%m-%d") in days:
        streak_count += 1
        cursor = cursor - timedelta(days=1)
    return jsonify({
        "streak": streak_count,
        "today_count": days.get(today, 0),
        "last_active": max(days) if days else None,
    })


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


@app.route("/api/takeaways", methods=["POST"])
def takeaways():
    """Phase 2: distill a finished question/debrief into exactly 3 prioritized takeaways so
    the candidate leaves each session with a short, memorable list instead of a wall of text.
    Reuses the signals the debrief already computes (missed concepts, rubric gaps, weak topic)."""
    data = request.json or {}
    q = QUESTIONS.get(data.get("question_id", ""))
    if not q:
        return jsonify({"error": "not found"}), 404

    items = []
    if q["lang"] == "design":
        missed = data.get("missed_concepts") or []
        rubric_scores = data.get("rubric_scores") or {}
        phase_maxes = {"phase1": 8, "phase2": 10, "phase3": 6, "phase4": 8, "phase5": 6, "phase6": 6}
        weakest = sorted(((p, rubric_scores.get(p, phase_maxes[p])) for p in phase_maxes),
                         key=lambda kv: kv[1])[:2]
        for c in missed[:2]:
            items.append({"kind": "concept", "label": c.replace("_", " "),
                          "text": "Concept to go read up on — it was missing or shallow in your debrief."})
        for p, score in weakest:
            if score < phase_maxes[p]:
                items.append({"kind": "rubric", "label": p.replace("phase", "Phase "),
                              "text": f"Your weakest scored area ({score}/{phase_maxes[p]})."})
    else:
        topic = topic_for(q)
        items.append({"kind": "topic", "label": topic, "text": "Topic to revisit — this is where your recent misses cluster."})
        if data.get("complexity_ok") is False:
            items.append({"kind": "complexity", "label": "Complexity", "text": "State the time/space complexity of your solution out loud."})
        if data.get("edge_ok") is False:
            items.append({"kind": "edge", "label": "Edge cases", "text": "Name the non-trivial edge cases you'd test before submitting."})

    # pad/fill to exactly 3 from a generic fallback if short
    fallbacks = [
        {"kind": "review", "label": "Spaced review", "text": "This question is now scheduled for a spaced-review pass — come back to it soon."},
        {"kind": "explain", "label": "Teach it back", "text": "Explain your solution to an imaginary interviewer — verbalizing catches gaps."},
        {"kind": "next", "label": "One more", "text": "Do one more question in a weak area before stopping."},
    ]
    for f in fallbacks:
        if len(items) >= 3:
            break
        if f["label"] not in [i["label"] for i in items]:
            items.append(f)
    return jsonify({"takeaways": items[:3]})


@app.route("/api/review", methods=["POST"])
def review():
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q:
        return jsonify({"error": "not found"}), 404

    recall = (data.get("recall_answer") or "").strip()
    if recall:
        recall_note = (
            f"\n\nThe candidate was just asked to explain the key idea in their own words and answered:\n"
            f"\"{recall}\"\n\n"
            "In your review, first briefly validate or correct their explanation (if it's wrong or incomplete, "
            "say so plainly and fill the gap). Then give the rest of the review below, tailored to what they "
            "did and didn't grasp. "
        )
    else:
        recall_note = ""

    prompt = f"""You are a terse senior interviewer reviewing a candidate's PASSING solution — they already got it correct, this is a quality review, not a hint.

Problem: {q['title']}
{q['prompt']}
Known idiomatic approach and pitfall: {q['concept']}

Candidate's passing solution:
```{q['lang']}
{data.get('code', '')}
```
{recall_note}
Give a short, blunt code review. Respond with a single JSON object — no prose outside it, no markdown fences — with these keys (omit or use a short "" for any category with nothing worth saying):
- "readability": style/readability issues, if any
- "edge_cases": edge cases their solution might miss that the test cases didn't cover
- "followup": whether this survives a follow-up twist in a real interview
- "alternate": one alternate approach and its complexity tradeoff, if genuinely different

Keep each value to 1-2 sentences, plain text, no headers, no "great job" preamble."""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        if not raw:
            return jsonify({"error": "model returned an empty response — try again"}), 502
        sections = _parse_review_sections(raw)
        if recall:
            sections["recall"] = recall
        return jsonify({"review_sections": sections})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


def _parse_review_sections(raw):
    import re, json as _json
    text = raw.strip()
    # strip accidental code fences
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        obj = _json.loads(text)
        if isinstance(obj, dict):
            return {k: (obj.get(k) or "").strip() for k in ("readability", "edge_cases", "followup", "alternate")}
    except Exception:
        pass
    # fallback: split on labelled headers if model ignored the JSON instruction
    sections = {"readability": "", "edge_cases": "", "followup": "", "alternate": ""}
    cur = None
    for line in text.splitlines():
        low = line.lower()
        if "readab" in low or "style" in low:
            cur = "readability"
        elif "edge" in low or "corner" in low:
            cur = "edge_cases"
        elif "follow" in low or "twist" in low:
            cur = "followup"
        elif "alternat" in low or "tradeoff" in low or "approach" in low:
            cur = "alternate"
        elif cur:
            sections[cur] += line.strip() + " "
    return {k: v.strip() for k, v in sections.items()}


if __name__ == "__main__":
    app.run(debug=True, port=5050)
