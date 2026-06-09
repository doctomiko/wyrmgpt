# Discord Connector Containerization Notes

## Current approach
The connector source lives in Git. Mutable runtime state lives outside Git in persistent host storage.

Recommended runtime root:
- `/opt/openclaw-data/discord-connector/`

Recommended runtime subfolders:
- `config/`
- `data/default_tenant/`
- `data/q-continuum/`
- `data/vivians-boudoir/`
- `prompts/`
- `logs/`
- `backups/`

## Runtime assumptions
The connector already supports environment-driven runtime settings.

Important variables:
- `DISCORD_TOKEN`
- `SQLITE_PATH`
- `SYSTEM_PROMPT_PATH`

Suggested values in container runtime:
- `SQLITE_PATH=/runtime/data/default_tenant/callie.sqlite3`
- `SYSTEM_PROMPT_PATH=/runtime/prompts/system_prompt.txt`

## Why prompts are mounted
Prompt defaults are kept in the repo, but the live mounted prompt path should be mutable so prompt edits survive container restarts and rebuilds.

## Build model
The repo now includes:
- `Dockerfile`
- `docker-compose.example.yml`

The intended deployment model is:
1. source is versioned in GitHub
2. runtime state is mounted from `/opt/openclaw-data/discord-connector/`
3. the container is built from repo source, not from a dirty mutable working tree

## Notes
- `.venv` is intentionally not part of runtime persistence.
- SQLite, backups, and real `.env` files should stay outside Git.
- Multi-tenant runtime data can live under per-tenant subfolders beneath `data/`.
