# Phase 5 refactor — routes (verbatim from app.py).
from flask import Blueprint
from flask import jsonify, request, session, g, render_template, redirect, flash, current_app, send_file, url_for, abort

bp = Blueprint('practice', __name__)

@bp.route("/api/questions")
def list_questions():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    return jsonify([{"id": q["id"], "title": q["title"], "lang": q["lang"], "difficulty": q.get("difficulty"),
                      "solved": is_solved(q["id"]), "due": is_due(q["id"])}
                     for q in QUESTIONS.values()])



@bp.route("/api/mock-loop/start")
def mock_loop_start():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/mock-loop/report")
def mock_loop_report():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/questions/<qid>")
def get_question(qid):
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    q = QUESTIONS.get(qid)
    if not q:
        return jsonify({"error": "not found"}), 404
    if q["lang"] in ("design", "tradeoff", "decomposition"):
        # ponytail: no test_cases/starter_code for design/tradeoff/decomposition questions
        prompt = q.get("prompt", "") or q.get("persona", {}).get("opening_line", "")
        resp = {"id": q["id"], "lang": q["lang"], "title": q["title"], "prompt": prompt}
        if q["lang"] in ("design", "decomposition"):
            resp["track"] = q.get("track", "data")
        if q["lang"] == "decomposition" and q.get("archetypes"):
            resp["archetypes"] = {k: {"label": v.get("label", k)} for k, v in q["archetypes"].items()}
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



@bp.route("/api/run", methods=["POST"])
def run():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/debug", methods=["POST"])
def debug():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/diff", methods=["POST"])
def diff():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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
                log.exception("diff: unhandled exception")
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



@bp.route("/api/submit", methods=["POST"])
def submit():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/check-approach", methods=["POST"])
def check_approach():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/spot-bug", methods=["POST"])
def spot_bug():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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
        log.exception("spot_bug: unhandled exception")
        return jsonify({"error": str(e)}), 502



@bp.route("/api/spot-bug-grade", methods=["POST"])
def spot_bug_grade():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/reverse", methods=["POST"])
def reverse():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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
            log.exception("reverse: unhandled exception")
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



@bp.route("/api/curveball", methods=["POST"])
def curveball():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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
        log.exception("curveball: unhandled exception")
        return jsonify({"error": str(e)}), 502



@bp.route("/api/fresh-angle", methods=["POST"])
def fresh_angle():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/curveball-grade", methods=["POST"])
def curveball_grade():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/debrief", methods=["POST"])
def debrief():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/whatif", methods=["POST"])
def whatif():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/concept-map", methods=["POST"])
def concept_map():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/trace", methods=["POST"])
def gen_trace():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/trace-check", methods=["POST"])
def trace_check():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/api/hint", methods=["POST"])
def hint():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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




