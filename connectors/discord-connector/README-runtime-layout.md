# Discord Connector Runtime Layout Notes

This connector is intended to be committed to Git as source, templates, prompts, docs, and historical reference material.

## What stays in the repo
- Python source files
- PowerShell helper scripts
- `Prompts/` defaults
- `.env.example`
- `.env.redacted`
- `_cruft/` historical reference material retained intentionally
- documentation and changelog material

## What stays out of the repo
Live runtime state and secrets should live outside Git in persistent host storage.

Recommended host runtime root:
- `/opt/openclaw-data/discord-connector/`

Recommended subfolders:
- `config/`
- `data/default_tenant/`
- `data/q-continuum/`
- `data/vivians-boudoir/`
- `prompts/`
- `logs/`
- `backups/`

## Recommended runtime mapping
Typical live files outside Git:
- real `.env` at `config/.env`
- live SQLite database files under `data/<tenant>/`
- mutable prompt overrides under `prompts/`
- runtime logs under `logs/`
- backup archives under `backups/`

## Intent
This split keeps Git as the canonical source for code and reference material while allowing containerized deployments to preserve secrets, tenant data, prompt edits, logs, and backups across restarts.
