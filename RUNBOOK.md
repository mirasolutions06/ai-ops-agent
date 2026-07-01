# Runbook

How to run this agent and adapt it for your own setup. This repo ships the
**tool server, dashboard, and scheduled scripts** (real, tested code); you drive
them with an MCP-capable runtime and a scheduler, which the steps below set up.

## 1. Install and test

```bash
python3 -m venv .venv
. .venv/bin/activate
make install
make test          # runs the integration smoke tests
make db-init       # create the SQLite schema
```

## 2. Configure your setup

Copy the template and edit it:

```bash
cp config.example.json config.json
```

- **vault_dir** - where your markdown vault and `db.sqlite` live.
- **models** - which model each tier uses; these map to `scripts/models.py`.
- **schedule** - cron expressions for the brief, digest, review, and sweeps.
- **dashboard** - the gateway unit/port to monitor and the dashboard port.

Point the paths at your own vault and runtime with the `AGENT_*` variables in
`.env.example`.

## 3. Set credentials

```bash
cp .env.example .env
```

Fill in the provider key you use. The default provider is **OpenAI**; to use any
OpenAI-compatible provider (z.ai, DeepSeek, a local server), change the endpoint
URLs and `API_KEY_ENV` in `scripts/models.py`.

- **OPENAI_API_KEY** - chat, vision, OCR, image generation, and embeddings (default).
- **GLM_API_KEY** / **DEEPSEEK_API_KEY** - optional, only if you point `models.py`
  at those providers.

Keep real values in `.env` locally, or in a server env file referenced by
`AGENT_ENV_FILE`.

## 4. Run the pieces

```bash
# MCP tool server (stdio) - your runtime spawns this
AGENT_VAULT_DIR="$PWD/.vault" python3 scripts/agent_mcp.py

# Ops dashboard - http://localhost:7474
AGENT_VAULT_DIR="$PWD/.vault" python3 scripts/dashboard_main.py

# The scheduled scripts (wire these to cron / systemd timers)
python3 scripts/daily_digest.py       # evening: assemble the day
python3 scripts/vault_index.py        # re-index the vault for semantic search
python3 scripts/tasks_md_sweep.py     # sync the tasks.md mirror
python3 scripts/voicenote_sweep.py    # archive stray voice notes
```

## 5. Wire a runtime and a schedule

- **Local / manual** - spawn the MCP server and call tools from your runtime on
  demand.
- **Always-on (VPS)** - run the runtime under a process manager
  (systemd / pm2 / supervisor), and fire the brief, digest, review, and sweep
  scripts from cron or timers using the cadence in your config. Keep credentials
  in a server env file outside git.

## Useful commands

```bash
make test                                   # run the smoke tests
make db-init                                # create the schema
python3 scripts/agent_db.py tasks list      # list open tasks
python3 scripts/agent_db.py query "SELECT name FROM sqlite_master WHERE type='table'"
```
