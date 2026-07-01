#!/usr/bin/env python3
"""
voicenote_sweep.py - sweeps orphan .ogg files from ~/.agent-runtime/media/inbound/
that the agent didn't archive at runtime, transcribes them, and archives to vault.

Idempotent: skips .oggs younger than 5 min (avoids racing live agent turns)
and skips files whose basename is already referenced in voicenotes.file_path.

Cron: 0 * * * * /usr/bin/python3 /path/to/ai-ops-agent/scripts/voicenote_sweep.py >> /tmp/voicenote_sweep.log 2>&1
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

HOME = Path.home()
INBOUND = HOME / ".agent-runtime" / "media" / "inbound"
VAULT = Path(os.environ.get("AGENT_VAULT_DIR", str(Path.home() / "vault"))).expanduser()
VOICENOTES_DIR = VAULT / "voicenotes"
DB_PATH = VAULT / "db.sqlite"
TRANSCRIBE = HOME / "scripts" / "transcribe.py"
SECRETS = Path(os.environ.get("AGENT_ENV_FILE", str(Path.home() / ".config" / "ai-ops-agent" / "secrets.env"))).expanduser()

MIN_AGE_SECONDS = 300  # 5 min - avoids racing an active the agent turn


def load_secrets() -> dict:
    out = {}
    if not SECRETS.exists():
        return out
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def transcribe(audio_path: Path) -> str:
    env = os.environ.copy()
    env.update(load_secrets())
    r = subprocess.run(
        ["python3", str(TRANSCRIBE), str(audio_path)],
        capture_output=True, text=True, timeout=180, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"transcribe failed: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def already_archived(basename: str, conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM voicenotes WHERE file_path LIKE ? LIMIT 1",
        (f"%{basename}",),
    ).fetchone()
    return bool(row)


def archive(audio_src: Path, transcript: str) -> Path:
    today = date.today().isoformat()
    now = datetime.now().strftime("%H%M%S")
    out_dir = VOICENOTES_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)
    # Disambiguate if multiple voicenotes arrive in same second
    base = now
    audio_dst = out_dir / f"{base}.ogg"
    n = 1
    while audio_dst.exists():
        audio_dst = out_dir / f"{base}-{n}.ogg"
        n += 1
    md_dst = audio_dst.with_suffix(".md")
    try:
        audio_src.rename(audio_dst)
    except OSError:
        shutil.copy2(audio_src, audio_dst)
        try:
            audio_src.unlink()
        except OSError:
            pass
    rel_audio = audio_dst.relative_to(VAULT).as_posix()
    md_dst.write_text(
        "---\n"
        f"date: {today}\n"
        f"time: {datetime.now().strftime('%H:%M:%S')}\n"
        f"audio: {rel_audio}\n"
        "category: \n"
        "routed_to: sweep\n"
        "source_basename: " + audio_src.name + "\n"
        "---\n\n"
        f"{transcript.strip()}\n"
    )
    return audio_dst


def main():
    if not INBOUND.exists():
        print(f"[skip] no inbound dir: {INBOUND}")
        return
    if not DB_PATH.exists():
        print(f"[skip] no db at {DB_PATH}")
        return
    conn = sqlite3.connect(str(DB_PATH))
    now = time.time()
    swept = 0
    skipped_young = 0
    skipped_dup = 0
    errors = 0
    for src in sorted(INBOUND.glob("*.ogg")):
        try:
            age = now - src.stat().st_mtime
        except OSError:
            continue
        if age < MIN_AGE_SECONDS:
            skipped_young += 1
            continue
        if already_archived(src.name, conn):
            try:
                src.unlink()
                print(f"[clean] {src.name}: already archived, removed orphan from inbound")
            except OSError:
                pass
            continue
        try:
            transcript = transcribe(src)
            if not transcript:
                print(f"[skip] {src.name}: empty transcript", file=sys.stderr)
                continue
            audio_dst = archive(src, transcript)
            conn.execute(
                "INSERT INTO voicenotes (transcription, category, routed_to, file_path) "
                "VALUES (?, ?, ?, ?)",
                (transcript, None, "sweep", str(audio_dst)),
            )
            conn.commit()
            swept += 1
            print(f"[ok] {src.name} -> {audio_dst.relative_to(VAULT)}")
        except Exception as e:
            errors += 1
            print(f"[err] {src.name}: {e}", file=sys.stderr)
    conn.close()
    print(f"[done] swept={swept} skipped_young={skipped_young} skipped_dup={skipped_dup} errors={errors}")


if __name__ == "__main__":
    main()
