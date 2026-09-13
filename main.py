import os
import asyncio
import aiohttp
import logging
import re
import json
import math
import xml.etree.ElementTree as ET
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Variables not configured")

logger.info("✅ Prime Gems Bot started!")

token_initial_data = {}
user_calls_data = {}
pnl_settings = {}
x_return_alerts = {}
processed_tweets = set()
alerted_tokens = set()
processed_cas = set()

DATA_FILE = "user_calls.json"
PNL_SETTINGS_FILE = "pnl_settings.json"
X_ALERTS_FILE = "x_alerts.json"

CHAIN_NAMES = {
    "solana": "SOL", "ethereum": "ETH", "bsc": "BSC", "base": "BASE",
    "hood": "HOOD", "polygon": "POLYGON", "arbitrum": "ARBITRUM",
    "avalanche": "AVALANCHE", "optimism": "OPTIMISM", "fantom": "FANTOM"
}

PNL_THEMES = {
    "dark": {"bg": (26, 26, 46), "text": (255, 255, 255), "secondary": (139, 148, 158)},
    "light": {"bg": (245, 245, 247), "text": (0, 0, 0), "secondary": (100, 100, 100)}
}

PNL_COLORS = {
    "green": (0, 255, 136), "cyan": (0, 255, 255), "purple": (155, 89, 182),
    "pink": (255, 105, 180), "gold": (255, 215, 0), "orange": (255, 140, 0)
}

X_RETURN_MILESTONES = [2.0, 5.0, 10.0, 20.0, 50.0, 100.0]

INFLUENCER_ACCOUNTS = {
    "elonmusk": "🚀 Elon Musk",
    "realDonaldTrump": "🇺🇸 Donald Trump",
    "CZ_Binance": "💰 CZ Binance",
    "VitalikButerin": "💎 Vitalik",
    "aantonop": " Andreas A.",
    "CathieDWood": "🌳 Cathie Wood",
    "michael_saylor": "₿ Michael Saylor",
    "Pentosh1": " Pentosh",
    "HsakaTrades": "💎 Hsaka",
    "CryptoGodJohn": "📊 CryptoGod",
    "0xMert": "⚡ Mert",
    "Ansem": "🌊 Ansem",
    "ClownIRL": " Clown",
    "MaxCrypto__": " Max Crypto",
    "OzzyManReview": "🔍 Ozzy",
    "DefiIgnas": "🔥 Defi Ignas",
    "MilesDeutscher": "📊 Miles",
    "TheMoonCarl": "🌙 Carl Moon",
    "AltcoinSherpa": "🎯 Sherpa",
    "CryptoKaleo": "🎯 Kaleo",
    "rektcapital": "📉 Rekt Capital",
    "WatcherGuru": " WatcherGuru",
    "CoinDesk": "📰 CoinDesk",
    "Cointelegraph": "📰 Cointelegraph",
    "whale_alert": "🐋 Whale Alert",
    "lookonchain": " Lookonchain",
    "spotonchain": "🔎 SpotOnchain",
    "ai_9000": "🤖 AI9000",
    "Tree_of_Alpha": "🌳 Tree Alpha",
    "solana": "☀️ Solana",
    "raydiumprotocol": "🌊 Raydium",
    "jupiter_exchange": "🪐 Jupiter",
    "base": "🔵 Base",
    "ethereum": "💙 Ethereum",
    "arbitrum": "🔷 Arbitrum",
}

KEYWORD_ALERTS = [
    "to the moon", "moon", "pump", "100x", "1000x", "gem", "alpha",
    "buy now", "don't miss", "next big", "breaking", "announcement",
    "partnership", "listing", "launch", "presale", "IDO", "ICO"
]

MONITOR_ACCOUNTS = list(INFLUENCER_ACCOUNTS.keys())
NITTER_INSTANCES = ["https://nitter.net", "https://nitter.privacydev.net", "https://nitter.lunar.icu"]

