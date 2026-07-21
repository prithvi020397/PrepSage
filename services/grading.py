# Phase 4 refactor — judging / grading (verbatim from app.py).
import json
import re
from core.constants import CONCEPT_TAXONOMY
from services.llm import chat_content
from app import JUDGE_SYSTEM_PROMPT, JUDGE_OUTPUT_SCHEMA, client, MODEL

WHITEBOARD_WRAP_RE = re.compile(r"^\[Candidate's current whiteboard\]\n(.*?)\n\n\[Candidate says\]\n(.*)$", re.S)

def _repair_truncated_json(raw):
    """Best-effort repair of a JSON string the model cut off mid-output.

    Re-balances braces/brackets and strips a dangling trailing comma so a
    truncated judge reply can still be parsed instead of failing the whole
    scoring pass. Returns the repaired string; callers should expect a possible
    further JSONDecodeError if the content is too corrupt to salvage.
    """
    s = raw.rstrip()
    # close any unterminated string by appending a quote
    if s.count('"') % 2 == 1:
        s += '"'
    # re-balance with a depth-aware stack so closers are emitted in LIFO order
    # (handles a truncated innermost object, not just net counts).
    stack = []
    in_str = False
    esc = False
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == '\\':
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{' or ch == '[':
            stack.append(ch)
        elif ch == '}' or ch == ']':
            if stack:
                stack.pop()
    while stack:
        opener = stack.pop()
        s += '}' if opener == '{' else ']'
    # drop a trailing comma left before a closing bracket/brace
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s



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
    judge_transcript = build_judge_transcript(transcript_turns)

    system = (JUDGE_SYSTEM_PROMPT
              .replace("{scenario_json}", json.dumps(scenario_json, indent=2))
              .replace("{transcript_json}", json.dumps(judge_transcript, indent=2))
              .replace("{output_schema}", json.dumps(JUDGE_OUTPUT_SCHEMA, indent=2)))

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": "Score this session. Output JSON only."}],
            max_tokens=4096,
            temperature=0,
            extra_body={"reasoning": {"enabled": False}},
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3].strip()
        if "{" in raw and "}" in raw:
            raw = raw[raw.index("{"):raw.rindex("}") + 1]
        # ponytail: the judge reply can be long (full scenario echo + coaching).
        # If the model still truncated mid-JSON, try to repair common breakages
        # (trailing comma, unterminated string/array/object) before giving up.
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            repaired = _repair_truncated_json(raw)
            result = json.loads(repaired)
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

def build_judge_transcript(transcript_turns):
    """Convert raw chat turns ({role, content, turn?}) into the judge-facing
    transcript. Candidate turns that carry a whiteboard diagram get a structured
    `whiteboard` field so D2 (architecture) and D4 (ML formulation) can be scored
    from what was actually drawn, not just what was said."""
    judge_transcript = []
    for t in transcript_turns:
        role = "candidate" if t["role"] == "user" else "client"
        content = t["content"]
        turn = {"turn": t.get("turn", len(judge_transcript)),
                "role": role, "text": content[:2000]}
        if role == "candidate":
            wm = WHITEBOARD_WRAP_RE.match(content)
            if wm:
                diagram = wm.group(1).strip()
                if diagram:
                    turn["whiteboard"] = diagram
        judge_transcript.append(turn)
    return judge_transcript



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




