# Phase 1: SQLite Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace JSON file persistence for 5 state dicts (PROGRESS, HISTORY, CHATS, JUDGES, REPLAY_COMMENTS) with SQLite-backed store.

**Architecture:** Create `services/store.py` as a standalone SQLite wrapper with load/save/clear_all/migrate_from_json. Each of the 5 dicts gets one table with a JSON-blob value column. Load at startup from SQLite, save on mutation to SQLite. One-shot migration from existing JSON files on first run.

**Tech Stack:** Python sqlite3 (stdlib), no new dependencies.

## Global Constraints

- Zero behavior change — 72 existing tests must pass unchanged
- No new dependencies (sqlite3 is stdlib)
- DB file: `app_state.db` in the app root
- JSON files remain on disk (not deleted) for rollback
- Read-only JSON files (`questions.json`, `solutions.json`, etc.) stay as-is
- Ephemeral dicts (`ATTEMPTS`, `STRUGGLES`, `PENDING_RECALL`, `PENDING_DRYRUN`) stay in-memory

---

### Task 1: `services/store.py` core + tests

**Files:**
- Create: `services/store.py`
- Create: `tests/test_store.py`

**Interfaces:**
- Produces: `store.load_all() -> tuple[dict, list, dict, dict, dict]`, `store.save_progress(dict)`, `store.save_history(list)`, `store.save_chats(dict)`, `store.save_judges(dict)`, `store.save_replay_comments(dict)`, `store.clear_all()`, `store.db_path` (for test setup)

- [ ] **Step 1: Write the test file**

