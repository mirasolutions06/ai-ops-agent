#!/usr/bin/env python3
"""
vault_index.py - incremental embedding indexer for ~/vault/

Walks the vault, chunks markdown by heading, embeds via OpenAI
text-embedding-3-small, stores in db.sqlite's vault_chunks table.

Default: incremental (only re-embed files whose mtime changed).
--rebuild: wipe + full reindex.

Cron (every 15 min on VPS):
  */15 * * * * /usr/bin/python3 /path/to/ai-ops-agent/scripts/vault_index.py

Reads OPENAI_API_KEY from your env file (AGENT_ENV_FILE) (or env).
"""

import json
import os
import re
import sqlite3
import struct
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import models as M  # noqa: E402

HOME = Path.home()
VAULT = Path(os.environ.get("AGENT_VAULT_DIR", str(Path.home() / "vault"))).expanduser()
DB_PATH = VAULT / "db.sqlite"
SECRETS = Path(os.environ.get("AGENT_ENV_FILE", str(Path.home() / ".config" / "ai-ops-agent" / "secrets.env"))).expanduser()

EXCLUDE_DIRS = {".git", ".obsidian", ".trash", "inbox/generated", "node_modules", "another agent"}
INCLUDE_EXTS = {".md", ".txt"}
MAX_CHUNK_CHARS = 3200          # ~800 tokens
BATCH_SIZE = 64                 # OpenAI embeddings batch
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)


def load_secrets() -> dict:
    out = {}
    if SECRETS.exists():
        for line in SECRETS.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    for k in (M.API_KEY_ENV,):
        if k not in out and os.environ.get(k):
            out[k] = os.environ[k]
    return out


def iter_files():
    for p in VAULT.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in INCLUDE_EXTS:
            continue
        rel = p.relative_to(VAULT).as_posix()
        if any(rel.startswith(d) or f"/{d}/" in rel for d in EXCLUDE_DIRS):
            continue
        yield p, rel


def chunk_markdown(text: str) -> list[tuple[str, str]]:
    """Split markdown on headings. Returns [(heading, chunk), ...].

    If a section exceeds MAX_CHUNK_CHARS, further split on double-newlines.
    """
    if not text.strip():
        return []
    # find heading positions
    matches = list(HEADING_RE.finditer(text))
    sections: list[tuple[str, str]] = []
    if not matches:
        sections.append(("", text))
    else:
        if matches[0].start() > 0:
            sections.append(("", text[: matches[0].start()]))
        for i, m in enumerate(matches):
            heading = m.group(2).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if body:
                sections.append((heading, body))

    out: list[tuple[str, str]] = []
    for heading, body in sections:
        if len(body) <= MAX_CHUNK_CHARS:
            out.append((heading, body))
            continue
        # split on paragraph breaks, greedy pack into MAX_CHUNK_CHARS
        paras = re.split(r"\n\n+", body)
        buf = ""
        for para in paras:
            if len(buf) + len(para) + 2 > MAX_CHUNK_CHARS and buf:
                out.append((heading, buf.strip()))
                buf = para
            else:
                buf = f"{buf}\n\n{para}" if buf else para
        if buf.strip():
            out.append((heading, buf.strip()))
    return out


def embed_batch(texts: list[str], api_key: str) -> list[list[float]]:
    payload = {"model": M.EMBED, "input": texts}
    req = urllib.request.Request(
        M.EMBED_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    return [d["embedding"] for d in data["data"]]


def pack_embedding(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def ensure_schema(conn):
    conn.executescript("""
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
    conn.commit()


def main():
    rebuild = "--rebuild" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    keys = load_secrets()
    api_key = keys.get(M.API_KEY_ENV)
    if not api_key:
        print("ERROR: OPENAI_API_KEY missing in your env file (AGENT_ENV_FILE) or env", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    if rebuild:
        conn.execute("DELETE FROM vault_chunks")
        conn.commit()
        print("[rebuild] cleared vault_chunks")

    # mtime map of what's already indexed
    existing = {
        r["path"]: r["mtime"]
        for r in conn.execute("SELECT path, MAX(mtime) AS mtime FROM vault_chunks GROUP BY path")
    }

    to_embed: list[tuple[str, str, str, float]] = []   # (path, heading, chunk, mtime)
    changed_paths: set[str] = set()
    scanned = 0

    for p, rel in iter_files():
        scanned += 1
        mtime = p.stat().st_mtime
        if not rebuild and existing.get(rel) == mtime:
            continue
        try:
            text = p.read_text(errors="ignore")
        except Exception as e:
            print(f"[skip] {rel}: {e}", file=sys.stderr)
            continue
        chunks = chunk_markdown(text)
        if not chunks:
            continue
        changed_paths.add(rel)
        for heading, chunk in chunks:
            to_embed.append((rel, heading, chunk, mtime))

    if not to_embed:
        print(f"[ok] scanned {scanned} files, nothing to index")
        conn.close()
        return

    # delete existing rows for changed paths
    if changed_paths and not rebuild:
        conn.executemany("DELETE FROM vault_chunks WHERE path = ?", [(p,) for p in changed_paths])
        conn.commit()

    # embed + insert in batches
    inserted = 0
    for i in range(0, len(to_embed), BATCH_SIZE):
        batch = to_embed[i : i + BATCH_SIZE]
        texts = [f"{h}\n\n{c}" if h else c for (_, h, c, _) in batch]
        for attempt in range(3):
            try:
                vectors = embed_batch(texts, api_key)
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode()[:300] if hasattr(e, "read") else str(e)
                print(f"[retry {attempt+1}] http {e.code}: {msg}", file=sys.stderr)
                time.sleep(2 ** attempt)
            except Exception as e:
                print(f"[retry {attempt+1}] {e}", file=sys.stderr)
                time.sleep(2 ** attempt)
        else:
            print(f"[fail] batch {i} after 3 retries", file=sys.stderr)
            continue
        rows = [
            (path, heading, chunk, mtime, pack_embedding(vec))
            for ((path, heading, chunk, mtime), vec) in zip(batch, vectors)
        ]
        conn.executemany(
            "INSERT INTO vault_chunks (path, heading, chunk, mtime, embedding) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        inserted += len(rows)
        if verbose:
            print(f"[+] {inserted}/{len(to_embed)}")

    print(f"[ok] scanned {scanned} files, {len(changed_paths)} changed, {inserted} chunks indexed")
    conn.close()


if __name__ == "__main__":
    main()
