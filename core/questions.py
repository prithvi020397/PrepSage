# Phase 3 refactor — pure question/taxonomy helpers, verbatim from app.py.
from core.constants import (
    CONCEPT_TAXONOMY, CONCEPT_TAXONOMY_AI, CONCEPT_TAXONOMY_FDE,
    WAR_STORIES, WAR_STORIES_AI, WAR_STORIES_FDE,
    BASELINE_RUBRIC, BASELINE_RUBRIC_AI, BASELINE_RUBRIC_FDE,
    SQL_PATTERN_SKELETONS, PATTERN_MAP, PATTERN_SKELETONS, TOPIC_KEYWORDS,
)

def taxonomy_for(q):
    t = q.get("track")
    if t == "ai": return CONCEPT_TAXONOMY_AI
    if t == "fde": return CONCEPT_TAXONOMY_FDE
    return CONCEPT_TAXONOMY


def war_stories_for(q):
    t = q.get("track")
    if t == "ai": return WAR_STORIES_AI
    if t == "fde": return WAR_STORIES_FDE
    return WAR_STORIES


def baseline_rubric_for(q):
    t = q.get("track")
    if t == "ai": return BASELINE_RUBRIC_AI
    if t == "fde": return BASELINE_RUBRIC_FDE
    return BASELINE_RUBRIC


def persona_for(q):
    t = q.get("track")
    if t == "ai": return "senior AI/ML engineering interviewer"
    if t == "fde": return "senior forward deployed engineer interviewer"
    return "senior data engineering interviewer"


def pattern_for(q):
    t = topic_for(q)
    if q["lang"] == "sql":
        return SQL_PATTERN_SKELETONS.get(t, SQL_PATTERN_SKELETONS["_default"])
    key = PATTERN_MAP.get(t, "_default")
    return PATTERN_SKELETONS.get(key, PATTERN_SKELETONS["_default"])


def topic_for(q):
    # ponytail: decomposition/system-design scenarios use persona/triggers/rubric
    # (no flat "prompt" key), so pull whatever descriptive text exists.
    parts = [
        q.get("title", ""),
        q.get("prompt", ""),
        q.get("concept", ""),
        q.get("persona", ""),
        q.get("rubric", ""),
    ]
    triggers = q.get("triggers", [])
    if isinstance(triggers, list):
        parts.extend(triggers)
    elif isinstance(triggers, str):
        parts.append(triggers)
    desc = " ".join(str(p) for p in parts)
    text = desc.lower()
    for keyword, topic in TOPIC_KEYWORDS:
        if keyword in text:
            return topic
    return "other-" + q["lang"]
