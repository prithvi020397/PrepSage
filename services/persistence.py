"""Phase 4 refactor — persistence (verbatim from app.py).
Phase 1: JSON file I/O replaced with SQLite store."""
from services.state import sb, SUPABASE_ENABLED
from services.store import (
    save_progress as _store_save_progress,
    save_chats as _store_save_chats,
    save_judges as _store_save_judges,
    save_replay_comments as _store_save_replay_comments,
)


def save_progress():
    from services.state import PROGRESS
    _store_save_progress(PROGRESS)


def save_chats():
    from services.state import CHATS
    _store_save_chats(CHATS)


def save_judges():
    from services.state import JUDGES
    _store_save_judges(JUDGES)


def save_replay_comments():
    from services.state import REPLAY_COMMENTS
    _store_save_replay_comments(REPLAY_COMMENTS)


def current_user_id():
    if not SUPABASE_ENABLED or sb is None:
        return None
    from flask import request as _req
    return sb.get_user_id_from_request(_req)





