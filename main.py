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
alerted_posts = set()

# ============================================
# CONTAS INFLUENTES PARA MONITORAMENTO
# ============================================
INFLUENCER_ACCOUNTS = {
    # Mega Influencers - Crypto/General
    "elonmusk": "🚀 Elon Musk",
    "realDonaldTrump": "🇺🇸 Donald Trump", 
    "cz_binance": "💰 CZ Binance",
    
    # Crypto Leaders
    "VitalikButerin": "💎 Vitalik",
    "aantonop": "📚 Andreas A.",
    "CathieDWood": " Cathie Wood",
    "michael_saylor": "₿ Michael Saylor",
    
    # Crypto Traders/Analysts
    "Pentosh1": " Pentosh",
    "HsakaTrades": "💎 Hsaka",
    "CryptoGodJohn": "📊 CryptoGod",
    "0xMert": " Mert",
    "Ansem": "🌊 Ansem",
    "ClownIRL": "🤡 Clown",
    "MaxCrypto__": "⚡ Max Crypto",
    "OzzyManReview": " Ozzy",
    
    # DeFi/Degen
    "DefiIgnas": "🔥 Defi Ignas",
    "MilesDeutscher": " Miles Deutscher",
    "TheMoonCarl": "🌙 Carl Moon",
    "AltcoinSherpa": "️ Altcoin Sherpa",
    "CryptoKaleo": " Kaleo",
    "rektcapital": "📉 Rekt Capital",
    
    # News/Info
    "WatcherGuru": "📰 WatcherGuru",
    "CoinDesk": " CoinDesk",
    "Cointelegraph": "📰 Cointelegraph",
    "whale_alert": " Whale Alert",
    
    # Meme Coin Hunters
    "lookonchain": "🔍 Lookonchain",
    "spotonchain": "🔎 SpotOnchain",
    "ai_9000": "🤖 AI9000",
    "Tree_of_Alpha": "🌳 Tree Alpha",
    
    # Solana Ecosystem
    "solana": "☀️ Solana",
    "raydiumprotocol": " Raydium",
    "jupiter_exchange": "🪐 Jupiter",
    
    # Base/Ethereum
    "base": " Base",
    "ethereum": "💙 Ethereum",
    "arbitrum": "🔷 Arbitrum",
}

# Palavras-chave que indicam possíveis pumps/memes
KEYWORD_ALERTS = [
    "to the moon", "moon", "pump", "100x", "1000x", "gem", "alpha",
    "buy now", "don't miss", "next big", "breaking", "announcement",
    "partnership", "listing", "launch", "presale", "IDO", "ICO"
]

