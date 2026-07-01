# Contributing

Thanks for taking a look at AI Ops Agent. This repo is meant to stay easy to
read, safe to run locally, and clear about what is real versus environment-
specific wiring.

## Local checks

```bash
python3 -m venv .venv
. .venv/bin/activate
make install
make check
```

`make check` runs the lightweight lint gate and the no-secret test suite.

## What makes a good change

- Keep examples sanitized: no real vault paths, hostnames, IPs, tokens, calendar
  details, or personal data.
- Prefer small, deterministic tools over model-only behavior.
- Update `README.md`, `ARCHITECTURE.md`, or `RUNBOOK.md` when setup, commands, or
  behavior changes.
- Add or update tests for database state, tool behavior, scheduled jobs, and
  safety boundaries.

## Before opening a PR

1. Run `make check`.
2. Confirm `.env`, `config.json`, local vaults, and generated databases are not
   staged.
3. Explain which workflow changed and how you verified it.