def load_data():
    global user_calls_data, pnl_settings, x_return_alerts
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f: user_calls_data = json.load(f)
        if os.path.exists(PNL_SETTINGS_FILE):
            with open(PNL_SETTINGS_FILE, 'r') as f: pnl_settings = json.load(f)
        if os.path.exists(X_ALERTS_FILE):
            with open(X_ALERTS_FILE, 'r') as f: x_return_alerts = json.load(f)
        logger.info(" Data loaded")
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def save_data():
    try:
        with open(DATA_FILE, 'w') as f: json.dump(user_calls_data, f, indent=2)
        with open(PNL_SETTINGS_FILE, 'w') as f: json.dump(pnl_settings, f, indent=2)
        with open(X_ALERTS_FILE, 'w') as f: json.dump(x_return_alerts, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving: {e}")

def get_pnl_settings(chat_id):
    cid = str(chat_id)
    if cid not in pnl_settings:
        pnl_settings[cid] = {"theme": "dark", "color": "green", "custom_bg": None}
    return pnl_settings[cid]

def is_contract_address(text):
    text = text.strip()
    if re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', text): return "solana"
    elif re.match(r'^0x[a-fA-F0-9]{40,42}$', text): return "evm"
    return None

def detect_network_from_ca(ca):
    if ca.startswith("0x") and 40 <= len(ca) <= 42: return "evm"
    elif 32 <= len(ca) <= 44: return "solana"
    return None

def get_chain_name(chain_id):
    if not chain_id: return "UNKNOWN"
    return CHAIN_NAMES.get(chain_id.lower(), "UNKNOWN")

def escape_html(text):
    if not text: return "N/A"
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def calculate_time_ago(timestamp):
    if not timestamp: return "now"
    try:
        now = datetime.now(timezone.utc)
        posted = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        diff = now - posted
        seconds = int(diff.total_seconds())
        if seconds < 60: return f"{seconds}s ago"
        elif seconds < 3600: return f"{seconds//60}m ago"
        elif seconds < 86400: return f"{seconds//3600}h ago"
        else: return f"{seconds//86400}d ago"
    except: return "now"

def parse_period(period_str):
    period_str = period_str.lower().strip()
    if period_str.endswith('d'): return timedelta(days=int(period_str[:-1]))
    elif period_str.endswith('w'): return timedelta(weeks=int(period_str[:-1]))
    elif period_str.endswith('mo') or period_str.endswith('m'):
        return timedelta(days=int(period_str.replace('mo','').replace('m',''))*30)
    return timedelta(days=1)

def get_calls_in_period(user_id, period_str):
    if user_id not in user_calls_data: return []
    period = parse_period(period_str)
    cutoff = datetime.now(timezone.utc) - period
    return [c for c in user_calls_data[user_id].get("calls", [])
            if datetime.fromtimestamp(c["timestamp"], tz=timezone.utc) >= cutoff]

def calculate_median(values):
    if not values: return 0
    s = sorted(values)
    n = len(s)
    return (s[n//2-1] + s[n//2])/2 if n%2==0 else s[n//2]

def extract_contract_addresses(text):
    solana = re.findall(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b', text)
    ethereum = re.findall(r'\b0x[a-fA-F0-9]{40,42}\b', text)
    solana = [s for s in solana if 'http' not in s.lower() and 'www' not in s.lower()]
    ethereum = [e for e in ethereum if 'http' not in e.lower()]
    return {"solana": solana, "ethereum": ethereum}

def get_user_period_stats(user_id, period_str):
    calls = get_calls_in_period(user_id, period_str)
    if not calls: return None
    
    total = len(calls)
    returns, points_list = [], []
    wins, calls_2x = 0, 0
    best_ret, best_sym, best_ca = 0, None, None
    
    for c in calls:
        mc_in, mc_cur = c.get("mc_at_call", 0), c.get("current_mc", 0)
        if mc_in > 0 and mc_cur > 0:
            ratio = mc_cur / mc_in
            returns.append(ratio)
            pts = math.log2(ratio / 1.5) if ratio > 0 else -10
            points_list.append(pts)
            if ratio > 1: wins += 1
            if ratio >= 2: calls_2x += 1
            if ratio > best_ret:
                best_ret = ratio
                best_sym = c.get("symbol")
                best_ca = c.get("ca")
    
    return {
        "total_calls": total, "winning_calls": wins,
        "hit_rate": round((wins/total)*100, 1),
        "hit_rate_2x": round((calls_2x/total)*100, 1),
        "avg_return": round((sum(returns)/total - 1)*100, 1) if returns else 0,
        "median_return": round(calculate_median(returns), 2),
        "total_points": round(sum(points_list), 2),
        "best_call_symbol": best_sym, "best_call_return": round(best_ret, 2)
    }

async def fetch_token_info(ca):
    async with aiohttp.ClientSession() as session:
        # Tenta Solana primeiro (pump.fun)
        if detect_network_from_ca(ca) == "solana":
            try:
                async with session.get(f"https://frontend-api.pump.fun/coins/{ca}",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        data['source'] = 'pumpfun'
                        return data
            except: pass
        
        # Tenta DexScreener (todas as redes)
        try:
            async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
                timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        best_pair = max(pairs, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)
                        best_pair['source'] = 'dexscreener'
                        return {"pair": best_pair, "source": "dexscreener"}
        except: pass
    return None

async def fetch_trending_pumpfun():
    url = "https://frontend-api.pump.fun/coins?limit=20&offset=0"
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", []) if isinstance(data, dict) else data
        except: pass
    return []

async def fetch_new_pairs():
    url = "https://api.dexscreener.com/latest/dex/pairs/v2?order=createdAt&limit=50"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pairs", [])[:50]
        except: pass
    return []

async def fetch_graduated_tokens():
    url = "https://api.dexscreener.com/latest/dex/search?q=marketCap>50000&liquidity>10000&chainId=solana&dexId=raydium"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pairs", [])[:20]
        except: pass
    return []

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
                        if tweets: return tweets
        except: continue
    return []

def parse_rss(xml_content, account):
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
    except: return []

async def format_token_message(data, ca, network, caller, user_id):
    d = token_initial_data.get(ca, {})
    init_mc = d.get("initial_mc", 0)
    ts = d.get("timestamp", datetime.now(timezone.utc).timestamp())
    chain = d.get("chain_name", "UNKNOWN")
    
    if data.get('source') == 'pumpfun':
        cur_mc = data.get("marketCap", 0) or 0
        sym = escape_html(data.get("symbol", "N/A"))
        name = escape_html(data.get("name", "N/A"))
        liq = data.get("liquidity", 0) or 0
        vol = data.get("volume", 0) or 0
        mint = data.get("mint", ca)
        tw = data.get("twitter", "")
        tg = data.get("telegram", "")
        web = data.get("website", "")
    else:
        p = data.get("pair", {})
        cur_mc = p.get("marketCap", 0) or 0
        sym = escape_html(p.get("baseToken", {}).get("symbol", "N/A"))
        name = escape_html(p.get("baseToken", {}).get("name", "N/A"))
        liq = p.get("liquidity", {}).get("usd", 0) or 0
        vol = p.get("volume", {}).get("h24", 0) or 0
        mint = p.get("baseToken", {}).get("address", ca)
        inf = p.get("info", {})
        tw = inf.get("twitter", "")
        tg = inf.get("telegram", "")
        web = inf.get("website", "")
    
    if init_mc > 0 and cur_mc > 0:
        chg = ((cur_mc - init_mc) / init_mc) * 100
        chg_str = f" +{chg:.1f}%" if chg >= 0 else f" {chg:.1f}%"
    else: chg_str = "⏳ 0%"
    
    t_ago = calculate_time_ago(ts)
    c_safe = escape_html(caller)
    c_html = f'<a href="tg://user?id={user_id}">@{c_safe}</a>' if user_id else f"@{c_safe}"
    
    msg = f"🔖 <b>#{sym}</b> - {name}\n<b>{chain}</b>\n\n"
    msg += f"💵 <b>MC:</b> ${cur_mc:,.0f}\n"
    msg += f" <b>Vol 24h:</b> ${vol:,.0f}\n"
    msg += f"💧 <b>LP:</b> ${liq:,.0f}\n"
    msg += f"{chg_str} <i>since post</i>\n\n"
    
    if data.get('source') == 'pumpfun':
        msg += f"<a href='https://dexscreener.com/solana/{mint}'>📊 DexScreener</a> | "
        msg += f"<a href='https://www.dextools.io/app/solana/pair/explorer/{mint}'>📈 DexTools</a> | "
        msg += f"<a href='https://gmgn.ai/solana/token/{mint}'>🤖 GMGN</a>\n"
    else:
        pu = data.get("pair", {}).get("url", "")
        cl = data.get("pair", {}).get("chainId", "").lower()
        if pu: msg += f"<a href='{pu}'> DexScreener</a> | "
        cm = {"solana": "solana", "ethereum": "ether", "bsc": "bsc", "base": "base", "hood": "hood",
              "arbitrum": "arbitrum", "polygon": "polygon"}
        msg += f"<a href='https://www.dextools.io/app/{cm.get(cl, cl)}/pair/explorer/{mint}'>📈 DexTools</a> | "
        msg += f"<a href='https://gmgn.ai/{cl}/token/{mint}'> GMGN</a>\n"
    
    sl = []
    if tw: sl.append(f"<a href='{tw}'>𝕏</a>")
    if tg: sl.append(f"<a href='{tg}'>✈️ TG</a>")
    if web: sl.append(f"<a href='{web}'>🌐 Site</a>")
    if sl: msg += "\n" + " | ".join(sl) + "\n"
    
    msg += f"\n<i>⚠️ DYOR</i>\n\n👤 {c_html} • ${init_mc:,.0f} • ⏱️ {t_ago}"
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data=f"refresh:{ca}")]])
    return msg, kb

def format_twitter_alert(account, tweet_text, tweet_link, ca, token_info):
    msg = f" <b>INFLUENCER ALERT!</b>\n\n"
    msg += f" <b>{INFLUENCER_ACCOUNTS.get(account, account)}</b> (@{account})\n\n"
    msg += f" <i>{escape_html(tweet_text[:200])}</i>\n\n"
    
    if token_info:
        if token_info.get('source') == 'pumpfun':
            sym = token_info.get("symbol", "N/A")
            mc = token_info.get("marketCap", 0) or 0
        else:
            sym = token_info.get("pair", {}).get("baseToken", {}).get("symbol", "N/A")
            mc = token_info.get("pair", {}).get("marketCap", 0) or 0
        msg += f"💎 #{escape_html(sym)} • MC: ${mc:,.0f}\n\n"
    
    msg += f"🔗 <a href='{tweet_link}'>View Tweet</a>\n\n"
    msg += "<i>⚠️ DYOR - High risk!</i>"
    return msg

def create_pnl_card(data, ca, network, settings):
    """Cria imagem PNL - CORRIGIDA para usar chain_name salvo"""
    theme = PNL_THEMES.get(settings.get("theme", "dark"), PNL_THEMES["dark"])
    color = PNL_COLORS.get(settings.get("color", "green"), PNL_COLORS["green"])
    width, height = 1200, 630
    
    img = Image.new('RGB', (width, height), theme["bg"])
    draw = ImageDraw.Draw(img)
    
    try:
        font_l = ImageFont.load_default(size=80)
        font_m = ImageFont.load_default(size=50)
        font_s = ImageFont.load_default(size=32)
        font_xs = ImageFont.load_default(size=24)
    except:
        font_l = ImageFont.load_default()
        font_m = ImageFont.load_default()
        font_s = ImageFont.load_default()
        font_xs = ImageFont.load_default()
    
    # USAR chain_name SALVO no token_initial_data (CORREÇÃO DO BUG UNKNOWN)
    saved_data = token_initial_data.get(ca, {})
    chain = saved_data.get("chain_name", "UNKNOWN")
    
    # Extrair dados
    if data.get('source') == 'pumpfun':
        sym = data.get("symbol", "N/A")
        name = data.get("name", "N/A")
        mc = data.get("marketCap", 0) or 0
        vol = data.get("volume", 0) or 0
        liq = data.get("liquidity", 0) or 0
    else:
        p = data.get("pair", {})
        sym = p.get("baseToken", {}).get("symbol", "N/A")
        name = p.get("baseToken", {}).get("name", "N/A")
        mc = p.get("marketCap", 0) or 0
        vol = p.get("volume", {}).get("h24", 0) or 0
        liq = p.get("liquidity", {}).get("usd", 0) or 0
        # Se chain ainda é UNKNOWN, tenta pegar do pair
        if chain == "UNKNOWN":
            chain = get_chain_name(p.get("chainId", ""))
    
    # Calcular mudança
    init_mc = saved_data.get("initial_mc", 0)
    if init_mc > 0 and mc > 0:
        chg = ((mc - init_mc) / init_mc) * 100
        chg_str = f"+{chg:.1f}%" if chg >= 0 else f"{chg:.1f}%"
        chg_col = color if chg >= 0 else (255, 100, 100)
    else:
        chg_str, chg_col = "0%", theme["secondary"]
    
    # Layout
    x, y = 60, 50
    
    draw.text((x, y), f"#{sym}", fill=theme["text"], font=font_l)
    y += 100
    draw.text((x, y), name[:50], fill=theme["secondary"], font=font_s)
    y += 50
    draw.text((x, y), chain, fill=color, font=font_m)
    y += 80
    
    draw.line([(x, y), (width-60, y)], fill=theme["secondary"], width=2)
    y += 50
    
    metrics = [
        ("Market Cap", f"${mc:,.0f}"),
        ("Volume 24h", f"${vol:,.0f}"),
        ("Liquidity", f"${liq:,.0f}"),
    ]
    
    for lbl, val in metrics:
        draw.text((x, y), lbl, fill=theme["secondary"], font=font_s)
        y += 40
        draw.text((x, y), val, fill=theme["text"], font=font_m)
        y += 60
    
    draw.text((x, y), "Change", fill=theme["secondary"], font=font_s)
    y += 40
    draw.text((x, y), chg_str, fill=chg_col, font=font_l)
    
    y = height - 60
    draw.line([(x, y), (width-60, y)], fill=theme["secondary"], width=1)
    y += 15
    draw.text((x, y), "PRIME GEMS BOT • DYOR", fill=theme["secondary"], font=font_xs)
    
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    
    logger.info(f"✅ PNL card gerado: #{sym} - {chain} - {chg_str}")
    return buf

async def check_x_return_alerts(bot):
    """Verifica se algum token atingiu milestone de X-Return"""
    for ca, data in list(token_initial_data.items()):
        init_mc = data.get("initial_mc", 0)
        if init_mc <= 0:
            continue
        
        info = await fetch_token_info(ca)
        if not info:
            continue
        
        if info.get('source') == 'pumpfun':
            cur_mc = info.get("marketCap", 0) or 0
            sym = info.get("symbol", "N/A")
        else:
            cur_mc = info.get("pair", {}).get("marketCap", 0) or 0
            sym = info.get("pair", {}).get("baseToken", {}).get("symbol", "N/A")
        
        if cur_mc <= 0:
            continue
        
        ratio = cur_mc / init_mc
        
        if ca not in x_return_alerts:
            x_return_alerts[ca] = {str(m): False for m in X_RETURN_MILESTONES}
        
        for milestone in X_RETURN_MILESTONES:
            milestone_str = f"{milestone}x"
            if ratio >= milestone and not x_return_alerts[ca].get(milestone_str, False):
                msg = f"🚀 <b>X-RETURN ALERT!</b>\n\n"
                msg += f"🔥 <b>#{escape_html(sym)}</b> atingiu <b>{milestone_str}</b>!\n\n"
                msg += f"💰 MC Inicial: ${init_mc:,.0f}\n"
                msg += f"💵 MC Atual: ${cur_mc:,.0f}\n"
                msg += f" Retorno: {ratio:.2f}x\n\n"
                msg += f"👤 Called by: {escape_html(data.get('user', 'Unknown'))}\n\n"
                msg += "<i>⚠️ DYOR - Não é recomendação de investimento!</i>"
                
                try:
                    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.HTML)
                    x_return_alerts[ca][milestone_str] = True
                    save_data()
                    logger.info(f"🚀 X-Return alert: {sym} {milestone_str}")
                except Exception as e:
                    logger.error(f"Error sending X-Return alert: {e}")
                
                await asyncio.sleep(2)