```python
"""Tests for services/store.py — SQLite persistence layer."""
import json, os, tempfile, pytest
from unittest.mock import patch

@pytest.fixture
def temp_db():
    """Run tests against a temporary SQLite DB so we never touch the real one."""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    with patch("services.store.DB_FILE", db_path):
        # Ensure a clean start
        if os.path.exists(db_path):
            os.remove(db_path)
        yield db_path
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)
    os.rmdir(tmpdir)

SAMPLE_PROGRESS = {"_deadline": {"date": "2026-08-01"}, "q-1": {"solved": True, "attempts": 3}}
SAMPLE_HISTORY = [{"qid": "q-1", "event": "submit", "passed": True, "ts": "2026-01-01T00:00:00"}]
SAMPLE_CHATS = {"q-1": {"entry-1": {"role": "user", "content": "hello"}}}
SAMPLE_JUDGES = {"q-1": {"score": 85, "verdict": "hire"}}
SAMPLE_REPLAY_COMMENTS = {"q-1-entry-1": {"comment": "good approach"}}

class TestStoreLoadAll:
    def test_load_all_empty_db_returns_empty_state(self, temp_db):
        from services.store import load_all
        progress, history, chats, judges, replay = load_all()
        assert progress == {}
        assert history == []
        assert chats == {}
        assert judges == {}
        assert replay == {}

    def test_round_trip(self, temp_db):
        from services.store import load_all, save_progress, save_history, save_chats, save_judges, save_replay_comments
        save_progress(SAMPLE_PROGRESS)
        save_history(SAMPLE_HISTORY)
        save_chats(SAMPLE_CHATS)
        save_judges(SAMPLE_JUDGES)
        save_replay_comments(SAMPLE_REPLAY_COMMENTS)
        p, h, c, j, r = load_all()
        assert p == SAMPLE_PROGRESS
        assert h == SAMPLE_HISTORY
        assert c == SAMPLE_CHATS
        assert j == SAMPLE_JUDGES
        assert r == SAMPLE_REPLAY_COMMENTS

    def test_overwrite_clears_old_data(self, temp_db):
        from services.store import load_all, save_progress
        save_progress({"old-key": "old-val"})
        save_progress(SAMPLE_PROGRESS)
        p, _, _, _, _ = load_all()
        assert p == SAMPLE_PROGRESS

    def test_clear_all_empties_all_tables(self, temp_db):
        from services.store import load_all, save_progress, save_history, clear_all
        save_progress(SAMPLE_PROGRESS)
        save_history(SAMPLE_HISTORY)
        clear_all()
        p, h, _, _, _ = load_all()
        assert p == {}
        assert h == []

class TestStoreMigration:
    def test_migrate_from_json_files(self, temp_db):
        import tempfile
        # Write JSON files into a temp dir and patch the paths
        tmpdir = os.path.dirname(temp_db)
        def _patch_json(file_name):
            return os.path.join(tmpdir, file_name)
        with open(_patch_json("progress.json"), "w") as f:
            json.dump(SAMPLE_PROGRESS, f)
        with open(_patch_json("history.json"), "w") as f:
            json.dump(SAMPLE_HISTORY, f)
        with open(_patch_json("chats.json"), "w") as f:
            json.dump(SAMPLE_CHATS, f)
        with open(_patch_json("judges.json"), "w") as f:
            json.dump(SAMPLE_JUDGES, f)
        with open(_patch_json("replay_comments.json"), "w") as f:
            json.dump(SAMPLE_REPLAY_COMMENTS, f)

        from services.store import load_all, DB_FILE
        # delete the DB so migration triggers
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        # We need to patch the JSON file paths inside load_all/_migrate_from_json
        # Since they hardcode "progress.json" etc., we run from tmpdir
        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            p, h, c, j, r = load_all()
            assert p == SAMPLE_PROGRESS
            assert h == SAMPLE_HISTORY
            assert c == SAMPLE_CHATS
            assert j == SAMPLE_JUDGES
            assert r == SAMPLE_REPLAY_COMMENTS
        finally:
            os.chdir(old_cwd)

    def test_migration_skipped_if_db_exists(self, temp_db):
        """If DB already exists, don't re-migrate even if JSON files exist."""
        from services.store import save_progress, load_all
        save_progress({"manually-set": True})
        # Write a stale JSON file
        import tempfile
        tmpdir = os.path.dirname(temp_db)
        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            with open("progress.json", "w") as f:
                json.dump({"stale": "data"}, f)
            p, _, _, _, _ = load_all()
            assert p == {"manually-set": True}  # not the stale JSON
        finally:
            os.chdir(old_cwd)
        os.remove(os.path.join(tmpdir, "progress.json"))

class TestStoreEdgeCases:
    def test_empty_dict_values(self, temp_db):
        from services.store import load_all, save_progress, save_chats
        save_progress({"empty-dict": {}})
        save_chats({"q-1": {}})
        p, _, c, _, _ = load_all()
        assert p == {"empty-dict": {}}
        assert c == {"q-1": {}}

    def test_special_chars_in_keys(self, temp_db):
        from services.store import load_all, save_progress
        save_progress({"key/with/slashes": {"nested": True}, "key.with.dots": "val"})
        p, _, _, _, _ = load_all()
        assert p == {"key/with/slashes": {"nested": True}, "key.with.dots": "val"}
```

- [ ] **Step 2: Create `services/store.py`**

