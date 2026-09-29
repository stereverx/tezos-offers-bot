"""TzKT price quotes for XTZ -> fiat conversion.

Uses the /v1/head endpoint, which carries the current quoteUsd rate. This is
preferred over /v1/quotes, which returns the block-by-block history (24KB+ on
every call) for a single number we already get from head.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from bot.config import TZKT_QUOTES

log = logging.getLogger(__name__)

TZKT_HEAD = "https://api.tzkt.io/v1/head"

# XTZ moves slowly; refetching every few minutes is plenty.
_QUOTE_TTL_SECONDS = 300


class TzktPriceClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._http = client
        self._usd_rate: float | None = None
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def xtz_to_usd(self) -> float | None:
        """Current XTZ price in USD, or the last known value if unreachable."""
        if (
            self._usd_rate is not None
            and time.time() - self._fetched_at < _QUOTE_TTL_SECONDS
        ):
            return self._usd_rate

        async with self._lock:
            if (
                self._usd_rate is not None
                and time.time() - self._fetched_at < _QUOTE_TTL_SECONDS
            ):
                return self._usd_rate

            try:
                response = await self._http.get(TZKT_HEAD)
                response.raise_for_status()
                rate = float(response.json().get("quoteUsd") or 0)
                if rate > 0:
                    self._usd_rate = rate
                    self._fetched_at = time.time()
                    return self._usd_rate
                log.warning("TzKT head returned a non-positive XTZ price")
                return self._usd_rate
            except Exception as exc:  # noqa: BLE001 - price is optional
                log.warning("could not fetch XTZ price: %s", exc)
                return self._usd_rate


__all__ = ["TzktPriceClient", "TZKT_QUOTES"]