async def xalerts_command(update: Update, context):
    if not context.args:
        msg = " <b>X-RETURN ALERTS</b>\n\n"
        msg += "Use: <code>/xalerts on</code> para ativar\n"
        msg += "Use: <code>/xalerts off</code> para desativar\n\n"
        msg += "Milestones: 2x, 5x, 10x, 20x, 50x, 100x"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return
    
    action = context.args[0].lower()
    if action == "on":
        context.bot_data['x_alerts_enabled'] = True
        await update.message.reply_text("✅ X-Return alerts ativados!")
    elif action == "off":
        context.bot_data['x_alerts_enabled'] = False
        await update.message.reply_text("⚠️ X-Return alerts desativados!")
    else:
        await update.message.reply_text("❌ Use: /xalerts on|off")

async def start(update: Update, context):
    await update.message.reply_text(
        "🚀 <b>PRIME GEMS BOT ACTIVE!</b>\n\n"
        "🔍 <code>/check &lt;CA&gt;</code> - Token analysis\n"
        "🏆 <code>/lb</code> - Leaderboard\n"
        " <code>/stats</code> - Your stats\n"
        "🎨 <code>/pnl &lt;CA&gt;</code> - PNL card\n"
        "🚀 <code>/xalerts on|off</code> - X-Return alerts\n"
        "📈 <code>/trending</code> - Top Pump.fun\n"
        "⭐ <code>/migrations</code> - Graduated tokens\n"
        "🆕 <code>/newpairs</code> - New pairs\n"
        "📱 <code>/monitor</code> - Influencers list\n"
        " <code>/help</code> - Help",
        parse_mode=ParseMode.HTML)

