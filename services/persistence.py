# Phase 4 refactor — persistence (verbatim from app.py).


import json
import os
def _atomic_json(path, data):
    import app as _app  # lazy: full app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """Write JSON atomically: write to temp file, then rename. Prevents corruption on crash."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)



def save_progress():
    import app as _app  # lazy: full app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    _atomic_json(PROGRESS_FILE, PROGRESS)


# ---------------------------------------------------------------------------
# Supabase multi-user auth (optional). When SUPABASE_ENABLED is False these
# endpoints return 404 and the rest of the app runs in legacy single-user mode.
# When enabled, they issue Supabase Auth JWTs and resolve the caller's id.
# ---------------------------------------------------------------------------

def save_chats():
    import app as _app  # lazy: full app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    _atomic_json(CHATS_FILE, CHATS)



def save_judges():
    import app as _app  # lazy: full app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    _atomic_json(JUDGES_FILE, JUDGES)



def save_replay_comments():
    import app as _app  # lazy: full app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    _atomic_json(REPLAY_COMMENTS_FILE, REPLAY_COMMENTS)



def current_user_id():
    import app as _app  # lazy: full app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """Return the Supabase auth user id for the current request, or None.

    None means: Supabase is off, or no valid bearer token — callers should
    fall back to the legacy global PROGRESS/HISTORY/CHATS state.
    """
    if not SUPABASE_ENABLED or sb is None:
        return None
    from flask import request as _req
    return sb.get_user_id_from_request(_req)





