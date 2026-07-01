#!/usr/bin/env python3
# Unit tests for the digest logic in daily_digest.py (pure functions + a temp DB).
# daily_digest imports only stdlib, so this runs without mcp/fastapi.

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import daily_digest as dd  # noqa: E402


def _fresh_db(tmp_path):
    """Create a schema-initialised db and return an open connection."""
    v = tmp_path / "v"
    env = dict(os.environ, AGENT_VAULT_DIR=str(v))
    subprocess.run([sys.executable, str(SCRIPTS / "agent_db.py"), "init"],
                   capture_output=True, text=True, env=env)
    return sqlite3.connect(str(v / "db.sqlite"))


def test_tasks_summary_counts(tmp_path):
    conn = _fresh_db(tmp_path)
    conn.execute("INSERT INTO tasks (text, status, done_at) VALUES ('a','done',datetime('now'))")
    conn.execute("INSERT INTO tasks (text, status) VALUES ('b','open')")
    conn.execute("INSERT INTO tasks (text, status, done_at) VALUES ('c','dropped',datetime('now'))")
    conn.commit()
    s = dd.tasks_summary(conn, dd.iso_today())
    conn.close()
    assert s["closed_count"] == 1
    assert s["open_count"] == 1
    assert s["dropped_count"] == 1


def test_mood_trend_reads_recent(tmp_path):
    conn = _fresh_db(tmp_path)
    conn.execute("INSERT INTO body_daily (date, mood) VALUES (date('now','-1 day'), 6)")
    conn.execute("INSERT INTO body_daily (date, mood) VALUES (date('now'), 8)")
    conn.commit()
    trend = dd.mood_trend(conn)
    conn.close()
    assert len(trend) == 2
    assert trend[-1]["mood"] == 8


def test_detect_flags_task_carryover():
    tasks = {"open_old_count": 6, "closed_count": 2, "open_count": 6}
    flags = dd.detect_flags(tasks, None, [], [])
    assert any("carrying over" in f for f in flags)


def test_detect_flags_mood_drop():
    tasks = {"open_old_count": 0, "closed_count": 1, "open_count": 1}
    trend = [{"date": "d", "mood": m} for m in (8, 8, 9, 8)]
    mood = {"mood": 3, "note": ""}
    flags = dd.detect_flags(tasks, mood, [], trend)
    assert any("below 7-day avg" in f for f in flags)


def test_detect_flags_no_close_full_queue():
    tasks = {"open_old_count": 0, "closed_count": 0, "open_count": 4}
    flags = dd.detect_flags(tasks, None, [], [])
    assert any("no tasks closed" in f for f in flags)


def test_quick_notes_sweep_is_idempotent(tmp_path):
    conn = _fresh_db(tmp_path)
    conn.execute("INSERT INTO quick_notes (text) VALUES ('idea one')")
    conn.commit()
    first = dd.quick_notes_today(conn, dd.iso_today())
    conn.commit()
    second = dd.quick_notes_today(conn, dd.iso_today())
    conn.close()
    assert len(first) == 1 and first[0]["text"] == "idea one"
    assert second == []  # already swept
