#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/deploy-wyrmgpt.sh [options]

Build and run the main WyrmGPT web container from this checkout.

Options:
  --no-build       Start without rebuilding the image.
  --pull           Run git pull --ff-only before deploying.
  --logs           Follow container logs after deploy.
  --status         Show container status and exit.
  --down           Stop and remove the WyrmGPT container.
  -h, --help       Show this help.

Environment:
  WYRMGPT_PORT            Host port to bind. Default: 18080
  WYRMGPT_RUNTIME_ROOT    Persistent runtime root.
                          Default: /opt/openclaw-data/wyrmgpt when writable,
                          otherwise $HOME/.local/share/wyrmgpt
  WYRMGPT_CONTAINER_NAME  Container name. Default: wyrmgpt-web
  WYRMGPT_IMAGE_NAME      Image name. Default: wyrmgpt-web:local
  WYRMGPT_COMPOSE_PROJECT Compose project name. Default: wyrmgpt

Examples:
  scripts/deploy-wyrmgpt.sh
  WYRMGPT_PORT=8080 scripts/deploy-wyrmgpt.sh --logs
  WYRMGPT_RUNTIME_ROOT=/opt/openclaw-data/wyrmgpt scripts/deploy-wyrmgpt.sh
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${WYRMGPT_PORT:-18080}"
container_name="${WYRMGPT_CONTAINER_NAME:-wyrmgpt-web}"
image_name="${WYRMGPT_IMAGE_NAME:-wyrmgpt-web:local}"
compose_project="${WYRMGPT_COMPOSE_PROJECT:-wyrmgpt}"

if [[ -n "${WYRMGPT_RUNTIME_ROOT:-}" ]]; then
  runtime_root="$WYRMGPT_RUNTIME_ROOT"
elif [[ -d /opt/openclaw-data && -w /opt/openclaw-data ]]; then
  runtime_root="/opt/openclaw-data/wyrmgpt"
else
  runtime_root="${HOME}/.local/share/wyrmgpt"
fi

build=1
pull=0
follow_logs=0
status_only=0
down=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build) build=0 ;;
    --pull) pull=1 ;;
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
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required: docker compose ..." >&2
  exit 1
fi

compose_file="$(mktemp "${TMPDIR:-/tmp}/wyrmgpt-compose.XXXXXX.yml")"
trap 'rm -f "$compose_file"' EXIT

cat >"$compose_file" <<EOF
services:
  wyrmgpt:
    build:
      context: ${repo_root}
      dockerfile: Dockerfile
    image: ${image_name}
    container_name: ${container_name}
    restart: unless-stopped
    ports:
      - "${port}:8000"
    volumes:
      - ${runtime_root}/config/config.toml:/app/config.toml
      - ${runtime_root}/config/config.secrets.toml:/app/config.secrets.toml
      - ${runtime_root}/prompts:/app/prompts
      - ${runtime_root}/data:/app/data
    environment:
      PYTHONUNBUFFERED: "1"
EOF

compose() {
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

mkdir -p "$runtime_root/config" "$runtime_root/prompts" "$runtime_root/data/sql"

if [[ ! -f "$runtime_root/config/config.toml" ]]; then
  if [[ -f "$repo_root/config.toml" ]]; then
    cp "$repo_root/config.toml" "$runtime_root/config/config.toml"
  else
    cp "$repo_root/config.toml.example" "$runtime_root/config/config.toml"
  fi
  echo "Created $runtime_root/config/config.toml"
fi

if [[ ! -f "$runtime_root/config/config.secrets.toml" ]]; then
  cp "$repo_root/config.secrets.toml.example" "$runtime_root/config/config.secrets.toml"
  chmod 600 "$runtime_root/config/config.secrets.toml" || true
  echo "Created $runtime_root/config/config.secrets.toml; edit it with real provider keys before remote-model testing."
fi

if [[ -z "$(find "$runtime_root/prompts" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  cp -a "$repo_root/prompts/." "$runtime_root/prompts/"
  echo "Seeded $runtime_root/prompts"
fi

up_args=(up -d)
if [[ "$build" -eq 1 ]]; then
  up_args+=(--build)
fi

compose "${up_args[@]}"

echo "WyrmGPT is starting on http://localhost:${port}"
echo "Runtime root: $runtime_root"

for _ in $(seq 1 30); do
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