```python
"""Phase 1: SQLite persistence store replacing JSON file I/O.

Each of the 5 file-backed state dicts gets one table with a JSON-blob value column.
On first startup, migrates existing JSON files into SQLite automatically.
Read-only JSON (questions.json, solutions.json, etc.) and ephemeral in-memory
dicts (ATTEMPTS, STRUGGLES, PENDING_RECALL, PENDING_DRYRUN) are NOT touched.
"""
import json
import os
import sqlite3

DB_FILE = "app_state.db"

_TABLES = {
    "progress": "CREATE TABLE IF NOT EXISTS progress (key TEXT PRIMARY KEY, value TEXT)",
    "history": "CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, entry TEXT)",
    "chats": "CREATE TABLE IF NOT EXISTS chats (qid TEXT, entry_id TEXT, value TEXT, PRIMARY KEY (qid, entry_id))",
    "judges": "CREATE TABLE IF NOT EXISTS judges (qid TEXT PRIMARY KEY, value TEXT)",
    "replay_comments": "CREATE TABLE IF NOT EXISTS replay_comments (key TEXT PRIMARY KEY, value TEXT)",
}

_JSON_FILES = {
    "progress": ("progress.json", True),
    "history": ("history.json", False),
    "chats": ("chats.json", False),
    "judges": ("judges.json", True),
    "replay_comments": ("replay_comments.json", True),
}


def _get_conn():
    return sqlite3.connect(DB_FILE)


def _init_db():
    conn = _get_conn()
    for ddl in _TABLES.values():
        conn.execute(ddl)
    conn.commit()
    conn.close()


def _replace_all(table, items, pk_col="key"):
    """DELETE all rows, then INSERT all items. Single transaction."""
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
    """Load all persisted state. Returns (progress, history, chats, judges, replay_comments)."""
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
    conn = _get_conn()
    conn.execute("DELETE FROM history")
    for entry in data:
        conn.execute("INSERT INTO history (entry) VALUES (?)", (json.dumps(entry),))
    conn.commit()
    conn.close()


def save_chats(data):
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
    conn = _get_conn()
    for table in _TABLES:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


def _migrate_from_json():
    """One-shot migration from JSON files to SQLite. Only called when DB didn't exist before _init_db."""
    for table, filepath, is_dict in [
        ("progress", "progress.json", True),
        ("history", "history.json", False),
        ("chats", "chats.json", False),
        ("judges", "judges.json", True),
        ("replay_comments", "replay_comments.json", True),
    ]:
        if not os.path.exists(filepath):
            continue
        with open(filepath) as f:
            data = json.load(f)
        if table == "history":
            save_history(data)
        elif table == "chats":
            save_chats(data)
        else:
            _replace_all(table, data.items(), pk_col="key" if is_dict else "value")
```

Wait, the `_migrate_from_json` signature is wrong. Let me fix it — I don't need the list of tuples, I can use _JSON_FILES. But `_JSON_FILES` uses (path, is_dict) tuples. Let me simplify.

Actually, let me just rewrite _migrate_from_json more cleanly:

```python
def _migrate_from_json():
    for table, (filepath, is_dict) in _JSON_FILES.items():
        if not os.path.exists(filepath):
            continue
        with open(filepath) as f:
            data = json.load(f)
        if table == "history":
            save_history(data)
        elif table == "chats":
            save_chats(data)
        else:
            _replace_all(table, data.items(), pk_col="key" if is_dict else "qid")
```

Hmm, the pk_col for judges is "qid", for progress and replay_comments it's "key". Let me add that to _JSON_FILES.

OK, I think the code in the plan should be correct. Let me refine the plan.

Actually wait, I think the plan should have cleaner code. Let me be more precise.<｜end▁of▁thinking｜>

<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="write">
<｜｜DSML｜｜parameter name="content" string="true"># Phase 1: SQLite Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace JSON file persistence for 5 state dicts (PROGRESS, HISTORY, CHATS, JUDGES, REPLAY_COMMENTS) with SQLite-backed store.

**Architecture:** Create `services/store.py` as a standalone SQLite wrapper with load/save/clear_all/migrate_from_json. Each of the 5 dicts gets one table with a JSON-blob value column. Load at startup from SQLite, save on mutation to SQLite. One-shot migration from existing JSON files on first run.

**Tech Stack:** Python sqlite3 (stdlib), no new dependencies.

## Global Constraints

- Zero behavior change — 72 existing tests must pass unchanged
- No new dependencies (sqlite3 is stdlib)
- DB file: `app_state.db` in the app root
- JSON files remain on disk (not deleted) for rollback
- Read-only JSON files (`questions.json`, `solutions.json`, etc.) stay as-is
- Ephemeral dicts (`ATTEMPTS`, `STRUGGLES`, `PENDING_RECALL`, `PENDING_DRYRUN`) stay in-memory

---

### Task 1: `services/store.py` core + tests

**Files:**
- Create: `services/store.py`
- Create: `tests/test_store.py`

**Interfaces:**
- Produces: `store.load_all() -> tuple[dict, list, dict, dict, dict]`, `store.save_progress(dict)`, `store.save_history(list)`, `store.save_chats(dict)`, `store.save_judges(dict)`, `store.save_replay_comments(dict)`, `store.clear_all()`, `store.DB_FILE` (for test patching)

- [ ] **Step 1: Write the test file `tests/test_store.py`**

