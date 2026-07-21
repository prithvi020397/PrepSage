# Phase 5 refactor — routes (verbatim from app.py).
from datetime import datetime

from flask import Blueprint
from flask import jsonify, request, session, g, render_template, redirect, flash, current_app, send_file, url_for, abort

from app import (
    QUESTIONS, HISTORY, is_solved, current_progress,
    _compute_role_readiness, _compute_gap_alerts, _compute_study_plan,
    _compute_claim_validation, _compute_concept_match,
)
from core.constants import CONCEPT_TAXONOMY, CONCEPT_TAXONOMY_AI, CONCEPT_TAXONOMY_FDE, WAR_STORIES
from core.concepts import CONCEPT_NORMALIZATION
from services.persistence import save_progress

bp = Blueprint('pages', __name__)

@bp.route("/")
def index():
    # Show onboarding for new users (no progress, no deadline set)
    progress = current_progress()
    has_progress = any(is_solved(qid) for qid in progress if qid in QUESTIONS)
    has_deadline = isinstance(progress.get("_deadline"), dict) and progress["_deadline"].get("date")
    if not has_progress and not has_deadline:
        return redirect("/onboarding")
    return redirect("/dashboard")



@bp.route("/taxonomy")
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



@bp.route("/practice")
def practice():
    jd = current_progress().get("_jd", {})
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



@bp.route("/onboarding")
def onboarding():
    return render_template("onboarding.html")



@bp.route("/api/onboarding", methods=["POST"])
def save_onboarding():
    data = request.json or {}
    deadline = data.get("deadline", "").strip()
    strongest = data.get("strongest", "").strip()
    weakest = data.get("weakest", "").strip()
    progress = current_progress()
    if deadline:
        try:
            datetime.fromisoformat(deadline)
            progress["_deadline"] = {"date": deadline}
        except ValueError:
            pass
    progress["_onboarding"] = {"strongest": strongest, "weakest": weakest}
    save_progress()
    return jsonify({"ok": True})



@bp.route("/dashboard")
def dashboard():
    progress = current_progress()
    total_questions = len(QUESTIONS)
    total_solved = sum(1 for qid in progress if is_solved(qid))
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
        resume_loaded=bool(progress.get("_resume")),
        resume=progress.get("_resume", {}),
        gap_alerts=_compute_gap_alerts(),
        study_plan=_compute_study_plan(),
        claim_validation=_compute_claim_validation(),
        jd_loaded=bool(progress.get("_jd")),
        jd=progress.get("_jd", {}),
        jd_synthetic=bool((progress.get("_jd") or {}).get("synthetic")),
        concept_match=_compute_concept_match(),
        role_readiness=role_readiness,
        first_use=(total_solved == 0 and bool(progress.get("_jd")) and bool(progress.get("_resume"))),
        jd_concept_list=jd_concept_list,
        coverage_signal=coverage_signal,
        reparse_available=bool(
            (progress.get("_jd") or {}).get("raw_text")
            or (progress.get("_resume") or {}).get("raw_text")
        ),
    )



@bp.route("/favicon.ico")
def favicon():
    return "", 204

# The Loop: single-user local interview prep platform


