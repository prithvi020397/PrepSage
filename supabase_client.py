"""Supabase client + per-user state helpers for pawscode.

This module is OPTIONAL. The app works fine without Supabase (single-user,
file-based state in progress.json / history.json / chats.json). When the
SUPABASE_URL and SUPABASE_KEY env vars are set, the helpers transparently
switch to per-user Postgres storage backed by Supabase Auth.

All public functions accept a `user_id` and fall back to the legacy file
backend when Supabase is not configured, so callers never need to branch.

The Supabase Python client (supabase-py) is imported lazily so its absence
never breaks app startup.
"""

import os
import json

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_ENABLED = bool(SUPABASE_URL and SUPABASE_KEY)

_client = None


def get_client():
    """Return the Supabase client, or None if not configured."""
    global _client
    if not SUPABASE_ENABLED:
        return None
    if _client is None:
        try:
            from supabase import create_client
            _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception:
            return None
    return _client


def get_client_with_token(access_token, refresh_token=None):
    """Return a Supabase client authenticated as the given user.

    For RLS-compliant queries: table operations use the user's JWT so
    policies like auth.uid() = user_id pass. Falls back to the anon client
    if token is None.
    """
    if not SUPABASE_ENABLED:
        return None
    c = get_client()
    if c and access_token:
        try:
            c.auth.set_session(access_token, refresh_token or "")
        except Exception:
            pass
    return c


# ---------------------------------------------------------------------------
# Legacy file backends (used when Supabase is not configured).
# ---------------------------------------------------------------------------
PROGRESS_FILE = "progress.json"
HISTORY_FILE = "history.json"
CHATS_FILE = "chats.json"
REPLAY_COMMENTS_FILE = "replay_comments.json"


def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path, data):
    import tempfile
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# progress: qid -> {solved_at, fails, due_at, code, trace, pattern, ...}
# ---------------------------------------------------------------------------
def load_progress(user_id, token=None):
    """Return {qid: {...}} for the user (or the legacy global dict).

    When token is provided, queries use the user's JWT so RLS policies pass.
    """
    if SUPABASE_ENABLED and user_id:
        c = get_client_with_token(token) if token else get_client()
        if c:
            try:
                res = c.table("progress").select("*").eq("user_id", user_id).execute()
            except Exception:
                return _read_json(PROGRESS_FILE, {})
            out = {}
            for row in (res.data or []):
                qid = row.pop("qid")
                row.pop("user_id", None)
                row.pop("updated_at", None)
                out[qid] = row
            return out
    return _read_json(PROGRESS_FILE, {})


def save_progress(user_id, progress, token=None):
    """Persist the full {qid: {...}} map for a user.

    When token is provided, upserts use the user's JWT so RLS policies pass.
    """
    if SUPABASE_ENABLED and user_id:
        c = get_client_with_token(token) if token else get_client()
        if c:
            rows = [
                {"user_id": user_id, "qid": qid, **state}
                for qid, state in progress.items()
            ]
            try:
                for row in rows:
                    c.table("progress").upsert(row).execute()
            except Exception:
                pass
            else:
                return
    _write_json(PROGRESS_FILE, progress)


def _load_json_state(user_id, table, default, token=None):
    """Load a whole-dict jsonb state row for the user (or legacy file)."""
    if SUPABASE_ENABLED and user_id:
        c = get_client_with_token(token) if token else get_client()
        if c:
            try:
                res = c.table(table).select("data").eq("user_id", user_id).maybe_single().execute()
                if res and res.data and res.data.get("data") is not None:
                    return res.data["data"]
            except Exception:
                pass
    if table == "chats":
        return _read_json(CHATS_FILE, default)
    if table == "judges":
        return _read_json(JUDGES_FILE, default)
    if table == "replay_comments":
        return _read_json(REPLAY_COMMENTS_FILE, default)
    return default


def _save_json_state(user_id, table, data, token=None):
    """Upsert a whole-dict jsonb state row for the user (or legacy file)."""
    if SUPABASE_ENABLED and user_id:
        c = get_client_with_token(token) if token else get_client()
        if c:
            try:
                c.table(table).upsert({"user_id": user_id, "data": data}).execute()
                return
            except Exception:
                pass
    if table == "chats":
        _write_json(CHATS_FILE, data)
    elif table == "judges":
        _write_json(JUDGES_FILE, data)
    elif table == "replay_comments":
        _write_json(REPLAY_COMMENTS_FILE, data)


def load_chats(user_id, token=None):
    return _json_state(user_id, "chats", {})


def save_chats(user_id, chats, token=None):
    _save_json_state(user_id, "chats", chats, token)


def load_judges(user_id, token=None):
    return _json_state(user_id, "judges", {})


def save_judges(user_id, judges, token=None):
    _save_json_state(user_id, "judges", judges, token)


def load_replay_comments(user_id, token=None):
    return _json_state(user_id, "replay_comments", {})


def save_replay_comments(user_id, comments, token=None):
    _save_json_state(user_id, "replay_comments", comments, token)


def get_user_id_from_request(request):
    """Extract the Supabase auth user id from the Authorization bearer token.

    Returns None when Supabase is disabled or the token is missing/invalid,
    which signals callers to fall back to the legacy single-user mode.
    """
    if not SUPABASE_ENABLED:
        return None
    c = get_client()
    if not c:
        return None
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[len("Bearer "):]
    try:
        user = c.auth.get_user(token)
        return user.user.id if user and user.user else None
    except Exception:
        return None