async def help_command(update: Update, context):
    await update.message.reply_text(
        "📖 <b>COMMANDS:</b>\n\n"
        "<code>/check &lt;CA&gt;</code> - Token analysis\n"
        "<code>/lb</code> - Leaderboard\n"
        "<code>/stats</code> - Your stats\n"
        "<code>/pnl &lt;CA&gt;</code> - PNL card\n"
        "<code>/pnlbg</code> - Set background\n"
        "<code>/pnltheme</code> - Theme\n"
        "<code>/pnlcolor</code> - Color\n"
        "<code>/xalerts on|off</code> - X-Return alerts\n"
        "<code>/trending</code> - Top Pump.fun\n"
        "<code>/migrations</code> - Graduated\n"
        "<code>/newpairs</code> - New pairs\n"
        "<code>/monitor</code> - Influencers\n"
        "<code>/influencers</code> - All accounts",
        parse_mode=ParseMode.HTML)

async def check_command(update: Update, context):
    if not context.args:
        await update.message.reply_text(" Usage: <code>/check &lt;CA&gt;</code>", parse_mode=ParseMode.HTML)
        return
    ca = context.args[0].strip()
    user = update.effective_user
    u_disp = user.username or user.first_name or "User"
    uid = str(user.id)
    status = await update.message.reply_text("🔍 Analyzing...")
    
    info = await fetch_token_info(ca)
    if not info:
        await status.edit_text("❌ Token not found")
        return
    
    net = detect_network_from_ca(ca) or "solana"
    if info.get('source') == 'pumpfun':
        chain, sym = "SOL", info.get("symbol", "N/A")
        mc = info.get("marketCap", 0) or 0
    else:
        p = info.get("pair", {})
        chain = get_chain_name(p.get("chainId", ""))
        sym = p.get("baseToken", {}).get("symbol", "N/A")
        mc = p.get("marketCap", 0) or 0
    
    if uid not in user_calls_data: user_calls_data[uid] = {"username": u_disp, "calls": []}
    user_calls_data[uid]["calls"].append({
        "ca": ca, "timestamp": datetime.now(timezone.utc).timestamp(),
        "mc_at_call": mc, "current_mc": mc, "network": chain, "symbol": sym})
    save_data()
    
    if ca not in token_initial_data:
        token_initial_data[ca] = {
            "initial_mc": mc, "timestamp": datetime.now(timezone.utc).timestamp(),
            "user": u_disp, "user_id": user.id, "network": net,
            "chain_name": chain, "symbol": sym}
        x_return_alerts[ca] = {str(m): False for m in X_RETURN_MILESTONES}
        save_data()
    
    msg, kb = await format_token_message(info, ca, net, u_disp, user.id)
    try:
        await status.delete()
        await update.message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error: {e}")
        await status.edit_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def handle_message(update: Update, context):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    if text.startswith("/"): return
    
    net = is_contract_address(text)
    if net and text not in processed_cas:
        processed_cas.add(text)
        user = update.effective_user
        u_disp = user.username or user.first_name or "User"
        uid = str(user.id)
        status = await update.message.reply_text("🔍 Analyzing...")
        
        info = await fetch_token_info(text)
        if not info:
            await status.edit_text("❌ Token not found")
            return
        
        ca = text
        if info.get('source') == 'pumpfun':
            chain, sym = "SOL", info.get("symbol", "N/A")
            mc = info.get("marketCap", 0) or 0
        else:
            p = info.get("pair", {})
            chain = get_chain_name(p.get("chainId", ""))
            sym = p.get("baseToken", {}).get("symbol", "N/A")
            mc = p.get("marketCap", 0) or 0
        
        if uid not in user_calls_data: user_calls_data[uid] = {"username": u_disp, "calls": []}
        user_calls_data[uid]["calls"].append({
            "ca": ca, "timestamp": datetime.now(timezone.utc).timestamp(),
            "mc_at_call": mc, "current_mc": mc, "network": chain, "symbol": sym})
        save_data()
        
        if ca not in token_initial_data:
            token_initial_data[ca] = {
                "initial_mc": mc, "timestamp": datetime.now(timezone.utc).timestamp(),
                "user": u_disp, "user_id": user.id, "network": net,
                "chain_name": chain, "symbol": sym}
            x_return_alerts[ca] = {str(m): False for m in X_RETURN_MILESTONES}
            save_data()
        
        msg, kb = await format_token_message(info, ca, net, u_disp, user.id)
        try:
            await status.delete()
            await update.message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"Error: {e}")
            await status.edit_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

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
    net = detect_network_from_ca(ca) or "solana"
    d = token_initial_data.get(ca, {})
    msg, kb = await format_token_message(info, ca, net, d.get("user", "User"), d.get("user_id", 0))
    await query.edit_message_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def show_leaderboard(message, context, period='1d'):
    if not user_calls_data:
        await message.reply_text("📊 No data yet.", parse_mode=ParseMode.HTML)
        return
    
    lb, meds, rets, h2x, bests = [], [], [], [], []
    g_calls = 0
    
    for uid in user_calls_data:
        s = get_user_period_stats(uid, period)
        if s and s["total_calls"] >= 1:
            uname = user_calls_data[uid].get("username", f"User_{uid[-6:]}")
            lb.append({"uid": uid, "name": uname, "stats": s})
            g_calls += s["total_calls"]
            meds.append(s["median_return"])
            rets.append(s["avg_return"])
            h2x.append(s["hit_rate_2x"])
            if s['best_call_symbol']:
                bests.append({
                    "name": uname, "sym": s['best_call_symbol'],
                    "ret": s['best_call_return'],
                    "net": user_calls_data[uid]["calls"][-1].get("network", "SOL")})
    
    if not lb:
        await message.reply_text("📊 No data in this period.", parse_mode=ParseMode.HTML)
        return
    
    lb.sort(key=lambda x: x["stats"]["total_points"], reverse=True)
    avg_med = round(sum(meds)/len(meds), 2) if meds else 0
    avg_ret = round(sum(rets)/len(rets), 2) if rets else 0
    avg_h2x = round(sum(h2x)/len(h2x), 1) if h2x else 0
    best = max(bests, key=lambda x: x["ret"]) if bests else None
    
    msg = f"🏆 <b>Top Callers</b>\n"
    msg += f"  🏆 {escape_html(lb[0]['name'])} [{lb[0]['stats']['total_points']} pts]\n\n"
    msg += f"📊 <b>Group Stats</b>\n"
    msg += f"  Period: {period}\n"
    msg += f"  Calls: {g_calls}\n"
    msg += f"  Hit Rate: {avg_h2x}% ≥2x\n"
    msg += f"  Median: {avg_med}x\n"
    msg += f"  Return: {avg_ret}x (Avg: {avg_ret}x)\n"
    
    if best:
        flag = {"SOL": "🟢", "ETH": "🔷", "BSC": "🟡", "BASE": "🔵", "HOOD": "🟠"}.get(best["net"], "")
        msg += f"\n  {flag} #{escape_html(best['sym'])} • {escape_html(best['name'])} [{best['ret']}x]"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1D", callback_data="lb_1d"),
         InlineKeyboardButton("1W", callback_data="lb_1w"),
         InlineKeyboardButton("2W", callback_data="lb_2w"),
         InlineKeyboardButton("1M", callback_data="lb_1m")],
        [InlineKeyboardButton("🔄", callback_data=f"lb_refresh_{period}")]
    ])
    try: await message.edit_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML)
    except: await message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML)

