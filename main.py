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
    raise ValueError("Variables not configured")

logger.info("✅ Prime Gems Bot started!")

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

def escape_html(text):
    if not text:
        return "N/A"
    text = str(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def calculate_time_ago(timestamp):
    if not timestamp:
        return "now"
    try:
        if isinstance(timestamp, str):
            return timestamp
        now = datetime.now(timezone.utc)
        posted = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        diff = now - posted
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes}m ago"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours}h ago"
        else:
            days = seconds // 86400
            return f"{days}d ago"
    except:
        return "now"

async def start(update: Update, context):
    await update.message.reply_text("🚀 <b>PRIME GEMS BOT ACTIVE!</b>\n\nUse <code>/check &lt;CA&gt;</code>", parse_mode=ParseMode.HTML)

async def help_command(update: Update, context):
    await update.message.reply_text("📖 <b>COMMANDS:</b>\n<code>/check &lt;CA&gt;</code> - Token analysis with refresh button", parse_mode=ParseMode.HTML)

async def check_command(update: Update, context):
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/check &lt;CA&gt;</code>", parse_mode=ParseMode.HTML)
        return
    
    ca = context.args[0].strip()
    user = update.effective_user
    user_display = user.username or user.first_name or "User"
    user_id = user.id
    status_msg = await update.message.reply_text("🔍 Analyzing...")
    
    info = await fetch_token_info(ca)
    if not info:
        await status_msg.edit_text(" Token not found")
        return
    
    network = detect_network_from_ca(ca) or "solana"
    
    if ca not in token_initial_data:
        if info.get('source') == 'pumpfun':
            initial_mc = info.get("marketCap", 0) or 0
        else:
            initial_mc = info.get("pair", {}).get("marketCap", 0) or 0
        
        token_initial_data[ca] = {
            "initial_mc": initial_mc,
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "user": user_display,
            "user_id": user_id
        }
    
    msg, keyboard = await format_token_message(info, ca, network, user_display, user_id)
    
    try:
        await status_msg.delete()
        await update.message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        await status_msg.edit_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def handle_message(update: Update, context):
    if not update.message or not update.message.text:
        return
    
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    
    network = is_contract_address(text)
    if network and text not in processed_cas:
        processed_cas.add(text)
        user = update.effective_user
        user_display = user.username or user.first_name or "User"
        user_id = user.id
        status_msg = await update.message.reply_text("🔍 Analyzing...")
        
        info = await fetch_token_info(text)
        if not info:
            await status_msg.edit_text("❌ Token not found")
            return
        
        ca = text
        
        if ca not in token_initial_data:
            if info.get('source') == 'pumpfun':
                initial_mc = info.get("marketCap", 0) or 0
            else:
                initial_mc = info.get("pair", {}).get("marketCap", 0) or 0
            
            token_initial_data[ca] = {
                "initial_mc": initial_mc,
                "timestamp": datetime.now(timezone.utc).timestamp(),
                "user": user_display,
                "user_id": user_id
            }
        
        msg, keyboard = await format_token_message(info, ca, network, user_display, user_id)
        
        try:
            await status_msg.delete()
            await update.message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            await status_msg.edit_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def refresh_callback(update: Update, context):
    query = update.callback_query
    await query.answer("🔄 Refreshing...")
    
    ca = query.data.replace("refresh:", "")
    
    if not ca:
        await query.edit_message_text("❌ Data expired. Use /check again", parse_mode=ParseMode.HTML)
        return
    
    info = await fetch_token_info(ca)
    if not info:
        await query.edit_message_text("❌ Token not found", parse_mode=ParseMode.HTML)
        return
    
    network = detect_network_from_ca(ca) or "solana"
    
    initial_data = token_initial_data.get(ca, {})
    user_display = initial_data.get("user", "User")
    user_id = initial_data.get("user_id", 0)
    
    msg, keyboard = await format_token_message(info, ca, network, user_display, user_id)
    await query.edit_message_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def format_token_message(data, ca, network, caller, user_id):
    initial_data = token_initial_data.get(ca, {})
    initial_mc = initial_data.get("initial_mc", 0)
    timestamp = initial_data.get("timestamp", datetime.now(timezone.utc).timestamp())
    
    if data.get('source') == 'pumpfun':
        current_mc = data.get("marketCap", 0) or 0
        symbol = escape_html(data.get("symbol", "N/A"))
        name = escape_html(data.get("name", "N/A"))
        liq = data.get("liquidity", 0) or 0
        vol = data.get("volume", 0) or 0
        mint = data.get("mint", ca)
    else:
        pair = data.get("pair", {})
        current_mc = pair.get("marketCap", 0) or 0
        symbol = escape_html(pair.get("baseToken", {}).get("symbol", "N/A"))
        name = escape_html(pair.get("baseToken", {}).get("name", "N/A"))
        liq = pair.get("liquidity", {}).get("usd", 0) or 0
        vol = pair.get("volume", {}).get("h24", 0) or 0
        mint = pair.get("baseToken", {}).get("address", ca)
    
    if initial_mc > 0 and current_mc > 0:
        change_percent = ((current_mc - initial_mc) / initial_mc) * 100
        if change_percent >= 0:
            change_str = f"📈 +{change_percent:.1f}%"
        else:
            change_str = f"📉 {change_percent:.1f}%"
    else:
        change_str = "⏳ 0%"
    
    time_ago = calculate_time_ago(timestamp)
    caller_safe = escape_html(caller)
    
    if user_id:
        user_link = f"tg://user?id={user_id}"
        caller_html = f'<a href="{user_link}">@{caller_safe}</a>'
    else:
        caller_html = f"@{caller_safe}"
    
    msg = f"🔖 <b>#{symbol}</b> - {name}\n\n"
    msg += f"💵 <b>MC:</b> ${current_mc:,.0f}\n"
    msg += f"📊 <b>Vol 24h:</b> ${vol:,.0f}\n"
    msg += f" <b>Liq:</b> ${liq:,.0f}\n"
    msg += f"{change_str} <i>since post</i>\n\n"
    
    # Links lado a lado
    msg += "🔍 <b>Links:</b> "
    
    if data.get('source') == 'pumpfun':
        msg += f"<a href='https://dexscreener.com/solana/{mint}'>📊 DexScreener</a> | "
        msg += f"<a href='https://www.dextools.io/app/solana/pair/explorer/{mint}'>📈 DexTools</a> | "
        msg += f"<a href='https://gmgn.ai/solana/token/{mint}'>🤖 GMGN</a>\n"
    else:
        pair_url = data.get("pair", {}).get("url", "")
        
        if pair_url:
            msg += f"<a href='{pair_url}'>📊 DexScreener</a> | "
        
        chain_lower = data.get("pair", {}).get("chainId", "").lower()
        chain_map = {"solana": "solana", "ethereum": "ether", "bsc": "bsc", "base": "base", "arbitrum": "arbitrum", "polygon": "polygon"}
        dextools_chain = chain_map.get(chain_lower, chain_lower)
        
        msg += f"<a href='https://www.dextools.io/app/{dextools_chain}/pair/explorer/{mint}'>📈 DexTools</a> | "
        msg += f"<a href='https://gmgn.ai/{chain_lower}/token/{mint}'> GMGN</a>\n"
    
    msg += f"\n<i>⚠️ DYOR</i>\n\n"
    msg += f"👤 {caller_html} • 💵 MC Post: ${initial_mc:,.0f} • ⏱️ {time_ago}"
    
    # Botão com apenas o símbolo 🔄
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄", callback_data=f"refresh:{ca}")]
    ])
    
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
    logger.info("🚀 Starting bot...")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CallbackQueryHandler(refresh_callback, pattern="^refresh:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    try:
        asyncio.get_event_loop().run_until_complete(application.bot.send_message(
            chat_id=CHAT_ID,
            text="✅ <b>PRIME GEMS BOT ONLINE!</b>\nUse <code>/check &lt;CA&gt;</code>",
            parse_mode=ParseMode.HTML
        ))
        logger.info("✅ Welcome message sent!")
    except Exception as e:
        logger.error(f"Error: {e}")
    
    logger.info("✅ Bot running!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
