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
    await update.message.reply_text(" *COMANDOS:*\n`/check <CA>` - Análise", parse_mode=ParseMode.MARKDOWN)

async def check_command(update: Update, context):
    if not context.args:
        await update.message.reply_text("❌ Uso: `/check <CA>`", parse_mode=ParseMode.MARKDOWN)
        return
    
    ca = context.args[0].strip()
    user = update.effective_user.username or update.effective_user.first_name or "User"
    status_msg = await update.message.reply_text("🔍 Analisando...")
    
    info = await fetch_token_info(ca)
    if not info:
        await status_msg.edit_text("❌ Token não encontrado")
        return
    
    network = detect_network_from_ca(ca) or "solana"
    msg = format_gmgn_style_info(info, ca, network, user)
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
        user = update.effective_user.username or update.effective_user.first_name or "User"
        status_msg = await update.message.reply_text("🔍 Analisando...")
        info = await fetch_token_info(text)
        if info:
            msg = format_gmgn_style_info(info, text, network, user)
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

def format_gmgn_style_info(data, ca, network, caller):
    if data.get('source') == 'pumpfun':
        symbol = data.get("symbol", "N/A")
        name = data.get("name", "N/A")
        mint = data.get("mint", ca)
        mc = data.get("marketCap", 0) or 0
        liq = data.get("liquidity", 0) or 0
        vol = data.get("volume", 0) or 0
        image_url = data.get("image", "") or data.get("logo", "")
        
        # Formatar mensagem estilo imagem
        msg = f"👤 *@{caller}*\n"
        msg += f"🔖 *#{symbol}* - {name}\n\n"
        msg += f"💰 *MC:* ${mc:,.0f}\n"
        msg += f" *Vol 24h:* ${vol:,.0f}\n"
        msg += f"💧 *Liq:* ${liq:,.0f}\n\n"
        msg += "🔍 *Links:*\n"
        msg += f"📊 [DexScreener](https://dexscreener.com/solana/{mint})\n"
        msg += f"📈 [DexTools](https://www.dextools.io/app/solana/pair/explorer/{mint})\n"
        msg += f"🚀 [Pump.fun](https://pump.fun/{mint})\n"
        msg += f"🤖 [GMGN](https://gmgn.ai/solana/token/{mint})\n\n"
        msg += "⚠️ _DYOR_"
        
        return msg, image_url
    else:
        pair = data.get("pair", {})
        base = pair.get("baseToken", {})
        symbol = base.get("symbol", "N/A")
        name = base.get("name", "N/A")
        address = base.get("address", ca)
        price = float(pair.get("priceUsd", 0))
        mc = pair.get("marketCap", 0) or 0
        liq = pair.get("liquidity", {}).get("usd", 0) or 0
        vol24h = pair.get("volume", {}).get("h24", 0) or 0
        chain = pair.get("chainId", "N/A").upper()
        image_url = pair.get("info", {}).get("imageUrl", "") or pair.get("info", {}).get("logoURI", "")
        
        msg = f"👤 *@{caller}*\n"
        msg += f"🔖 *#{symbol}* - {name}\n\n"
        msg += f"💵 *Preço:* ${price:.8f}\n"
        msg += f"💰 *MC:* ${mc:,.0f}\n"
        msg += f"📊 *Vol 24h:* ${vol24h:,.0f}\n"
        msg += f"💧 *Liq:* ${liq:,.0f}\n\n"
        msg += " *Links:*\n"
        
        pair_url = pair.get("url", "")
        if pair_url:
            msg += f" [DexScreener]({pair_url})\n"
        
        chain_lower = pair.get("chainId", "").lower()
        chain_map = {
            "solana": "solana",
            "ethereum": "ether", 
            "bsc": "bsc",
            "base": "base",
            "arbitrum": "arbitrum",
            "polygon": "polygon"
        }
        
        dextools_chain = chain_map.get(chain_lower, chain_lower)
        
        msg += f"📈 [DexTools](https://www.dextools.io/app/{dextools_chain}/pair/explorer/{address})\n"
        msg += f"🤖 [GMGN](https://gmgn.ai/{chain_lower}/token/{address})\n\n"
        msg += "⚠️ _DYOR_"
        
        return msg, image_url

async def send_formatted_message(bot, chat_id, text, image_url=None):
    """Envia mensagem com ou sem imagem"""
    if image_url:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
            return
        except:
            pass
    
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

def main():
    logger.info(" Iniciando bot...")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
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
