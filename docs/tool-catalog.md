# Tool Catalog

The public MCP surface is grouped by what an operator or runtime is trying to do.
All writes are constrained to configured paths or SQLite state.

## Vault and recall

| Tool | Purpose |
|---|---|
| `vault_read` | Read a markdown file from the configured vault. |
| `vault_append` | Append a headed note to a markdown file. |
| `vault_tree` | Inspect the vault structure without opening every file. |
| `semantic_search` | Search indexed vault chunks by meaning. |
| `web_search` / `web_fetch` | Pull public web context when the runtime needs it. |

## Tasks and daily state

| Tool | Purpose |
|---|---|
| `task_add` | Add a task with priority and source metadata. |
| `task_close` | Close a task by id or text match. |
| `task_list` | List tasks by status. |
| `tasks_render_md` | Render the markdown task mirror. |
| `mood_log` | Store a simple mood note. |
| `activity_log` / `activity_update` | Record or revise activity entries. |
| `note_quick` | Capture a short inbox note. |
| `workout_archive` | Archive structured workout details. |

## Calendar and schedule context

| Tool | Purpose |
|---|---|
| `calendar_list` | Read upcoming events. |
| `calendar_add` | Create an event. |
| `calendar_delete` | Remove an event by id. |

## Voice, media, and multimodal

| Tool | Purpose |
|---|---|
| `voicenote_archive` | Store audio plus transcript and routing metadata. |
| `vision_analyze` | Ask a vision model to describe or inspect an image. |
| `video_analyze` | Ask a vision model to inspect a video. |
| `ocr_extract` | Extract text from an image. |
| `image_generate` | Generate an image into the configured vault output folder. |

## Data inspection

| Tool | Purpose |
|---|---|
| `query_db` | Read-only SQL inspection for trusted operators and dashboards. |

## Scheduled scripts

| Script | Purpose |
|---|---|
| `daily_digest.py` | Build the daily digest payload. |
| `vault_index.py` | Chunk and embed changed markdown files. |
| `tasks_md_sweep.py` | Keep the markdown task mirror in sync. |
| `voicenote_sweep.py` | Archive voice notes that were not captured live. |
| `dashboard_main.py` | Serve the local status dashboard. |

## Safety boundaries

- Vault paths resolve under `AGENT_VAULT_DIR`.
- SQL is read-only through the MCP surface.
- Secrets are loaded from environment files, not committed.
- The runtime can be swapped without changing the tool server.
