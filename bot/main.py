"""Telegram bot handlers and application wiring."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import alerts
from bot.config import load_config
from bot.db import Database
from bot.scanner import NEW_OFFER_BATCH_LIMIT, Scanner, WalletScan
from bot.sources.objkt import ObjktClient
from bot.sources.teia import TeiaClient
from bot.sources.tzkt import TzktPriceClient
from bot.utils import is_valid_tezos_address

log = logging.getLogger(__name__)

escape = alerts.escape

WELCOME = (
    "👋 <b>Tezos Offers Bot</b>\n\n"
    "I watch the NFTs in your wallet and alert you the moment someone makes an "
    "offer on one.\n\n"
    "<b>Getting started</b>\n"
    "1. Send me your Tezos wallet address (tz1… or tz2…)\n"
    "2. I'll start scanning it\n\n"
    "<b>Commands</b>\n"
    "/track tz1… — add a wallet\n"
    "/untrack tz1… — stop tracking\n"
    "/wallet — your tracked wallets\n"
    "/offers — current active offers\n"
    "/scan — force a scan now\n"
    "/help — this message"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML)


async def track_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/track tz1...</code>", parse_mode=ParseMode.HTML
        )
        return

    address = context.args[0].strip()
    if not is_valid_tezos_address(address):
        await update.message.reply_text("That is not a valid Tezos address.")
        return

    await _track_wallet(update, context, address)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Treat any plain text that looks like an address as a wallet to track."""
    text = (update.message.text or "").strip()
    if not is_valid_tezos_address(text):
        await update.message.reply_text(
            "That doesn't look like a Tezos address. It should start with "
            "<code>tz1</code>, <code>tz2</code> or <code>tz3</code> and be 36 "
            "characters long.",
            parse_mode=ParseMode.HTML,
        )
        return

    await _track_wallet(update, context, text)


async def _track_wallet(
    update: Update, context: ContextTypes.DEFAULT_TYPE, address: str
) -> None:
    db: Database = context.application.bot_data["db"]
    objkt: ObjktClient = context.application.bot_data["objkt"]
    telegram_id = update.effective_user.id

    status = await update.message.reply_text("🔍 Checking your wallet…")

    try:
        holdings = await objkt.get_holdings(address)
    except Exception as exc:  # noqa: BLE001
        log.exception("holdings lookup failed")
        await status.edit_text(f"⚠️ Could not reach the data source: {exc}")
        return

    await db.add_wallet(telegram_id, address)
    await db.mark_scanned(telegram_id, address, len(holdings))

    if not holdings:
        await status.edit_text(
            f"👀 Tracking <code>{escape(address)}</code>\n\n"
            "I don't see any NFTs in this wallet yet. I'll still keep an eye on "
            "it — send me another address any time.",
            parse_mode=ParseMode.HTML,
        )
        return

    await status.edit_text(
        f"✅ Tracking <code>{escape(address)}</code>\n"
        f"Found <b>{len(holdings)}</b> NFT(s). Checking for offers now…",
        parse_mode=ParseMode.HTML,
    )

    # Scan immediately so the user gets instant value instead of waiting a cycle.
    scanner: Scanner = context.application.bot_data["scanner"]
    result = await scanner.scan_wallet(telegram_id, address)

    if result.error:
        await status.edit_text(
            f"⚠️ Tracking <code>{escape(address)}</code>, but the first scan "
            f"failed: {escape(result.error)}",
            parse_mode=ParseMode.HTML,
        )
        return

    rows = [
        {
            "marketplace": o.marketplace,
            "price_mutez": o.price_mutez,
            "price_usd": None,
            "token_name": o.token_name,
            "token_id": o.token_id,
        }
        for o in result.new_offers
    ]
    await status.edit_text(
        f"✅ Tracking <b>{len(result.new_offers)}</b> new offer(s) across "
        f"{result.nft_count} NFT(s).\n\n"
        f"{alerts.build_summary(rows, None)}",
        parse_mode=ParseMode.HTML,
    )


async def untrack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/untrack tz1...</code>", parse_mode=ParseMode.HTML
        )
        return

    db: Database = context.application.bot_data["db"]
    removed = await db.remove_wallet(update.effective_user.id, context.args[0].strip())
    await update.message.reply_text("Removed." if removed else "That wallet was not being tracked.")


