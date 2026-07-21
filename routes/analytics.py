# Phase 5 refactor — routes (verbatim from app.py).
from datetime import datetime, timedelta

from flask import Blueprint
from flask import jsonify, request, session, g, render_template, redirect, flash, current_app, send_file, url_for, abort

from app import HISTORY, QUESTIONS, client, MODEL, log, current_progress, _parse_review_sections
from core.questions import topic_for
from services.llm import chat_content
from services.persistence import save_progress

bp = Blueprint('analytics', __name__)

@bp.route("/api/deadline", methods=["GET", "POST"])
def deadline():
    # ponytail: reuses PROGRESS's flat dict with a reserved "_deadline" key instead of a new file —
    # every PROGRESS.items() loop elsewhere already guards with `oid in QUESTIONS`, so this is safe.
    progress = current_progress()
    if request.method == "POST":
        date_str = (request.json or {}).get("deadline", "").strip()
        if date_str:
            datetime.fromisoformat(date_str)  # raises ValueError -> 500 on bad input, fine for a solo local tool
            progress["_deadline"] = {"date": date_str}
        else:
            progress.pop("_deadline", None)
        save_progress()
    d = progress.get("_deadline")
    return jsonify({"deadline": d["date"] if isinstance(d, dict) else None})



@bp.route("/api/streak", methods=["GET"])
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



@bp.route("/api/takeaways", methods=["POST"])
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



@bp.route("/api/review", methods=["POST"])
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
        log.exception("review: unhandled exception")
        return jsonify({"error": str(e)}), 502




