"""Configuration loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

OBJKT_GRAPHQL = "https://data.objkt.com/v3/graphql"
TEIA_GRAPHQL = "https://teztok.teia.rocks/v1/graphql"
TZKT_QUOTES = "https://api.tzkt.io/v1/quotes"

# objkt's indexer covers these marketplace groups. Teia is absent from it
# (verified: group "teia" returns no offers), so Teia is polled separately.
# Versum is excluded deliberately - the platform shut down on 2023-12-01.
OBJKT_MARKETPLACE_GROUPS = ("objktcom", "fxhash", "hen")

# marketplace_contract -> human label, from data.objkt.com marketplace_contract
MARKETPLACE_LABELS = {
    "KT1FvqJwEDWb1Gwc55Jd1jjTHRVWbYKUUpyq": "objkt",
    "KT1WvzYHCNBvDSdwafTHv7nJ1dWmZ8GCYuuC": "objkt",
    "KT1CePTyk6fk4cFr6fasY5YXPGks6ttjSLp4": "objkt",
    "KT1Xjap1TwmDR1d8yEd8ErkraAj2mbdMrPZY": "objkt",
    "KT1SwbTqhSKF6Pdokiu1K4Fpi17ahPPzmt1X": "objkt",
    "KT1Hkg5qeNhfwpKW4fXvq7HGZB9z2EnmCCA9": "hic et nunc",
    "KT1HbQepzV1nVGg8QVznG7z4RcHseD5kwqBn": "hic et nunc",
    "KT1GbyoDi7H1sfXmimXpptZJuCdHMh66WS9u": "fxhash",
    "KT1M1NyU9X4usEimt2f3kDaijZnDMNBu42Ja": "fxhash",
    "KT1HGL8vx7DP4xETVikL4LUYvFxSV19DxdFN": "akaSwap",
    "KT1Qieo8hJWj2rHFfe8BRqnMHXYga9av89GJ": "akaSwap",
    "KT1Dn3sambs7KZGW88hH2obZeSzfmCmGvpFo": "akaSwap",
    "KT1HnV6WJFLksLaLZRLck1TX4SbbcTXULX9t": "dogami",
}

# Reject these explicitly so a typo doesn't silently scan nothing.
KNOWN_MARKETPLACES = {
    "objkt", "fxhash", "teia", "hic et nunc", "akaswap", "dogami", "versum",
}

# Tezos address shapes: tz1/tz2/tz3 + 33 chars, or KT1 + 32 chars.
TEZOS_ADDRESS_RE = r"^(tz[123][1-9A-HJ-NP-Za-km-z]{33}|KT1[1-9A-HJ-NP-Za-km-z]{33})$"


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    database_url: str
    scan_interval: int
    objkt_rate_limit_rpm: int
    debug: bool


def load_config() -> Config:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    return Config(
        telegram_bot_token=token,
        database_url=os.getenv(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tezos_offers"
        ),
        scan_interval=_int_env("SCAN_INTERVAL", 300),
        objkt_rate_limit_rpm=_int_env("OBJKT_RATE_LIMIT_RPM", 100),
        debug=os.getenv("DEBUG", "false").lower() == "true",
    )
