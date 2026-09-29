# Tezos Offers Bot

A Telegram bot that watches the NFTs in your Tezos wallet and tells you the
moment someone makes an offer on one. Built to match the core of
[cryptonoises.com](https://cryptonoises.com), focused on the feature that
matters most: **offers on the NFTs you already hold**.

## Supported marketplaces

| Marketplace | Source | Notes |
|---|---|---|
| **objkt.com** | objkt v3 GraphQL | Also covers v1/v6 contract generations |
| **fxhash** | objkt v3 GraphQL | Its own API is Cloudflare-blocked for servers |
| **hic et nunc** | objkt v3 GraphQL | Legacy HEN marketplace contracts |
| **akaSwap** | objkt v3 GraphQL | |
| **Teia** | teztok.teia.rocks | Separate indexer; objkt does not index Teia offers |
| Versum | not supported | Platform shut down 2023-12-01, contract frozen |

objkt's indexer aggregates offers made on fxhash, HEN and akaSwap, so a single
query covers all of them. Teia requires its own pass.

## Setup

### 1. Create a bot token

Message [@BotFather](https://t.me/BotFather) and use `/newbot`.

Use a **new** token. If another app already uses your existing token, both
apps will poll `getUpdates` on it and steal each other's updates.

### 2. Install (local development)

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
cp .env.example .env
```

### 3. Deploy to a server

See [Deployment](#deployment) below for the recommended GCP setup.

## Deployment

Target: **AWS Lightsail**, which is a flat monthly bundle (compute + disk +
static public IPv4 + 2 TB transfer) and has no VPC, so there is nothing to
accidentally provision a NAT Gateway into.

```bash
# 1. install the AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
sudo apt-get install -y unzip && unzip awscliv2.zip && sudo ./aws/install

# 2. sign in
aws configure

# 3. create the instance (resolves the real bundle/blueprint ids for you)
export AWS_REGION=us-east-1
./deploy/aws-setup.sh
```

Then:

```bash
./deploy/deploy.sh ubuntu@THE_IP     # from this machine
ssh ubuntu@THE_IP
./deploy/vm-setup.sh                 # installs Docker on the VM
cd ~/tezos-offers-bot
cp .env.example .env                 # set TELEGRAM_BOT_TOKEN and POSTGRES_PASSWORD
docker compose up -d --build
docker compose logs -f bot
```

`docker-compose.yml` runs Postgres alongside the bot, tuned for 1 GB of RAM
(`shared_buffers=64MB`, `max_connections=20`). The bot needs no published
port: it only makes outbound calls.

**Cost**

| Item | Cost |
|---|---|
| `micro_3_0` bundle (1 GB, 40 GB disk, 2 TB transfer) | $7/mo |
| Over a 6-month credit window | ~$42 of the $100 credit |

Set `RAM_GB=2.0` for a `small_3_0` bundle ($12/mo) if you want more headroom.
`nano_3_0` ($5) has 0.5 GB RAM, which is too tight to run Postgres alongside
the bot.

**Cost traps to avoid**

- Do **not** create a NAT Gateway. It is ~$32.85/mo with no free tier and
  would exhaust the credit in about three weeks. Lightsail has no VPC, so
  nothing tempts you into it.
- On EC2, a public IPv4 costs $0.005/hr (~$3.65/mo) on top of the instance.
  Lightsail bundles it.
- Set a billing alarm in the AWS console so you hear about charges before
  they accumulate.

## Commands

| Command | What it does |
|---|---|
| `/start` | Intro and help |
| `/track tz1…` | Start watching a wallet (or just send the address) |
| `/untrack tz1…` | Stop watching a wallet |
| `/wallet` | Your tracked wallets and NFT counts |
| `/offers` | All active offers, highest first, with a total |
| `/scan` | Force an immediate scan |

## How it works

```
every SCAN_INTERVAL seconds (default 300):
  for each tracked wallet:
    1. resolve held NFTs           objkt: token_holder
    2. fetch active offers         objkt: offer_active (batched by token_pk)
                                   teia: offers (batched by contract + token_id)
    3. diff against stored offers  only new (marketplace, offer_id) pairs
    4. convert XTZ -> USD          TzKT /v1/head quoteUsd
    5. send an alert per new offer
```

Offers are deduplicated on `(telegram_id, marketplace, offer_id)`, so each
offer alerts exactly once. Offers that disappear from the indexer are marked
`expired` rather than deleted, keeping history intact.

### API details worth knowing

- objkt's `offers` bigmap (ptr 103260) is keyed by **offer id**, not by token,
  so it cannot answer "which offers exist for this token". The GraphQL
  `token_pk` path is the only way to do that lookup.
- `token_pk` is a `bigint` in the schema, so it must be passed as a string.
- Comparison operators are underscore-prefixed: `_eq`, `_in`.
- Teia must be filtered by **both** `fa2_address` and `token_id`. Filtering by
  contract alone returns arbitrary recent offers for that contract.
- Teia rows can have a null `offer_id`; those are collection-level offers and
  are skipped, since they cannot be addressed to a token.

## Tests

```bash
.venv/bin/python tests/test_pipeline.py   # live mainnet scan, needs network
.venv/bin/python tests/test_db.py         # real PostgreSQL: schema, dedupe, expiry
.venv/bin/python tests/test_startup.py    # DB connect + Application wiring
```

`test_pipeline.py` runs a full live scan against a wallet that holds NFTs and
asserts dedupe behaviour across two consecutive scans. `test_db.py` and
`test_startup.py` spin up an embedded PostgreSQL via `pgserver`, so they need
no external database. All three require network access except where noted.

`deploy/gcp-setup.sh` is kept for anyone who prefers GCP's always-free
`e2-micro`; the AWS path in `deploy/aws-setup.sh` is the primary target.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Required |
| `POSTGRES_PASSWORD` | — | Required under Docker Compose |
| `SCAN_INTERVAL` | `300` | Seconds between scans |
| `OBJKT_RATE_LIMIT_RPM` | `100` | Client-side throttle (objkt allows 120) |
| `DEBUG` | `false` | Verbose logging |
| `DATABASE_URL` | set by compose | Only for running outside Docker |

## Not implemented

Deliberately out of scope for this version, listed so the gaps are explicit:
sales/purchases, mints, listings, royalties, auctions, .tez domain expiry,
coin-rate conversions, Discord support, and premium tiers.
