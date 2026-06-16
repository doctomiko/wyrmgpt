#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/rebuild-host-container.sh [options]

Rebuild and restart the WyrmGPT host container.

This is the host-oriented deploy path. It defaults to the persistent layout:
  source:  /opt/openclaw-data/workspace/wyrmgpt
  runtime: /opt/openclaw-data/wyrmgpt
  port:    18080

Options:
  --pull        Run git pull --ff-only before rebuilding.
  --no-build    Restart without rebuilding the image.
  --logs        Follow logs after restart.
  --status      Show compose status and exit.
  --down        Stop/remove the container and exit.
  -h, --help    Show this help.

Environment:
  WYRMGPT_HOST_REPO       Source checkout. Default: script repo, or /opt/openclaw-data/workspace/wyrmgpt when present
  WYRMGPT_RUNTIME_ROOT    Persistent runtime root. Default: /opt/openclaw-data/wyrmgpt
  WYRMGPT_DATA_ROOT       Persistent app data folder. Default: $WYRMGPT_RUNTIME_ROOT/data
  WYRMGPT_PORT            Host port. Default: 18080
  WYRMGPT_CONTAINER_NAME  Container name. Default: wyrmgpt-web
  WYRMGPT_IMAGE_NAME      Image name. Default: wyrmgpt-web:host
  WYRMGPT_COMPOSE_PROJECT Compose project name. Default: wyrmgpt

Examples:
  scripts/rebuild-host-container.sh
  scripts/rebuild-host-container.sh --pull --logs
  WYRMGPT_PORT=8080 scripts/rebuild-host-container.sh
EOF
}

script_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${WYRMGPT_HOST_REPO:-}" ]]; then
  repo_root="$WYRMGPT_HOST_REPO"
elif [[ -d /opt/openclaw-data/workspace/wyrmgpt ]]; then
  repo_root="/opt/openclaw-data/workspace/wyrmgpt"
else
  repo_root="$script_repo"
fi

runtime_root="${WYRMGPT_RUNTIME_ROOT:-/opt/openclaw-data/wyrmgpt}"
config_root="${WYRMGPT_CONFIG_ROOT:-$runtime_root/config}"
prompts_root="${WYRMGPT_PROMPTS_ROOT:-$runtime_root/prompts}"
port="${WYRMGPT_PORT:-18080}"
container_name="${WYRMGPT_CONTAINER_NAME:-wyrmgpt-web}"
image_name="${WYRMGPT_IMAGE_NAME:-wyrmgpt-web:host}"
compose_project="${WYRMGPT_COMPOSE_PROJECT:-wyrmgpt}"
data_root="${WYRMGPT_DATA_ROOT:-$runtime_root/data}"

pull=0
build=1
follow_logs=0
status_only=0
down=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pull) pull=1 ;;
    --no-build) build=0 ;;
    --logs) follow_logs=1 ;;
    --status) status_only=1 ;;
    --down) down=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

need_cmd docker
need_cmd curl
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required: docker compose ..." >&2
  exit 1
fi

if [[ ! -d "$repo_root" ]]; then
  echo "Source checkout not found: $repo_root" >&2
  exit 1
fi
if [[ ! -f "$repo_root/Dockerfile" ]]; then
  echo "Dockerfile not found in source checkout: $repo_root" >&2
  exit 1
fi

compose_file="$repo_root/docker-compose.host.yml"
if [[ ! -f "$compose_file" ]]; then
  echo "Host compose file not found: $compose_file" >&2
  exit 1
fi

compose() {
  WYRMGPT_HOST_REPO="$repo_root" \
  WYRMGPT_RUNTIME_ROOT="$runtime_root" \
  WYRMGPT_CONFIG_ROOT="$config_root" \
  WYRMGPT_PROMPTS_ROOT="$prompts_root" \
  WYRMGPT_DATA_ROOT="$data_root" \
  WYRMGPT_PORT="$port" \
  WYRMGPT_CONTAINER_NAME="$container_name" \
  WYRMGPT_IMAGE_NAME="$image_name" \
  docker compose -p "$compose_project" -f "$compose_file" "$@"
}

if [[ "$status_only" -eq 1 ]]; then
  compose ps
  exit 0
fi

if [[ "$down" -eq 1 ]]; then
  compose down
  exit 0
fi

if [[ "$pull" -eq 1 ]]; then
  git -C "$repo_root" pull --ff-only
fi

mkdir -p "$config_root" "$prompts_root" "$data_root/sql"

if [[ ! -f "$config_root/config.toml" ]]; then
  if [[ -f "$repo_root/config.toml" ]]; then
    cp "$repo_root/config.toml" "$config_root/config.toml"
  else
    cp "$repo_root/config.toml.example" "$config_root/config.toml"
  fi
  echo "Created $config_root/config.toml"
fi

if [[ ! -f "$config_root/config.secrets.toml" ]]; then
  cp "$repo_root/config.secrets.toml.example" "$config_root/config.secrets.toml"
  chmod 600 "$config_root/config.secrets.toml" || true
  echo "Created $config_root/config.secrets.toml; edit it with real provider keys before remote-model testing."
fi

if [[ -z "$(find "$prompts_root" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  cp -a "$repo_root/prompts/." "$prompts_root/"
  echo "Seeded $prompts_root"
fi

up_args=(up -d --remove-orphans)
if [[ "$build" -eq 1 ]]; then
  up_args+=(--build)
fi

echo "Rebuilding WyrmGPT from: $repo_root"
echo "Runtime root: $runtime_root"
echo "Config root: $config_root"
echo "Prompts root: $prompts_root"
echo "Data root: $data_root"
echo "Compose file: $compose_file"
compose "${up_args[@]}"

echo "WyrmGPT is starting on http://localhost:${port}"
for _ in $(seq 1 45); do
  if curl -fsS "http://127.0.0.1:${port}/" >/dev/null 2>&1; then
    echo "Health check passed."
    break
  fi
  sleep 1
done

compose ps

if [[ "$follow_logs" -eq 1 ]]; then
  compose logs -f wyrmgpt
fi
