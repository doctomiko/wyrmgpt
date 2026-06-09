# Host Rebuild and Persistent Storage Notes

This document explains how to rebuild the current WyrmGPT-related containers from GitHub-backed source on the host, and what persistent storage is currently expected for the main WyrmGPT service.

## Rebuilding from GitHub-backed source

These commands assume the working copy already exists at:
- `/opt/openclaw-data/workspace/wyrmgpt`

### 1. Update the repo on the host
```bash
cd /opt/openclaw-data/workspace/wyrmgpt
git pull
```

If you want to see what changed first:
```bash
cd /opt/openclaw-data/workspace/wyrmgpt
git fetch
git log --oneline HEAD..origin/main
```

## Rebuild the main WyrmGPT web container
```bash
cd /opt/openclaw-data/workspace/wyrmgpt
docker compose -f docker-compose.host.yml up -d --build
```

### Watch logs
```bash
docker logs --tail 200 -f wyrmgpt-web
```

## Rebuild the Discord connector container
```bash
cd /opt/openclaw-data/workspace/wyrmgpt/connectors/discord-connector
docker compose -f docker-compose.host.yml up -d --build
```

### Watch logs
```bash
docker logs --tail 200 -f wyrmgpt-discord-connector
```

## WyrmGPT persistent storage

Current host runtime root:
- `/opt/openclaw-data/wyrmgpt/`

### What lives there now
- `config/config.toml`
- `config/config.secrets.toml`
- `prompts/`
- `data/`

### Current host-to-container mounts
- host: `/opt/openclaw-data/wyrmgpt/config/config.toml`
  - container: `/app/config.toml`
- host: `/opt/openclaw-data/wyrmgpt/config/config.secrets.toml`
  - container: `/app/config.secrets.toml`
- host: `/opt/openclaw-data/wyrmgpt/prompts/`
  - container: `/app/prompts/`
- host: `/opt/openclaw-data/wyrmgpt/data/`
  - container: `/app/data/`

### Why those mounts exist
This preserves the path assumptions already used by WyrmGPT, including repo-root-relative references such as:
- `./prompts/...`
- `./data/...`
- `./config.toml`
- `./config.secrets.toml`

## What is persistent today
Currently persistent for the WyrmGPT web service:
- main TOML config
- secrets TOML config
- prompt files copied to host storage
- SQLite and related app data under `data/`
- local Qdrant storage if configured under `./data/qdrant`

## What could exist later, but is not formalized yet
These may be added later if the deployment grows up more:
- dedicated logs folder mounted from host storage
- dedicated backups folder for DB/app exports
- mounted config-side helper files such as filler-word lists
- per-tenant or per-persona subtrees under data
- import/export staging folders
- more structured memory-migration staging areas

## Important note about dependencies
Neither WyrmGPT nor the Discord connector creates a `.venv` inside the container.

Dependencies are installed into the image at build time from `requirements.txt`.

If requirements change, rebuild the image with:
```bash
docker compose -f docker-compose.host.yml up -d --build
```
