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

### 2. Install

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
cp .env.example .env
```

### 3. Database

```bash
createdb tezos_offers
```

Then set `DATABASE_URL` in `.env`. Tables are created automatically on first
run.

### 4. Run

```bash
.venv/bin/python -m bot.main
```

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
.venv/bin/python tests/test_pipeline.py
```

Runs unit checks plus a full live scan against mainnet using a wallet that
holds NFTs, and asserts dedupe behaviour across two consecutive scans.
Requires network access.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Required |
| `DATABASE_URL` | local postgres | PostgreSQL DSN |
| `SCAN_INTERVAL` | `300` | Seconds between scans |
| `OBJKT_RATE_LIMIT_RPM` | `100` | Client-side throttle (objkt allows 120) |
| `DEBUG` | `false` | Verbose logging |

## Not implemented

Deliberately out of scope for this version, listed so the gaps are explicit:
sales/purchases, mints, listings, royalties, auctions, .tez domain expiry,
coin-rate conversions, Discord support, and premium tiers.