```python
"""Tests for services/store.py — SQLite persistence layer."""
import json, os, tempfile, pytest
from unittest.mock import patch

pytest_plugins = []  # no external plugins needed

FIXTURE_DIR = None  # set by fixture

def _db_path():
    return os.path.join(FIXTURE_DIR, "test.db")

@pytest.fixture(autouse=True)
def tmp_workdir(monkeypatch):
    """Run every test in a temp dir so JSON paths resolve there, and patch DB_FILE."""
    global FIXTURE_DIR
    FIXTURE_DIR = tempfile.mkdtemp()
    monkeypatch.chdir(FIXTURE_DIR)
    import services.store as store
    monkeypatch.setattr(store, "DB_FILE", _db_path())
    yield
    import shutil
    shutil.rmtree(FIXTURE_DIR, ignore_errors=True)

SAMPLE_PROGRESS = {"_deadline": {"date": "2026-08-01"}, "q-1": {"solved": True, "attempts": 3}}
SAMPLE_HISTORY = [{"qid": "q-1", "event": "submit", "passed": True, "ts": "2026-01-01T00:00:00"}]
SAMPLE_CHATS = {"q-1": {"entry-1": {"role": "user", "content": "hello"}}}
SAMPLE_JUDGES = {"q-1": {"score": 85, "verdict": "hire"}}
SAMPLE_REPLAY_COMMENTS = {"q-1-entry-1": {"comment": "good approach"}}


class TestStoreLoadAll:
    def test_load_all_empty_db_returns_empty_state(self):
        from services.store import load_all
        progress, history, chats, judges, replay = load_all()
        assert progress == {}
        assert history == []
        assert chats == {}
        assert judges == {}
        assert replay == {}

    def test_round_trip(self):
        from services.store import load_all, save_progress, save_history, save_chats, save_judges, save_replay_comments
        save_progress(SAMPLE_PROGRESS)
        save_history(SAMPLE_HISTORY)
        save_chats(SAMPLE_CHATS)
        save_judges(SAMPLE_JUDGES)
        save_replay_comments(SAMPLE_REPLAY_COMMENTS)
        p, h, c, j, r = load_all()
        assert p == SAMPLE_PROGRESS
        assert h == SAMPLE_HISTORY
        assert c == SAMPLE_CHATS
        assert j == SAMPLE_JUDGES
        assert r == SAMPLE_REPLAY_COMMENTS

    def test_overwrite_clears_old_data(self):
        from services.store import load_all, save_progress
        save_progress({"old-key": "old-val"})
        save_progress(SAMPLE_PROGRESS)
        p, _, _, _, _ = load_all()
        assert p == SAMPLE_PROGRESS

    def test_clear_all_empties_all_tables(self):
        from services.store import load_all, save_progress, save_history, clear_all
        save_progress(SAMPLE_PROGRESS)
        save_history(SAMPLE_HISTORY)
        clear_all()
        p, h, _, _, _ = load_all()
        assert p == {}
        assert h == []


class TestStoreMigration:
    def test_migrate_from_json_files(self):
        from services.store import load_all
        for name, data in [
            ("progress.json", SAMPLE_PROGRESS),
            ("history.json", SAMPLE_HISTORY),
            ("chats.json", SAMPLE_CHATS),
            ("judges.json", SAMPLE_JUDGES),
            ("replay_comments.json", SAMPLE_REPLAY_COMMENTS),
        ]:
            with open(name, "w") as f:
                json.dump(data, f)
        p, h, c, j, r = load_all()
        assert p == SAMPLE_PROGRESS
        assert h == SAMPLE_HISTORY
        assert c == SAMPLE_CHATS
        assert j == SAMPLE_JUDGES
        assert r == SAMPLE_REPLAY_COMMENTS

    def test_migration_skipped_if_db_exists(self):
        from services.store import save_progress, load_all
        save_progress({"manually-set": True})
        with open("progress.json", "w") as f:
            json.dump({"stale": "data"}, f)
        p, _, _, _, _ = load_all()
        assert p == {"manually-set": True}


class TestStoreEdgeCases:
    def test_empty_dict_values(self):
        from services.store import load_all, save_progress, save_chats
        save_progress({"empty-dict": {}})
        save_chats({"q-1": {}})
        p, _, c, _, _ = load_all()
        assert p == {"empty-dict": {}}
        assert c == {"q-1": {}}
```

