# Auto-extracted constants from app.py (Phase 3 refactor). Verbatim.
PATTERN_SKELETONS = {
    "two pointers": (
        "Two-pointer",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">left, right = 0, len(arr) - 1
while left &lt; right:
    if condition:
        left += 1
    else:
        right -= 1
return result</pre>""",
    ),
    "sliding window": (
        "Sliding Window",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">window_start, window_sum = 0, 0
for window_end in range(len(arr)):
    window_sum += arr[window_end]
    while window_sum &gt; target:
        window_sum -= arr[window_start]
        window_start += 1
    if window_sum == target:
        update result</pre>""",
    ),
    "hashing": (
        "Hashmap",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">seen = {}
for i, val in enumerate(arr):
    complement = target - val
    if complement in seen:
        return [seen[complement], i]
    seen[val] = i</pre>""",
    ),
    "stacks / queues": (
        "Stack",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">stack = []
for char in s:
    if char in '({[':
        stack.append(char)
    else:
        if not stack or not matching:
            return False
        stack.pop()
return len(stack) == 0</pre>""",
    ),
    "dynamic programming": (
        "Dynamic Programming",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">dp = [0] * (n + 1)
dp[0], dp[1] = base_case_0, base_case_1
for i in range(2, n + 1):
    dp[i] = recurrence(dp[i-1], dp[i-2])
return dp[n]</pre>""",
    ),
    "backtracking": (
        "Backtracking",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">def backtrack(path, remaining):
    if goal_reached:
        result.append(path.copy())
        return
    for choice in choices:
        make_choice
        backtrack(path, remaining)
        undo_choice</pre>""",
    ),
    "graphs / BFS-DFS": (
        "BFS/DFS",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">from collections import deque
queue = deque([start])
visited = {start}
while queue:
    node = queue.popleft()
    for neighbor in graph[node]:
        if neighbor not in visited:
            visited.add(neighbor)
            queue.append(neighbor)</pre>""",
    ),
    "trees": (
        "Tree Traversal",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">def dfs(node):
    if not node:
        return 0
    left = dfs(node.left)
    right = dfs(node.right)
    return combine(left, right, node.val)</pre>""",
    ),
    "linked lists": (
        "Linked List",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">prev, curr = None, head
while curr:
    nxt = curr.next
    curr.next = prev
    prev, curr = curr, nxt
return prev</pre>""",
    ),
    "sorting": (
        "Sorting",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">arr.sort()
for i in range(len(arr)):
    if condition:
        # process</pre>""",
    ),
    "greedy": (
        "Greedy",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">items.sort(key=fn)
result = []
for item in items:
    if condition:
        result.append(item)
        update_state</pre>""",
    ),
    "heaps": (
        "Heap",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">import heapq
heap = []
for item in items:
    heapq.heappush(heap, item)
    if len(heap) &gt; k:
        heapq.heappop(heap)
return heap[0]</pre>""",
    ),
    "string manipulation": (
        "String",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">result = []
for char in s:
    if condition:
        result.append(char)
return ''.join(result)</pre>""",
    ),
    "intervals": (
        "Intervals",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">intervals.sort(key=lambda x: x[0])
merged = []
for interval in intervals:
    if not merged or interval[0] &gt; merged[-1][1]:
        merged.append(interval)
    else:
        merged[-1][1] = max(merged[-1][1], interval[1])
return merged</pre>""",
    ),
    "matrices": (
        "Matrix",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">rows, cols = len(matrix), len(matrix[0])
for r in range(rows):
    for c in range(cols):
        if condition:
            process(matrix[r][c])</pre>""",
    ),
    "recursion": (
        "Recursion",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">def solve(state):
    if base_case(state):
        return base_result
    return combine(solve(smaller_state))</pre>""",
    ),
    "_default": (
        "General Problem-Solving",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">for item in input:
    if condition:
        # update result based on item
result = ...
return result</pre>""",
    ),
}

SQL_PATTERN_SKELETONS = {
    "window functions": (
        "Window Function",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">SELECT col,
       RANK() OVER (PARTITION BY group_col ORDER BY order_col DESC) AS rnk
FROM table_name</pre>""",
    ),
    "group by / aggregation": (
        "Group By / Aggregation",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">SELECT group_col, AGG_FUNC(value_col) AS result
FROM table_name
GROUP BY group_col
HAVING condition</pre>""",
    ),
    "joins": (
        "Join",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">SELECT a.col, b.col
FROM table_a a
JOIN table_b b ON a.key = b.key
WHERE condition</pre>""",
    ),
    "subqueries": (
        "Subquery",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">SELECT col
FROM table_name
WHERE col = (
    SELECT AGG_FUNC(col)
    FROM table_name
)</pre>""",
    ),
    "_default": (
        "Query Structure",
        """<pre style="font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--card-2);padding:10px;border-radius:6px;margin:0;">SELECT col
FROM table_name
WHERE condition
ORDER BY col</pre>""",
    ),
}

TOPIC_KEYWORDS = [
    ("window function", "window functions"),
    ("over (partition", "window functions"),
    ("rank", "window functions"),
    ("running total", "window functions"),
    ("group by", "group by / aggregation"),
    ("having", "group by / aggregation"),
    ("join", "joins"),
    ("subquery", "subqueries"),
    ("self join", "joins"),
    ("recursion", "recursion"),
    ("recursive", "recursion"),
    ("dynamic programming", "dynamic programming"),
    ("dp", "dynamic programming"),
    ("graph", "graphs / BFS-DFS"),
    ("bfs", "graphs / BFS-DFS"),
    ("dfs", "graphs / BFS-DFS"),
    ("tree", "trees"),
    ("binary search tree", "trees"),
    ("linked list", "linked lists"),
    ("two pointer", "two pointers"),
    ("sliding window", "sliding window"),
    ("hash", "hashing"),
    ("dictionary", "hashing"),
    ("hashmap", "hashing"),
    ("sort", "sorting"),
    ("heap", "heaps"),
    ("priority queue", "heaps"),
    ("backtrack", "backtracking"),
    ("greedi", "greedy"),
    ("fibonacci", "dynamic programming"),
    ("kadane", "dynamic programming"),
    ("memo", "dynamic programming"),
    ("string", "string manipulation"),
    ("palindrome", "string manipulation"),
    ("interval", "intervals"),
    ("matrix", "matrices"),
    ("bit", "bit manipulation"),
    ("stack", "stacks / queues"),
    ("queue", "stacks / queues"),
    ("date", "date / time"),
    ("null", "NULL handling"),
]


PATTERN_MAP = {
    "dynamic programming": "dynamic programming",
    "graphs / BFS-DFS": "graphs / BFS-DFS",
    "trees": "trees",
    "linked lists": "linked lists",
    "two pointers": "two pointers",
    "sliding window": "sliding window",
    "hashing": "hashing",
    "sorting": "sorting",
    "heaps": "heaps",
    "backtracking": "backtracking",
    "greedy": "greedy",
    "string manipulation": "string manipulation",
    "intervals": "intervals",
    "matrices": "matrices",
    "stacks / queues": "stacks / queues",
    "bit manipulation": "hashing",
    "recursion": "recursion",
}

# ponytail: cross-cutting DE system-design concepts — shared taxonomy for baseline
# rubric items, war-stories bank, and wrap-up debrief concept classification below
CONCEPT_TAXONOMY = [
    "clarifying_requirements",
    "batch_vs_stream_choice",
    "partitioning_hot_key_skew",
    "idempotency_dedup",
    "backfill_reprocessing",
    "schema_evolution_compat",
    "replication_consistency",
    "data_quality_observability",
    "storage_format_choice",
    "late_data_watermarks",
    "domain_alignment",
    "entity_enumeration",
    "grain_awareness",
    "scd_strategy",
    "missing_dimension_audit",
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
                {
                    "id": "r1",
                    "desc": "Asks about scale — event volume, row counts, growth projections",
                    "max": 2,
                },
                {
                    "id": "r2",
                    "desc": "Asks about latency SLAs — batch hourly? streaming? sub-second?",
                    "max": 2,
                },
                {
                    "id": "r3",
                    "desc": "Asks about data sources — how many, what format, reliable or not",
                    "max": 2,
                },
                {
                    "id": "r4",
                    "desc": "Asks about consumers — who reads, how many teams, query patterns",
                    "max": 2,
                },
                {
                    "id": "r5",
                    "desc": "Asks about constraints — budget, team, timeline, compliance, existing infra",
                    "max": 2,
                },
                {
                    "id": "r6",
                    "desc": "Summarizes understanding — restates requirements before designing",
                    "max": 2,
                },
                {
                    "id": "r7",
                    "desc": "Identifies ambiguities — flags what's unclear and makes reasonable assumptions",
                    "max": 2,
                },
                {
                    "id": "r8",
                    "desc": "Defines 'done' — what does success look like for this system",
                    "max": 2,
                },
            ],
        },
        {
            "name": "Phase 2: High-Level Architecture",
            "max": 10,
            "items": [
                {
                    "id": "a1",
                    "desc": "Correct ingestion layer — picks appropriate tool for scale/latency",
                    "max": 2,
                },
                {
                    "id": "a2",
                    "desc": "Correct processing layer — batch/streaming/hybrid is appropriate",
                    "max": 2,
                },
                {
                    "id": "a3",
                    "desc": "Correct storage layer — right format, right system, right tiering",
                    "max": 2,
                },
                {
                    "id": "a4",
                    "desc": "Correct serving layer — matches consumer access patterns",
                    "max": 2,
                },
                {
                    "id": "a5",
                    "desc": "Clean data flow — sources → ingestion → processing → storage → serving",
                    "max": 2,
                },
                {
                    "id": "a6",
                    "desc": "Appropriate complexity — not over-engineered for stated scale",
                    "max": 2,
                },
                {
                    "id": "a7",
                    "desc": "Uses existing infrastructure — acknowledges what already exists",
                    "max": 2,
                },
                {
                    "id": "a8",
                    "desc": "Component naming — uses specific tools, not vague boxes",
                    "max": 2,
                },
                {
                    "id": "a9",
                    "desc": "Handles the happy path first — doesn't get bogged down in edge cases early",
                    "max": 2,
                },
                {
                    "id": "a10",
                    "desc": "Can defend against 'why not X?' — has alternatives ready",
                    "max": 2,
                },
            ],
        },
        {
            "name": "Phase 3: Deep Dive — Data Modeling",
            "max": 6,
            "items": [
                {
                    "id": "d1",
                    "desc": "Schema design — tables/entities/relationships discussed",
                    "max": 2,
                },
                {
                    "id": "d2",
                    "desc": "Partitioning strategy — chosen and explained",
                    "max": 2,
                },
                {
                    "id": "d3",
                    "desc": "File format choice — Parquet/ORC/Avro/etc with reasoning",
                    "max": 2,
                },
                {
                    "id": "d4",
                    "desc": "Schema evolution handling — forward/backward compatibility",
                    "max": 2,
                },
                {
                    "id": "d5",
                    "desc": "Deduplication strategy — how to handle duplicate records",
                    "max": 2,
                },
                {
                    "id": "d6",
                    "desc": "Data versioning — how to track changes over time",
                    "max": 2,
                },
            ],
        },
        {
            "name": "Phase 4: Deep Dive — Reliability & Fault Tolerance",
            "max": 8,
            "items": [
                {
                    "id": "f1",
                    "desc": "Late/arriving data — explicit handling mechanism",
                    "max": 2,
                },
                {
                    "id": "f2",
                    "desc": "Idempotency — reruns don't corrupt state",
                    "max": 2,
                },
                {
                    "id": "f3",
                    "desc": "Error handling — dead letter queues, retries, alerting",
                    "max": 2,
                },
                {
                    "id": "f4",
                    "desc": "Exactly-once semantics — trade-offs articulated",
                    "max": 2,
                },
                {
                    "id": "f5",
                    "desc": "Backpressure — what happens when consumer is slow",
                    "max": 2,
                },
                {
                    "id": "f6",
                    "desc": "Data quality checks — validation at ingestion and processing",
                    "max": 2,
                },
                {
                    "id": "f7",
                    "desc": "Failure isolation — one bad source doesn't kill everything",
                    "max": 2,
                },
                {
                    "id": "f8",
                    "desc": "Recovery/rollback — how to fix a bad run",
                    "max": 2,
                },
            ],
        },
        {
            "name": "Phase 5: Deep Dive — Operational Maturity",
            "max": 6,
            "items": [
                {
                    "id": "o1",
                    "desc": "Monitoring & alerting — metrics, dashboards, SLOs",
                    "max": 2,
                },
                {
                    "id": "o2",
                    "desc": "Data freshness tracking — how consumers know data is fresh",
                    "max": 2,
                },
                {
                    "id": "o3",
                    "desc": "Cost estimation — rough awareness of cloud spend",
                    "max": 2,
                },
                {
                    "id": "o4",
                    "desc": "Scaling strategy — how system grows with data",
                    "max": 2,
                },
                {
                    "id": "o5",
                    "desc": "Access control — who can read/write what",
                    "max": 2,
                },
                {
                    "id": "o6",
                    "desc": "Deployment/CI-CD — how changes get to production safely",
                    "max": 2,
                },
            ],
        },
        {
            "name": "Phase 6: Communication & Presence",
            "max": 6,
            "items": [
                {
                    "id": "c1",
                    "desc": "Structured walkthrough — clear beginning, middle, end",
                    "max": 2,
                },
                {
                    "id": "c2",
                    "desc": "Trade-off articulation — 'I chose X over Y because...'",
                    "max": 2,
                },
                {
                    "id": "c3",
                    "desc": "Handles pushback — doesn't get defensive, pivots well",
                    "max": 2,
                },
                {
                    "id": "c4",
                    "desc": "Asks for feedback — checks in with interviewer",
                    "max": 2,
                },
                {
                    "id": "c5",
                    "desc": "Time management — covers all areas without rushing",
                    "max": 2,
                },
                {
                    "id": "c6",
                    "desc": "Confidence vs humility — knows what they know and don't",
                    "max": 2,
                },
            ],
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
    "retrieval_relevance_chunking",
    "embedding_index_choice",
    "context_window_budget",
    "hallucination_grounding",
    "prompt_versioning_regression",
    "eval_observability",
    "latency_cost_tradeoff",
    "tool_use_safety",
    "agent_loop_termination",
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
    "ambiguous_problem_scoping",
    "stakeholder_mapping_alignment",
    "production_deployment_strategy",
    "legacy_enterprise_integration",
    "failure_mode_risk_analysis",
    "iterative_delivery_mvp",
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

CONCEPT_NORMALIZATION = {
    "streaming": "streaming_paradigm",
    "streaming paradigm": "streaming_paradigm",
    "stream processing": "streaming_paradigm",
    "real-time": "streaming_paradigm",
    "real time": "streaming_paradigm",
    "realtime": "streaming_paradigm",
    "streaming paradigm": "streaming_paradigm",
    "kafka": "streaming_paradigm",
    "flink": "streaming_paradigm",
    "kinesis": "streaming_paradigm",
    "event streaming": "streaming_paradigm",
    "pub/sub": "streaming_paradigm",
    "batch": "batch_paradigm",
    "batch processing": "batch_paradigm",
    "batch paradigm": "batch_paradigm",
    "etl": "batch_paradigm",
    "pyspark": "batch_paradigm",
    "spark": "batch_paradigm",
    "dataproc": "batch_paradigm",
    "cloud": "cloud_platform",
    "cloud platform": "cloud_platform",
    "cloud provider": "cloud_platform",
    "azure": "cloud_platform",
    "aws": "cloud_platform",
    "gcp": "cloud_platform",
    "google cloud": "cloud_platform",
    "databricks": "cloud_platform",
    "partitioning": "partitioning_hot_key_skew",
    "hot key": "partitioning_hot_key_skew",
    "skew": "partitioning_hot_key_skew",
    "data skew": "partitioning_hot_key_skew",
    "idempotency": "idempotency_dedup",
    "dedup": "idempotency_dedup",
    "idempotent": "idempotency_dedup",
    "exactly once": "idempotency_dedup",
    "backfill": "backfill_reprocessing",
    "reprocessing": "backfill_reprocessing",
    "replay": "backfill_reprocessing",
    "reprocess": "backfill_reprocessing",
    "schema evolution": "schema_evolution_compat",
    "watermark": "late_data_watermarks",
    "late data": "late_data_watermarks",
    "late arrival": "late_data_watermarks",
    "event time": "late_data_watermarks",
    "data quality": "data_quality_observability",
    "observability": "data_quality_observability",
    "monitoring": "data_quality_observability",
    "data validation": "data_quality_observability",
    "storage format": "storage_format_choice",
    "file format": "storage_format_choice",
    "replication": "replication_consistency",
    "consistency": "replication_consistency",
    "failover": "replication_consistency",
    "stakeholder": "domain_alignment",
    "requirements gathering": "clarifying_requirements",
    "clarifying": "clarifying_requirements",
    "scoping": "clarifying_requirements",
    "orchestration": "orchestration",
    "scheduler": "orchestration",
    "iac": "iac",
    "infrastructure as code": "iac",
    "data modeling": "data_modeling",
    "modeling": "data_modeling",
    "warehouse": "warehouse",
    "snowflake": "warehouse",
    "bigquery": "warehouse",
    "redshift": "warehouse",
    "sql": "sql_database",
    "relational": "sql_database",
    "kubernetes": "container_orchestration",
    "k8s": "container_orchestration",
    "eks": "container_orchestration",
    "aks": "container_orchestration",
    "gke": "container_orchestration",
    "containers": "containers",
    "grain": "grain_awareness",
    "star schema": "grain_awareness",
    "scd": "scd_strategy",
    "slowly changing": "scd_strategy",
    "entity": "entity_enumeration",
    "dimension": "missing_dimension_audit",
    "feature store": "feature_store",
    "feature serving": "feature_store",
    "low-latency serving": "feature_store",
    "ml platform": "feature_store",
    "pipeline design": "pipeline_design",
    "data pipeline": "pipeline_design",
    "system design": "system_design_tradeoffs",
    "architecture tradeoffs": "system_design_tradeoffs",
    "design tradeoffs": "system_design_tradeoffs",
    "tradeoff analysis": "system_design_tradeoffs",
    "decomposition": "architecture_decomposition",
    "system decomposition": "architecture_decomposition",
    "problem decomposition": "architecture_decomposition",
    "breaking down": "architecture_decomposition",
    "latency": "latency_throughput_tradeoffs",
    "throughput": "latency_throughput_tradeoffs",
    "latency vs throughput": "latency_throughput_tradeoffs",
}
