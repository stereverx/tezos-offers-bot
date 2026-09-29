#!/usr/bin/env bash
#
# Provision a GCP e2-micro VM for the bot.
#
# e2-micro is the only instance in the Always Free tier: 1 GB RAM, 30 GB disk,
# free forever in us-west1 / us-central1 / us-east1. One such instance per
# project, billed by time used, capped at one month per calendar month.
#
# Usage:
#   ./deploy/gcp-setup.sh            # create the VM
#   ./deploy/gcp-setup.sh --ip-only  # just print the IP of an existing VM
#
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-}"
ZONE="${GCP_ZONE:-us-central1-a}"
VM_NAME="${VM_NAME:-tezos-offers-bot}"
SSH_USER="${SSH_USER:-rog}"

usage() { sed -n '2,12p' "$0"; exit 1; }
[[ $# -gt 0 && "$1" == "--ip-only" ]] && usage

if [[ -z "$PROJECT_ID" ]]; then
  echo "error: set GCP_PROJECT_ID, e.g. GCP_PROJECT_ID=my-project-123 ./deploy/gcp-setup.sh" >&2
  exit 1
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "error: gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install" >&2
  exit 1
fi

echo "==> Project: $PROJECT_ID   Zone: $ZONE"

# 1. Enable the APIs the VM needs.
echo "==> Enabling compute API"
gcloud services enable compute.googleapis.com --project="$PROJECT_ID" --quiet

# 2. Create a firewall rule for SSH only. The bot itself has no open ports:
#    it makes outbound calls to Telegram/objkt/Teia and is never reached.
echo "==> Creating SSH firewall rule (tcp:22 from your IP only, not 0.0.0.0/0)"
MY_IP="$(curl -s https://api.ipify.org)"
gcloud compute firewall-rules describe allow-ssh-bot \
  --project="$PROJECT_ID" >/dev/null 2>&1 || \
gcloud compute firewall-rules create allow-ssh-bot \
  --project="$PROJECT_ID" \
  --allow=tcp:22 \
  --source-ranges="$MY_IP" \
  --network=default \
  --target-tags=bot \
  --quiet

# 3. Create the VM. --scopes limits the instance's API access to logging only.
#    No Cloud NAT is created: that would cost ~$32/mo and is not needed,
#    because an instance with an external IP gets outbound internet directly.
echo "==> Creating $VM_NAME (e2-micro)"
gcloud compute instances create "$VM_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --machine-type=e2-micro \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --tags=bot \
  --scopes=logging-write \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-balanced \
  --no-address 2>&1 || {
    # Older gclient versions use --no-address; newer want nothing at all.
    gcloud compute instances create "$VM_NAME" \
      --project="$PROJECT_ID" --zone="$ZONE" --machine-type=e2-micro \
      --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
      --tags=bot --scopes=logging-write --boot-disk-size=30GB --boot-disk-type=pd-balanced
  }

IP="$(gcloud compute instances describe "$VM_NAME" \
  --project="$PROJECT_ID" --zone="$ZONE" \
  --format='value(networkInterfaces[0].accessConfigs[0].natIP)')"

echo
echo "VM created: $VM_NAME ($IP)"
echo
echo "Next steps:"
echo "  ssh $SSH_USER@$IP"
echo "  git clone <your-repo> tezos-offers-bot && cd tezos-offers-bot"
echo "  cp .env.example .env   # then fill in TELEGRAM_BOT_TOKEN and POSTGRES_PASSWORD"
echo "  docker compose up -d --build"
echo "  docker compose logs -f bot"
echo
echo "Add this to your .env on the VM:"
echo "  POSTGRES_PASSWORD=$(openssl rand -hex 16)"
