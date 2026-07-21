# Phase 5 refactor — routes (verbatim from app.py).
import json
import re
from datetime import datetime

from flask import Blueprint
from flask import jsonify, request, session, g, render_template, redirect, flash, current_app, send_file, url_for, abort

from app import (
    client, MODEL, log, QUESTIONS, HISTORY, is_solved, is_due, current_progress,
    _stamp_taxonomy, _compute_concept_match, _compute_role_readiness,
)
from core.constants import CONCEPT_TAXONOMY
from core.concepts import _normalize_concept
from services.llm import chat_content, _call_json_extract
from services.persistence import save_progress
from services.extraction import (
    _extract_text_from_resume, _clean_pdf_artifacts, _extraction_fallback_chain,
    _extract_concepts_from_jd, _fallback_extract_jd,
    _extract_skills_from_resume, _fallback_extract_resume,
)

bp = Blueprint('documents', __name__)

from services.state import (
    PROGRESS, HISTORY, QUESTIONS, ATTEMPTS, STRUGGLES, PENDING_RECALL, PENDING_DRYRUN,
    CHATS, REPLAY_COMMENTS, JUDGES,
    sb, SUPABASE_ENABLED, LEGACY_FAKE_TOKEN, TEST_EMAIL, TEST_PASSWORD,
    PRECOMPUTED_SOLUTIONS, PRECOMPUTED_CONCEPTS, PRECOMPUTED_TRACES,
)
from services.persistence import save_progress, save_chats, save_judges, save_replay_comments, current_user_id
from core.constants import *
from app import (
    log, client, MODEL,
    is_solved, is_due, schedule_review, _reset_entry,
    _compute_gap_alerts, _compute_study_plan, _compute_claim_validation,
    _compute_concept_match, _compute_role_readiness,
    _stamp_taxonomy, _exec_case, _gen_question_context,
    _generate_report, _replay_chat_key, _parse_review_sections,
    recurring_missed_concepts, recurring_missed_topics,
    CONCEPT_NORMALIZATION,
    _normalize_concept, _extract_text_from_resume, _clean_pdf_artifacts,
    _extraction_fallback_chain, _extract_concepts_from_jd, _fallback_extract_jd,
    _extract_skills_from_resume, _fallback_extract_resume,
    _call_json_extract,
    WHITEBOARD_WRAP_RE, JUDGE_SYSTEM_PROMPT, JUDGE_OUTPUT_SCHEMA,
    JD_CONCEPT_TRANSLATIONS,
    CALIBRATION_FIXTURES,
    ADVERSARIAL_PERSONAS, ADVERSARIAL_RULES, PERSONAS, SCALING_TIERS,
    INCIDENT_RULES, V2_SCENARIOS, JUDGE_RUBRIC,
    DEEPGRAM_API_KEY,
    CONSTRAINT_WORDS, OVERSIMPLIFY_WORDS, RISK_WORDS,
    TRADEOFF_ROLLS, SOLUTION_CACHE,
)
import json, re, os

@bp.route("/api/upload-jd", methods=["POST"])
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
    current_progress()["_jd"] = jd_data
    save_progress()
    return jsonify({"ok": True, "role_title": jd_data.get("role_title"),
                    "seniority": jd_data.get("seniority"),
                    "domain": jd_data.get("domain"),
                    "concepts_required": len(jd_data.get("concepts_required", [])),
                    "tool_keywords": jd_data.get("tool_keywords", [])})



@bp.route("/api/jd", methods=["GET"])
def get_jd():
    """Return stored JD concept data or empty."""
    return jsonify(current_progress().get("_jd", {}))



@bp.route("/api/set-profile", methods=["POST"])
def set_profile():
    """Generate a synthetic JD profile from role + industry + cloud via direct LLM prompt."""
    data = request.json or {}
    role = (data.get("role") or "").strip()
    industry = (data.get("industry") or "").strip()
    cloud = (data.get("cloud") or "").strip()
    if not role:
        return jsonify({"error": "Role is required"}), 400
    resume = current_progress().get("_resume")
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
    current_progress()["_jd"] = jd_data
    save_progress()
    return jsonify({"ok": True, "role_title": jd_data.get("role_title"),
                    "concepts_required": len(jd_data.get("concepts_required", [])),
                    "synthetic": True})



