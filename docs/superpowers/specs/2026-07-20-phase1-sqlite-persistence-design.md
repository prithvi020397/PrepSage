# Phase 1: SQLite Persistence Store

## Scope

Replace the 5 file-backed JSON dicts (`PROGRESS`, `HISTORY`, `CHATS`, `JUDGES`, `REPLAY_COMMENTS`) with a SQLite-backed store. No other behavior change.

**In scope:** 5 file-backed dicts (loaded at startup, saved on mutation).
**Out of scope:** Read-only JSON files (`questions.json`, `solutions.json`, etc.), ephemeral in-memory dicts (`ATTEMPTS`, `STRUGGLES`, `PENDING_RECALL`, `PENDING_DRYRUN`).

## Schema

One table per state dict, using key-value JSON blobs:

```sql
CREATE TABLE IF NOT EXISTS progress (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry TEXT
);

CREATE TABLE IF NOT EXISTS chats (
    qid TEXT,
    entry_id TEXT,
    value TEXT,
    PRIMARY KEY (qid, entry_id)
);

CREATE TABLE IF NOT EXISTS judges (
    qid TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS replay_comments (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

JSON blobs (`value`, `entry`) contain the serialized Python value (dict, list, scalar) that was previously stored as a JSON file entry.

## Interface

`services/store.py` exports:

```python
def load_all() -> tuple[dict, list, dict, dict, dict]
    """Load all persisted state. Returns (progress, history, chats, judges, replay_comments)."""

def save_progress(data: dict) -> None
    """Replace all rows in the progress table. Single transaction."""

def save_history(data: list) -> None
    """Replace all rows in the history table. Single transaction."""

def save_chats(data: dict) -> None
    """Replace all rows in the chats table. Single transaction."""

def save_judges(data: dict) -> None
    """Replace all rows in the judges table. Single transaction."""

def save_replay_comments(data: dict) -> None
    """Replace all rows in the replay_comments table. Single transaction."""

def clear_all() -> None
    """DELETE FROM all 5 tables. Equivalent to removing all JSON files."""
```

Each `save_*` function:
1. Opens a connection
2. DELETEs all rows from the table
3. INSERTs all rows from the provided data dict/list
4. COMMITs and closes

This matches the current `_atomic_json` pattern of writing the entire state on every save, with the added benefit of transactional integrity across tables.

## Migration

On first startup, if `app_state.db` does not exist:
1. Create DB + tables
2. Check if any of the 5 JSON files exist
3. If yes, read each file and INSERT all entries into the corresponding table, then COMMIT
4. If no JSON files exist either, start with empty state (same as current behavior when JSON files are absent)

After migration (or if DB already exists on startup), JSON files are ignored for reads. They are left in place (not deleted) so rollback is trivial — just delete the DB.

The migration check is "does DB file exist?" — not "are tables empty?" — to avoid double-migration if a previous run failed mid-migration.

## File Changes

### New: `services/store.py`
- SQLite connection management
- Table DDL + auto-creation
- 5 load functions (wrapped in one `load_all`)
- 5 save functions
- `clear_all`
- `_migrate_from_json` (private, called during first-run setup when DB file didn't exist but JSON files are present)

### Modified: `services/state.py`
- `_read_state(path, default)` is no longer used for the 5 persisted dicts
- Replace `json.load(open(...)) if os.path.exists(...) else {}` blocks with `store.load_all()` call
- Load only once and destructure into `PROGRESS`, `HISTORY`, `CHATS`, `JUDGES`, `REPLAY_COMMENTS`

### Modified: `services/persistence.py`
- Remove `_atomic_json` and its imports
- `save_progress()`, `save_chats()`, `save_judges()`, `save_replay_comments()` call `store.save_*` instead
- File path imports (`PROGRESS_FILE`, etc.) become unused — consider removing or leaving as dead imports during migration period

### Modified: `app.py`
- Line ~207: `_atomic_json(HISTORY_FILE, HISTORY)` → `store.save_history(HISTORY)`
- May need to add `from services.store import save_history` (or call through `services.persistence`)

### Modified: `routes/auth.py`
- Line ~227: file `os.remove` loop → `store.clear_all()`
- Update imports: remove `PROGRESS_FILE`, `HISTORY_FILE`, etc. if no longer needed; add `clear_all` from store

## Save Sites

All 4 existing save functions keep their exact call signatures and call sites:

| Function | Call sites |
|---|---|
| `save_progress()` | `auth.py:130,143,204,216`, `documents.py:67,141,168,205,547,591`, `practice.py:389,899,947,965,979,1094`, `pages.py:107`, `analytics.py:50` |
| `save_chats()` | `interview.py:342,347,1001`, `practice.py:1308` |
| `save_judges()` | `interview.py:392` |
| `save_replay_comments()` | `interview.py:622` |
| `save_history()` (new, `app.py:207`) | `app.py:207` |

## Verification

After Phase 1:
1. Delete `app_state.db`, ensure JSON files still exist
2. Start app → verify DB is created with identical content to JSON files
3. `python3 -m pytest` still passes 72 tests
4. Manual: trigger a save, restart, confirm data persisted

To verify correctness: write a test that loads from JSON, saves to SQLite, then loads from SQLite and asserts `==`. Since the interface is `load_all()` returning the same Python types as the JSON load, this is straightforward.

## Rollback

Keep the JSON file read logic in `_read_state` as a fallback (gated on `import store; store.db_exists()`), or simply delete `app_state.db` and restart — JSON files are still present on disk and still valid. The JSON file deletion in `auth.py:227` (account reset) is replaced by `store.clear_all()`, which is a strict superset (clears DB without touching JSON files on disk).
