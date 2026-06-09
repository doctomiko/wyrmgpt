# Discord Connector Host Rebuild Notes

This document explains how to rebuild the Discord connector container from the GitHub-backed working copy on the host.

## Working copy location on host
- `/opt/openclaw-data/workspace/wyrmgpt/connectors/discord-connector`

## Update the repo on the host
From the WyrmGPT repo root:
```bash
cd /opt/openclaw-data/workspace/wyrmgpt
git pull
```

If you want to preview inbound commits first:
```bash
cd /opt/openclaw-data/workspace/wyrmgpt
git fetch
git log --oneline HEAD..origin/main
```

## Rebuild and restart the connector container
```bash
cd /opt/openclaw-data/workspace/wyrmgpt/connectors/discord-connector
docker compose -f docker-compose.host.yml up -d --build
```

## Watch logs
```bash
docker logs --tail 200 -f wyrmgpt-discord-connector
```

## Current persistent runtime root
- `/opt/openclaw-data/discord-connector/`

### Current host runtime contents
- `config/.env`
- `data/`
- `prompts/`
- `logs/`
- `backups/`

### Current host-to-container mounts
- host: `/opt/openclaw-data/discord-connector/data/`
  - container: `/runtime/data/`
- host: `/opt/openclaw-data/discord-connector/prompts/`
  - container: `/runtime/prompts/`
- host: `/opt/openclaw-data/discord-connector/config/`
  - container: `/runtime/config/`
- host: `/opt/openclaw-data/discord-connector/logs/`
  - container: `/runtime/logs/`
- host: `/opt/openclaw-data/discord-connector/backups/`
  - container: `/runtime/backups/`

## Notes
- Real secrets stay outside Git in `config/.env`.
- Live SQLite state stays outside Git under `data/`.
- Prompt overrides stay outside Git under `prompts/`, while repo copies remain useful as defaults/reference.
- The container does not create a `.venv`; dependencies are installed into the image at build time from `requirements.txt`.
