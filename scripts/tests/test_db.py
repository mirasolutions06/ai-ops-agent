#!/usr/bin/env python3
# Round-trip tests for every agent_db command, run in a subprocess against a
# temp vault. No live secrets, no mcp/fastapi needed.

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def _db(vault, *args):
    env = dict(os.environ, AGENT_VAULT_DIR=str(vault))
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "agent_db.py"), *args],
        capture_output=True, text=True, env=env,
    )


def _init(vault):
    _db(vault, "init")


def test_streaks_log_and_show(tmp_path):
    v = tmp_path / "v"; _init(v)
    _db(v, "streaks", "log", "morning", "done", "--note", "up early")
    out = _db(v, "streaks", "show", "--routine", "morning").stdout
    assert "morning" in out and "done" in out and "up early" in out


def test_streaks_upsert_same_day(tmp_path):
    v = tmp_path / "v"; _init(v)
    _db(v, "streaks", "log", "training", "missed")
    _db(v, "streaks", "log", "training", "done")  # same routine+date -> replace
    conn = sqlite3.connect(str(v / "db.sqlite"))
    rows = conn.execute("SELECT status FROM streaks WHERE routine='training'").fetchall()
    conn.close()
    assert len(rows) == 1 and rows[0][0] == "done"


def test_activity_log(tmp_path):
    v = tmp_path / "v"; _init(v)
    r = _db(v, "activity", "log", "deep_work", "wrote the engine", "--duration", "90", "--energy", "8")
    assert "Logged" in r.stdout
    conn = sqlite3.connect(str(v / "db.sqlite"))
    row = conn.execute("SELECT type, duration_min, energy_rating FROM activity").fetchone()
    conn.close()
    assert row == ("deep_work", 90, 8)


def test_body_today_upsert(tmp_path):
    v = tmp_path / "v"; _init(v)
    _db(v, "body", "today", "--mood", "6", "--sleep", "7.0")
    _db(v, "body", "today", "--mood", "9")  # upsert on date
    conn = sqlite3.connect(str(v / "db.sqlite"))
    row = conn.execute("SELECT mood, sleep_hours FROM body_daily").fetchone()
    conn.close()
    assert row[0] == 9 and abs(row[1] - 7.0) < 1e-6  # mood updated, sleep preserved


def test_capital_memo_and_feedback(tmp_path):
    v = tmp_path / "v"; _init(v)
    _db(v, "capital", "memo", "2026-W27", "--opportunity", "ship it", "--risk", "scope")
    conn = sqlite3.connect(str(v / "db.sqlite"))
    mid = conn.execute("SELECT id FROM capital_memos").fetchone()[0]
    conn.close()
    _db(v, "capital", "feedback", str(mid), "worked")
    conn = sqlite3.connect(str(v / "db.sqlite"))
    fb = conn.execute("SELECT feedback FROM capital_feedback WHERE memo_id=?", (mid,)).fetchone()
    conn.close()
    assert fb[0] == "worked"


def test_voicenote_log(tmp_path):
    v = tmp_path / "v"; _init(v)
    _db(v, "voicenote", "log", "remember to call the bank", "--category", "task", "--routed-to", "tasks.md")
    conn = sqlite3.connect(str(v / "db.sqlite"))
    row = conn.execute("SELECT transcription, category, routed_to FROM voicenotes").fetchone()
    conn.close()
    assert row == ("remember to call the bank", "task", "tasks.md")


def test_media_log_and_query(tmp_path):
    v = tmp_path / "v"; _init(v)
    r = _db(v, "media", "log", "photo", "/tmp/x.png", "--agent", "agent", "--source", "telegram")
    assert '"kind": "photo"' in r.stdout
    out = _db(v, "query", "SELECT kind, source FROM media").stdout
    assert '"kind": "photo"' in out and '"source": "telegram"' in out


def test_tasks_done_moves_status(tmp_path):
    v = tmp_path / "v"; _init(v)
    _db(v, "tasks", "add", "finish tests")
    conn = sqlite3.connect(str(v / "db.sqlite"))
    tid = conn.execute("SELECT id FROM tasks").fetchone()[0]
    conn.close()
    _db(v, "tasks", "done", str(tid))
    assert "finish tests" not in _db(v, "tasks", "list").stdout       # not in open list
    assert "finish tests" in _db(v, "tasks", "list", "--status", "done").stdout
