#!/usr/bin/env bash
#
# Bootstrap a fresh Ubuntu VM for the bot. Run this ON THE VM.
# Installs Docker + Compose and prepares the deployment directory.
#
# Designed for a small instance (GCP e2-micro, 1 GB RAM) - nothing heavy.
#
# Usage:  curl -fsSL <this-file> | bash
#
set -euo pipefail

log() { printf '\n==> %s\n' "$1"; }

log "Checking for existing Docker"
if command -v docker >/dev/null 2>&1; then
  echo "docker already installed: $(docker --version)"
else
  log "Installing Docker from the official apt repo"
  # Use Docker's own repo rather than distro packages: ubuntu's docker.io is
  # older and lags on compose v2.
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc

  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

  sudo apt-get update
  sudo apt-get install -y docker.io docker-compose-v2 || {
    echo "compose-v2 package unavailable, trying docker-compose-plugin" >&2
    sudo apt-get install -y docker.io docker-compose-plugin
  }
fi

log "Enabling Docker service"
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
echo "added $USER to the docker group (log out and back in for this to apply)"

log "Verifying"
docker --version
docker compose version 2>/dev/null || echo "note: 'docker compose' needs a re-login, or use 'docker-compose'"

cat <<'INFO'

Docker is ready.

Next:
  1. Get the code onto this VM (rsync, scp, or a git clone).
  2. cd tezos-offers-bot
  3. cp .env.example .env
  4. Edit .env and set TELEGRAM_BOT_TOKEN and POSTGRES_PASSWORD
       POSTGRES_PASSWORD=$(openssl rand -hex 16)
  5. docker compose up -d --build
  6. docker compose logs -f bot

Send the bot a tz1... address and it will scan that wallet.
INFO