@bp.route("/api/upload-jd-text", methods=["POST"])
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
    current_progress()["_jd"] = jd_data
    save_progress()
    return jsonify({"ok": True, "role_title": jd_data.get("role_title"),
                    "seniority": jd_data.get("seniority"),
                    "domain": jd_data.get("domain"),
                    "concepts_required": len(jd_data.get("concepts_required", [])),
                    "tool_keywords": jd_data.get("tool_keywords", [])})



@bp.route("/api/upload-resume", methods=["POST"])
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
    current_progress()["_resume"] = skills_data
    save_progress()
    # build summary for response
    skill_names = [s.get("name", s) if isinstance(s, dict) else s for s in skills_data.get("skills", [])]
    return jsonify({"ok": True, "skills": skill_names, "domains": skills_data.get("domains", []),
                     "projects_count": len(skills_data.get("projects", [])),
                     "target_role": skills_data.get("target_role"),
                     "strongest_skills": skills_data.get("strongest_skills", [])})



@bp.route("/api/resume", methods=["GET"])
def get_resume():
    """Return stored resume data (skills, projects, domains) or empty."""
    return jsonify(current_progress().get("_resume", {}))



@bp.route("/api/gap-alert", methods=["GET"])
def gap_alert():
    """Compare resume-claimed skills against actual performance data.
    Returns a list of gaps: claimed skill with low or no accuracy."""
    resume = current_progress().get("_resume")
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



@bp.route("/api/talk-about", methods=["POST"])
def talk_about():
    """Generate interview follow-up questions for a resume project.
    Uses rich project data from resume extraction (specificity, interview probes)."""
    data = request.json
    project_name = data.get("project_name", "")
    project_tech = data.get("tech", [])
    project_desc = data.get("one_liner", "")

    resume = current_progress().get("_resume", {})
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
        log.exception("talk_about: unhandled exception")
        return jsonify({"error": str(e)}), 502



@bp.route("/api/study-plan", methods=["GET"])
def study_plan():
    """Generate a personalized study plan based on resume + performance data."""
    resume = current_progress().get("_resume")
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
    due = sum(1 for qid in current_progress() if is_due(qid))

    # deadline info
    deadline_info = ""
    deadline = current_progress().get("_deadline")
    if isinstance(deadline, dict) and deadline.get("date"):
        days_left = (datetime.fromisoformat(deadline["date"]) - datetime.now()).days
        deadline_info = f"\nInterview in {days_left} days."

    practice_summary = "\n".join(practice_lines) if practice_lines else "  No practice data yet."

    prompt = f"""You are a technical interview coach creating a personalized weekly study plan.

Candidate profile:
- Target role: {target_role}
- Strongest skills (from resume): {', '.join(strongest) if strongest else 'unknown'}
- Skills needing validation (shallow/no context): {', '.join(weakest) if weakest else 'unknown'}
- Resume domains: {', '.join(d.get('name') if isinstance(d, dict) else d for d in resume.get('domains', [])[:5])}

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



@bp.route("/api/claim-validation", methods=["GET"])
def claim_validation():
    """Track which resume claims have been validated by practice performance."""
    resume = current_progress().get("_resume")
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



@bp.route("/api/jd-gap", methods=["GET"])
def jd_gap():
    """Tool-to-concept gap analysis between the loaded JD and resume."""
    return jsonify(_compute_concept_match())



@bp.route("/api/jd-confirm", methods=["POST"])
def jd_confirm():
    """Self-attest that a JD concept has been handled (even if the resume didn't
    evidence it). Stored on the JD record so it persists across re-renders and
    re-uploads. Toggling the same concept off removes the confirmation."""
    progress = current_progress()
    jd = progress.get("_jd")
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
    progress["_jd"] = jd
    save_progress()
    return jsonify({"ok": True, "user_confirmed": sorted(confirmed)})



@bp.route("/api/role-readiness", methods=["GET"])
def role_readiness():
    """Composite readiness + framed practice for the loaded JD."""
    return jsonify(_compute_role_readiness())



@bp.route("/api/reparse-stale", methods=["POST"])
def reparse_stale():
    """Re-extract concepts from stored raw text when taxonomy changes.
    Returns the number of concepts extracted for both resume and JD."""
    progress = current_progress()
    jd = progress.get("_jd")
    resume = progress.get("_resume")
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
            progress["_jd"] = jd_data
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
            progress["_resume"] = skills_data
            result["resume"] = len(skills_data.get("skills", []))
    save_progress()
    return jsonify({"ok": True, **result})