MONITOR_ACCOUNTS = list(INFLUENCER_ACCOUNTS.keys())
NITTER_INSTANCES = ["https://nitter.net", "https://nitter.privacydev.net", "https://nitter.lunar.icu"]
processed_tweets = set()
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
    msg = (
        "🚀 <b>PRIME GEMS BOT ACTIVE!</b>\n\n"
        "<b>Commands:</b>\n"
        "<code>/check &lt;CA&gt;</code> - Token analysis\n"
        "<code>/alerts on</code> - Enable influencer alerts\n"
        "<code>/alerts off</code> - Disable alerts\n"
        "<code>/influencers</code> - List monitored accounts"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def help_command(update: Update, context):
    await update.message.reply_text(
        " <b>COMMANDS:</b>\n"
        "<code>/check &lt;CA&gt;</code> - Token analysis\n"
        "<code>/alerts on/off</code> - Toggle alerts\n"
        "<code>/influencers</code> - Show monitored accounts",
        parse_mode=ParseMode.HTML
    )

async def influencers_command(update: Update, context):
    msg = "📊 <b>MONITORED INFLUENCERS:</b>\n\n"
    for acc, name in INFLUENCER_ACCOUNTS.items():
        msg += f"{name} - @{acc}\n"
    msg += f"\nTotal: {len(INFLUENCER_ACCOUNTS)} accounts"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def check_command(update: Update, context):
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/check &lt;CA&gt;</code>", parse_mode=ParseMode.HTML)
        return
    
    ca = context.args[0].strip()
    user = update.effective_user
    user_display = user.username or user.first_name or "User"
    user_id = user.id
    status_msg = await update.message.reply_text(" Analyzing...")
    
    info = await fetch_token_info(ca)
    if not info:
        await status_msg.edit_text("❌ Token not found")
        return
    
    network = detect_network_from_ca(ca) or "solana"
    
    launch_mc = await get_launch_mc(ca, network, info)
    
    if ca not in token_initial_data:
        token_initial_data[ca] = {
            "initial_mc": launch_mc,
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "user": user_display,
            "user_id": user_id,
            "network": network
        }
    
    msg, keyboard = await format_token_message(info, ca, network, user_display, user_id)
    
    try:
        await status_msg.delete()
        await update.message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error: {e}")
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
        
        launch_mc = await get_launch_mc(ca, network, info)
        
        if ca not in token_initial_data:
            token_initial_data[ca] = {
                "initial_mc": launch_mc,
                "timestamp": datetime.now(timezone.utc).timestamp(),
                "user": user_display,
                "user_id": user_id,
                "network": network
            }
        
        msg, keyboard = await format_token_message(info, ca, network, user_display, user_id)
        
        try:
            await status_msg.delete()
            await update.message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"Error: {e}")
            await status_msg.edit_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def refresh_callback(update: Update, context):
    query = update.callback_query
    await query.answer("🔄")
    
    ca = query.data.replace("refresh:", "")
    
    if not ca:
        await query.edit_message_text("❌ Data expired", parse_mode=ParseMode.HTML)
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

async def get_launch_mc(ca, network, info):
    try:
        if info.get('source') == 'pumpfun':
            created_at = info.get("createdAt", 0)
            if created_at:
                current_mc = info.get("marketCap", 0) or 0
                return min(current_mc, 69000) if current_mc > 0 else 69000
            return 69000
        else:
            pair = info.get("pair", {})
            fdv = pair.get("fdv", 0) or 0
            mc = pair.get("marketCap", 0) or 0
            return min(fdv, mc) if fdv > 0 and mc > 0 else (fdv or mc or 0)
    except:
        return 0

