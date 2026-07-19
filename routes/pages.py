# Phase 5 refactor — routes (verbatim from app.py).
from flask import Blueprint
from flask import jsonify, request, session, g, render_template, redirect, flash, current_app, send_file, url_for, abort

bp = Blueprint('pages', __name__)

@bp.route("/")
def index():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    # Show onboarding for new users (no progress, no deadline set)
    has_progress = any(is_solved(qid) for qid in PROGRESS if qid in QUESTIONS)
    has_deadline = isinstance(PROGRESS.get("_deadline"), dict) and PROGRESS["_deadline"].get("date")
    if not has_progress and not has_deadline:
        return redirect("/onboarding")
    return redirect("/dashboard")



@bp.route("/taxonomy")
def taxonomy():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/onboarding")
def onboarding():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    return render_template("onboarding.html")



@bp.route("/api/onboarding", methods=["POST"])
def save_onboarding():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/dashboard")
def dashboard():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
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



@bp.route("/favicon.ico")
def favicon():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    return "", 204

# The Loop: single-user local interview prep platform


