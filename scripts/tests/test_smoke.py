#!/usr/bin/env python3
# Integration smoke tests: schema init, a task round-trip, and digest assembly.
# These run the CLI scripts in a subprocess against a temp vault, so they need
# no live secrets and no mcp/fastapi/psutil.

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def _run(vault, script, *args):
    env = dict(os.environ, AGENT_VAULT_DIR=str(vault))
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True, text=True, env=env,
    )


def test_init_creates_full_schema(tmp_path):
    vault = tmp_path / "vault"
    r = _run(vault, "agent_db.py", "init")
    assert "schema ready" in r.stdout, r.stderr
    assert (vault / "db.sqlite").exists()

    conn = sqlite3.connect(str(vault / "db.sqlite"))
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    for t in ("tasks", "streaks", "activity", "body_daily", "capital_memos",
              "voicenotes", "quick_notes", "daily_digests", "media", "vault_chunks"):
        assert t in tables, f"missing table {t}; have {tables}"


def test_task_roundtrip(tmp_path):
    vault = tmp_path / "vault"
    _run(vault, "agent_db.py", "init")
    _run(vault, "agent_db.py", "tasks", "add", "ship it", "--priority", "high")
    out = _run(vault, "agent_db.py", "tasks", "list").stdout
    assert "ship it" in out
    assert "priority=high" in out


def test_daily_digest_builds(tmp_path):
    vault = tmp_path / "vault"
    _run(vault, "agent_db.py", "init")
    r = _run(vault, "daily_digest.py")
    assert '"date"' in r.stdout, r.stderr
    assert '"tasks"' in r.stdout
    assert '"mood_trend_7d"' in r.stdout