async def format_token_message(data, ca, network, caller, user_id):
    initial_data = token_initial_data.get(ca, {})
    launch_mc = initial_data.get("initial_mc", 0)
    timestamp = initial_data.get("timestamp", datetime.now(timezone.utc).timestamp())
    token_network = initial_data.get("network", network).upper()
    
    if data.get('source') == 'pumpfun':
        current_mc = data.get("marketCap", 0) or 0
        symbol = escape_html(data.get("symbol", "N/A"))
        name = escape_html(data.get("name", "N/A"))
        liq = data.get("liquidity", 0) or 0
        vol = data.get("volume", 0) or 0
        mint = data.get("mint", ca)
        twitter = data.get("twitter", "")
        telegram = data.get("telegram", "")
        website = data.get("website", "")
    else:
        pair = data.get("pair", {})
        current_mc = pair.get("marketCap", 0) or 0
        symbol = escape_html(pair.get("baseToken", {}).get("symbol", "N/A"))
        name = escape_html(pair.get("baseToken", {}).get("name", "N/A"))
        liq = pair.get("liquidity", {}).get("usd", 0) or 0
        vol = pair.get("volume", {}).get("h24", 0) or 0
        mint = pair.get("baseToken", {}).get("address", ca)
        info_data = pair.get("info", {})
        twitter = info_data.get("twitter", "")
        telegram = info_data.get("telegram", "")
        website = info_data.get("website", "")
    
    if launch_mc > 0 and current_mc > 0:
        change_percent = ((current_mc - launch_mc) / launch_mc) * 100
        if change_percent >= 0:
            change_str = f" +{change_percent:.1f}%"
        else:
            change_str = f" {change_percent:.1f}%"
    else:
        change_str = "⏳ 0%"
    
    time_ago = calculate_time_ago(timestamp)
    caller_safe = escape_html(caller)
    
    if user_id:
        user_link = f"tg://user?id={user_id}"
        caller_html = f'<a href="{user_link}">@{caller_safe}</a>'
    else:
        caller_html = f"@{caller_safe}"
    
    launch_mc_str = f"${launch_mc:,.0f}"
    
    # Título: #SYMBOL - Name (SEM MC)
    msg = f"🔖 <b>#{symbol}</b> - {name}\n"
    # Apenas a rede em negrito
    msg += f"<b>{token_network}</b>\n\n"
    
    msg += f"💵 <b>MC:</b> ${current_mc:,.0f}\n"
    msg += f"📊 <b>Vol 24h:</b> ${vol:,.0f}\n"
    msg += f"💧 <b>LP:</b> ${liq:,.0f}\n"
    msg += f"{change_str} <i>since post</i>\n\n"
    
    # Links
    if data.get('source') == 'pumpfun':
        msg += f"<a href='https://dexscreener.com/solana/{mint}'>📊 DexScreener</a> | "
        msg += f"<a href='https://www.dextools.io/app/solana/pair/explorer/{mint}'> DexTools</a> | "
        msg += f"<a href='https://gmgn.ai/solana/token/{mint}'>🤖 GMGN</a>\n"
    else:
        pair_url = data.get("pair", {}).get("url", "")
        if pair_url:
            msg += f"<a href='{pair_url}'>📊 DexScreener</a> | "
        
        chain_lower = data.get("pair", {}).get("chainId", "").lower()
        chain_map = {"solana": "solana", "ethereum": "ether", "bsc": "bsc", "base": "base", "arbitrum": "arbitrum", "polygon": "polygon"}
        dextools_chain = chain_map.get(chain_lower, chain_lower)
        
        msg += f"<a href='https://www.dextools.io/app/{dextools_chain}/pair/explorer/{mint}'>📈 DexTools</a> | "
        msg += f"<a href='https://gmgn.ai/{chain_lower}/token/{mint}'>🤖 GMGN</a>\n"
    
    # Redes sociais
    social_links = []
    if twitter:
        social_links.append(f"<a href='{twitter}'></a>")
    if telegram:
        social_links.append(f"<a href='{telegram}'>✈️ TG</a>")
    if website:
        social_links.append(f"<a href='{website}'>🌐 Site</a>")
    
    if social_links:
        msg += "\n" + " | ".join(social_links) + "\n"
    
    msg += f"\n<i>⚠️ DYOR</i>\n\n"
    msg += f"👤 {caller_html} • {launch_mc_str} • ⏱️ {time_ago}"
    
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

