"""Verify the bot's real startup path: connect to Postgres, create schema.

Exercises Database.connect(), init_schema() and Application wiring against a
real cluster. Does not need a Telegram token, so it can run before the bot is
registered.

Run: .venv/bin/python tests/test_startup.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import shutil
import sys

import httpx
import pgserver

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bot.db import Database  # noqa: E402
from bot.main import build_application  # noqa: E402
from bot.scanner import Scanner  # noqa: E402
from bot.sources.objkt import ObjktClient  # noqa: E402
from bot.sources.teia import TeiaClient  # noqa: E402
from bot.sources.tzkt import TzktPriceClient  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    return not condition


async def main() -> int:
    failures = 0

    data_dir = pathlib.Path("/tmp/pgdata_startup_test")
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir(exist_ok=True)
    pgserver.get_server(data_dir)
    dsn = f"postgresql://postgres@/postgres?host={data_dir}"

    print("\n== Database.connect + init_schema ==")
    db = await Database.connect(dsn)
    failures += check("connected and schema applied", True)

    rows = await db._pool.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    )
    tables = {r["table_name"] for r in rows}
    failures += check(
        "both tables exist", {"wallets", "offers"} <= tables, str(sorted(tables))
    )

    print("\n== unique constraint for dedupe ==")
    constraints = await db._pool.fetch(
        """
        SELECT constraint_name FROM information_schema.table_constraints
        WHERE table_name = 'offers' AND constraint_type = 'UNIQUE'
        """
    )
    names = {c["constraint_name"] for c in constraints}
    failures += check("offers has a UNIQUE constraint", len(names) >= 1, str(names))

    print("\n== Application wiring ==")
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-placeholder-not-used")

    async with httpx.AsyncClient(timeout=10.0) as http:
        objkt = ObjktClient(http, 100)
        teia = TeiaClient(http)
        prices = TzktPriceClient(http)
        scanner = Scanner(db, objkt, teia, prices)

        app = build_application(db, scanner, prices, objkt)
        failures += check("application built", app is not None)

        cmds = set()
        total = 0
        for group in app.handlers.values():
            for h in group:
                total += 1
                if hasattr(h, "commands"):
                    cmds.update(h.commands)

        expected = {"start", "track", "untrack", "wallet", "offers", "scan", "help"}
        missing = expected - cmds
        failures += check(
            "all commands registered",
            not missing,
            f"missing {missing}" if missing else f"{len(cmds)} commands",
        )
        failures += check("text message handler registered", total >= 8, f"{total} handlers")

        await app.shutdown()
        print("  (application shut down cleanly)")

    await db.close()
    failures += check("db closed cleanly", True)

    print("\n" + "=" * 46)
    if failures:
        print(f"RESULT: {failures} check(s) FAILED")
        return 1
    print("RESULT: all checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
