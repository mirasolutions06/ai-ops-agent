<div align="center">

# AI Ops Agent

**A self-hosted AI chief-of-staff with a heartbeat.** Tasks, calendar, a
searchable memory vault, scheduled briefings, and a live mission-control
dashboard, all driven from chat and owned entirely by you.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/mirasolutions06/ai-ops-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/mirasolutions06/ai-ops-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![MCP tools](https://img.shields.io/badge/MCP%20tools-24-8A2BE2.svg)
![Tests](https://img.shields.io/badge/tests-22-brightgreen.svg)

[Architecture](ARCHITECTURE.md) · [Runbook](RUNBOOK.md) · [Configure](#configure-it-for-your-setup)

<img src="docs/images/dashboard.png" alt="AI Ops Agent mission-control dashboard: agent status, uptime, scheduled jobs, token usage and cost" width="820">

</div>

## Why

Most "AI assistants" are a chat box that forgets everything and does nothing when
you stop typing. This is the opposite: an agent with a heartbeat. It wakes on a
schedule, keeps durable memory in a markdown vault and SQLite, does real work
through typed tools, and only ever writes inside safe boundaries. You run it, you
own the data, and a dashboard shows you exactly what it is doing.

The hard part was never "call an LLM." It was the operating system around it: what
the agent should know before it speaks, which actions are deterministic tools
instead of model guesses, and how state survives across days. This repo is that
operating system, generalised so you can point it at your own vault, models, and
schedule.

## What it does

| Capability | What you get |
|---|---|
| **Memory vault** | Read, append, and search a private markdown vault; a background indexer embeds it for semantic recall. |
| **Tasks and routines** | Task lifecycle in SQLite, mirrored to an Obsidian-compatible `tasks.md`; habit streaks; daily activity and mood. |
| **Scheduled loop** | Morning brief, evening digest (writes a journal entry), weekly review, plus sweeps that keep the index and task mirror in sync. |
| **Voice notes** | Archive audio and transcript, then route by shape into tasks, notes, or longer entries. |
| **Multimodal** | Image and video analysis, OCR, and text-to-image, behind one tool surface. |
| **Ops dashboard** | A FastAPI mission-control panel: agent status, uptime, scheduled jobs, logs, token usage, and cost. |

**24 MCP tools** in total: vault (`vault_read`, `vault_append`, `vault_tree`,
`semantic_search`), tasks and state (`task_add`, `task_close`, `task_list`,
`tasks_render_md`, `mood_log`, `note_quick`, `activity_log`, `activity_update`,
`workout_archive`, `voicenote_archive`), calendar (`calendar_list`,
`calendar_add`, `calendar_delete`), multimodal (`vision_analyze`,
`video_analyze`, `ocr_extract`, `image_generate`), and data (`query_db`,
`web_search`, `web_fetch`).

## How it works

Three layers you change independently: the **tool server** (this repo), the
**agent runtime** that drives it (any MCP-capable brain), and the **schedule**
that wakes it.

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

Full detail in [ARCHITECTURE.md](ARCHITECTURE.md).

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
make install
make test          # 22 tests, no live secrets needed
make db-init        # create the SQLite schema
```

Run the tool server or the dashboard locally:

```bash
AGENT_VAULT_DIR="$PWD/.vault" python3 scripts/agent_mcp.py       # MCP tool server (stdio)
AGENT_VAULT_DIR="$PWD/.vault" python3 scripts/dashboard_main.py  # dashboard at http://localhost:7474
```

## Configure it for your setup

Copy `config.example.json` to `config.json` and set your vault path, the model for
each tier (`scripts/models.py`), and the schedule. Point the paths at your own
vault and runtime with the `AGENT_*` variables in `.env.example`. Wire the tool
server to an MCP runtime and a scheduler, and run it locally or on a VPS for
always-on operation. Step by step in [RUNBOOK.md](RUNBOOK.md).

Defaults to OpenAI (`gpt-4o` and friends); switch to any OpenAI-compatible
provider (z.ai, DeepSeek, a local server) with a one-line edit in `models.py`.

## Built with

Python · [MCP](https://modelcontextprotocol.io) (FastMCP) · SQLite · FastAPI ·
OpenAI-compatible model providers. No framework lock-in; the tool layer is plain
Python behind a typed MCP surface.

## Safety and privacy

Credentials never live in the repo (`.env` locally, or a server env file via
`AGENT_ENV_FILE`). Vault paths are resolved under the vault root and reject
escapes; free-form SQL is read-only. No hostnames, IPs, vault contents, or
personal data are committed.

## License

MIT, see [LICENSE](LICENSE). Use it, fork it, adapt it for your own setup.

## Contact

Built and operated by Mira Solutions, an AI engineering and automation studio.

mira.solutions06@gmail.com
