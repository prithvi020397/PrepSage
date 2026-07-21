# Phase 4 refactor — persistence (verbatim from app.py).


import json
import os

from app import (
    PROGRESS_FILE, CHATS_FILE, JUDGES_FILE, REPLAY_COMMENTS_FILE,
    SUPABASE_ENABLED, sb,
    current_progress, current_chats, current_judges, current_replay_comments,
)


def _atomic_json(path, data):
    """Write JSON atomically: write to temp file, then rename. Prevents corruption on crash."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)



def save_progress():
    _atomic_json(PROGRESS_FILE, current_progress())


# ---------------------------------------------------------------------------
# Supabase multi-user auth (optional). When SUPABASE_ENABLED is False these
# endpoints return 404 and the rest of the app runs in legacy single-user mode.
# When enabled, they issue Supabase Auth JWTs and resolve the caller's id.
# ---------------------------------------------------------------------------

def save_chats():
    _atomic_json(CHATS_FILE, current_chats())



def save_judges():
    _atomic_json(JUDGES_FILE, current_judges())



def save_replay_comments():
    _atomic_json(REPLAY_COMMENTS_FILE, current_replay_comments())



def current_user_id():
    """Return the Supabase auth user id for the current request, or None.

    None means: Supabase is off, or no valid bearer token — callers should
    fall back to the legacy global PROGRESS/HISTORY/CHATS state.
    """
    if not SUPABASE_ENABLED or sb is None:
        return None
    from flask import request as _req
    return sb.get_user_id_from_request(_req)





