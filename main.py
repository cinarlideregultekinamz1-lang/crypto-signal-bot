import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from analyzer import full_analysis

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN ortam değişkeni ayarlanmamış.")


def _fmt(price: float, ref: float) -> str:
    if ref >= 1000:
        return f"{price:,.2f}"
    elif ref >= 10:
        return f"{price:.3f}"
    elif ref >= 1:
        return f"{price:.4f}"
    elif ref >= 0.01:
        return f"{price:.5f}"
    else:
        return f"{price:.8f}"


def build_message(data: dict) -> str:
    if "error" in data:
        return f"❌ {data['error']}"

    symbol  = data["symbol"]
    verdict = data["verdict"]
    score   = data["score"]
    price   = data["price"]
    reasons = data["reasons"]

    if verdict == "LONG":
        karar_str = "LONG 🟢"
    elif verdict == "SHORT":
        karar_str = "SHORT 🔴"
    else:
        karar_str = "İŞLEM YOK ⚪"

    lines = []
    lines.append(f"📊 *{symbol}*")
    lines.append("")
    lines.append(f"Karar: *{karar_str}*")
    lines.append(f"Güven: *{score:.0f}/100*")
    lines.append("")

    ref = price
    if verdict in ("LONG", "SHORT") and data["sl"] is not None:
        lines.append(f"Giriş: `{_fmt(data['entry_low'], ref)} - {_fmt(data['entry_high'], ref)}`")
        lines.append(f"SL:    `{_fmt(data['sl'], ref)}`")
        lines.append(f"TP1:   `{_fmt(data['tp1'], ref)}`")
        lines.append(f"TP2:   `{_fmt(data['tp2'], ref)}`")
        lines.append("")

    if reasons:
        lines.append("*Sebep:*")
        for r in reasons:
            lines.append(f"• {r}")
    else:
        lines.append("_Belirgin bir sinyal yok_")

    lines.append("")
    lines.append("⚠️ _Yatırım tavsiyesi değildir._")

    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *Kripto Analiz Botu*\n\n"
        "Coin sembolü gönderin, analiz edilsin.\n\n"
        "*Örnekler:*\n"
        "`BTC` · `ETH` · `SOL` · `PEPE` · `WIF`\n\n"
        "Binance'teki tüm USDT pariteli coinler desteklenir.\n\n"
        "*Analiz:*\n"
        "• RSI 14 — 1m / 5m / 15m\n"
        "• EMA 9 / 21 / 50\n"
        "• Hacim patlaması tespiti\n"
        "• Futures: Funding Rate, Open Interest, Emir Defteri\n"
        "• BTC yönü filtresi\n"
        "• Destek / Direnç\n"
        "• 0–100 güven puanı"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("/"):
        text = text[1:]

    symbol = text.upper().replace("USDT", "").replace("/", "").replace("-", "").strip()

    if not symbol or len(symbol) > 15:
        await update.message.reply_text(
            "Geçerli bir coin sembolü gönderin. Örnek: `BTC`, `SOL`, `PEPE`",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text(
        f"⏳ *{symbol}* analiz ediliyor...",
        parse_mode="Markdown",
    )

    try:
        data = full_analysis(symbol)
        await msg.edit_text(build_message(data), parse_mode="Markdown")
    except Exception as e:
        logger.exception("Analiz hatası")
        await msg.edit_text(f"❌ Analiz başarısız: {e}")


def main():
    from telegram.request import HTTPXRequest
    req = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30, pool_timeout=30)
    upd = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30, pool_timeout=30)
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .request(req)
        .get_updates_request(upd)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze))
    logger.info("Bot başlatıldı.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
