import os
import asyncio
import aiohttp
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Variáveis não configuradas")

logger.info("✅ Prime Gems Bot iniciado!")

# Cache para dados iniciais dos tokens
token_initial_data = {}

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

def calculate_time_ago(timestamp):
    """Calcula tempo decorrido desde timestamp"""
    if not timestamp:
        return "agora"
    
    try:
        if isinstance(timestamp, str):
            return timestamp
        
        now = datetime.now(timezone.utc)
        posted = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        diff = now - posted
        
        seconds = int(diff.total_seconds())
        
        if seconds < 60:
            return f"{seconds}s atrás"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes}m atrás"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours}h atrás"
        else:
            days = seconds // 86400
            return f"{days}d atrás"
    except:
        return "agora"

async def start(update: Update, context):
    await update.message.reply_text("🚀 *PRIME GEMS BOT ATIVO!*\n\nUse `/check <CA>`", parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context):
    await update.message.reply_text(" *COMANDOS:*\n`/check <CA>` - Análise com botão atualizar", parse_mode=ParseMode.MARKDOWN)

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
    
    # Salvar dados iniciais se for primeira vez
    if ca not in token_initial_data:
        if info.get('source') == 'pumpfun':
            initial_mc = info.get("marketCap", 0) or 0
        else:
            initial_mc = info.get("pair", {}).get("marketCap", 0) or 0
        
        token_initial_data[ca] = {
            "initial_mc": initial_mc,
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "user": user
        }
    
    msg, keyboard = await format_token_message(info, ca, network, user)
    
    try:
        await status_msg.delete()
        await update.message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except:
        await status_msg.edit_text(msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

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
        if not info:
            await status_msg.edit_text("❌ Token não encontrado")
            return
        
        ca = text
        
        # Salvar dados iniciais
        if ca not in token_initial_data:
            if info.get('source') == 'pumpfun':
                initial_mc = info.get("marketCap", 0) or 0
            else:
                initial_mc = info.get("pair", {}).get("marketCap", 0) or 0
            
            token_initial_data[ca] = {
                "initial_mc": initial_mc,
                "timestamp": datetime.now(timezone.utc).timestamp(),
                "user": user
            }
        
        msg, keyboard = await format_token_message(info, ca, network, user)
        
        try:
            await status_msg.delete()
            await update.message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        except:
            await status_msg.edit_text(msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def refresh_callback(update: Update, context):
    """Handler para botão de atualizar"""
    query = update.callback_query
    await query.answer("🔄 Atualizando...")
    
    ca = context.user_data.get('refresh_ca')
    network = context.user_data.get('refresh_network')
    user = context.user_data.get('refresh_user')
    
    if not ca or not network:
        await query.edit_message_text("❌ Dados expirados. Use /check novamente")
        return
    
    info = await fetch_token_info(ca)
    if not info:
        await query.edit_message_text("❌ Token não encontrado")
        return
    
    msg, keyboard = await format_token_message(info, ca, network, user)
    await query.edit_message_text(msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def format_token_message(data, ca, network, caller):
    """Formata mensagem com botão de atualizar"""
    
    # Pegar dados iniciais
    initial_data = token_initial_data.get(ca, {})
    initial_mc = initial_data.get("initial_mc", 0)
    timestamp = initial_data.get("timestamp", datetime.now(timezone.utc).timestamp())
    
    # Calcular MC atual e variação
    if data.get('source') == 'pumpfun':
        current_mc = data.get("marketCap", 0) or 0
        symbol = data.get("symbol", "N/A")
        name = data.get("name", "N/A")
        liq = data.get("liquidity", 0) or 0
        vol = data.get("volume", 0) or 0
        image_url = data.get("image", "") or data.get("logo", "")
    else:
        pair = data.get("pair", {})
        current_mc = pair.get("marketCap", 0) or 0
        symbol = pair.get("baseToken", {}).get("symbol", "N/A")
        name = pair.get("baseToken", {}).get("name", "N/A")
        liq = pair.get("liquidity", {}).get("usd", 0) or 0
        vol = pair.get("volume", {}).get("h24", 0) or 0
        image_url = pair.get("info", {}).get("imageUrl", "")
    
    # Calcular % de variação
    if initial_mc > 0 and current_mc > 0:
        change_percent = ((current_mc - initial_mc) / initial_mc) * 100
        if change_percent >= 0:
            change_str = f"📈 +{change_percent:.1f}%"
        else:
            change_str = f" {change_percent:.1f}%"
    else:
        change_str = " 0%"
    
    # Tempo decorrido
    time_ago = calculate_time_ago(timestamp)
    
    # Formatar mensagem
    msg = f"🔖 *#{symbol}* - {name}\n\n"
    msg += f" *MC Atual:* ${current_mc:,.0f}\n"
    msg += f"📊 *Vol 24h:* ${vol:,.0f}\n"
    msg += f"💧 *Liq:* ${liq:,.0f}\n"
    msg += f"{change_str} *desde post*\n\n"
    msg += " *Links:*\n"
    
    if data.get('source') == 'pumpfun':
        mint = data.get("mint", ca)
        msg += f"📊 [DexScreener](https://dexscreener.com/solana/{mint})\n"
        msg += f" [DexTools](https://www.dextools.io/app/solana/pair/explorer/{mint})\n"
        msg += f" [Pump.fun](https://pump.fun/{mint})\n"
        msg += f" [GMGN](https://gmgn.ai/solana/token/{mint})\n"
    else:
        address = data.get("pair", {}).get("baseToken", {}).get("address", ca)
        pair_url = data.get("pair", {}).get("url", "")
        chain = data.get("pair", {}).get("chainId", "N/A").upper()
        
        if pair_url:
            msg += f"📊 [DexScreener]({pair_url})\n"
        
        chain_lower = data.get("pair", {}).get("chainId", "").lower()
        chain_map = {"solana": "solana", "ethereum": "ether", "bsc": "bsc", "base": "base", "arbitrum": "arbitrum", "polygon": "polygon"}
        dextools_chain = chain_map.get(chain_lower, chain_lower)
        
        msg += f"📈 [DexTools](https://www.dextools.io/app/{dextools_chain}/pair/explorer/{address})\n"
        msg += f"🤖 [GMGN](https://gmgn.ai/{chain_lower}/token/{address})\n"
    
    msg += f"\n️ _DYOR_\n\n"
    msg += f"👤 @{caller} • 💵 MC Post: ${initial_mc:,.0f} • ⏱️ {time_ago}"
    
    # Criar botão de atualizar
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Atualizar", callback_data="refresh")]])
    
    # Salvar dados para refresh
    return msg, keyboard

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

def main():
    logger.info("🚀 Iniciando bot...")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CallbackQueryHandler(refresh_callback, pattern="^refresh$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Mensagem de boas-vindas
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