async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    rows = await db.list_wallets(update.effective_user.id)

    if not rows:
        await update.message.reply_text(
            "You're not tracking any wallets yet.\n\nSend me a Tezos address to get started."
        )
        return

    lines = ["👛 <b>Your wallets</b>", ""]
    for row in rows:
        label = f" ({row['label']})" if row["label"] else ""
        lines.append(f"• <code>{escape(row['address'])}</code>{label}")
        lines.append(f"  {row['nft_count']} NFT(s) tracked")
    lines.append("")
    lines.append("Send /untrack tz1… to stop tracking one.")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def offers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    prices: TzktPriceClient = context.application.bot_data["prices"]

    rows = await db.list_offers(update.effective_user.id, limit=50)
    if not rows:
        await update.message.reply_text(
            "💼 No active offers right now.\n\n"
            "When someone bids on one of your NFTs, you'll get a message here."
        )
        return

    usd_rate = await prices.xtz_to_usd()
    await update.message.reply_text(
        alerts.build_summary(rows, usd_rate), parse_mode=ParseMode.HTML
    )


async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scanner: Scanner = context.application.bot_data["scanner"]
    db: Database = context.application.bot_data["db"]
    telegram_id = update.effective_user.id

    status = await update.message.reply_text("🔄 Scanning your wallets…")
    rows = await db.list_wallets(telegram_id)

    total_new = 0
    for row in rows:
        result = await scanner.scan_wallet(telegram_id, row["address"])
        total_new += len(result.new_offers)

    if total_new:
        await status.edit_text(
            f"✅ Found <b>{total_new}</b> new offer(s).", parse_mode=ParseMode.HTML
        )
    else:
        await status.edit_text("✅ Scan complete. No new offers.")


async def on_alert_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the View link on an offer alert."""
    query = update.callback_query
    await query.answer()

    url = query.data or ""
    if url.startswith("http"):
        await query.edit_message_text(
            f"Open this link to act on the offer:\n{url}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        )


async def notify_new_offers(scan: WalletScan, bot, prices: TzktPriceClient) -> None:
    """Send alerts for a finished wallet scan."""
    if not scan.new_offers:
        return

    usd_rate = await prices.xtz_to_usd()

    for offer in scan.new_offers[:NEW_OFFER_BATCH_LIMIT]:
        payload = alerts.build_alert(offer, usd_rate)
        with suppress(Exception):
            if "photo" in payload:
                await bot.send_photo(**payload)
            else:
                await bot.send_message(**payload)

    remaining = len(scan.new_offers) - NEW_OFFER_BATCH_LIMIT
    if remaining > 0:
        with suppress(Exception):
            await bot.send_message(
                f"…and {remaining} more new offer(s). Use /offers to see them all."
            )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("unhandled error", exc_info=context.error)


def build_application(
    db: Database, scanner: Scanner, prices: TzktPriceClient, objkt: ObjktClient
) -> Application:
    config = load_config()
    app = Application.builder().token(config.telegram_bot_token).build()

    app.bot_data["db"] = db
    app.bot_data["scanner"] = scanner
    app.bot_data["prices"] = prices
    app.bot_data["objkt"] = objkt

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("track", track_cmd))
    app.add_handler(CommandHandler("untrack", untrack_cmd))
    app.add_handler(CommandHandler("wallet", wallet_cmd))
    app.add_handler(CommandHandler("offers", offers_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(on_alert_click))
    app.add_error_handler(error_handler)

    return app


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs full request URLs, and every Telegram API URL carries the bot
    # token. Keep its INFO chatter out of the logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    config = load_config()

    db = await Database.connect(config.database_url)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"User-Agent": "tezos-offers-bot/1.0"},
    ) as http:
        objkt = ObjktClient(http, config.objkt_rate_limit_rpm)
        teia = TeiaClient(http)
        prices = TzktPriceClient(http)

        scanner = Scanner(db, objkt, teia, prices)
        app = build_application(db, scanner, prices, objkt)
        bot = app.bot
        log.info("starting scanner every %ds", config.scan_interval)

        async def on_scanned(scan: WalletScan) -> None:
            if scan.error:
                log.warning("scan error for %s: %s", scan.address, scan.error)
                return
            if scan.new_offers:
                await notify_new_offers(scan, bot, prices)

        try:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            # Created after start() so PTB tracks and cancels it on shutdown.
            # The scanner sleeps before its first pass, so nothing is missed.
            app.create_task(
                scanner.run_forever(config.scan_interval, on_scanned),
            )
            log.info("bot is running")
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()
            await app.shutdown()
            await db.close()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(run())
