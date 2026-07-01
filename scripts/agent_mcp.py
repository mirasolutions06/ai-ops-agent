#!/usr/bin/env python3
"""
agent_mcp - narrow MCP server exposing first-class tools to the agent.

Single-agent setup. Runs as `python3 agent_mcp.py` over stdio (the agent runtime spawns
via the mcp config block). Each tool wraps either db.py (for structured data)
or direct filesystem writes (for vault append).
"""

import base64
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent))
import models as M  # noqa: E402

HOME = Path.home()
DB_PY = HOME / "scripts" / "db.py"
VAULT = Path(os.environ.get("AGENT_VAULT_DIR", str(Path.home() / "vault"))).expanduser()
DB_PATH = VAULT / "db.sqlite"
SECRETS = Path(os.environ.get("AGENT_ENV_FILE", str(Path.home() / ".config" / "ai-ops-agent" / "secrets.env"))).expanduser()

mcp = FastMCP("agent")


# ---------- helpers ----------

def _run_db(args: list[str]) -> dict[str, Any]:
    """Shell db.py and return {ok, stdout, stderr}."""
    try:
        r = subprocess.run(
            ["python3", str(DB_PY), *args],
            capture_output=True, text=True, timeout=20,
        )
        return {
            "ok": r.returncode == 0,
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _safe_vault_path(rel: str) -> Path | None:
    """Resolve a vault-relative path; reject escapes."""
    p = (VAULT / rel).resolve()
    if not str(p).startswith(str(VAULT.resolve())):
        return None
    return p


# ---------- activity ----------

@mcp.tool()
def activity_log(type: str, summary: str, duration: int = 0, energy: int = 0) -> dict:
    """Log a training/movement session. type: gym|bike|run|walk|swim|other."""
    args = ["activity", "log", type, summary]
    if duration:
        args += ["--duration", str(duration)]
    if energy:
        args += ["--energy", str(energy)]
    return _run_db(args)


# ---------- vault ----------

@mcp.tool()
def vault_read(path: str) -> dict:
    """Read any file under ~/vault/."""
    p = _safe_vault_path(path)
    if p is None:
        return {"ok": False, "error": "path escapes vault"}
    if not p.exists():
        return {"ok": False, "error": f"not found: {path}"}
    if not p.is_file():
        return {"ok": False, "error": f"not a file: {path}"}
    try:
        return {"ok": True, "content": p.read_text()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def vault_append(path: str, heading: str, body: str) -> dict:
    """Append a dated section to a vault file.

    path: vault-relative (e.g. 'journal/2026-04-28.md')
    heading: short source/topic
    body: the content; a '## YYYY-MM-DD - heading' line is prepended automatically
    """
    p = _safe_vault_path(path)
    if p is None:
        return {"ok": False, "error": "path escapes vault"}
    p.parent.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    block = f"\n\n## {stamp} - {heading}\n\n{body.strip()}\n"
    try:
        with p.open("a") as f:
            f.write(block)
        return {"ok": True, "path": str(p), "appended_bytes": len(block)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


VAULT_EXCLUDE_DIRS = {".git", ".obsidian", ".trash", "node_modules", "another agent", "inbox/generated"}


@mcp.tool()
def vault_tree(path: str = "", depth: int = 3, include_sizes: bool = False) -> dict:
    """List the vault file/dir tree. path = vault-relative root (default = vault root).
    depth caps recursion. Excludes another agent/, .git/, .obsidian/, .trash/, node_modules/."""
    base = _safe_vault_path(path) if path else VAULT.resolve()
    if base is None or not base.exists():
        return {"ok": False, "error": "path escapes vault or not found"}
    if not base.is_dir():
        return {"ok": False, "error": f"{path} is not a directory"}
    base_depth = len(base.parts)
    entries: list[dict] = []
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(VAULT).as_posix()
        if any(rel == d or rel.startswith(d + "/") for d in VAULT_EXCLUDE_DIRS):
            continue
        d = len(p.parts) - base_depth
        if d > depth:
            continue
        if p.is_dir():
            entries.append({"path": rel + "/", "type": "dir", "depth": d})
        elif p.is_file():
            e = {"path": rel, "type": "file", "depth": d}
            if include_sizes:
                try:
                    e["size"] = p.stat().st_size
                except OSError:
                    pass
            entries.append(e)
    return {"ok": True, "count": len(entries), "entries": entries}


# ---------- structured-data helpers ----------

def _db_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ---------- tasks ----------

def _render_tasks_md() -> dict:
    """Regenerate ~/vault/tasks.md from sqlite. Obsidian Tasks plugin format."""
    conn = _db_conn()
    open_rows = conn.execute(
        "SELECT id, text, priority, created_at FROM tasks WHERE status='open' "
        "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, created_at DESC"
    ).fetchall()
    today = date.today().isoformat()
    done_today = conn.execute(
        "SELECT id, text, done_at FROM tasks WHERE status='done' AND date(done_at)=? "
        "ORDER BY done_at DESC",
        (today,),
    ).fetchall()
    conn.close()
    lines = [
        "# Tasks",
        "",
        "_Auto-generated by the agent from db.sqlite. Tick `[x]` to close (synced back every 10 min)._",
        "",
    ]
    if open_rows:
        lines.append("## Open")
        lines.append("")
        for r in open_rows:
            prio_icon = {"high": " 🔼", "low": " 🔽"}.get(r["priority"], "")
            lines.append(f"- [ ] {r['text']}{prio_icon}  ^t{r['id']}")
        lines.append("")
    if done_today:
        lines.append(f"## Done today ({today})")
        lines.append("")
        for r in done_today:
            lines.append(f"- [x] {r['text']}  ^t{r['id']}")
        lines.append("")
    if not open_rows and not done_today:
        lines.append("_No tasks yet._")
        lines.append("")
    out = "\n".join(lines)
    p = VAULT / "tasks.md"
    p.write_text(out)
    return {"ok": True, "path": str(p), "open": len(open_rows), "done_today": len(done_today)}


@mcp.tool()
def task_add(text: str, priority: str = "normal", source: str = "heartbeat") -> dict:
    """Add an open task.
    priority: 'high' | 'normal' | 'low'.
    source: free-form tag ('heartbeat', 'voicenote', 'manual', etc.)."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    if priority not in ("high", "normal", "low"):
        return {"ok": False, "error": f"invalid priority: {priority}"}
    conn = _db_conn()
    cur = conn.execute(
        "INSERT INTO tasks (text, status, priority, source) VALUES (?, 'open', ?, ?)",
        (text, priority, source),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    _render_tasks_md()
    return {"ok": True, "id": tid, "text": text, "priority": priority}


@mcp.tool()
def task_close(task_id: int = 0, match_text: str = "", status: str = "done") -> dict:
    """Close a task. status='done' (completed) or 'dropped' (skipped/abandoned).
    Pass task_id directly, OR match_text to fuzzy-match the most recent open task whose text contains it."""
    if status not in ("done", "dropped"):
        return {"ok": False, "error": "status must be 'done' or 'dropped'"}
    conn = _db_conn()
    if task_id:
        row = conn.execute(
            "SELECT id, text FROM tasks WHERE id=? AND status='open'", (task_id,)
        ).fetchone()
        if not row:
            conn.close()
            return {"ok": False, "error": f"no open task with id={task_id}"}
    elif match_text.strip():
        row = conn.execute(
            "SELECT id, text FROM tasks WHERE status='open' AND lower(text) LIKE ? "
            "ORDER BY created_at DESC LIMIT 1",
            (f"%{match_text.strip().lower()}%",),
        ).fetchone()
        if not row:
            conn.close()
            return {"ok": False, "error": f"no open task matched '{match_text}'"}
    else:
        conn.close()
        return {"ok": False, "error": "provide task_id or match_text"}
    conn.execute(
        "UPDATE tasks SET status=?, done_at=datetime('now') WHERE id=?",
        (status, row["id"]),
    )
    conn.commit()
    conn.close()
    _render_tasks_md()
    return {"ok": True, "id": row["id"], "text": row["text"], "status": status}


@mcp.tool()
def task_list(status: str = "open", limit: int = 20) -> dict:
    """List tasks. status: 'open' | 'done' | 'dropped' | 'all'."""
    conn = _db_conn()
    if status == "all":
        rows = conn.execute(
            "SELECT id, text, status, priority, created_at, done_at, source FROM tasks "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, text, status, priority, created_at, done_at, source FROM tasks "
            "WHERE status=? ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, "
            "created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    conn.close()
    return {"ok": True, "count": len(rows), "tasks": [dict(r) for r in rows]}


@mcp.tool()
def tasks_render_md() -> dict:
    """Manually regenerate tasks.md from db. Auto-called on task_add/task_close."""
    return _render_tasks_md()


# ---------- daily loop ----------

@mcp.tool()
def mood_log(value: int, note: str = "") -> dict:
    """Log today's mood/energy 1-10. Upserts body_daily for today."""
    if not (1 <= value <= 10):
        return {"ok": False, "error": "value must be 1-10"}
    today = date.today().isoformat()
    conn = _db_conn()
    existing = conn.execute("SELECT notes FROM body_daily WHERE date=?", (today,)).fetchone()
    if existing:
        new_notes = note.strip() if note.strip() else existing["notes"]
        conn.execute(
            "UPDATE body_daily SET mood=?, notes=? WHERE date=?",
            (value, new_notes, today),
        )
    else:
        conn.execute(
            "INSERT INTO body_daily (date, mood, notes) VALUES (?, ?, ?)",
            (today, value, note.strip() or None),
        )
    conn.commit()
    conn.close()
    return {"ok": True, "date": today, "mood": value, "note": note.strip()}


@mcp.tool()
def note_quick(text: str) -> dict:
    """Quick capture for thoughts that don't fit task/mood/activity.
    Stored in quick_notes (auto-creates table). Swept by evening review."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    conn = _db_conn()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS quick_notes (
            id INTEGER PRIMARY KEY,
            text TEXT NOT NULL,
            swept INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    cur = conn.execute("INSERT INTO quick_notes (text) VALUES (?)", (text,))
    conn.commit()
    nid = cur.lastrowid
    conn.close()
    return {"ok": True, "id": nid, "text": text}


@mcp.tool()
def activity_update(
    activity_id: int = 0,
    recent: bool = False,
    type: str = "",
    summary: str = "",
    duration_min: int = -1,
    energy_rating: int = -1,
) -> dict:
    """Edit an activity row (corrections like 'actually 4K not 5K').
    Pass activity_id directly OR recent=True to grab the latest row from today.
    Only fields you set get updated. Use -1 for ints to mean 'don't change'."""
    conn = _db_conn()
    if activity_id:
        row = conn.execute("SELECT id FROM activity WHERE id=?", (activity_id,)).fetchone()
    elif recent:
        today = date.today().isoformat()
        row = conn.execute(
            "SELECT id FROM activity WHERE date=? ORDER BY created_at DESC LIMIT 1",
            (today,),
        ).fetchone()
    else:
        conn.close()
        return {"ok": False, "error": "provide activity_id or set recent=True"}
    if not row:
        conn.close()
        return {"ok": False, "error": "no matching activity"}
    fields, params = [], []
    if type:
        fields.append("type=?"); params.append(type)
    if summary:
        fields.append("summary=?"); params.append(summary)
    if duration_min >= 0:
        fields.append("duration_min=?"); params.append(duration_min)
    if energy_rating >= 0:
        fields.append("energy_rating=?"); params.append(energy_rating)
    if not fields:
        conn.close()
        return {"ok": False, "error": "no fields to update"}
    params.append(row["id"])
    conn.execute(f"UPDATE activity SET {', '.join(fields)} WHERE id=?", params)
    conn.commit()
    conn.close()
    return {"ok": True, "id": row["id"], "updated": fields}


# ---------- voicenotes ----------

VOICENOTES_DIR = VAULT / "voicenotes"


@mcp.tool()
def voicenote_archive(audio_path: str, transcript: str, category: str = "", routed_to: str = "") -> dict:
    """Archive a voicenote: move audio into vault, write transcript .md, store sqlite row.
    audio_path: absolute path to .ogg (typically in ~/.agent-runtime/media/inbound/).
    transcript: transcribed text.
    category: short tag ('task' | 'mood' | 'activity' | 'note' | 'mixed').
    routed_to: comma-separated tools that fired (e.g. 'task_add,mood_log')."""
    src = Path(audio_path)
    if not src.exists():
        return {"ok": False, "error": f"audio not found: {audio_path}"}
    today = date.today().isoformat()
    now = datetime.now().strftime("%H%M%S")
    out_dir = VOICENOTES_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_dst = out_dir / f"{now}.ogg"
    md_dst = out_dir / f"{now}.md"
    try:
        src.rename(audio_dst)
    except OSError:
        shutil.copy2(src, audio_dst)
        try:
            src.unlink()
        except OSError:
            pass
    rel_audio = audio_dst.relative_to(VAULT).as_posix()
    md_content = (
        "---\n"
        f"date: {today}\n"
        f"time: {datetime.now().strftime('%H:%M:%S')}\n"
        f"audio: {rel_audio}\n"
        f"category: {category}\n"
        f"routed_to: {routed_to}\n"
        "---\n\n"
        f"{transcript.strip()}\n"
    )
    md_dst.write_text(md_content)
    conn = _db_conn()
    conn.execute(
        "INSERT INTO voicenotes (transcription, category, routed_to, file_path) VALUES (?, ?, ?, ?)",
        (transcript.strip(), category or None, routed_to or None, str(audio_dst)),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "audio": rel_audio, "transcript_md": md_dst.relative_to(VAULT).as_posix()}


# ---------- workouts ----------

WORKOUTS_DIR = VAULT / "workouts"


@mcp.tool()
def workout_archive(
    kind: str,
    summary: str,
    metrics_json: str = "",
    image_path: str = "",
    notes: str = "",
    duration_min: int = 0,
    energy: int = 0,
) -> dict:
    """Archive a workout. kind: treadmill|bike|run|walk|gym|rowing|other.
    summary: human-readable one-liner ('5.2km in 30:14, easy pace').
    metrics_json: optional JSON string with structured fields, e.g.
        '{"distance_km": 5.2, "time_min": 30, "calories": 350, "avg_hr": 145}'
        for cardio, or '{"exercises": [{"name":"bench","weight_kg":80,"sets":4,"reps":8}]}'
        for lifting. Freeform - just JSON.
    image_path: optional absolute path to a treadmill/bike screen, fitness-app
        screenshot, or handwritten-log photo. Gets moved to workouts/YYYY-MM-DD/.
    notes: free-text observations ('felt good, legs fresh').
    duration_min, energy: optional, mirrored to activity table for trend queries.
    Always writes a .md sidecar in workouts/YYYY-MM-DD/ AND an activity table row.
    Prefer this over activity_log for anything workout-shaped (with or without photo)."""
    today = date.today().isoformat()
    now_t = datetime.now().strftime("%H%M%S")
    out_dir = WORKOUTS_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        metrics = json.loads(metrics_json) if metrics_json else {}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"metrics_json invalid: {e}"}

    # Optional image
    image_rel = ""
    if image_path:
        src = Path(image_path)
        if not src.exists():
            return {"ok": False, "error": f"image not found: {image_path}"}
        ext = src.suffix.lower() or ".jpg"
        image_dst = out_dir / f"{now_t}_{kind}{ext}"
        try:
            src.rename(image_dst)
        except OSError:
            shutil.copy2(src, image_dst)
            try:
                src.unlink()
            except OSError:
                pass
        image_rel = image_dst.relative_to(VAULT).as_posix()

    # Sidecar
    md_dst = out_dir / f"{now_t}_{kind}.md"
    metrics_lines = (
        "\n".join(f"- {k}: {v}" for k, v in metrics.items())
        if metrics else "_(no structured metrics)_"
    )
    fm = ["---", f"date: {today}", f"time: {datetime.now().strftime('%H:%M:%S')}", f"kind: {kind}"]
    if image_rel:
        fm.append(f"image: {image_rel}")
    if duration_min:
        fm.append(f"duration_min: {duration_min}")
    if energy:
        fm.append(f"energy: {energy}")
    fm.append("---")
    body = [
        "",
        f"## {summary}",
        "",
        "### Metrics",
        metrics_lines,
        "",
        "### Notes",
        notes.strip() if notes else "_(none)_",
        "",
    ]
    md_dst.write_text("\n".join(fm + body))

    # Activity table row (via existing db.py - same path as activity_log)
    args = ["activity", "log", kind, summary]
    if duration_min:
        args += ["--duration", str(duration_min)]
    if energy:
        args += ["--energy", str(energy)]
    db_result = _run_db(args)

    return {
        "ok": True,
        "sidecar": md_dst.relative_to(VAULT).as_posix(),
        "image": image_rel or None,
        "activity_logged": db_result.get("ok", False),
        "metrics_count": len(metrics),
    }


# ---------- calendar ----------

GCAL_PY = HOME / "scripts" / "gcal.py"


def _run_gcal(args: list[str]) -> dict[str, Any]:
    """Shell gcal.py, parse JSON."""
    try:
        r = subprocess.run(
            ["python3", str(GCAL_PY), *args],
            capture_output=True, text=True, timeout=25,
        )
        out = r.stdout.strip()
        try:
            parsed = json.loads(out) if out else {}
            return {"ok": r.returncode == 0, "result": parsed}
        except json.JSONDecodeError:
            return {"ok": r.returncode == 0, "stdout": out[:2000], "stderr": r.stderr.strip()[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def calendar_list(days: int = 1, cal: str = "primary") -> dict:
    """List upcoming calendar events. days=1 = today, days=7 = week ahead."""
    return _run_gcal(["list", "--days", str(days), "--cal", cal])


def _default_end(start: str) -> str:
    """end = start + 30min. Accepts the same formats as gcal.py parses."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(start, fmt)
            return (dt + timedelta(minutes=30)).strftime(fmt)
        except ValueError:
            continue
    return start  # fall through - gcal.py will surface the bad-format error


@mcp.tool()
def calendar_add(title: str, start: str, end: str = "", description: str = "", cal: str = "primary") -> dict:
    """Add a calendar event. start: 'YYYY-MM-DD HH:MM' or ISO. end optional (defaults to start + 30min)."""
    if not end:
        end = _default_end(start)
    args = ["add", "--title", title, "--start", start, "--end", end, "--cal", cal]
    if description:
        args += ["--description", description]
    return _run_gcal(args)


@mcp.tool()
def calendar_delete(event_id: str, cal: str = "primary") -> dict:
    """Delete a calendar event by id. event_id comes from calendar_list or calendar_add response."""
    return _run_gcal(["delete", "--event_id", event_id, "--cal", cal])


# ---------- vision / image / embeddings ----------

GENERATED_DIR = VAULT / "inbox" / "generated"


def _load_secrets() -> dict[str, str]:
    """Parse your env file (AGENT_ENV_FILE) (KEY=VALUE lines). Cached per-process."""
    if hasattr(_load_secrets, "_cache"):
        return _load_secrets._cache
    out: dict[str, str] = {}
    if SECRETS.exists():
        for line in SECRETS.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("GLM_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        if k not in out and os.environ.get(k):
            out[k] = os.environ[k]
    _load_secrets._cache = out
    return out


def _http_post(url: str, payload: dict, api_key: str, timeout: int = 60) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"ok": True, "data": json.loads(r.read().decode())}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"http {e.code}: {e.read().decode()[:500]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _image_to_content_part(image: str) -> dict | None:
    if image.startswith(("http://", "https://")):
        return {"type": "image_url", "image_url": {"url": image}}
    p = Path(image).expanduser()
    if not p.exists():
        return None
    mime = "image/jpeg"
    ext = p.suffix.lower()
    if ext == ".png":
        mime = "image/png"
    elif ext == ".webp":
        mime = "image/webp"
    elif ext == ".gif":
        mime = "image/gif"
    b64 = base64.b64encode(p.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _video_to_content_part(video: str) -> dict | None:
    if video.startswith(("http://", "https://")):
        return {"type": "video_url", "video_url": {"url": video}}
    p = Path(video).expanduser()
    if not p.exists():
        return None
    b64 = base64.b64encode(p.read_bytes()).decode()
    return {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{b64}"}}


def _log_media(kind: str, path: str, prompt: str = "", analysis: str = "", source: str = "telegram"):
    """Best-effort log to media table."""
    args = ["media", "log", kind, path, "--agent", "agent", "--source", source]
    if prompt:
        args += ["--prompt", prompt]
    if analysis:
        args += ["--analysis", analysis[:2000]]
    try:
        _run_db(args)
    except Exception:
        pass


@mcp.tool()
def vision_analyze(image: str, prompt: str = "Describe this image.", hq: bool = False) -> dict:
    """Analyse an image via the vision model (gpt-4o by default).
    `image` = absolute path OR http(s) URL."""
    part = _image_to_content_part(image)
    if part is None:
        return {"ok": False, "error": f"image not found: {image}"}
    keys = _load_secrets()
    if not keys.get(M.API_KEY_ENV):
        return {"ok": False, "error": f"{M.API_KEY_ENV} missing"}
    model = M.VISION_HQ if hq else M.VISION
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [part, {"type": "text", "text": prompt}]}],
    }
    r = _http_post(M.CHAT_URL, payload, keys[M.API_KEY_ENV])
    if not r["ok"]:
        return r
    try:
        text = r["data"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return {"ok": False, "error": "unexpected response", "raw": r["data"]}
    _log_media("photo", image, prompt=prompt, analysis=text)
    return {"ok": True, "text": text, "model": model}


@mcp.tool()
def video_analyze(video: str, prompt: str = "Describe what happens in this video.") -> dict:
    """Analyse a short video. Requires a video-capable model/provider (see scripts/models.py)."""
    part = _video_to_content_part(video)
    if part is None:
        return {"ok": False, "error": f"video not found: {video}"}
    keys = _load_secrets()
    if not keys.get(M.API_KEY_ENV):
        return {"ok": False, "error": f"{M.API_KEY_ENV} missing"}
    payload = {
        "model": M.VIDEO,
        "messages": [{"role": "user", "content": [part, {"type": "text", "text": prompt}]}],
    }
    r = _http_post(M.CHAT_URL, payload, keys[M.API_KEY_ENV], timeout=120)
    if not r["ok"]:
        return r
    try:
        text = r["data"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return {"ok": False, "error": "unexpected response", "raw": r["data"]}
    _log_media("video", video, prompt=prompt, analysis=text)
    return {"ok": True, "text": text, "model": M.VIDEO}


@mcp.tool()
def ocr_extract(image: str) -> dict:
    """OCR via the vision model. Returns text verbatim."""
    part = _image_to_content_part(image)
    if part is None:
        return {"ok": False, "error": f"image not found: {image}"}
    keys = _load_secrets()
    if not keys.get(M.API_KEY_ENV):
        return {"ok": False, "error": f"{M.API_KEY_ENV} missing"}
    payload = {
        "model": M.OCR,
        "messages": [{"role": "user", "content": [
            part,
            {"type": "text", "text": "Extract all text from this image verbatim. Preserve line breaks and layout."},
        ]}],
    }
    r = _http_post(M.CHAT_URL, payload, keys[M.API_KEY_ENV])
    if not r["ok"]:
        return r
    try:
        text = r["data"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return {"ok": False, "error": "unexpected response", "raw": r["data"]}
    _log_media("photo", image, prompt="ocr", analysis=text)
    return {"ok": True, "text": text, "model": M.OCR}


@mcp.tool()
def image_generate(prompt: str, out_path: str = "", size: str = "1024x1024") -> dict:
    """Generate an image (gpt-image-1 by default). Writes to out_path (default ~/vault/inbox/generated/TS.png)."""
    keys = _load_secrets()
    if not keys.get(M.API_KEY_ENV):
        return {"ok": False, "error": f"{M.API_KEY_ENV} missing"}
    payload = {"model": M.IMAGE_GEN, "prompt": prompt, "size": size}
    r = _http_post(M.IMAGE_URL, payload, keys[M.API_KEY_ENV], timeout=120)
    if not r["ok"]:
        return r
    try:
        item = r["data"]["data"][0]
    except (KeyError, IndexError):
        return {"ok": False, "error": "unexpected response", "raw": r["data"]}
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    if not out_path:
        out_path = str(GENERATED_DIR / f"{int(time.time())}.png")
    if "b64_json" in item:
        Path(out_path).write_bytes(base64.b64decode(item["b64_json"]))
    elif "url" in item:
        try:
            with urllib.request.urlopen(item["url"], timeout=60) as resp:
                Path(out_path).write_bytes(resp.read())
        except Exception as e:
            return {"ok": False, "error": f"download failed: {e}", "url": item["url"]}
    else:
        return {"ok": False, "error": "no image data", "raw": item}
    _log_media("generated", out_path, prompt=prompt)
    return {"ok": True, "path": out_path, "model": M.IMAGE_GEN}


# ---------- semantic search ----------

def _embed_query(text: str) -> list[float] | None:
    keys = _load_secrets()
    if not keys.get(M.API_KEY_ENV):
        return None
    payload = {"model": M.EMBED, "input": text}
    r = _http_post(M.EMBED_URL, payload, keys[M.API_KEY_ENV])
    if not r["ok"]:
        return None
    try:
        return r["data"]["data"][0]["embedding"]
    except (KeyError, IndexError):
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _unpack_embedding(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


@mcp.tool()
def semantic_search(query: str, k: int = 5, path_prefix: str = "") -> dict:
    """Top-k vault chunks by cosine similarity. path_prefix filters (e.g. 'journal/')."""
    qv = _embed_query(query)
    if qv is None:
        return {"ok": False, "error": "OPENAI_API_KEY missing or embed call failed"}
    import sqlite3
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        sql = "SELECT path, heading, chunk, embedding FROM vault_chunks"
        params: list[Any] = []
        if path_prefix:
            sql += " WHERE path LIKE ?"
            params.append(f"{path_prefix}%")
        rows = conn.execute(sql, params).fetchall()
        conn.close()
    except Exception as e:
        return {"ok": False, "error": f"db read failed: {e}"}
    if not rows:
        return {"ok": True, "results": [], "note": "no vault_chunks indexed yet - run ~/scripts/vault_index.py --rebuild"}
    scored = []
    for r in rows:
        emb = _unpack_embedding(r["embedding"])
        scored.append((_cosine(qv, emb), r["path"], r["heading"], r["chunk"]))
    scored.sort(reverse=True, key=lambda t: t[0])
    results = [
        {"score": round(s, 4), "path": p, "heading": h, "chunk": c[:800]}
        for (s, p, h, c) in scored[:k]
    ]
    return {"ok": True, "results": results, "model": M.EMBED}


# ---------- query (read-only) ----------

@mcp.tool()
def query_db(sql: str) -> dict:
    """Run a read-only SELECT on db.sqlite. Rejects any non-SELECT."""
    sql_l = sql.lstrip().lower()
    if not sql_l.startswith("select"):
        return {"ok": False, "error": "only SELECT allowed"}
    return _run_db(["query", sql])


# ---------- web ----------

EXA_URL = "https://api.exa.ai/search"
FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"


@mcp.tool()
def web_search(query: str, num_results: int = 5) -> dict:
    """Semantic web search via Exa. Returns title / url / summary / highlights for each hit.
    Use for discovery - "what's the current state of X", "who's writing about Y"."""
    keys = _load_secrets()
    if not keys.get("EXA_API_KEY"):
        return {"ok": False, "error": "EXA_API_KEY missing"}
    payload = {
        "query": query,
        "numResults": max(1, min(int(num_results), 10)),
        "type": "auto",
        "useAutoprompt": True,
        "contents": {
            "text": {"maxCharacters": 1500},
            "highlights": {"numSentences": 2, "highlightsPerUrl": 2},
        },
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        EXA_URL,
        data=body,
        headers={
            "x-api-key": keys["EXA_API_KEY"],
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Default Python-urllib UA is blocked by Cloudflare (err 1010).
            "User-Agent": "agent-mcp/1.0 (+)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"exa http {e.code}: {e.read().decode()[:400]}"}
    except Exception as e:
        return {"ok": False, "error": f"exa: {e}"}
    results = []
    for it in data.get("results", []):
        results.append({
            "title": it.get("title", ""),
            "url": it.get("url", ""),
            "score": it.get("score"),
            "published": it.get("publishedDate", ""),
            "summary": (it.get("text") or "")[:600],
            "highlights": it.get("highlights", []),
        })
    return {"ok": True, "results": results, "autoprompt": data.get("autopromptString", "")}


@mcp.tool()
def web_fetch(url: str, max_chars: int = 5000) -> dict:
    """Fetch a URL and return clean markdown via Firecrawl.
    Use for "summarise this article" or "what does this page actually say"."""
    keys = _load_secrets()
    if not keys.get("FIRECRAWL_API_KEY"):
        return {"ok": False, "error": "FIRECRAWL_API_KEY missing"}
    payload = {"url": url, "formats": ["markdown"], "onlyMainContent": True}
    r = _http_post(FIRECRAWL_URL, payload, keys["FIRECRAWL_API_KEY"], timeout=45)
    if not r["ok"]:
        return r
    data = r["data"]
    if not data.get("success", True):
        return {"ok": False, "error": data.get("error") or "firecrawl returned success=false", "raw": data}
    inner = data.get("data") or data
    md = inner.get("markdown") or ""
    meta = inner.get("metadata") or {}
    return {
        "ok": True,
        "url": meta.get("sourceURL") or url,
        "title": meta.get("title", ""),
        "status": meta.get("statusCode"),
        "markdown": md[:max(500, int(max_chars))],
        "truncated": len(md) > max_chars,
    }


if __name__ == "__main__":
    mcp.run()
