"""Teia offers source.

Teia is NOT indexed by objkt (verified: marketplace group "teia" returns no
offers even though the contract is registered), so it is polled separately
against teztok.teia.rocks.

Verified schema notes:
  - offers_bool_exp supports fa2_address and token_id, compared with _eq/_in
  - both must be supplied: filtering by contract alone returns arbitrary
    recent offers for that contract, not offers on the tokens we hold
  - the status enum is not "ACTIVE", so activity is filtered in code
  - some rows have a null offer_id (collection-level offers); those are
    skipped because they cannot be addressed or deduped
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from bot.config import TEIA_GRAPHQL
from bot.models import Holding, Offer

log = logging.getLogger(__name__)

# Teia has no published rate limit; stay well under any plausible threshold.
_MIN_INTERVAL_SECONDS = 0.3

# Keep the _in lists well below any server-side parameter limit.
_TOKENS_PER_QUERY = 40


class TeiaClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._http = client
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def _query(self, query: str, variables: dict | None = None) -> dict:
        async with self._lock:
            loop = asyncio.get_running_loop()
            wait = self._last_call + _MIN_INTERVAL_SECONDS - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = loop.time()

        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._http.post(TEIA_GRAPHQL, json=payload)
                response.raise_for_status()
                body = response.json()
                if body.get("errors"):
                    raise RuntimeError(f"teia GraphQL error: {body['errors']}")
                return body.get("data") or {}
            except Exception as exc:  # noqa: BLE001 - retried below
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))

        raise RuntimeError(f"teia query failed after 3 attempts: {last_error}")

    async def get_offers_for_holdings(self, holdings: list[Holding]) -> list[Offer]:
        """Active Teia offers on the specific tokens in `holdings`.

        Batched by contract and then by token id, so a wallet with hundreds of
        NFTs does not turn into hundreds of requests.
        """
        if not holdings:
            return []

        by_contract: dict[str, list[str]] = {}
        for holding in holdings:
            if holding.contract:
                by_contract.setdefault(holding.contract, []).append(holding.token_id)

        query = """
        query Offers($contract: String!, $tokens: [String!]) {
          offers(
            where: { fa2_address: { _eq: $contract }, token_id: { _in: $tokens } }
            limit: 100
          ) {
            offer_id
            price
            buyer_address
            fa2_address
            token_id
            status
          }
        }
        """

        offers: list[Offer] = []
        for contract, token_ids in by_contract.items():
            unique_ids = list(dict.fromkeys(token_ids))
            for start in range(0, len(unique_ids), _TOKENS_PER_QUERY):
                chunk = unique_ids[start : start + _TOKENS_PER_QUERY]
                try:
                    data = await self._query(
                        query, {"contract": contract, "tokens": chunk}
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "teia query failed for %s (%d tokens): %s",
                        contract[:12],
                        len(chunk),
                        exc,
                    )
                    continue

                for row in data.get("offers") or []:
                    offer = self._parse_offer(row)
                    if offer:
                        offers.append(offer)

        return offers

    @staticmethod
    def _parse_offer(row: dict) -> Offer | None:
        if not _is_active(row.get("status")):
            return None

        offer_id = row.get("offer_id")
        contract = row.get("fa2_address")
        if offer_id is None or not contract:
            # Collection-level Teia offer: not addressable to a single token.
            return None

        return Offer(
            marketplace="teia",
            offer_id=str(offer_id),
            token_pk=None,
            token_id=str(row.get("token_id") or "0"),
            contract=contract,
            token_name=None,
            media_uri=None,
            price_mutez=int(row.get("price") or 0),
            buyer=row.get("buyer_address"),
        )


def _is_active(status: str | None) -> bool:
    """Teia's status values vary by indexer version.

    Unknown values are treated as active, but explicitly finished states are
    not, so a stale CANCELLED offer is never surfaced.
    """
    if not status:
        return True
    return str(status).upper() in {"ACTIVE", "OPEN", "VALID"}