async def leaderboard_command(update: Update, context):
    context.user_data['lb_period'] = '1d'
    await show_leaderboard(update.message, context, '1d')

async def leaderboard_period_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    p = query.data.replace("lb_", "")
    context.user_data['lb_period'] = p
    await show_leaderboard(query.message, context, p)

async def stats_command(update: Update, context):
    uid = str(update.effective_user.id)
    s = get_user_period_stats(uid, '1d')
    if not s:
        await update.message.reply_text(" No calls today!", parse_mode=ParseMode.HTML)
        return
    uname = escape_html(update.effective_user.username or update.effective_user.first_name or "User")
    msg = f"📊 <b>YOUR STATS</b>\nPeriod: 1d\n\n👤 <b>{uname}</b>\n\n"
    msg += f"  Total Calls: {s['total_calls']}\n"
    msg += f"  Win Rate: {s['hit_rate']}%\n"
    msg += f"  Hit Rate ≥2x: {s['hit_rate_2x']}%\n"
    msg += f"  Median: {s['median_return']}x\n"
    msg += f"  Avg Return: +{s['avg_return']}%\n"
    msg += f"  Points: {s['total_points']}\n"
    if s['best_call_symbol']:
        msg += f"\n  📈 Best: #{s['best_call_symbol']} [{s['best_call_return']}x]"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def trending_command(update: Update, context):
    await update.message.reply_text("📊 Fetching trending...")
    tokens = await fetch_trending_pumpfun()
    if not tokens:
        await update.message.reply_text("❌ No tokens found")
        return
    msg = "🔥 <b>TOP 10 PUMP.FUN</b>\n\n"
    for i, t in enumerate(tokens[:10], 1):
        try:
            sym = t.get("symbol", "N/A")
            name = t.get("name", "N/A")
            mc = t.get("marketCap", 0) or 0
            mint = t.get("mint", "")
            msg += f"{i}. <b>{sym}</b> - {name}\n💰 MC: ${mc:,.0f}\n🔗 <a href='https://pump.fun/{mint}'>View</a>\n\n"
        except: continue
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def newpairs_command(update: Update, context):
    await update.message.reply_text("🆕 Fetching new pairs...")
    pairs = await fetch_new_pairs()
    if not pairs:
        await update.message.reply_text("❌ No pairs found")
        return
    msg = "🆕 <b>NEW PAIRS - LAST 24H</b>\n\n"
    for i, pair in enumerate(pairs[:10], 1):
        try:
            base = pair.get("baseToken", {})
            sym = base.get("symbol", "N/A")
            name = base.get("name", "N/A")
            chain = pair.get("chainId", "").upper()
            liq = pair.get("liquidity", {}).get("usd", 0) or 0
            vol = pair.get("volume", {}).get("h24", 0) or 0
            url = pair.get("url", "")
            msg += f"{i}. <b>{sym}</b> - {name}\n🌐 {chain}\n💧 Liq: ${liq:,.0f} | Vol: ${vol:,.0f}\n <a href='{url}'>View</a>\n\n"
        except: continue
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def migrations_command(update: Update, context):
    await update.message.reply_text("⭐ Fetching migrations...")
    migrations = await fetch_graduated_tokens()
    if not migrations:
        await update.message.reply_text("❌ No migrations found")
        return
    msg = "⭐ <b>GRADUATED - RAYDIUM</b>\n\n"
    for i, pair in enumerate(migrations[:8], 1):
        try:
            base = pair.get("baseToken", {})
            sym = base.get("symbol", "N/A")
            name = base.get("name", "N/A")
            liq = pair.get("liquidity", {}).get("usd", 0) or 0
            vol = pair.get("volume", {}).get("h24", 0) or 0
            mc = pair.get("marketCap", 0) or 0
            url = pair.get("url", "")
            msg += f"{i}. <b>{sym}</b> - {name}\n💰 MC: ${mc:,.0f}\n💧 Liq: ${liq:,.0f} | Vol: ${vol:,.0f}\n🔗 <a href='{url}'>View</a>\n\n"
        except: continue
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def monitor_command(update: Update, context):
    msg = "📱 <b>MONITORED INFLUENCERS:</b>\n\n"
    for acc, name in INFLUENCER_ACCOUNTS.items():
        msg += f"{name} - @{acc}\n"
    msg += f"\nTotal: {len(INFLUENCER_ACCOUNTS)} accounts"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def influencers_command(update: Update, context):
    await monitor_command(update, context)