- [ ] **Step 2: Run the tests to verify they fail**

```
python3 -m pytest tests/test_store.py -v --tb=short
```
Expected: ImportError for services.store (file doesn't exist yet).

- [ ] **Step 3: Create `services/store.py`**

```python
"""Phase 1: SQLite persistence store replacing JSON file I/O.
"""
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
    conn = _get_conn()
    conn.execute("DELETE FROM history")
    for entry in data:
        conn.execute("INSERT INTO history (entry) VALUES (?)", (json.dumps(entry),))
    conn.commit()
    conn.close()


def save_chats(data):
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
    conn = _get_conn()
    for ddl in _TABLES:
        table = ddl.split()[2]  # extract table name from CREATE TABLE IF NOT EXISTS <name> (
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
```

- [ ] **Step 4: Run the test suite to verify they pass**

```
python3 -m pytest tests/test_store.py -v --tb=short
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```
git add services/store.py tests/test_store.py
git commit -m "Phase 1: SQLite persistence store (services/store.py)"
```

---

### Task 2: Wire store into app — replace JSON I/O with SQLite

**Files:**
- Modify: `services/state.py:57-98` — load 5 persisted dicts from store.load_all() instead of JSON files
- Modify: `services/persistence.py:1-46` — save functions delegate to store instead of _atomic_json; remove _atomic_json
- Modify: `app.py:204-207` — `_atomic_json(HISTORY_FILE, HISTORY)` → `store.save_history(HISTORY)`
- Modify: `routes/auth.py:225-230` — file deletion loop → `store.clear_all()`

- [ ] **Step 1: Modify `services/state.py`**

Replace lines 57-98 (file-backed state loading) with a `store.load_all()` call:

```python
# File-backed persistent state — loaded from SQLite at startup, migration from JSON on first run
from services.store import load_all as _load_all
(
    PROGRESS,
    HISTORY,
    CHATS,
    JUDGES,
    REPLAY_COMMENTS,
) = _load_all()
```

Remove the individual `_read_state`, `PROGRESS_FILE`, `HISTORY_FILE`, `CHATS_FILE`, `REPLAY_COMMENTS_FILE`, `JUDGES_FILE` definitions and the individual json.load blocks. Keep the `_load_concept_links` function and the `_CONCEPT_LINKS_CACHE` variable unchanged.

Remove unused `_read_state` function (lines 60-66 in original state.py).

- [ ] **Step 2: Update imports in state.py**

The file path constants and `os` import may become unused. Remove `os` import if it's only used for file-checking in the removed blocks. Keep `json` import and `os` import if they're used elsewhere in the file (e.g., `os.path.exists` in `_load_concept_links`).

Current state.py imports:
```python
import json
import os
```
`os` is still used by `_load_concept_links` (line 37: `os.path.exists`), so keep it. `json` is still used by `_load_concept_links` (line 41: `json.load(open(path))`), so keep it.

- [ ] **Step 3: Run tests to verify state loads from store (still expected to fail — persistence.py still writes JSON)**

```
python3 -m pytest -q --tb=short 2>&1 | tail -10
```
Expected: some failures because persistence.py still saves to JSON but state now loads from
SQLite (which is empty since no migration happened and no JSON was read in the test
environment, or stale if DB exists from a prior run). This is the expected intermediate
state; the next step fixes it.

- [ ] **Step 4: Modify `services/persistence.py`**

Replace the entire file content:

```python
"""Phase 4 refactor — persistence (verbatim from app.py).
Phase 1: JSON file I/O replaced with SQLite store."""
from services.store import save_progress, save_chats, save_judges, save_replay_comments
from flask import request


def save_progress():
    from services.state import PROGRESS
    save_progress(PROGRESS)


def save_chats():
    from services.state import CHATS
    save_chats(CHATS)


def save_judges():
    from services.state import JUDGES
    save_judges(JUDGES)


def save_replay_comments():
    from services.state import REPLAY_COMMENTS
    save_replay_comments(REPLAY_COMMENTS)


def current_user_id():
    if not SUPABASE_ENABLED or sb is None:
        return None
    from flask import request as _req
    return sb.get_user_id_from_request(_req)
```

Wait — `SUPABASE_ENABLED` and `sb` need to be imported. Let me check what the current persistence.py imports. Current persistence.py imports:
```python
from services.state import (
    PROGRESS, PROGRESS_FILE,
    CHATS, CHATS_FILE,
    JUDGES, JUDGES_FILE,
    REPLAY_COMMENTS, REPLAY_COMMENTS_FILE,
    sb, SUPABASE_ENABLED,
)
```

Now `PROGRESS_FILE`, `CHATS_FILE`, etc. are gone from state.py. But `sb` and `SUPABASE_ENABLED` are still needed for `current_user_id`.

New persistence.py imports:
```python
from services.state import sb, SUPABASE_ENABLED
from services.store import (
    save_progress as _save_progress,
    save_chats as _save_chats,
    save_judges as _save_judges,
    save_replay_comments as _save_replay_comments,
)
from flask import request
```

Functions:
```python
def save_progress():
    from services.state import PROGRESS
    _save_progress(PROGRESS)

def save_chats():
    from services.state import CHATS
    _save_chats(CHATS)

def save_judges():
    from services.state import JUDGES
    _save_judges(JUDGES)

def save_replay_comments():
    from services.state import REPLAY_COMMENTS
    _save_replay_comments(REPLAY_COMMENTS)

def current_user_id():
    if not SUPABASE_ENABLED or sb is None:
        return None
    from flask import request as _req
    return sb.get_user_id_from_request(_req)
```

- [ ] **Step 5: Modify `app.py` — two changes**

**Change A: Import from store**

At the top of app.py (after the flask imports, around line ~14), add:
```python
from services.store import save_history, load_all as _reload_shared_state
```

**Change B: Replace `_read_state` / `*_FILE` fallback in `_req_start`**

Lines 92-95 (unauthenticated fallback) and 115-118 (Supabase error fallback) both call `_read_state(PROGRESS_FILE, {})` etc. Replace with a single reload from the SQLite store:

```python
    if not uid:
        PROGRESS, _, CHATS, JUDGES, REPLAY_COMMENTS = _reload_shared_state()
        g._supabase_user = None
        g._supabase_loaded = False
        return
    ...
        PROGRESS, _, CHATS, JUDGES, REPLAY_COMMENTS = _reload_shared_state()
        g._supabase_loaded = False
```

**Change C: Replace `_atomic_json(HISTORY_FILE, HISTORY)` in `log_history`**

```python
def log_history(entry):
    entry["ts"] = datetime.now().isoformat()
    HISTORY.append(entry)
    save_history(HISTORY)
```

- [ ] **Step 6: Modify `routes/auth.py`**

Replace lines ~225-230 (the `os.remove` loop):

```python
from services.store import clear_all

# Inside the reset endpoint:
clear_all()
```

Remove the `os` import if it's no longer needed in auth.py (check if `os` is used elsewhere in the file).

- [ ] **Step 7: Run full test suite**

```
python3 -m pytest -q --tb=short 2>&1 | tail -5
```
Expected: 72 passed (or more if test_store.py tests are discovered).

If there are failures, debug the most likely issues:
- State dicts that reference `PROGRESS_FILE` or `HISTORY_FILE` etc. would need updating
- Any module that `from services.state import PROGRESS_FILE` would break — grep for these

- [ ] **Step 8: Verify migration works end-to-end**

```
# Clean state
rm -f app_state.db
# Run the app briefly (or the test suite which triggers load_all)
python3 -m pytest tests/test_data_integrity.py -v --tb=short
# Verify DB exists and has data
python3 -c "import sqlite3; conn = sqlite3.connect('app_state.db'); print([r[0] for r in conn.execute('SELECT name FROM sqlite_master WHERE type=\\'table\\'').fetchall()])"
```

- [ ] **Step 9: Commit**

```
git add -A
git commit -m "Phase 1: wire SQLite store into app (state, persistence, app, auth)"
```
