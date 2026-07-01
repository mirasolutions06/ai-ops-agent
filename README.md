# AI Ops Agent

An always-on AI chief-of-staff for one person or a small team. It runs the
day-to-day from chat: tasks, calendar, notes, habits and activity, voice-note
capture, semantic search over a private markdown vault, scheduled briefings
(morning, evening, weekly), and multimodal tools (vision, OCR, image
generation). A live mission-control dashboard shows the agent's uptime,
scheduled jobs, token usage, and cost.

This is the reusable engine, built to be pointed at your own setup. Configure
your vault, your models, and your schedule, and the same pipeline runs for
personal ops, a founder's second brain, or a small team's assistant. It runs
locally, or on a VPS with a process manager for always-on operation.

## Architecture

Three layers you change independently: the **tool server** (this repo), the
**agent runtime** that drives it (any MCP-capable brain), and the **schedule**
that wakes it. Full detail in [ARCHITECTURE.md](ARCHITECTURE.md).

```mermaid
flowchart TD
    Cron["Scheduler: morning brief, evening digest, weekly review, sweeps"] --> Runtime["Agent runtime (any MCP brain)"]
    Chat["You (Telegram / chat)"] --> Runtime
    Runtime --> MCP["FastMCP tool server (this repo): 24 tools"]
    MCP --> Vault[("Markdown vault")]
    MCP --> DB[("SQLite: tasks, habits, activity, notes")]
    MCP --> Search["Semantic vault search (embeddings)"]
    MCP --> Multi["Vision / OCR / image gen / calendar"]
    Dash["Ops dashboard (FastAPI)"] --> DB
    Dash --> Metrics["System + gateway uptime, jobs, token cost"]
```

## What it does

- **Vault as memory**: read, append, and tree a private markdown vault; a
  background indexer chunks it and stores embeddings for semantic recall.
- **Tasks and routines**: task lifecycle in SQLite, mirrored to an
  Obsidian-compatible `tasks.md`; habit streaks; activity and daily state.
- **Scheduled operating loop**: morning brief, evening digest (writes a journal
  entry), weekly review, plus sweeps that keep the vault index and task mirror in
  sync.
- **Voice-note routing**: archive audio + transcript, then route by shape into
  tasks, notes, or longer entries.
- **Multimodal tools**: image and video analysis, OCR, and text-to-image.
- **Ops dashboard**: a FastAPI mission-control panel for agent status, uptime,
  scheduled jobs, logs, token usage, and cost.

## Tool surface

A FastMCP stdio server exposing **24 tools**: `vault_read`, `vault_append`,
`vault_tree`, `semantic_search`, `task_add`, `task_close`, `task_list`,
`tasks_render_md`, `mood_log`, `note_quick`, `activity_log`, `activity_update`,
`workout_archive`, `voicenote_archive`, `calendar_list`, `calendar_add`,
`calendar_delete`, `vision_analyze`, `video_analyze`, `ocr_extract`,
`image_generate`, `query_db`, `web_search`, `web_fetch`. The tool layer is
model-swappable and runs behind any MCP-capable agent runtime.

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
make install
make test
cp .env.example .env
make db-init
```

Run the MCP server, or the dashboard, locally:

```bash
AGENT_VAULT_DIR="$PWD/.vault" python3 scripts/agent_mcp.py       # MCP tool server (stdio)
AGENT_VAULT_DIR="$PWD/.vault" python3 scripts/dashboard_main.py  # dashboard on http://localhost:7474
```

Real provider calls require the keys in `.env`. Tests require no live secrets.

## Configure it for your setup

Copy `config.example.json` to `config.json` and set your vault path, the models
each tier uses (`scripts/models.py`), and the schedule. Point the paths at your
own vault and runtime with the `AGENT_*` variables in `.env.example`. Wire the
tool server to an MCP runtime and a scheduler, and run it locally or on a VPS.
Step by step in [RUNBOOK.md](RUNBOOK.md).

## Secrets

Credentials never live in the repo. Keep them in `.env` locally, or in a server
environment file (referenced by `AGENT_ENV_FILE`) outside git. No live
hostnames, IPs, vault contents, or personal data are committed.

## Contact

Built and operated by Mira Solutions, an AI engineering and automation studio.

mira.solutions06@gmail.com
