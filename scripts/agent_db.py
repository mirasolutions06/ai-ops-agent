#!/usr/bin/env python3
"""
agent_db.py - sqlite helper for the agent's structured store at ~/vault/db.sqlite.
Read/write structured data (tasks, habits, activity, notes, media, embeddings).

Usage:
  python3 agent_db.py init
  python3 agent_db.py tasks list [--status open|done|dropped]
  python3 agent_db.py tasks add "Task text" [--priority high|normal|low] [--source heartbeat|voicenote|manual]
  python3 agent_db.py tasks done <id>
  python3 agent_db.py streaks log <routine> <status> [--note "reason"]
  python3 agent_db.py streaks show [--routine ...] [--days 7]
  python3 agent_db.py activity log <type> <summary> [--duration 60] [--energy 7]
  python3 agent_db.py body today [--sleep 7.5] [--quality 8] [--weight 80.5] [--mood 7] [--notes "..."]
  python3 agent_db.py capital memo <week> --opportunity "..." --risk "..." --pace "..."
  python3 agent_db.py voicenote log "transcription" --category task --routed-to tasks.md [--file /path]
  python3 agent_db.py media log <kind> <path> [--agent ...] [--prompt "..."] [--source ...]
  python3 agent_db.py query "SELECT ..."
"""

import sqlite3
import sys
import json
import os
from datetime import datetime, date
from pathlib import Path

