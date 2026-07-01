#!/usr/bin/env python3
"""Assemble today's digest and write it to daily_digests.payload_json.

Run at 21:30 local. the agent's evening prompt reads the row and turns it into
a journal entry + reply.

Sources (post-2026-05 daily loop):
  - tasks: closed today, still-open carry-over, dropped today
  - body_daily: today's mood (sleep/weight no longer collected)
  - activity: today's sessions
  - voicenotes: today's count + gists
  - quick_notes: today's unswept entries (this script flips swept = 1 after reading)

Legacy columns (cortex_summary, coach_summary, body_summary, capital_summary)
are filled with empty strings for back-compat with the daily_digests schema.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from pathlib import Path

VAULT = Path(os.environ.get("AGENT_VAULT_DIR", str(Path.home() / "vault"))).expanduser()
DB = VAULT / "db.sqlite"


def iso_today() -> str:
    return date.today().isoformat()


def q(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(sql, args).fetchall()


def tasks_summary(conn: sqlite3.Connection, today: str) -> dict:
    closed = q(
        conn,
        "SELECT id, text, priority FROM tasks "
        "WHERE status='done' AND date(done_at) = ? "
        "ORDER BY done_at DESC",
        (today,),
    )
    dropped = q(
        conn,
        "SELECT id, text FROM tasks "
        "WHERE status='dropped' AND date(done_at) = ? "
        "ORDER BY done_at DESC",
        (today,),
    )
    open_now = q(
        conn,
        "SELECT id, text, priority, date(created_at) AS opened FROM tasks "
        "WHERE status='open' "
        "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, created_at",
    )
    open_old = [r for r in open_now if r["opened"] < today]
    return {
        "closed_count": len(closed),
        "closed": [{"text": r["text"], "priority": r["priority"]} for r in closed],
        "dropped_count": len(dropped),
        "dropped": [r["text"] for r in dropped],
        "open_count": len(open_now),
        "open_old_count": len(open_old),
        "open_old_sample": [{"text": r["text"], "opened": r["opened"]} for r in open_old[:5]],
    }


def mood_today(conn: sqlite3.Connection, today: str) -> dict | None:
    rows = q(
        conn,
        "SELECT mood, notes FROM body_daily WHERE date = ?",
        (today,),
    )
    if not rows:
        return None
    r = rows[0]
    return {"mood": r["mood"], "note": r["notes"]}


def mood_trend(conn: sqlite3.Connection) -> list[dict]:
    rows = q(
        conn,
        "SELECT date, mood FROM body_daily "
        "WHERE date >= date('now','-7 days') AND mood IS NOT NULL "
        "ORDER BY date",
    )
    return [{"date": r["date"], "mood": r["mood"]} for r in rows]


def activity_today(conn: sqlite3.Connection, today: str) -> list[dict]:
    rows = q(
        conn,
        "SELECT type, summary, duration_min, energy_rating FROM activity "
        "WHERE date = ? ORDER BY created_at",
        (today,),
    )
    return [
        {
            "type": r["type"],
            "summary": r["summary"],
            "duration_min": r["duration_min"],
            "energy": r["energy_rating"],
        }
        for r in rows
    ]


def voicenotes_today(conn: sqlite3.Connection, today: str) -> dict:
    rows = q(
        conn,
        "SELECT id, transcription, category FROM voicenotes "
        "WHERE date(created_at) = ? ORDER BY created_at",
        (today,),
    )
    return {
        "count": len(rows),
        "gists": [
            {
                "id": r["id"],
                "category": r["category"],
                "gist": (r["transcription"] or "")[:200],
            }
            for r in rows
        ],
    }


def quick_notes_today(conn: sqlite3.Connection, today: str) -> list[dict]:
    """Reads today's unswept quick_notes, returns them, then flips swept = 1.
    Idempotent: subsequent calls today return [] (nothing unswept left)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS quick_notes (
            id INTEGER PRIMARY KEY,
            text TEXT NOT NULL,
            swept INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    rows = q(
        conn,
        "SELECT id, text, created_at FROM quick_notes "
        "WHERE swept = 0 AND date(created_at) = ? "
        "ORDER BY created_at",
        (today,),
    )
    out = [{"id": r["id"], "text": r["text"], "at": r["created_at"]} for r in rows]
    if out:
        conn.execute(
            "UPDATE quick_notes SET swept = 1 WHERE swept = 0 AND date(created_at) = ?",
            (today,),
        )
    return out


def detect_flags(tasks: dict, mood: dict | None, activity: list, trend: list) -> list[str]:
    flags = []
    if tasks["open_old_count"] >= 5:
        flags.append(f"{tasks['open_old_count']} tasks carrying over from previous days")
    if mood and mood["mood"] is not None:
        recent_moods = [t["mood"] for t in trend[-7:] if t["mood"] is not None]
        if len(recent_moods) >= 4:
            avg = sum(recent_moods) / len(recent_moods)
            if mood["mood"] <= avg - 2:
                flags.append(
                    f"mood {mood['mood']} - {round(avg - mood['mood'], 1)} below 7-day avg"
                )
    if tasks["closed_count"] == 0 and tasks["open_count"] >= 3:
        flags.append("no tasks closed but open queue is full")
    return flags


def build_payload(today: str) -> dict:
    with sqlite3.connect(DB) as conn:
        tasks = tasks_summary(conn, today)
        mood = mood_today(conn, today)
        trend = mood_trend(conn)
        activity = activity_today(conn, today)
        voicenotes = voicenotes_today(conn, today)
        quicks = quick_notes_today(conn, today)
        conn.commit()

    return {
        "date": today,
        "tasks": tasks,
        "mood": mood,
        "mood_trend_7d": trend,
        "activity": activity,
        "voicenotes": voicenotes,
        "quick_notes": quicks,
        "flags": detect_flags(tasks, mood, activity, trend),
    }


def write_digest(today: str, payload: dict) -> None:
    with sqlite3.connect(DB) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_digests
               (date, cortex_summary, coach_summary, body_summary, capital_summary, payload_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (today, "", "", "", "", json.dumps(payload)),
        )
        conn.commit()


def main() -> None:
    today = iso_today()
    payload = build_payload(today)
    write_digest(today, payload)
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
