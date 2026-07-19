# Phase 4 refactor — code execution (verbatim from app.py).
import os
import sqlite3
import subprocess
import tempfile
from security_scan import has_blocker


def run_sql_case(schema_sql, code):
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_sql)
    try:
        cur = conn.execute(code)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchall()]
    except sqlite3.Error as e:
        return None, None, str(e)
    return cols, rows, None



def get_sample_tables(schema_sql):
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_sql)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    out = {}
    for t in tables:
        cur = conn.execute(f"SELECT * FROM {t}")
        out[t] = {"columns": [d[0] for d in cur.description], "rows": [list(r) for r in cur.fetchall()]}
    return out



def run_python_case(harness, code):
    # ponytail: security gate — never execute code that could damage the host.
    # Candidate code is scanned for process-spawn / eval / fs-destruction before
    # it ever reaches the interpreter. A BLOCK finding short-circuits execution.
    blocker = has_blocker(code)
    if blocker:
        return None, (
            f"Security scan blocked execution: {blocker.message} "
            f"(line {blocker.line}). This looks like it could harm the host machine, "
            f"not solve the interview problem. Rewrite using plain algorithm code."
        )
    full_code = code + "\n\n" + harness
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(full_code)
        path = f.name
    try:
        result = subprocess.run(["python3", path], capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return None, "Timed out (5s) — check for an infinite loop."
    finally:
        os.unlink(path)
    if result.returncode != 0:
        return None, result.stderr.strip()
    return result.stdout, None



