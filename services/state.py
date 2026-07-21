"""Phase 0: mutable app state extracted from app.py.
All module-level dicts, file paths, precomputed data, and system flags live here
so they can be imported by routes, services, and app.py without circular deps."""
import json
import os

# ---------------------------------------------------------------------------
# Supabase multi-user layer (optional, degraded to None when unconfigured)
# ---------------------------------------------------------------------------
try:
    import supabase_client as sb
    SUPABASE_ENABLED = sb.SUPABASE_ENABLED
except Exception:
    sb = None
    SUPABASE_ENABLED = False

if os.environ.get("LEGACY_MODE", "").lower() in ("1", "true", "yes"):
    SUPABASE_ENABLED = False
    sb = None

# ---------------------------------------------------------------------------
# Question bank — loaded once at startup
# ---------------------------------------------------------------------------
QUESTIONS = {q["id"]: q for q in json.load(open("questions.json"))}

# ---------------------------------------------------------------------------
# Concept links (framed practice), loaded + cached lazily — see _load_concept_links
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# In-memory session state (resets on restart — fine for a local tutor)
# ---------------------------------------------------------------------------
ATTEMPTS = {}
STRUGGLES = {}
PENDING_RECALL = set()
PENDING_DRYRUN = set()

# ---------------------------------------------------------------------------
# File-backed persistent state — loaded from SQLite at startup
# Phase 1: SQLite store replaces JSON file I/O (migration from JSON on first run)
# ---------------------------------------------------------------------------
from services.store import load_all as _load_all_state

(
    PROGRESS,
    HISTORY,
    CHATS,
    JUDGES,
    REPLAY_COMMENTS,
) = _load_all_state()

# ---------------------------------------------------------------------------
# Precomputed data (generated offline by precompute.py)
# ---------------------------------------------------------------------------
PRECOMPUTED_TRACES = (
    json.load(open("traces.json")) if os.path.exists("traces.json") else {}
)
PRECOMPUTED_CONCEPTS = (
    json.load(open("concept_maps.json")) if os.path.exists("concept_maps.json") else {}
)
PRECOMPUTED_SOLUTIONS = (
    json.load(open("solutions.json")) if os.path.exists("solutions.json") else {}
)
PRECOMPUTED_CONTEXTS = (
    json.load(open("question_contexts.json"))
    if os.path.exists("question_contexts.json")
    else {}
)

# ---------------------------------------------------------------------------
# Auth tokens used in legacy/local mode
# ---------------------------------------------------------------------------
LEGACY_FAKE_TOKEN = "legacy-local-mode"
TEST_EMAIL = "test@theloop.dev"
TEST_PASSWORD = "test-loop-2024"
