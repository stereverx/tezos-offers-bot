# Handoff: Tezos Offers Telegram Bot

Written for a new agent or developer picking this up cold. Everything you need
to understand the state of the project and finish the deployment.

## What this is

A Telegram bot that watches a Tezos wallet and alerts you when someone makes an
**offer on an NFT you own**. It is an offers-first reimplementation of the core
feature of [cryptonoises.com](https://cryptonoises.com), which is a broader
wallet-activity bot (sales, mints, auctions, .tez domains, coin rates, Discord,
premium tiers). Those extra features are explicitly out of scope here.

The user, a product manager, named "offers on my NFTs" as the single most
important feature, so the whole design serves that.

## Status

| Area | State |
|---|---|
| Bot code | Complete, tested against live mainnet |
| Database layer | Complete, tested against real PostgreSQL 16.2 |
| Docker + Compose | Written, but **never built or run** (no Docker on the dev machine) |
| GCP deployment | Script written, **VM not yet created** |
| Live Telegram bot | **Not yet running.** No bot token has been obtained |

The bot has never been executed end to end against real Telegram. The first
thing to do on the new machine is get it running and confirm it responds.

## Repository

`https://github.com/stereverx/tezos-offers-bot` (public, branch `master`)

```bash
git clone https://github.com/stereverx/tezos-offers-bot.git
```

The only secret is `TELEGRAM_BOT_TOKEN`, which is not in the repo and is
gitignored. Everything else is code and committed.

## Setup on a new machine

```bash
cd tezos-offers-bot
uv venv --python 3.12
uv pip install -r requirements.txt
cp .env.example .env      # then fill in TELEGRAM_BOT_TOKEN
```

Tests (the last two spin up an embedded Postgres via `pgserver`, so no
external database is needed, but all of them need network access):

```bash
.venv/bin/python tests/test_pipeline.py   # live mainnet scan
.venv/bin/python tests/test_db.py         # real Postgres: schema, dedupe, expiry
.venv/bin/python tests/test_startup.py    # DB connect + handler wiring
```

Expected: all three print `RESULT: all checks PASSED`.

## How the data flow works

```
every SCAN_INTERVAL seconds (default 300):
  for each tracked wallet:
    1. resolve held NFTs           objkt: token_holder
    2. fetch active offers         objkt: offer_active  (objkt + fxhash + HEN + akaSwap)
                                   teia:  offers        (separate indexer)
    3. diff against stored offers  only new (marketplace, offer_id) pairs
    4. convert XTZ -> USD          TzKT /v1/head quoteUsd
    5. send one alert per new offer
```

Dedupe lives entirely in Postgres, not in memory, so the bot is a single
process with no shared state. Offers are keyed on
`(telegram_id, marketplace, offer_id)`.

## API findings that are easy to get wrong

These were all verified against the live APIs and cost real debugging time.
Do not "simplify" them without re-testing.

1. **objkt's `offers` bigmap (ptr 103260) is keyed by offer id, not by token.**
   There is no way to ask it "which offers exist for this token". The GraphQL
   `token_pk` path is the only route to that lookup.

2. **objkt's indexer already covers fxhash, HEN and akaSwap offers.** One query
   with no `marketplace` filter returns offers from all of them. Filter by
   `marketplace: {group: {_eq: "fxhash"}}` if you need a single market.

3. **Teia offers are NOT in objkt's indexer.** `marketplace group "teia"`
   returns `[]` even though the Teia contract is registered. Teia needs its own
   API at `teztok.teia.rocks/v1/graphql`.

4. **Teia must be filtered by BOTH `fa2_address` and `token_id`.** Filtering by
   contract alone returns arbitrary recent offers for that contract. Getting
   this wrong silently produced 0 matched offers before it was fixed.

5. **objkt comparison operators are underscore-prefixed**: `_eq`, `_in`. And
   `token_pk` is a `bigint`, so it must be passed as a string.

6. **fxhash's own API is Cloudflare-blocked for server requests** (403 even with
   a browser User-Agent). Use objkt's indexer for fxhash instead.

7. **Versum is dead.** The platform shut down 2023-12-01 and the contract was
   frozen 2023-11-14. `versum.xyz` does not resolve. Excluded deliberately,
   even though objkt's indexer still serves stale Versum offers.

## Bugs found and fixed during the build

Keep these in mind if you touch the relevant code, because the fix is subtle
and reverting it reintroduces the bug.

