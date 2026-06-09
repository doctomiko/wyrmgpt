# WyrmGPT Containerization Notes

## Goal
Run the main WyrmGPT web service in a container on the server while keeping mutable runtime state outside Git.

## Runtime root
Recommended host runtime root:
- `/opt/openclaw-data/wyrmgpt/`

Suggested host contents:
- `config.toml`
- `config.secrets.toml`
- `prompts/`
- `data/`

## Why this layout
WyrmGPT already expects repo-root-relative paths such as:
- `./prompts/...`
- `./data/...`
- `./config.toml`
- `./config.secrets.toml`

The container setup preserves those expectations by mounting persistent host files and folders directly onto the in-container paths under `/app`.

## Container entrypoint
The current Dockerfile runs:
- `uvicorn server.main:app --host 0.0.0.0 --port 8000`

## Host compose example
The repo includes `docker-compose.host.yml` which:
- builds from `/opt/openclaw-data/workspace/wyrmgpt`
- exposes the app on host port `18080`
- mounts persistent config, prompts, and data from `/opt/openclaw-data/wyrmgpt/`

## Notes
- Python dependencies are installed at image build time, not container startup time.
- No `.venv` is required in the containerized runtime model.
- If requirements change, rebuild the image.
- If prompt or config files change on the host-mounted paths, the container sees those changes without rebuilding.
