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

## Cost and Backend UAT Notes

The connector can log per-response OpenAI usage/cost when the provider returns usage metadata. Configure these in `/opt/openclaw-data/discord-connector/config/.env`:

```bash
OPENAI_COST_LOG_ENABLED=1
OPENAI_MONTHLY_BUDGET_USD=30.00
OPENAI_MONTH_TO_DATE_SPEND_USD=0.00
OPENAI_COST_INPUT_PER_1M=1.75
OPENAI_COST_OUTPUT_PER_1M=14.00
OPENAI_MODEL_PRICING_JSON=/runtime/config/model_catalog.json
# OPENAI_MODEL_PRICING_JSON={"gpt-4o-mini":{"input_per_1m":0.15,"output_per_1m":0.60}}
```

`OPENAI_MONTH_TO_DATE_SPEND_USD` is an operator-provided starting offset. The connector adds its in-process estimates on top of it; it is not a billing API readout. `OPENAI_MODEL_PRICING_JSON` accepts either inline JSON or a path to a model catalog JSON file. In the host compose setup, the WyrmGPT repo's `server/model_catalog.json` is mounted read-only at `/runtime/config/model_catalog.json`. The fallback input/output prices are used when the current model is missing from the catalog.

The backend selector is also configurable:

```bash
CONNECTOR_LLM_BACKEND=authenticated_session
CONNECTOR_AUTH_MODE=oauth_device_code
OPENAI_API_KEY=<fallback-platform-api-token>
OPENAI_OAUTH_TOKEN=<chatgpt-or-codex-access-token>
OPENAI_OAUTH_REFRESH_TOKEN=<chatgpt-or-codex-refresh-token>
OPENAI_OAUTH_TOKEN_PATH=/runtime/config/openai_oauth_token
OPENAI_OAUTH_REFRESH_TOKEN_PATH=/runtime/config/openai_oauth_refresh_token
CONNECTOR_OAUTH_DEVICE_CODE_COMMAND=python /app/codex_device_auth.py --env-file /runtime/config/.env
```

`OPENAI_API_KEY` remains the existing Platform API token setting. `OPENAI_API_TOKEN` is accepted only as an optional alias fallback. `OPENAI_OAUTH_TOKEN` and `OPENAI_OAUTH_REFRESH_TOKEN` are future ChatGPT/Codex-style token slots. The connector can also read those OAuth tokens from the files named by `OPENAI_OAUTH_TOKEN_PATH` and `OPENAI_OAUTH_REFRESH_TOKEN_PATH`.

To generate OAuth token files for UAT, run this from inside the rebuilt connector container or an equivalent environment:

```bash
python /app/codex_device_auth.py --env-file /runtime/config/.env
```

The helper prints `https://auth.openai.com/codex/device` and a short user code, waits while you complete browser authorization, then writes the access and refresh tokens to the configured token files with owner-only permissions where possible. The short-lived device code is not stored.

`authenticated_session` is reserved for future OAuth/device-code/session providers. If selected before a provider transport exists, the connector logs a clear configuration error and does not fall back silently.