async def pnl_command(update: Update, context):
    if not context.args:
        await update.message.reply_text("Usage: <code>/pnl &lt;CA&gt;</code>", parse_mode=ParseMode.HTML)
        return
    ca = context.args[0].strip()
    status = await update.message.reply_text("🎨 Generating PNL card...")
    info = await fetch_token_info(ca)
    if not info:
        await status.edit_text("❌ Token not found")
        return
    
    # Garante que token_initial_data tenha chain_name
    if ca not in token_initial_data:
        net = detect_network_from_ca(ca) or "solana"
        if info.get('source') == 'pumpfun':
            chain, sym, mc = "SOL", info.get("symbol", "N/A"), info.get("marketCap", 0) or 0
        else:
            p = info.get("pair", {})
            chain = get_chain_name(p.get("chainId", ""))
            sym = p.get("baseToken", {}).get("symbol", "N/A")
            mc = p.get("marketCap", 0) or 0
        token_initial_data[ca] = {
            "initial_mc": mc, "timestamp": datetime.now(timezone.utc).timestamp(),
            "user": "System", "user_id": 0, "network": net,
            "chain_name": chain, "symbol": sym}
    
    settings = get_pnl_settings(update.effective_chat.id)
    img_buf = create_pnl_card(info, ca, detect_network_from_ca(ca), settings)
    
    await status.delete()
    sym = info.get('symbol', 'N/A') if info.get('source')=='pumpfun' else info.get('pair',{}).get('baseToken',{}).get('symbol','N/A')
    await update.message.reply_photo(photo=img_buf, caption=f"📊 PNL Card - #{escape_html(sym)}")