async def monitor_influencers(bot):
    """Monitora postagens de influenciadores e detecta possíveis pumps"""
    logger.info(" Starting influencer monitoring...")
    
    while True:
        try:
            for account in MONITOR_ACCOUNTS:
                try:
                    tweets = await fetch_latest_tweets(account)
                    
                    for tweet in tweets:
                        tweet_id = tweet["link"]
                        
                        if tweet_id in processed_tweets:
                            continue
                        
                        processed_tweets.add(tweet_id)
                        
                        # Verificar se o tweet contém CA
                        addresses = extract_contract_addresses(tweet["text"])
                        all_cas = addresses.get("solana", []) + addresses.get("ethereum", [])
                        
                        # Verificar palavras-chave
                        text_lower = tweet["text"].lower()
                        has_keyword = any(keyword in text_lower for keyword in KEYWORD_ALERTS)
                        
                        # Se tem CA ou palavra-chave importante, enviar alerta
                        if all_cas or has_keyword:
                            influencer_name = INFLUENCER_ACCOUNTS.get(account, account)
                            
                            alert_msg = f"🚨 <b>INFLUENCER ALERT!</b>\n\n"
                            alert_msg += f"👤 <b>{influencer_name}</b> (@{account})\n\n"
                            alert_msg += f"📝 <i>{escape_html(tweet['text'][:200])}</i>\n\n"
                            
                            if all_cas:
                                alert_msg += f"📄 <b>CA detected:</b>\n"
                                for ca in all_cas[:2]:
                                    alert_msg += f"<code>{ca}</code>\n"
                                    
                                    # Buscar info do token se tiver CA
                                    token_info = await fetch_token_info(ca)
                                    if token_info:
                                        if token_info.get('source') == 'pumpfun':
                                            symbol = token_info.get("symbol", "N/A")
                                            mc = token_info.get("marketCap", 0) or 0
                                            alert_msg += f"💎 {symbol} • MC: ${mc:,.0f}\n"
                                
                                alert_msg += "\n"
                            
                            alert_msg += f"🔗 <a href='{tweet['link']}'>View Tweet</a>\n\n"
                            alert_msg += "<i>️ DYOR - High risk!</i>"
                            
                            try:
                                await bot.send_message(
                                    chat_id=CHAT_ID,
                                    text=alert_msg,
                                    parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True
                                )
                                logger.info(f"✅ Alert sent: @{account}")
                            except Exception as e:
                                logger.error(f"Error sending alert: {e}")
                            
                            await asyncio.sleep(2)
                    
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Error monitoring @{account}: {e}")
                    continue
            
            if len(processed_tweets) > 1000:
                processed_tweets.clear()
            
            await asyncio.sleep(180)  # Verificar a cada 3 minutos
            
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")
            await asyncio.sleep(60)

def extract_contract_addresses(text):
    solana = re.findall(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b', text)
    ethereum = re.findall(r'\b0x[a-fA-F0-9]{40}\b', text)
    
    solana = [s for s in solana if 'http' not in s.lower() and 'www' not in s.lower()]
    ethereum = [e for e in ethereum if 'http' not in e.lower()]
    
    return {"solana": solana, "ethereum": ethereum}

async def fetch_latest_tweets(account):
    for instance in NITTER_INSTANCES:
        try:
            url = f"{instance}/{account}/rss"
            headers = {"User-Agent": "Mozilla/5.0"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        xml = await resp.text()
                        tweets = parse_rss(xml, account)
                        if tweets:
                            return tweets
        except:
            continue
    return []

def parse_rss(xml_content, account):
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_content)
        tweets = []
        for item in root.findall(".//item"):
            title = item.find("title")
            link = item.find("link")
            if title is not None and link is not None:
                tweets.append({
                    "account": account,
                    "text": title.text,
                    "link": link.text.replace("nitter.net", "twitter.com")
                })
        return tweets[:5]
    except:
        return []

def main():
    logger.info("🚀 Starting bot...")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("influencers", influencers_command))
    application.add_handler(CallbackQueryHandler(refresh_callback, pattern="^refresh:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    try:
        asyncio.get_event_loop().run_until_complete(application.bot.send_message(
            chat_id=CHAT_ID,
            text=(
                "✅ <b>PRIME GEMS BOT ONLINE!</b>\n\n"
                "🔍 <b>Features:</b>\n"
                "• Token analysis: /check &lt;CA&gt;\n"
                "• Influencer alerts: Active\n"
                "• Monitored: " + str(len(INFLUENCER_ACCOUNTS)) + " accounts"
            ),
            parse_mode=ParseMode.HTML
        ))
        logger.info("✅ Welcome message sent!")
    except Exception as e:
        logger.error(f"Error: {e}")
    
    # Iniciar monitoramento de influenciadores
    bot = application.bot
    asyncio.create_task(monitor_influencers(bot))
    
    logger.info("✅ Bot running with influencer monitoring!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
