"""Tests for services/store.py — SQLite persistence layer."""
import json, os, tempfile, pytest
from unittest.mock import patch

FIXTURE_DIR = None


def _db_path():
    return os.path.join(FIXTURE_DIR, "test.db")

@pytest.fixture(autouse=True)
def tmp_workdir(monkeypatch):
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
    def test_empty_dict_value_round_trips(self):
        """An empty dict as a value is stored as a row and restored on load."""
        from services.store import load_all, save_progress, save_chats
        save_progress({"empty-dict": {}})
        p, _, _, _, _ = load_all()
        assert p == {"empty-dict": {}}

    def test_empty_chats_subdict_produces_no_rows(self):
        """CHATS qid with no entries produces no rows, so 'q-1 in CHATS' is False."""
        from services.store import load_all, save_chats
        save_chats({"q-1": {}})
        _, _, c, _, _ = load_all()
        assert c == {}