async def pnlbg_command(update: Update, context):
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("Reply to an image with <code>/pnlbg</code>", parse_mode=ParseMode.HTML)
        return
    photo = update.message.reply_to_message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    bg_path = f"pnl_bg_{update.effective_chat.id}.png"
    await file.download_to_drive(bg_path)
    
    cid = str(update.effective_chat.id)
    if cid not in pnl_settings: pnl_settings[cid] = {"theme": "dark", "color": "green"}
    pnl_settings[cid]["custom_bg"] = bg_path
    save_data()
    await update.message.reply_text("✅ Custom background set!")

async def pnltheme_command(update: Update, context):
    if not context.args or context.args[0].lower() not in ["dark", "light"]:
        await update.message.reply_text("Usage: <code>/pnltheme dark|light</code>", parse_mode=ParseMode.HTML)
        return
    cid = str(update.effective_chat.id)
    if cid not in pnl_settings: pnl_settings[cid] = {"theme": "dark", "color": "green"}
    pnl_settings[cid]["theme"] = context.args[0].lower()
    save_data()
    await update.message.reply_text(f"✅ Theme set to: {context.args[0].lower()}")

async def pnlcolor_command(update: Update, context):
    if not context.args or context.args[0].lower() not in PNL_COLORS:
        await update.message.reply_text(f"Usage: <code>/pnlcolor &lt;color&gt;</code>\nOptions: {', '.join(PNL_COLORS.keys())}", parse_mode=ParseMode.HTML)
        return
    cid = str(update.effective_chat.id)
    if cid not in pnl_settings: pnl_settings[cid] = {"theme": "dark", "color": "green"}
    pnl_settings[cid]["color"] = context.args[0].lower()
    save_data()
    await update.message.reply_text(f"✅ Color set to: {context.args[0].lower()}")

