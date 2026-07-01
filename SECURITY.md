# Security Policy

## Supported versions

The public `main` branch is the supported version for this demo/reference repo.

## Reporting a vulnerability

Please email `mira.solutions06@gmail.com` with:

- The affected repo and file or endpoint.
- Steps to reproduce.
- Impact and any suggested fix.

Please do not open a public issue for a vulnerability that exposes secrets,
private data, auth bypasses, filesystem escapes, or unsafe tool execution.

## Data handling expectations

- Do not commit `.env`, `config.json`, local SQLite databases, vault contents, or
  generated logs.
- Keep example paths and screenshots sanitized.
- Tool paths should stay rooted under the configured vault/data directories.
- SQL-facing tools should remain read-only unless a change explicitly documents
  and tests a write path.