VAULT = Path(os.environ.get("AGENT_VAULT_DIR", str(Path.home() / "vault"))).expanduser()
DB_PATH = VAULT / "db.sqlite"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def cmd_tasks(args):
    db = get_db()
    if not args or args[0] == "list":
        status = "open"
        if "--status" in args:
            status = args[args.index("--status") + 1]
        rows = db.execute(
            "SELECT id, text, priority, created_at, source FROM tasks WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
        for r in rows:
            print(f"  [{r['id']}] {r['text']} (priority={r['priority']}, src={r['source']}, {r['created_at']})")
        if not rows:
            print(f"  No {status} tasks.")
    elif args[0] == "add":
        text = args[1]
        priority = "normal"
        source = "manual"
        if "--priority" in args:
            priority = args[args.index("--priority") + 1]
        if "--source" in args:
            source = args[args.index("--source") + 1]
        db.execute("INSERT INTO tasks (text, priority, source) VALUES (?, ?, ?)", (text, priority, source))
        db.commit()
        print(f"  Added: {text}")
    elif args[0] == "done":
        task_id = int(args[1])
        db.execute("UPDATE tasks SET status = 'done', done_at = datetime('now') WHERE id = ?", (task_id,))
        db.commit()
        print(f"  Task {task_id} marked done.")
    db.close()


def cmd_streaks(args):
    db = get_db()
    if args[0] == "log":
        routine = args[1]
        status = args[2]
        note = None
        if "--note" in args:
            note = args[args.index("--note") + 1]
        today = date.today().isoformat()
        now = datetime.now().strftime("%H:%M:%S")
        db.execute(
            "INSERT OR REPLACE INTO streaks (routine, date, status, ack_time, note) VALUES (?, ?, ?, ?, ?)",
            (routine, today, status, now, note),
        )
        db.commit()
        print(f"  {routine}: {status} ({today})")
    elif args[0] == "show":
        routine_filter = None
        days = 7
        if "--routine" in args:
            routine_filter = args[args.index("--routine") + 1]
        if "--days" in args:
            days = int(args[args.index("--days") + 1])
        query = "SELECT routine, date, status, note FROM streaks WHERE date >= date('now', ?) ORDER BY routine, date"
        params = [f"-{days} days"]
        if routine_filter:
            query = "SELECT routine, date, status, note FROM streaks WHERE date >= date('now', ?) AND routine = ? ORDER BY date"
            params.append(routine_filter)
        rows = db.execute(query, params).fetchall()
        for r in rows:
            note_str = f" ({r['note']})" if r["note"] else ""
            print(f"  {r['routine']} | {r['date']} | {r['status']}{note_str}")
    db.close()


def cmd_activity(args):
    db = get_db()
    if args[0] == "log":
        activity_type = args[1]
        summary = args[2]
        duration = None
        energy = None
        if "--duration" in args:
            duration = int(args[args.index("--duration") + 1])
        if "--energy" in args:
            energy = int(args[args.index("--energy") + 1])
        today = date.today().isoformat()
        db.execute(
            "INSERT INTO activity (date, type, summary, duration_min, energy_rating) VALUES (?, ?, ?, ?, ?)",
            (today, activity_type, summary, duration, energy),
        )
        db.commit()
        print(f"  Logged: {activity_type} - {summary}")
    db.close()


def cmd_body(args):
    db = get_db()
    if args[0] == "today":
        today = date.today().isoformat()
        updates = {}
        for flag in ["--sleep", "--quality", "--weight", "--mood", "--notes"]:
            if flag in args:
                key = flag.lstrip("-")
                val = args[args.index(flag) + 1]
                if key in ("sleep",):
                    updates["sleep_hours"] = float(val)
                elif key == "quality":
                    updates["sleep_quality"] = int(val)
                elif key == "weight":
                    updates["weight_kg"] = float(val)
                elif key == "mood":
                    updates["mood"] = int(val)
                elif key == "notes":
                    updates["notes"] = val
        if updates:
            # Upsert
            existing = db.execute("SELECT * FROM body_daily WHERE date = ?", (today,)).fetchone()
            if existing:
                sets = ", ".join(f"{k} = ?" for k in updates)
                db.execute(f"UPDATE body_daily SET {sets} WHERE date = ?", (*updates.values(), today))
            else:
                updates["date"] = today
                cols = ", ".join(updates.keys())
                placeholders = ", ".join("?" for _ in updates)
                db.execute(f"INSERT INTO body_daily ({cols}) VALUES ({placeholders})", tuple(updates.values()))
            db.commit()
            print(f"  Body daily updated for {today}: {updates}")
    db.close()


def cmd_capital(args):
    db = get_db()
    if args[0] == "memo":
        week = args[1]
        opp = risk = pace = None
        if "--opportunity" in args:
            opp = args[args.index("--opportunity") + 1]
        if "--risk" in args:
            risk = args[args.index("--risk") + 1]
        if "--pace" in args:
            pace = args[args.index("--pace") + 1]
        db.execute(
            "INSERT INTO capital_memos (week, opportunity, risk, goal_pace) VALUES (?, ?, ?, ?)",
            (week, opp, risk, pace),
        )
        db.commit()
        print(f"  Memo logged for {week}")
    elif args[0] == "feedback":
        memo_id = int(args[1])
        feedback = args[2]
        db.execute("INSERT INTO capital_feedback (memo_id, feedback) VALUES (?, ?)", (memo_id, feedback))
        db.commit()
        print(f"  Feedback logged for memo {memo_id}: {feedback}")
    db.close()


def cmd_voicenote(args):
    db = get_db()
    if args[0] == "log":
        transcription = args[1]
        category = routed_to = file_path = None
        if "--category" in args:
            category = args[args.index("--category") + 1]
        if "--routed-to" in args:
            routed_to = args[args.index("--routed-to") + 1]
        if "--file" in args:
            file_path = args[args.index("--file") + 1]
        db.execute(
            "INSERT INTO voicenotes (transcription, category, routed_to, file_path) VALUES (?, ?, ?, ?)",
            (transcription, category, routed_to, file_path),
        )
        db.commit()
        print(f"  Voicenote logged: [{category}] → {routed_to}")
    db.close()


def cmd_media(args):
    db = get_db()
    if not args:
        print("usage: media init|log|show"); return
    if args[0] == "init":
        db.executescript("""
            CREATE TABLE IF NOT EXISTS media (
              id INTEGER PRIMARY KEY,
              ts TEXT NOT NULL DEFAULT (datetime('now')),
              agent TEXT NOT NULL,
              kind TEXT NOT NULL,
              path TEXT NOT NULL,
              prompt TEXT,
              analysis TEXT,
              source TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_media_agent ON media(agent);
            CREATE INDEX IF NOT EXISTS idx_media_ts ON media(ts);
        """)
        db.commit()
        print("  media table ready")
    elif args[0] == "log":
        kind = args[1]
        path = args[2]
        agent = "unknown"
        prompt = analysis = source = None
        if "--agent" in args:
            agent = args[args.index("--agent") + 1]
        if "--prompt" in args:
            prompt = args[args.index("--prompt") + 1]
        if "--analysis" in args:
            analysis = args[args.index("--analysis") + 1]
        if "--source" in args:
            source = args[args.index("--source") + 1]
        cur = db.execute(
            "INSERT INTO media (agent, kind, path, prompt, analysis, source) VALUES (?, ?, ?, ?, ?, ?)",
            (agent, kind, path, prompt, analysis, source),
        )
        db.commit()
        print(json.dumps({"id": cur.lastrowid, "kind": kind, "path": path}))
    elif args[0] == "show":
        agent_filter = None
        limit = 20
        if "--agent" in args:
            agent_filter = args[args.index("--agent") + 1]
        if "--limit" in args:
            limit = int(args[args.index("--limit") + 1])
        q = "SELECT id, ts, agent, kind, path, prompt, source FROM media"
        params = []
        if agent_filter:
            q += " WHERE agent = ?"
            params.append(agent_filter)
        q += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        for r in db.execute(q, params).fetchall():
            print(json.dumps(dict(r), default=str))
    db.close()


def cmd_vault_chunks(args):
    db = get_db()
    if not args or args[0] == "init":
        db.executescript("""
            CREATE TABLE IF NOT EXISTS vault_chunks (
              id INTEGER PRIMARY KEY,
              path TEXT NOT NULL,
              heading TEXT,
              chunk TEXT NOT NULL,
              mtime REAL NOT NULL,
              embedding BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_vault_chunks_path ON vault_chunks(path);
        """)
        db.commit()
        print("  vault_chunks table ready")
    db.close()


def cmd_init(args):
    """Create the full schema. Idempotent; safe to re-run."""
    VAULT.mkdir(parents=True, exist_ok=True)
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY,
          text TEXT NOT NULL,
          priority TEXT NOT NULL DEFAULT 'normal',
          status TEXT NOT NULL DEFAULT 'open',
          source TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          done_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

        CREATE TABLE IF NOT EXISTS streaks (
          id INTEGER PRIMARY KEY,
          routine TEXT NOT NULL,
          date TEXT NOT NULL,
          status TEXT NOT NULL,
          ack_time TEXT,
          note TEXT,
          UNIQUE(routine, date)
        );

        CREATE TABLE IF NOT EXISTS activity (
          id INTEGER PRIMARY KEY,
          date TEXT NOT NULL,
          type TEXT NOT NULL,
          summary TEXT,
          duration_min INTEGER,
          energy_rating INTEGER,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS body_daily (
          date TEXT PRIMARY KEY,
          sleep_hours REAL,
          sleep_quality INTEGER,
          weight_kg REAL,
          mood INTEGER,
          notes TEXT
        );

        CREATE TABLE IF NOT EXISTS capital_memos (
          id INTEGER PRIMARY KEY,
          week TEXT NOT NULL,
          opportunity TEXT,
          risk TEXT,
          goal_pace TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS capital_feedback (
          id INTEGER PRIMARY KEY,
          memo_id INTEGER NOT NULL,
          feedback TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS voicenotes (
          id INTEGER PRIMARY KEY,
          transcription TEXT,
          category TEXT,
          routed_to TEXT,
          file_path TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS quick_notes (
          id INTEGER PRIMARY KEY,
          text TEXT NOT NULL,
          swept INTEGER DEFAULT 0,
          created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS daily_digests (
          date TEXT PRIMARY KEY,
          cortex_summary TEXT,
          coach_summary TEXT,
          body_summary TEXT,
          capital_summary TEXT,
          payload_json TEXT
        );

        CREATE TABLE IF NOT EXISTS media (
          id INTEGER PRIMARY KEY,
          ts TEXT NOT NULL DEFAULT (datetime('now')),
          agent TEXT NOT NULL,
          kind TEXT NOT NULL,
          path TEXT NOT NULL,
          prompt TEXT,
          analysis TEXT,
          source TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_media_ts ON media(ts);

        CREATE TABLE IF NOT EXISTS vault_chunks (
          id INTEGER PRIMARY KEY,
          path TEXT NOT NULL,
          heading TEXT,
          chunk TEXT NOT NULL,
          mtime REAL NOT NULL,
          embedding BLOB NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_vault_chunks_path ON vault_chunks(path);
    """)
    db.commit()
    print(f"  schema ready at {DB_PATH}")
    db.close()


def cmd_query(args):
    db = get_db()
    sql = " ".join(args)
    rows = db.execute(sql).fetchall()
    for r in rows:
        print(json.dumps(dict(r), default=str))
    db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "init": cmd_init,
        "tasks": cmd_tasks,
        "streaks": cmd_streaks,
        "activity": cmd_activity,
        "body": cmd_body,
        "capital": cmd_capital,
        "voicenote": cmd_voicenote,
        "media": cmd_media,
        "vault_chunks": cmd_vault_chunks,
        "query": cmd_query,
    }

    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