async def monitor_twitter_loop(bot):
    logger.info("🐦 Starting Twitter monitoring...")
    while True:
        try:
            for account in MONITOR_ACCOUNTS:
                try:
                    tweets = await fetch_latest_tweets(account)
                    for tweet in tweets:
                        tweet_id = tweet["link"]
                        if tweet_id in processed_tweets: continue
                        processed_tweets.add(tweet_id)
                        
                        addresses = extract_contract_addresses(tweet["text"])
                        all_cas = addresses.get("solana", []) + addresses.get("ethereum", [])
                        text_lower = tweet["text"].lower()
                        has_keyword = any(kw in text_lower for kw in KEYWORD_ALERTS)
                        
                        if all_cas or has_keyword:
                            for ca in all_cas[:2]:
                                if ca in alerted_tokens: continue
                                token_info = await fetch_token_info(ca)
                                msg = format_twitter_alert(account, tweet["text"], tweet["link"], ca, token_info)
                                try:
                                    await bot.send_message(chat_id=CHAT_ID, text=msg,
                                        parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                                    alerted_tokens.add(ca)
                                    logger.info(f"✅ Twitter alert sent: {ca[:10]}...")
                                except Exception as e:
                                    logger.error(f"Error sending alert: {e}")
                                await asyncio.sleep(2)
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Error monitoring @{account}: {e}")
                    continue
            
            if len(processed_tweets) > 1000: processed_tweets.clear()
            await asyncio.sleep(180)
        except Exception as e:
            logger.error(f"Error in Twitter loop: {e}")
            await asyncio.sleep(60)

async def monitor_newpairs_loop(bot):
    logger.info("🆕 Starting new pairs monitoring...")
    alerted_pairs = set()
    while True:
        try:
            pairs = await fetch_new_pairs()
            for pair in pairs:
                try:
                    base = pair.get("baseToken", {})
                    mint = base.get("address", "")
                    sym = base.get("symbol", "N/A")
                    chain = pair.get("chainId", "")
                    if chain not in ["solana", "ethereum", "bsc", "base"]: continue
                    liq = pair.get("liquidity", {}).get("usd", 0) or 0
                    vol = pair.get("volume", {}).get("h24", 0) or 0
                    mc = pair.get("marketCap", 0) or 0
                    url = pair.get("url", "")
                    
                    if mint and mint not in alerted_pairs and liq > 5000 and vol > 10000:
                        msg = (f"🆕 <b>NEW PAIR!</b>\n\n🔥 <b>{escape_html(sym)}</b>\n"
                               f"🌐 {chain.upper()}\n MC: ${mc:,.0f}\n Liq: ${liq:,.0f}\n"
                               f"📈 Vol: ${vol:,.0f}\n\n🔗 <a href='{url}'>View</a>\n\n<i>⚠️ DYOR</i>")
                        await bot.send_message(chat_id=CHAT_ID, text=msg,
                            parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                        alerted_pairs.add(mint)
                        logger.info(f"🆕 New pair: {sym}")
                        await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Error processing pair: {e}")
                    continue
            await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"Error in new pairs loop: {e}")
            await asyncio.sleep(60)

async def monitor_migrations_loop(bot):
    logger.info("⭐ Starting migrations monitoring...")
    while True:
        try:
            migrations = await fetch_graduated_tokens()
            for pair in migrations:
                try:
                    base = pair.get("baseToken", {})
                    mint = base.get("address", "")
                    sym = base.get("symbol", "N/A")
                    if mint and mint not in alerted_tokens:
                        liq = pair.get("liquidity", {}).get("usd", 0) or 0
                        vol = pair.get("volume", {}).get("h24", 0) or 0
                        mc = pair.get("marketCap", 0) or 0
                        url = pair.get("url", "")
                        msg = (f"⭐ <b>GRADUATION!</b>\n\n <b>{escape_html(sym)}</b>\n"
                               f"💰 MC: ${mc:,.0f}\n💧 Liq: ${liq:,.0f}\n📈 Vol: ${vol:,.0f}\n\n"
                               f"🔗 <a href='{url}'>DexScreener</a>\n\n<i>️ DYOR</i>")
                        await bot.send_message(chat_id=CHAT_ID, text=msg,
                            parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                        alerted_tokens.add(mint)
                        logger.info(f"⭐ Graduation: {sym}")
                        await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Error migration: {e}")
                    continue
            await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"Error in migrations loop: {e}")
            await asyncio.sleep(60)

async def x_return_monitor_loop(bot):
    """Loop de monitoramento de X-Return"""
    logger.info("🚀 Starting X-Return monitoring...")
    while True:
        try:
            await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"Error in X-Return loop: {e}")
            await asyncio.sleep(60)

def main():
    logger.info("🚀 Starting bot...")
    load_data()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.bot_data['x_alerts_enabled'] = True
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("lb", leaderboard_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("pnl", pnl_command))
    app.add_handler(CommandHandler("pnlbg", pnlbg_command))
    app.add_handler(CommandHandler("pnltheme", pnltheme_command))
    app.add_handler(CommandHandler("pnlcolor", pnlcolor_command))
    app.add_handler(CommandHandler("xalerts", xalerts_command))
    app.add_handler(CommandHandler("trending", trending_command))
    app.add_handler(CommandHandler("migrations", migrations_command))
    app.add_handler(CommandHandler("newpairs", newpairs_command))
    app.add_handler(CommandHandler("monitor", monitor_command))
    app.add_handler(CommandHandler("influencers", influencers_command))
    
    app.add_handler(CallbackQueryHandler(leaderboard_period_callback, pattern="^lb_(1d|1w|2w|1m)$"))
    app.add_handler(CallbackQueryHandler(refresh_callback, pattern="^refresh:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    async def post_init(application):
        bot = application.bot
        asyncio.create_task(monitor_twitter_loop(bot))
        asyncio.create_task(monitor_newpairs_loop(bot))
        asyncio.create_task(monitor_migrations_loop(bot))
        asyncio.create_task(x_return_monitor_loop(bot))
        logger.info("✅ Monitores iniciados!")
    
    app.post_init = post_init
    
    logger.info("✅ Bot running with all features!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