1. **Teia filtering.** Contract-only filtering returned unrelated offers.
   Fixed with contract + token_id batching. This took Teia from 0 offers to 67
   on the reference wallet.

2. **Expired offers could never re-alert.** The upsert used
   `ON CONFLICT DO NOTHING`, so once an offer was marked `expired` it could
   never come back. Fixed with `ON CONFLICT DO UPDATE ... WHERE
   offers.status = 'expired'`, which reactivates and re-alerts, while a
   still-active offer is neither updated nor returned (so no duplicate alerts).

3. **A Teia outage would mass-expire Teia offers.** The single `mark_expired`
   call covered all marketplaces, so a transient Teia failure would mark every
   Teia offer expired, and the next healthy scan would re-alert all of them.
   Fixed by scoping expiry per marketplace and skipping Teia entirely when it
   failed to answer.

## Deployment status and next steps

Target: **GCP `e2-micro`**, free permanently in the Always Free tier (1 GB RAM,
30 GB disk). The user has a GCP project named `Tezos Offers Bot` with billing
linked; they signed in via `gcloud auth login` on their previous machine. That
GCP session does not carry over, so **`gcloud auth login` is required again**.

Known state as of the handoff:

- Project `Tezos Offers Bot` exists, numeric project ID `513909964603`
- Billing account `010159-F60EA09-6534FD` exists and was being linked
- **No VM has been created yet**

To finish:

```bash
gcloud auth login
export GCP_PROJECT_ID=<project-id>
./deploy/gcp-setup.sh          # creates the VM, prints the IP
./deploy/deploy.sh <user>@IP   # from the machine holding the repo
ssh <user>@IP
./deploy/vm-setup.sh           # installs Docker
cd ~/tezos-offers-bot
cp .env.example .env           # set TELEGRAM_BOT_TOKEN
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
docker compose up -d --build
docker compose logs -f bot
```

**Do not create a Cloud NAT Gateway.** It costs roughly $32/mo and would
destroy the free tier. The VM's external IP handles outbound traffic.

### Get the bot token

The bot has never been run, so no token exists yet. Message
[@BotFather](https://t.me/BotFather) and use `/newbot`.

**Use a brand new token.** The user has a token for a different project. Two
apps polling `getUpdates` on the same token steal each other's updates, which
is a confusing failure to debug.

## Reference wallet used in tests

`tz1UBZUkXpKGhYsP5KtzDNqLLchwF4uHrGjw` — a real mainnet wallet holding 151
HEN NFTs, used by `tests/test_pipeline.py` because it reliably has active
offers. On it the bot finds 27 objkt/fxhash offers and 67 Teia offers.

## Not implemented

Deliberately deferred, to keep the first version focused on offers: sales and
purchases, mints, listings, royalties, auctions, .tez domain expiry, coin-rate
conversions, Discord support, and premium tiers. See "Not implemented" in
README.md.

## Repo layout

```
bot/
  main.py         Telegram handlers, app wiring, entrypoint
  scanner.py      poll loop, diffing, per-source error isolation
  db.py           asyncpg, schema, dedupe upsert, expiry
  alerts.py       message formatting
  config.py       env config, marketplace contract -> label map
  models.py       Holding, Offer
  utils.py        address validation, mutez formatting, IPFS -> gateway
  sources/
    objkt.py      holdings + offers (objkt, fxhash, HEN, akaSwap)
    teia.py       Teia offers
    tzkt.py       XTZ -> USD
deploy/
  gcp-setup.sh    create the GCP VM (idempotent)
  aws-setup.sh    create an AWS Lightsail instance (alternative)
  vm-setup.sh     install Docker on a bare VM
  deploy.sh       rsync the code to a remote VM
tests/
  test_pipeline.py  live mainnet scan + dedupe
  test_db.py        real Postgres 16.2 via pgserver
  test_startup.py   DB connect + handler registration
```

## Working notes

- `move_agent_to_root` failed in the previous environment with
  `InstantiationService has been disposed`, so the workspace was never moved
  off the home directory. Call it early in the new session.
- The dev machine has `uv` but no `pip`, no Docker, and no passwordless sudo.
  `pgserver` (an embedded Postgres) was used to test the DB layer; it is a dev
  dependency only and is not in `requirements.txt`.
- `pgserver` listens on a Unix socket, so the DB tests connect with
  `postgresql://postgres@/postgres?host=<data-dir>`.
