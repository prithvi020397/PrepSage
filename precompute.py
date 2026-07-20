import json
import os
import sys
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"]
)
MODEL = "deepseek/deepseek-v4-flash"

QUESTIONS = {q["id"]: q for q in json.load(open("questions.json"))}

TRACE_FILE = "traces.json"
CONCEPT_FILE = "concept_maps.json"
SOLUTION_FILE = "solutions.json"
CONTEXT_FILE = "question_contexts.json"
LINK_FILE = "question_concept_links.json"

# Gap concepts a JD might require. The framed-practice feature maps a candidate's real
# gaps to bank questions that BUILD the underlying pattern. Instead of a hand-authored
# dict (author assertion, unverified), we ask the LLM once, per question, which of these
# concepts the question actually exercises. Cached to LINK_FILE so runtime is free.
GAP_CONCEPTS = [
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
    "streaming_paradigm",
    "batch_paradigm",
    "feature_store",
    "cloud_platform",
    "orchestration",
    "iac",
    "warehouse",
    "sql_database",
    "container_orchestration",
    "containers",
    "pipeline_design",
    "system_design_tradeoffs",
    "architecture_decomposition",
    "data_modeling",
    "latency_throughput_tradeoffs",
]

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

PATTERN_SKELETONS = {
    "two pointers": ("Two-pointer", "left, right = 0, len(arr) - 1"),
    "sliding window": ("Sliding Window", "window_start, window_sum = 0, 0"),
    "hashing": ("Hashmap", "seen = {}"),
    "stacks / queues": ("Stack", "stack = []"),
    "dynamic programming": ("Dynamic Programming", "dp = [0] * (n + 1)"),
    "backtracking": ("Backtracking", "def backtrack(path, remaining):"),
    "graphs / BFS-DFS": ("BFS/DFS", "from collections import deque"),
    "trees": ("Tree Traversal", "def dfs(node):"),
    "linked lists": ("Linked List", "prev, curr = None, head"),
    "sorting": ("Sorting", "arr.sort()"),
    "greedy": ("Greedy", "items.sort(key=fn)"),
    "heaps": ("Heap", "import heapq"),
    "string manipulation": ("String", "result = []"),
    "intervals": ("Intervals", "intervals.sort(key=lambda x: x[0])"),
    "matrices": ("Matrix", "rows, cols = len(matrix), len(matrix[0])"),
    "recursion": ("Recursion", "def solve(state):"),
    "_default": ("General Problem-Solving", "for item in input:"),
}

SQL_PATTERN_SKELETONS = {
    "window functions": ("Window Function", "SELECT col, RANK() OVER (...)"),
    "group by / aggregation": (
        "Group By / Aggregation",
        "SELECT group_col, AGG_FUNC(value_col)",
    ),
    "joins": ("Join", "SELECT a.col, b.col FROM table_a a JOIN table_b b"),
    "subqueries": ("Subquery", "SELECT col FROM table WHERE col = (SELECT ...)"),
    "_default": ("Query Structure", "SELECT col FROM table WHERE condition"),
}


def topic_for(q):
    text = (q["title"] + " " + q["prompt"] + " " + q.get("concept", "")).lower()
    for keyword, topic in TOPIC_KEYWORDS:
        if keyword in text:
            return topic
    return "other-" + q["lang"]


def pattern_for(q):
    t = topic_for(q)
    if q["lang"] == "sql":
        return SQL_PATTERN_SKELETONS.get(t, SQL_PATTERN_SKELETONS["_default"])
    key = PATTERN_MAP.get(t, "_default")
    return PATTERN_SKELETONS.get(key, PATTERN_SKELETONS["_default"])


