import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from analyzer import full_analysis

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN ayarlanmamış.")

def _fmt(price, ref):
    if ref >= 1000: return f"{price:,.2f}"
    elif ref >= 10: return f"{price:.3f}"
    elif ref >= 1: return f"{price:.4f}"
    elif ref >= 0.01: return f"{price:.5f}"
    else: return f"{price:.8f}"

def build_message(data):
    if "error" in data:
        return f"❌ {data['error']}"
    symbol, verdict, score, price, reasons = data["symbol"], data["verdict"], data["score"], data["price"], data["reasons"]
    karar_str = {"LONG": "LONG 🟢", "SHORT": "SHORT 🔴"}.get(verdict, "İŞLEM YOK ⚪")
    lines = [f"📊 *{symbol}*", "", f"Karar: *{karar_str}*", f"Güven: *{score:.0f}/100*", ""]
    if verdict in ("LONG", "SHORT") and data["sl"]:
        lines += [f"Giriş: `{_fmt(data['entry_low'], price)} - {_fmt(data['entry_high'], price)}`",
                  f"SL:    `{_fmt(data['sl'], price)}`",
                  f"TP1:   `{_fmt(data['tp1'], price)}`",
                  f"TP2:   `{_fmt(data['tp2'], price)}`", ""]
    lines += (["*Sebep:*"] + [f"• {r}" for r in reasons]) if reasons else ["_Belirgin sinyal yok_"]
    lines += ["", "⚠️ _Yatırım tavsiyesi değildir._"]
    return "\n".join(lines)

async def start(update, context):
    await update.message.reply_text(
        "👋 *Kripto Analiz Botu*\n\nCoin sembolü gönderin.\nÖrnek: `BTC` `ETH` `SOL`",
        parse_mode="Markdown")

async def analyze(update, context):
    text = update.message.text.strip().upper().replace("USDT","").replace("/","").replace("-","")
    if not text or len(text) > 15:
        await update.message.reply_text("Geçerli bir coin girin. Örnek: `BTC`", parse_mode="Markdown")
        return
    msg = await update.message.reply_text(f"⏳ *{text}* analiz ediliyor...", parse_mode="Markdown")
    try:
        data = full_analysis(text)
        await msg.edit_text(build_message(data), parse_mode="Markdown")
    except Exception as e:
        logger.exception("Hata")
        await msg.edit_text(f"❌ Hata: {e}")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze))
    logger.info("Bot başlatıldı.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
