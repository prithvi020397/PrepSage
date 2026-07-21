"""Phase 1: SQLite persistence store replacing JSON file I/O."""
import json
import os
import sqlite3

DB_FILE = "app_state.db"

_TABLES = [
    "CREATE TABLE IF NOT EXISTS progress (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, entry TEXT)",
    "CREATE TABLE IF NOT EXISTS chats (qid TEXT, entry_id TEXT, value TEXT, PRIMARY KEY (qid, entry_id))",
    "CREATE TABLE IF NOT EXISTS judges (qid TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS replay_comments (key TEXT PRIMARY KEY, value TEXT)",
]

_JSON_FILES = {
    "progress": ("progress.json", "key"),
    "history": ("history.json", None),
    "chats": ("chats.json", None),
    "judges": ("judges.json", "qid"),
    "replay_comments": ("replay_comments.json", "key"),
}


def _get_conn():
    return sqlite3.connect(DB_FILE)


def _init_db():
    conn = _get_conn()
    for ddl in _TABLES:
        conn.execute(ddl)
    conn.commit()
    conn.close()


def _replace_all(table, items, pk_col="key"):
    _init_db()
    conn = _get_conn()
    conn.execute(f"DELETE FROM {table}")
    for k, v in items:
        conn.execute(
            f"INSERT INTO {table} ({pk_col}, value) VALUES (?, ?)",
            (k, json.dumps(v)),
        )
    conn.commit()
    conn.close()


def load_all():
    db_exists = os.path.exists(DB_FILE)
    _init_db()
    if not db_exists:
        _migrate_from_json()

    conn = _get_conn()

    progress = {}
    for row in conn.execute("SELECT key, value FROM progress"):
        progress[row[0]] = json.loads(row[1])

    history = []
    for row in conn.execute("SELECT entry FROM history ORDER BY id"):
        history.append(json.loads(row[0]))

    chats = {}
    for row in conn.execute("SELECT qid, entry_id, value FROM chats"):
        chats.setdefault(row[0], {})[row[1]] = json.loads(row[2])

    judges = {}
    for row in conn.execute("SELECT qid, value FROM judges"):
        judges[row[0]] = json.loads(row[1])

    replay_comments = {}
    for row in conn.execute("SELECT key, value FROM replay_comments"):
        replay_comments[row[0]] = json.loads(row[1])

    conn.close()
    return progress, history, chats, judges, replay_comments


def save_progress(data):
    _replace_all("progress", data.items())


def save_history(data):
    _init_db()
    conn = _get_conn()
    conn.execute("DELETE FROM history")
    for entry in data:
        conn.execute("INSERT INTO history (entry) VALUES (?)", (json.dumps(entry),))
    conn.commit()
    conn.close()


def save_chats(data):
    _init_db()
    conn = _get_conn()
    conn.execute("DELETE FROM chats")
    for qid, entries in data.items():
        for entry_id, value in entries.items():
            conn.execute(
                "INSERT INTO chats (qid, entry_id, value) VALUES (?, ?, ?)",
                (qid, entry_id, json.dumps(value)),
            )
    conn.commit()
    conn.close()


def save_judges(data):
    _replace_all("judges", data.items(), pk_col="qid")


def save_replay_comments(data):
    _replace_all("replay_comments", data.items())


def clear_all():
    _init_db()
    conn = _get_conn()
    for table in ("progress", "history", "chats", "judges", "replay_comments"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


def _migrate_from_json():
    for table, (filepath, pk_col) in _JSON_FILES.items():
        if not os.path.exists(filepath):
            continue
        with open(filepath) as f:
            data = json.load(f)
        if pk_col is None:
            if table == "history":
                save_history(data)
            elif table == "chats":
                save_chats(data)
        else:
            _replace_all(table, data.items(), pk_col=pk_col)