def load_existing(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  saved {path}")


def gen_trace(q):
    pattern_info = pattern_for(q)
    tc = q["test_cases"][0]
    sample_data = (
        tc.get("harness", "") if q["lang"] == "python" else tc.get("schema_sql", "")
    )
    sample_output = (
        tc.get("expected_stdout", "")
        if q["lang"] == "python"
        else json.dumps(tc.get("expected", []))
    )

    if q["lang"] == "sql":
        example = """Example of a good full trace for 'Second Highest Salary':
[
  {"q": "What keyword removes duplicate salaries before ranking?", "a": "SELECT DISTINCT salary"},
  {"q": "How do you sort salaries from highest to lowest?", "a": "ORDER BY salary DESC"},
  {"q": "How do you skip the first row and limit to one row to land on the second highest?", "a": "LIMIT 1 OFFSET 1"}
]"""
        prompt = f"""You are a coding tutor that teaches CODE TRANSLATION. The student knows the theory but struggles to write specific code lines. Generate trace steps that teach them WHICH CODE to write.

Problem: {q["title"]}
{q["prompt"]}
Concept: {q["concept"]}
Pattern skeleton: {pattern_info[1] if pattern_info[1] else "N/A"}

Sample call/harness: {sample_data}
Expected output: {sample_output}
Starter code: {q.get("starter_code", "")}

Generate 3-5 steps. Each step must ask about a SPECIFIC, DISTINCT line or code construct the student needs to write, in SQL. The answer is the ACTUAL CODE (not a description).

Do NOT add a final "put it all together" step.

Bad (conceptual): Q: "What do we do after filtering?" A: "Compare the string to its reverse."

Good (code-focused): Q: "What SQL keyword removes duplicates?" A: "SELECT DISTINCT salary"

{example}

Respond with ONLY JSON:
{{"steps": [{{"q": "what line of code to write?", "a": "the actual code"}}]}}"""
    else:
        prompt = f"""You are a coding tutor that teaches CODE TRANSLATION through SCAFFOLDED CODE CONSTRUCTION. The student knows the theory but struggles to write specific code lines.

Problem: {q["title"]}
{q["prompt"]}
Concept: {q["concept"]}
Pattern skeleton: {pattern_info[1] if pattern_info[1] else "N/A"}

Sample call/harness: {sample_data}
Expected output: {sample_output}
Starter code: {q.get("starter_code", "")}

Generate 4-7 steps. Each step asks for ONE specific code line the student needs to write, in the ORDER those lines appear in the function body.

Rules:
- Step 1 asks for the first substantive line after initialization
- Each later step asks for the NEXT line
- Do NOT combine multiple lines
- Do NOT add a "write the full function" final step
- The answer for each step is the ACTUAL CODE LINE

Example for 'Two Sum':
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
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        start = raw.find("{")
        end = raw.rfind("}")
        raw = raw[start : end + 1]
        result = json.loads(raw)
        steps = result.get("steps", [])
    except Exception as e:
        print(f"    trace LLM error: {e}")
        steps = [{"q": "What's the first step?", "a": "Identify the core operation."}]

    return {"trace": steps, "pattern": pattern_info[0], "skeleton": pattern_info[1]}


def gen_concept_map(q):
    prompt = f"""You are a coding tutor. For this problem, generate concise one-liner explanations for each concept-map stage.

Problem: {q["title"]}
{q["prompt"]}
Concept: {q["concept"]}

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
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700,
            temperature=0,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        start = raw.find("{")
        end = raw.rfind("}")
        raw = raw[start : end + 1]
        result = json.loads(raw)
        details = result.get("details", {})
    except Exception as e:
        print(f"    concept-map LLM error: {e}")
        details = {}

    nodes = ["Problem", "Approach", "Pattern", "Skeleton", "Solution"]
    for n in nodes:
        if n not in details:
            details[n] = {"why": "", "what_if": "", "intuition": ""}

    return {"nodes": nodes, "details": details, "active_count": 3}


def gen_question_context(q):
    """Expand a bare textbook prompt into a realistic interview framing: a believable
    business scenario, why an interviewer asks this, and the edge cases to watch. This is
    the difference between 'write a query' and a question that reads like a real interview.
    Cached to question_contexts.json so it's served instantly afterwards."""
    prompt = f"""You are rewriting a coding-interview question so it reads like a real interview prompt, not a textbook exercise.

Bare problem:
Title: {q["title"]}
Prompt: {q["prompt"]}
The concept this tests (for your judgment only — do NOT copy it verbatim): {q.get("concept", "")}

Produce THREE short fields:
- "scenario": 1-2 sentences framing this as a realistic task a data engineer / backend engineer would actually be given (a team, a system, a real reason the result is needed). Concrete, not generic. Keep it under 40 words.
- "why_asked": one sentence on what skill this question actually probes in an interview (the underlying reasoning/communication skill, not the SQL/Python mechanics). Under 25 words.
- "edge_cases": 2 short bullet-style strings of the non-obvious edge cases a candidate should consider (ties, nulls, empties, duplicates, ordering). Each under 12 words. Return as a list of 2 strings.

Respond ONLY strict JSON, no markdown fences:
{{"scenario": "...", "why_asked": "...", "edge_cases": ["...", "..."]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.3,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{") : raw.rindex("}") + 1]
        result = json.loads(raw)
        scenario = (result.get("scenario") or "").strip()
        why = (result.get("why_asked") or "").strip()
        edges = result.get("edge_cases") or []
        edges = [str(e).strip() for e in edges if str(e).strip()][:2]
        if not scenario or not why or not edges:
            raise ValueError("incomplete context")
        return {"scenario": scenario, "why_asked": why, "edge_cases": edges}
    except Exception as e:
        print(f"    context LLM error: {e}")
        return {"scenario": "", "why_asked": "", "edge_cases": []}


def gen_solution(q):
    prompt = f"""Write a correct, clean {q["lang"]} solution for this problem.

Problem: {q["title"]}
{q["prompt"]}
Concept: {q["concept"]}

Respond ONLY with the code, no markdown fences, no commentary."""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0,
            extra_body={"reasoning": {"enabled": False}},
        )
        solution = resp.choices[0].message.content.strip()
        if "```" in solution:
            for part in solution.split("```"):
                if q["lang"] in part or (
                    not part.startswith("{")
                    and not part.startswith("<")
                    and not part.startswith("[")
                ):
                    solution = part
                    if solution.startswith(q["lang"]):
                        solution = solution[len(q["lang"]) :].strip()
                    break
        return solution.strip()
    except Exception as e:
        print(f"    solution LLM error: {e}")
        return ""


def gen_concept_links(q):
    """Ask the LLM which JD gap-concepts this question actually builds. Returns a list of
    {concept, relevance (0-3), reason}. relevance 0 means 'not relevant' and is dropped by the
    caller. This replaces the hand-authored GAP_TO_QUESTIONS dict with a verifiable,
    reason-bearing mapping — every link is traceable to an LLM judgment, not an author guess."""
    concept_block = "\n".join(f"- {c}" for c in GAP_CONCEPTS)
    prompt = f"""You are auditing a coding-interview question bank for a data-engineering interview coach. For the question below, decide which of the listed CONCEPTS it genuinely helps a candidate PRACTICE or BUILD — not just concepts it incidentally touches.

Question title: {q["title"]}
Language: {q["lang"]}
Prompt: {q["prompt"]}

Concepts (pick the ones this question's SKILL transfers to — this includes system design, tradeoff analysis, and architecture decomposition skills):
{concept_block}

For each concept you judge relevant, give a relevance 1-3:
  3 = core skill the question directly teaches
  2 = meaningful secondary practice
  1 = weak / tangential transfer only
Skip concepts with no real transfer (treat as 0, do not list).

Be strict: a plain GROUP BY does NOT build 'streaming_paradigm' or 'late_data_watermarks' unless the question actually involves windowing, event-time, ordering-by-date, or dedup-by-key. A JOIN does not build 'schema_evolution_compat' unless it touches versioned/evolving schemas.

Respond ONLY strict JSON, no markdown:
{{"links": [{{"concept": "concept_key", "relevance": 2, "reason": "one-line why it transfers"}}]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.index("{") : raw.rindex("}") + 1]
        result = json.loads(raw)
        links = result.get("links", [])
        clean = []
        for link in links:
            c = link.get("concept")
            r = int(link.get("relevance", 0))
            if c in GAP_CONCEPTS and r >= 1:
                clean.append(
                    {
                        "concept": c,
                        "relevance": r,
                        "reason": str(link.get("reason", "")).strip(),
                    }
                )
        return clean
    except Exception as e:
        print(f"    link LLM error: {e}")
        return []


def main():
    traces = load_existing(TRACE_FILE)
    concepts = load_existing(CONCEPT_FILE)
    solutions = load_existing(SOLUTION_FILE)
    contexts = load_existing(CONTEXT_FILE)
    links = load_existing(LINK_FILE)

    qids = list(QUESTIONS.keys())
    done = 0
    errors = 0

    print(f"Pre-computing for {len(qids)} questions...")

    for qid in qids:
        q = QUESTIONS[qid]
        print(f"[{done + 1}/{len(qids)}] {qid}: {q['title']}")

        if qid not in contexts:
            contexts[qid] = gen_question_context(q)
            save_json(CONTEXT_FILE, contexts)
        else:
            print("  context cached")

        if qid not in traces:
            traces[qid] = gen_trace(q)
            save_json(TRACE_FILE, traces)
        else:
            print("  trace cached")

        if qid not in concepts:
            concepts[qid] = gen_concept_map(q)
            save_json(CONCEPT_FILE, concepts)
        else:
            print("  concept-map cached")

        if qid not in solutions:
            solutions[qid] = gen_solution(q)
            save_json(SOLUTION_FILE, solutions)
        else:
            print("  solution cached")

        if qid not in links:
            links[qid] = gen_concept_links(q)
            save_json(LINK_FILE, links)
        else:
            print("  concept-links cached")

        done += 1

    print(f"\nDone. {done} questions processed.")
    print(f"  contexts: {len(contexts)} questions")
    print(f"  traces: {len(traces)} questions")
    print(f"  concept_maps: {len(concepts)} questions")
    print(f"  solutions: {len(solutions)} questions")
    print(f"  concept_links: {len(links)} questions")


if __name__ == "__main__":
    main()
