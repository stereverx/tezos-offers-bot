#!/usr/bin/env bash
#
# Copy the bot to a remote VM and restart it there.
# Run this from your LOCAL machine, inside the project directory.
#
# Usage:
#   ./deploy/deploy.sh <user@host> [ssh-key]
#
# Examples:
#   ./deploy/deploy.sh rog34.1.2.3
#   ./deploy/deploy.sh rog@34.1.2.3 ~/.ssh/id_ed25519
#
set -euo pipefail

TARGET="${1:-}"
KEY="${2:-}"

if [[ -z "$TARGET" ]]; then
  echo "usage: $0 <user@host> [ssh-key]" >&2
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_DIR="${REMOTE_DIR:-tezos-offers-bot}"

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[[ -n "$KEY" ]] && SSH_OPTS+=(-i "$KEY")

echo "==> Deploying $PROJECT_DIR to $TARGET:~$REMOTE_DIR"

if command -v rsync >/dev/null 2>&1; then
  rsync -az --delete \
    --exclude '.venv' --exclude '.git' --exclude '.env' \
    --exclude '__pycache__' --exclude '*.pyc' --exclude '*.log' \
    "${SSH_OPTS[@]}" \
    "$PROJECT_DIR/" "$TARGET:~$REMOTE_DIR/"
else
  echo "rsync not found locally; falling back to tar over ssh"
  # Normalise CRLF before shipping. A Windows checkout (core.autocrlf) turns
  # the .sh files CRLF, and the VM then fails on "set -euo pipefail: invalid
  # option name". .gitattributes stops new checkouts, this catches the rest.
  find "$PROJECT_DIR" \
    -name '*.sh' -o -name 'Dockerfile' -o -name 'docker-compose.yml' |
  while read -r f; do
    tr -d '\r' < "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  done
  tar -czf - \
    --exclude=.venv --exclude=.git --exclude=.env \
    --exclude=__pycache__ --exclude='*.pyc' --exclude='*.log' \
    -C "$PROJECT_DIR" . \
    | ssh "${SSH_OPTS[@]}" "$TARGET" \
        "mkdir -p ~/$REMOTE_DIR && tar -xzf - -C ~/$REMOTE_DIR"
fi

echo "==> Files synced. Now on the VM:"
echo "    cd ~/$REMOTE_DIR"
echo "    [ -f .env ] || cp .env.example .env"
echo "    # then set TELEGRAM_BOT_TOKEN and POSTGRES_PASSWORD in .env"
echo "    docker compose up -d --build"
echo "    docker compose logs -f bot"
