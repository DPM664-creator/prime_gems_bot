import os
import asyncio
import aiohttp
import logging
import re
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Variáveis não configuradas")

logger.info("✅ Prime Gems Bot iniciado!")

MONITOR_ACCOUNTS = ["OzzyManReview", "MaxCrypto__", "Ansem", "ClownIRL", "0xMert", "CryptoGodJohn", "HsakaTrades", "Pentosh1"]
NITTER_INSTANCES = ["https://nitter.net", "https://nitter.privacydev.net"]
processed_tweets = set()
alerted_tokens = set()
processed_cas = set()

def is_contract_address(text):
    text = text.strip()
    if re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', text):
        return "solana"
    elif re.match(r'^0x[a-fA-F0-9]{40}$', text):
        return "evm"
    return None

def detect_network_from_ca(ca):
    if ca.startswith("0x") and len(ca) == 42:
        return "evm"
    elif 32 <= len(ca) <= 44:
        return "solana"
    return None

async def start(update: Update, context):
    await update.message.reply_text("🚀 *PRIME GEMS BOT ATIVO!*\n\nUse `/check <CA>`", parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context):
    await update.message.reply_text("📖 *COMANDOS:*\n`/check <CA>` - Análise", parse_mode=ParseMode.MARKDOWN)

async def check_command(update: Update, context):
    if not context.args:
        await update.message.reply_text("❌ Uso: `/check <CA>`", parse_mode=ParseMode.MARKDOWN)
        return
    
    ca = context.args[0].strip()
    status_msg = await update.message.reply_text("🔍 Analisando...")
    
    info = await fetch_token_info(ca)
    if not info:
        await status_msg.edit_text("❌ Token não encontrado")
        return
    
    network = detect_network_from_ca(ca) or "solana"
    msg = format_gmgn_style_info(info, ca, network)
    await status_msg.edit_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def handle_message(update: Update, context):
    if not update.message or not update.message.text:
        return
    
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    
    network = is_contract_address(text)
    if network and text not in processed_cas:
        processed_cas.add(text)
        status_msg = await update.message.reply_text("🔍 Analisando...")
        info = await fetch_token_info(text)
        if info:
            msg = format_gmgn_style_info(info, text, network)
            await status_msg.edit_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        else:
            await status_msg.edit_text("❌ Token não encontrado")

async def fetch_token_info(ca):
    async with aiohttp.ClientSession() as session:
        if detect_network_from_ca(ca) == "solana":
            try:
                async with session.get(f"https://frontend-api.pump.fun/coins/{ca}", headers={"User-Agent": "Mozilla/5.0"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        data['source'] = 'pumpfun'
                        return data
            except:
                pass
        
        try:
            async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        return {"pair": max(pairs, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0), "source": "dexscreener"}
        except:
            pass
    return None

def format_gmgn_style_info(data, ca, network):
    if data.get('source') == 'pumpfun':
        symbol = data.get("symbol", "N/A")
        mint = data.get("mint", ca)
        mc = data.get("marketCap", 0) or 0
        liq = data.get("liquidity", 0) or 0
        vol = data.get("volume", 0) or 0
        
        msg = f"🚀 *{symbol}*\n📄 `{mint}`\n\n"
        msg += f"📊 *Stats:*\n• MC: ${mc:,.0f}\n• LIQ: ${liq:,.0f}\n• Vol: ${vol:,.0f}\n\n"
        msg += "🔍 *Links:*\n"
        msg += f"📊 [DexScreener](https://dexscreener.com/solana/{mint})\n"
        msg += f"📈 [DexTools](https://www.dextools.io/app/solana/pair/explorer/{mint})\n"
        msg += f"🚀 [Pump.fun](https://pump.fun/{mint})\n"
        msg += f"🤖 [GMGN](https://gmgn.ai/solana/token/{mint})\n\n"
        msg += "⚠️ _DYOR_"
        return msg
    else:
        pair = data.get("pair", {})
        base = pair.get("baseToken", {})
        symbol = base.get("symbol", "N/A")
        address = base.get("address", ca)
        price = float(pair.get("priceUsd", 0))
        mc = pair.get("marketCap", 0) or 0
        liq = pair.get("liquidity", {}).get("usd", 0) or 0
        chain = pair.get("chainId", "N/A").upper()
        pair_url = pair.get("url", "")
        
        msg = f"📊 *{symbol}* ({chain})\n📄 `{address}`\n\n"
        msg += f"💵 *Preço:* ${price:.8f}\n💰 MC: ${mc:,.0f}\n💧 Liq: ${liq:,.0f}\n\n"
        if pair_url:
            msg += f"📊 [DexScreener]({pair_url})\n"
        msg += "⚠️ _DYOR_"
        return msg

def main():
    logger.info("🚀 Iniciando bot...")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Enviar mensagem de boas-vindas
    try:
        asyncio.get_event_loop().run_until_complete(application.bot.send_message(
            chat_id=CHAT_ID,
            text="✅ *PRIME GEMS BOT ONLINE!*\nUse `/check <CA>`",
            parse_mode=ParseMode.MARKDOWN
        ))
        logger.info("✅ Boas-vindas enviada!")
    except Exception as e:
        logger.error(f"Erro: {e}")
    
    logger.info("✅ Bot rodando!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
