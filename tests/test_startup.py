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
import tempfile

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

    data_dir = pathlib.Path(tempfile.gettempdir()) / "pgdata_startup_test"
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
    data_dir.mkdir(exist_ok=True)
    dsn = pgserver.get_server(data_dir).get_uri()

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

        # Regression: the scanner task used to be created with a
        # create_task(update_interval=...) kwarg that PTB v21 does not accept,
        # so the bot died on every real boot. Building the app never caught it.
        # Parse the real call site in main.py so a bad kwarg fails here.
        import ast
        import inspect as _inspect

        from telegram.ext import Application as _Application

        accepted = set(_inspect.signature(_Application.create_task).parameters)
        main_py = pathlib.Path(__file__).resolve().parent.parent / "bot" / "main.py"
        tree = ast.parse(main_py.read_text(encoding="utf-8"))
        bad = [
            f"line {n.lineno}: {kw.arg}"
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create_task"
            for kw in n.keywords
            if kw.arg and kw.arg not in accepted
        ]
        failures += check(
            "create_task kwargs in main.py are valid",
            not bad,
            "; ".join(bad) if bad else f"accepted={sorted(accepted)}",
        )

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
