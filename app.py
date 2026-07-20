import difflib
import glob
import json
import logging
import logging.handlers
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

# Phase 0 — failure observability. Module logger writes to stderr AND a
# size-capped rotating file so production failures are debuggable. Format
# includes module:lineno so every log line shows where it fired.
_LOG_FMT = "%(asctime)s [%(levelname)s] %(name)s %(module)s:%(lineno)d %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FMT)
log = logging.getLogger("theloop")
_log_fh = logging.handlers.RotatingFileHandler(
    "theloop.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_log_fh.setLevel(logging.DEBUG)
_log_fh.setFormatter(logging.Formatter(_LOG_FMT))
log.addHandler(_log_fh)
log.setLevel(logging.DEBUG)
# Don't double-log to stderr via the root basicConfig handler.
log.propagate = False

# Phase 3 refactor — pure helpers extracted to core/ (verbatim; behavior unchanged).
# Re-exported here so existing call sites keep working without edits.
from core.constants import *  # noqa: F401,F403
from core.questions import (  # noqa: F401
    taxonomy_for, war_stories_for, baseline_rubric_for,
    persona_for, pattern_for, topic_for,
)
from core.concepts import (  # noqa: F401
    CONCEPT_NORMALIZATION, _normalize_concept, _concept_is_present,
    _translation_source, _find_translation_sibling,
)

# Per-user Supabase persistence (cloud multi-user mode).
# For authenticated requests we load the user's progress/chats/judges/replay
# from Supabase into the module globals for the request, then write them back
# on teardown. Anonymous/legacy/local requests keep using the local JSON files,
# and the existing save_*() helpers still write those as a fallback.
@app.before_request
def _req_start():
    global PROGRESS, CHATS, JUDGES, REPLAY_COMMENTS
    g._t0 = time.time()
    if request.path.startswith("/static") or request.path in ("/health", "/ping"):
        return
    if not SUPABASE_ENABLED or sb is None:
        return
    try:
        uid = sb.get_user_id_from_request(request)
    except Exception:
        uid = None
    if not uid:
        # No authenticated user: serve the shared legacy file-based state so a
        # previous authenticated user's data doesn't leak into this request.
        PROGRESS = _read_state(PROGRESS_FILE, {})
        CHATS = _read_state(CHATS_FILE, {})
        JUDGES = _read_state(JUDGES_FILE, {})
        REPLAY_COMMENTS = _read_state(REPLAY_COMMENTS_FILE, {})
        g._supabase_user = None
        g._supabase_loaded = False
        return
    # Authenticated: load this user's state for the request. Any Supabase error
    # must NEVER 500 the request — fall back to legacy file state instead.
    auth = request.headers.get("Authorization", "")
    token = auth[len("Bearer "):] if auth.startswith("Bearer ") else None
    g._supabase_user = uid
    g._supabase_token = token
    g._supabase_loaded = True
    try:
        PROGRESS = sb.load_progress(uid, token)
        CHATS = sb.load_chats(uid, token)
        JUDGES = sb.load_judges(uid, token)
        REPLAY_COMMENTS = sb.load_replay_comments(uid, token)
    except Exception:
        log.exception("before_request: Supabase load failed for %s; using legacy state", uid)
        PROGRESS = _read_state(PROGRESS_FILE, {})
        CHATS = _read_state(CHATS_FILE, {})
        JUDGES = _read_state(JUDGES_FILE, {})
        REPLAY_COMMENTS = _read_state(REPLAY_COMMENTS_FILE, {})
        g._supabase_loaded = False

@app.after_request
def _req_log(resp):
    ms = int((time.time() - getattr(g, "_t0", time.time())) * 1000)
    log.info("%s %s %s %dms", request.method, request.path, resp.status_code, ms)
    return resp

@app.teardown_request
def _persist_user_state(exc):
    uid = getattr(g, "_supabase_user", None)
    if not uid or not getattr(g, "_supabase_loaded", False):
        return
    token = getattr(g, "_supabase_token", None)
    try:
        sb.save_progress(uid, PROGRESS, token)
        sb.save_chats(uid, CHATS, token)
        sb.save_judges(uid, JUDGES, token)
        sb.save_replay_comments(uid, REPLAY_COMMENTS, token)
    except Exception:
        log.exception("teardown: failed to persist user state for %s", uid)


HEADROOM_ENABLED = os.environ.get("HEADROOM_ENABLED", "").lower() in ("1", "true", "yes")
API_BASE = "http://localhost:9090/v1" if HEADROOM_ENABLED else "https://openrouter.ai/api/v1"
client = OpenAI(base_url=API_BASE, api_key=os.environ.get("OPENROUTER_API_KEY", "sk-placeholder-not-used"),
                timeout=60, max_retries=1)
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
def _read_state(path, default):
    """Reload a JSON state file (used to restore legacy globals per request)."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

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




LEGACY_FAKE_TOKEN = "legacy-local-mode"

TEST_EMAIL = "test@theloop.dev"
TEST_PASSWORD = "test-loop-2024"


RESET_FIELDS = ("code", "trace", "pattern", "skeleton", "concept_map")


def _reset_entry(qid):
    p = PROGRESS.get(qid)
    if not isinstance(p, dict):
        return
    for f in RESET_FIELDS:
        p.pop(f, None)


def log_history(entry):
    entry["ts"] = datetime.now().isoformat()
    HISTORY.append(entry)
    _atomic_json(HISTORY_FILE, HISTORY)


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
    user_confirmed = set(jd.get("user_confirmed", []))
    if not resume:
        # JD loaded but no resume — report every required concept as unverifiable.
        # User self-attestations (user_confirmed) still move a concept out of the
        # real-gap list into self_reported so "I've done this" visibly sticks.
        real_gaps, self_reported = [], []
        for c in jd.get("concepts_required", []):
            concept = _normalize_concept(c.get("concept", ""))
            entry = {"concept": c.get("concept"), "evidence": c.get("evidence", ""),
                     "importance": c.get("importance", "must_have")}
            if concept in user_confirmed:
                self_reported.append(entry)
            else:
                real_gaps.append(entry)
        return {"jd_loaded": True, "resume_loaded": False,
                "real_gaps": real_gaps, "translations": [], "covered": [],
                "verify": [], "self_reported": self_reported,
                "real_gap_count": len(real_gaps), "translation_count": 0, "covered_count": 0,
                "verify_count": 0, "self_reported_count": len(self_reported)}

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




def _compute_role_readiness():
    """Composite role-readiness: concept coverage × resume claim validation × practice
    mastery. NOT a single reductive match score — three lenses the candidate can act on.
    Returns framed practice: which of our question bank topics exercise the JD's real gaps."""
    match = _compute_concept_match()
    if not match.get("jd_loaded"):
        return {"jd_loaded": False}

    # lens 1: concept coverage from the matcher. Verify items are uncertain — excluded
    # from both numerator and denominator so coverage reflects only confident matches.
    # Self-reported (user-confirmed) concepts DO count toward the headline coverage so
    # tapping "I've done this" makes the number visibly rise, but the count is also
    # shown separately so the reader knows how much is self-claimed vs resume-proven.
    total_concepts = (match["real_gap_count"] + match["translation_count"]
                      + match["covered_count"] + match["verify_count"] + match["self_reported_count"])
    proven = match["covered_count"] + match["translation_count"] + match["self_reported_count"]
    self_reported = match["self_reported_count"]
    # Headline = proven (resume evidence + self-claimed). verify stays in the denominator.
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


def _exec_case(q, code, case):
    if q["lang"] == "sql":
        cols, actual, err = run_sql_case(case["schema_sql"], code)
        expected = case["expected"]
    else:
        cols, actual, err = None, *run_python_case(case["harness"], code)
        expected = case["expected_stdout"]
    return cols, actual, expected, err


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

# Calibration gold transcripts: precomputed strong/borderline/weak attempts with expected
# dimension ranges, used by the "Calibrate vs gold" feature so candidates can see the gap
# between their attempt and a known-good one dimension by dimension.
CALIBRATION_FIXTURES = {}
_CALIB_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
if os.path.isdir(_CALIB_DIR):
    for _cf in glob.glob(os.path.join(_CALIB_DIR, "calibration_*.json")):
        try:
            _cd = json.load(open(_cf))
            _sid = _cd.get("scenario_id")
            if not _sid:
                continue
            CALIBRATION_FIXTURES.setdefault(_sid, []).append({
                "file": os.path.basename(_cf),
                "note": _cd.get("gold_label_note", ""),
                "expected": _cd.get("expected", {}),
            })
        except Exception:
            pass

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
                diagram_raw = wm.group(1).strip()
                lines.append(f"**You:** {text}")
                if diagram_raw:
                    lines.append("")
                    lines.append("**Whiteboard:**")
                    lines.append("```")
                    lines.append(diagram_raw)
                    lines.append("```")
            else:
                lines.append(f"**You:** {content}")
        elif role == "assistant":
            lines.append(f"**Client:** {content}")
        lines.append("")

    return "\n".join(lines) + "\n"


SOLUTION_WORDS = re.compile(r"\b(use|build|deploy|implement|kafka|kubernetes|k8s|redis|postgresql|mongodb|spark|flink|airflow|docker|terraform)\b", re.I)
CONSTRAINT_WORDS = re.compile(r"\b(budget|timeline|deadline|compliance|gdpr|hipaa|regulation|data.sovereign|privacy|security|risk|cost|bottleneck|team|stakeholder|dpo|legal)\b", re.I)
OVERSIMPLIFY_WORDS = re.compile(r"\b(we should just|obviously|clearly|trivially|easy|just need to|simply)\b", re.I)
RISK_WORDS = re.compile(r"\b(risk|fallback|backup|contingency|rollback|pilot|poc|mvp|phased|iteration|incremental|canary|blue.green)\b", re.I)


def _replay_chat_key(args):
    qid = args.get("question_id", "")
    adversarial = args.get("adversarial") == "1"
    requirements_only = args.get("requirements_only") == "1"
    scaling = args.get("scaling") == "1"
    incident = args.get("incident") == "1"
    decomposition = args.get("decomposition") == "1"
    return qid + (":clarify" if requirements_only else (":adversarial" if adversarial else (":scaling" if scaling else (":incident" if incident else (":decomposition" if decomposition else "")))))


TRADEOFF_ROLLS = {}


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




# ---------------------------------------------------------------------------
# Phase 4 refactor — services extracted to services/ (verbatim; behavior unchanged).
# Re-exported here so existing call sites keep working without edits.
# Imported at the END of the module so all app-level globals the services
# depend on (client, MODEL, PROGRESS, JUDGE_* etc.) are already defined.
# ---------------------------------------------------------------------------
from services.llm import chat_content, _call_json_extract  # noqa: E402,F401
from services.extraction import (  # noqa: E402,F401
    _ocr_with_stirling, _extract_text_from_resume, _clean_pdf_artifacts,
    _is_technical_skill, _extract_skills_from_resume, _extract_concepts_from_jd,
    _fallback_extract_jd, _fallback_extract_resume, _extraction_fallback_chain,
)
from services.execution import run_sql_case, get_sample_tables, run_python_case  # noqa: E402,F401
from services.grading import (  # noqa: E402,F401
    _repair_truncated_json, run_judge, build_judge_transcript,
    split_wrap_up_reply, hire_verdict, WHITEBOARD_WRAP_RE,
)
from services.persistence import (  # noqa: E402,F401
    _atomic_json, save_progress, save_chats, save_judges,
    save_replay_comments, current_user_id,
)



# Phase 5 refactor — routes -> blueprints (verbatim, behavior unchanged)
from routes.pages import bp as pages_bp
from routes.auth import bp as auth_bp
from routes.documents import bp as documents_bp
from routes.analytics import bp as analytics_bp
from routes.practice import bp as practice_bp
from routes.interview import bp as interview_bp

app.register_blueprint(pages_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(documents_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(practice_bp)
app.register_blueprint(interview_bp)


# Custom 404 so unknown paths (incl. /login, /signup which are overlay-only)
# render a styled page instead of Flask's default plain text.
@app.errorhandler(404)
def not_found(e):
    # Respect direct nav to the overlay-only auth routes: send them to "/",
    # where the auth overlay is reachable from any page.
    return render_template("404.html"), 404
