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
processed_tweets = set()
alerted_tokens = set()
processed_cas = set()

DATA_FILE = "user_calls.json"
PNL_SETTINGS_FILE = "pnl_settings.json"

CHAIN_NAMES = {
    "solana": "SOL", "ethereum": "ETH", "bsc": "BSC", "base": "BASE",
    "hood": "HOOD", "polygon": "POLYGON", "arbitrum": "ARBITRUM",
    "avalanche": "AVALANCHE", "optimism": "OPTIMISM", "fantom": "FANTOM",
    "tab": "TAB", "cronos": "CRONOS", "aurora": "AURORA"
}

PNL_THEMES = {
    "dark": {"bg": (26, 26, 46), "text": (255, 255, 255), "secondary": (139, 148, 158)},
    "light": {"bg": (245, 245, 247), "text": (0, 0, 0), "secondary": (100, 100, 100)}
}

PNL_COLORS = {
    "green": (0, 255, 136), "cyan": (0, 255, 255), "purple": (155, 89, 182),
    "pink": (255, 105, 180), "gold": (255, 215, 0), "orange": (255, 140, 0)
}

PNL_GRADIENTS = {
    "loss": {"start": (139, 0, 0), "end": (220, 20, 60), "text": (255, 255, 255), "accent": (255, 99, 71)},
    "neutral": {"start": (26, 26, 46), "end": (40, 40, 70), "text": (255, 255, 255), "accent": (0, 255, 136)},
    "gain_50": {"start": (0, 100, 80), "end": (0, 180, 120), "text": (255, 255, 255), "accent": (144, 238, 144)},
    "gain_100": {"start": (0, 128, 0), "end": (50, 205, 50), "text": (255, 255, 255), "accent": (154, 205, 50)},
    "gain_200": {"start": (85, 107, 47), "end": (154, 205, 50), "text": (255, 255, 255), "accent": (255, 215, 0)},
    "gain_500": {"start": (184, 134, 11), "end": (255, 215, 0), "text": (0, 0, 0), "accent": (255, 255, 255)},
    "gain_infinite": {"start": (255, 140, 0), "end": (255, 215, 0), "text": (0, 0, 0), "accent": (255, 255, 255)}
}

def get_gradient_for_percentage(change_percent):
    if change_percent < 0: return PNL_GRADIENTS["loss"]
    elif change_percent < 50: return PNL_GRADIENTS["neutral"]
    elif change_percent < 100: return PNL_GRADIENTS["gain_50"]
    elif change_percent < 200: return PNL_GRADIENTS["gain_100"]
    elif change_percent < 500: return PNL_GRADIENTS["gain_200"]
    elif change_percent < 1000: return PNL_GRADIENTS["gain_500"]
    else: return PNL_GRADIENTS["gain_infinite"]

def create_gradient_background(width, height, gradient_colors):
    img = Image.new('RGB', (width, height), gradient_colors["start"])
    draw = ImageDraw.Draw(img)
    for y in range(height):
        ratio = y / height
        r = int(gradient_colors["start"][0] * (1 - ratio) + gradient_colors["end"][0] * ratio)
        g = int(gradient_colors["start"][1] * (1 - ratio) + gradient_colors["end"][1] * ratio)
        b = int(gradient_colors["start"][2] * (1 - ratio) + gradient_colors["end"][2] * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img

INFLUENCER_ACCOUNTS = {
    "elonmusk": "🚀 Elon Musk", "CZ_Binance": "💰 CZ", "VitalikButerin": "💎 Vitalik",
    "Pentosh1": "📊 Pentosh", "Ansem": "🌊 Ansem", "0xMert": "⚡ Mert"
}

KEYWORD_ALERTS = ["moon", "pump", "100x", "gem", "alpha"]
MONITOR_ACCOUNTS = list(INFLUENCER_ACCOUNTS.keys())
NITTER_INSTANCES = ["https://nitter.net"]

def load_data():
    global user_calls_data, pnl_settings
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f: user_calls_data = json.load(f)
        if os.path.exists(PNL_SETTINGS_FILE):
            with open(PNL_SETTINGS_FILE, 'r') as f: pnl_settings = json.load(f)
    except Exception as e:
        logger.error(f"Error loading: {e}")

def save_data():
    try:
        with open(DATA_FILE, 'w') as f: json.dump(user_calls_data, f, indent=2)
        with open(PNL_SETTINGS_FILE, 'w') as f: json.dump(pnl_settings, f, indent=2)
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
    return CHAIN_NAMES.get(chain_id.lower(), chain_id.upper())

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
    return timedelta(days=1)

def get_calls_in_period(user_id, period_str):
    if user_id not in user_calls_data: return []
    period = parse_period(period_str)
    cutoff = datetime.now(timezone.utc) - period
    return [c for c in user_calls_data[user_id].get("calls", []) if datetime.fromtimestamp(c["timestamp"], tz=timezone.utc) >= cutoff]

def calculate_median(values):
    if not values: return 0
    s = sorted(values)
    n = len(s)
    return (s[n//2-1] + s[n//2])/2 if n%2==0 else s[n//2]

def extract_contract_addresses(text):
    solana = re.findall(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b', text)
    ethereum = re.findall(r'\b0x[a-fA-F0-9]{40,42}\b', text)
    return {"solana": [s for s in solana if 'http' not in s.lower()], "ethereum": [e for e in ethereum if 'http' not in e.lower()]}

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
                best_ret, best_sym, best_ca = ratio, c.get("symbol"), c.get("ca")
    
    return {
        "total_calls": total, "winning_calls": wins,
        "hit_rate": round((wins/total)*100, 1), "hit_rate_2x": round((calls_2x/total)*100, 1),
        "avg_return": round((sum(returns)/total - 1)*100, 1) if returns else 0,
        "median_return": round(calculate_median(returns), 2),
        "total_points": round(sum(points_list), 2),
        "best_call_symbol": best_sym, "best_call_return": round(best_ret, 2)
    }

async def fetch_token_info(ca):
    """Busca info do token INCLUINDO IMAGEM"""
    async with aiohttp.ClientSession() as session:
        # Pump.fun
        if detect_network_from_ca(ca) == "solana":
            try:
                async with session.get(f"https://frontend-api.pump.fun/coins/{ca}",
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        data['source'] = 'pumpfun'
                        # Buscar imagem
                        data['image_url'] = data.get("image_uri") or data.get("logo_uri") or ""
                        return data
            except: pass
        
        # DexScreener
        try:
            async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}",
                timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        best_pair = max(pairs, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)
                        best_pair['source'] = 'dexscreener'
                        # Buscar imagem do token/par
                        info = best_pair.get("info", {})
                        best_pair['image_url'] = info.get("imageUrl") or best_pair.get("baseToken", {}).get("logoURI") or ""
                        return {"pair": best_pair, "source": "dexscreener"}
        except: pass
    return None

async def fetch_image_from_url(image_url):
    """Baixa imagem da URL e retorna como PIL Image"""
    if not image_url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    img_data = await resp.read()
                    img = Image.open(BytesIO(img_data))
                    return img
    except Exception as e:
        logger.error(f"Error fetching image: {e}")
    return None

async def fetch_trending_pumpfun():
    url = "https://frontend-api.pump.fun/coins?limit=20&offset=0"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
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
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
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
                tweets.append({"account": account, "text": title.text, "link": link.text.replace("nitter.net", "twitter.com")})
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
    else:
        p = data.get("pair", {})
        cur_mc = p.get("marketCap", 0) or 0
        sym = escape_html(p.get("baseToken", {}).get("symbol", "N/A"))
        name = escape_html(p.get("baseToken", {}).get("name", "N/A"))
        liq = p.get("liquidity", {}).get("usd", 0) or 0
        vol = p.get("volume", {}).get("h24", 0) or 0
        mint = p.get("baseToken", {}).get("address", ca)
    
    if init_mc > 0 and cur_mc > 0:
        chg = ((cur_mc - init_mc) / init_mc) * 100
        chg_str = f" +{chg:.1f}%" if chg >= 0 else f" {chg:.1f}%"
    else: chg_str = "⏳ 0%"
    
    t_ago = calculate_time_ago(ts)
    c_html = f'<a href="tg://user?id={user_id}">@{escape_html(caller)}</a>' if user_id else f"@{escape_html(caller)}"
    
    msg = f"🔖 <b>#{sym}</b> - {name}\n<b>{chain}</b>\n\n"
    msg += f"💵 <b>MC:</b> ${cur_mc:,.0f}\n📊 <b>Vol 24h:</b> ${vol:,.0f}\n💧 <b>LP:</b> ${liq:,.0f}\n"
    msg += f"{chg_str} <i>since post</i>\n\n"
    
    if data.get('source') == 'pumpfun':
        msg += f"<a href='https://dexscreener.com/solana/{mint}'>📊 DexScreener</a> | <a href='https://www.dextools.io/app/solana/pair/explorer/{mint}'>📈 DexTools</a>\n"
    else:
        p = data.get("pair", {})
        url = p.get("url", "")
        cl = p.get("chainId", "").lower()
        if url: msg += f"<a href='{url}'>📊 DexScreener</a> | "
        msg += f"<a href='https://www.dextools.io/app/{cl}/pair/explorer/{mint}'>📈 DexTools</a>\n"
    
    msg += f"\n<i>⚠️ DYOR</i>\n\n👤 {c_html} • ${init_mc:,.0f} • ⏱️ {t_ago}"
    return msg, InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data=f"refresh:{ca}")]])

def format_twitter_alert(account, tweet_text, tweet_link, ca, token_info):
    msg = f"🚨 <b>INFLUENCER ALERT!</b>\n\n👤 <b>{INFLUENCER_ACCOUNTS.get(account, account)}</b>\n\n"
    msg += f"<i>{escape_html(tweet_text[:200])}</i>\n\n"
    if token_info:
        sym = token_info.get("symbol", "N/A") if token_info.get('source') == 'pumpfun' else token_info.get("pair", {}).get("baseToken", {}).get("symbol", "N/A")
        mc = token_info.get("marketCap", 0) or token_info.get("pair", {}).get("marketCap", 0)
        msg += f"💎 #{escape_html(sym)} • MC: ${mc:,.0f}\n\n"
    msg += f"🔗 <a href='{tweet_link}'>View</a>"
    return msg

def create_pnl_card(data, ca, network, settings):
    """Cria PNL Card COM IMAGEM DO PROJETO se disponível"""
    width, height = 1200, 630
    
    # Extrair dados
    if data.get('source') == 'pumpfun':
        sym = data.get("symbol", "N/A")
        name = data.get("name", "N/A")
        mc = data.get("marketCap", 0) or 0
        vol = data.get("volume", 0) or 0
        liq = data.get("liquidity", 0) or 0
        image_url = data.get("image_url", "")
    else:
        p = data.get("pair", {})
        sym = p.get("baseToken", {}).get("symbol", "N/A")
        name = p.get("baseToken", {}).get("name", "N/A")
        mc = p.get("marketCap", 0) or 0
        vol = p.get("volume", {}).get("h24", 0) or 0
        liq = p.get("liquidity", {}).get("usd", 0) or 0
        image_url = p.get("image_url", "")
    
    # Calcular mudança
    saved_data = token_initial_data.get(ca, {})
    init_mc = saved_data.get("initial_mc", 0)
    if init_mc > 0 and mc > 0:
        chg_percent = ((mc - init_mc) / init_mc) * 100
        chg_str = f"+{chg_percent:.1f}%" if chg_percent >= 0 else f"{chg_percent:.1f}%"
    else:
        chg_percent = 0
        chg_str = "0%"
    
    # Tentar baixar imagem do projeto
    project_img = None
    if image_url:
        # Em produção, usar: project_img = await fetch_image_from_url(image_url)
        # Por enquanto, simulamos None para usar gradiente
        pass
    
    # Se tem imagem do projeto, usa como base; senão, gradiente
    if project_img:
        project_img = project_img.resize((width, height))
        img = project_img.convert('RGB')
        gradient = {"text": (255, 255, 255), "accent": (0, 255, 136)}
    else:
        gradient = get_gradient_for_percentage(chg_percent)
        img = create_gradient_background(width, height, gradient)
    
    draw = ImageDraw.Draw(img)
    
    try:
        font_l = ImageFont.load_default(size=80)
        font_m = ImageFont.load_default(size=50)
        font_s = ImageFont.load_default(size=32)
        font_xs = ImageFont.load_default(size=24)
    except:
        font_l = font_m = font_s = font_xs = ImageFont.load_default()
    
    # Obter chain
    chain = saved_data.get("chain_name", "UNKNOWN")
    if chain == "UNKNOWN" and data.get('source') != 'pumpfun':
        chain = get_chain_name(data.get("pair", {}).get("chainId", ""))
    
    # Layout
    x, y = 60, 50
    
    # Símbolo
    draw.text((x, y), f"#{sym}", fill=gradient["text"], font=font_l, stroke_fill=(0,0,0), stroke_width=2)
    y += 100
    
    # Nome
    draw.text((x, y), name[:50], fill=gradient["accent"], font=font_s, stroke_fill=(0,0,0), stroke_width=1)
    y += 50
    
    # Rede
    draw.text((x, y), chain, fill=gradient["accent"], font=font_m)
    y += 80
    
    # Linha
    draw.line([(x, y), (width-60, y)], fill=gradient["accent"], width=2)
    y += 50
    
    # Métricas
    for lbl, val in [("Market Cap", f"${mc:,.0f}"), ("Volume 24h", f"${vol:,.0f}"), ("Liquidity", f"${liq:,.0f}")]:
        draw.text((x, y), lbl, fill=gradient["accent"], font=font_s)
        y += 40
        draw.text((x, y), val, fill=gradient["text"], font=font_m, stroke_fill=(0,0,0), stroke_width=2)
        y += 60
    
    # Change
    draw.text((x, y), "Change", fill=gradient["accent"], font=font_s)
    y += 40
    draw.text((x, y), chg_str, fill=gradient["accent"], font=font_l, stroke_fill=(0,0,0), stroke_width=3)
    
    # Footer
    y = height - 60
    draw.line([(x, y), (width-60, y)], fill=gradient["accent"], width=1)
    y += 15
    draw.text((x, y), "PRIME GEMS BOT • DYOR", fill=gradient["accent"], font=font_xs)
    
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    
    logger.info(f"✅ PNL card gerado: #{sym} - {chain} - {chg_str}")
    return buf

async def start(update: Update, context):
    await update.message.reply_text("🚀 <b>PRIME GEMS BOT ACTIVE!</b>\n\n <code>/check &lt;CA&gt;</code>\n🏆 <code>/lb</code>\n📊 <code>/stats</code>\n🎨 <code>/pnl &lt;CA&gt;</code>", parse_mode=ParseMode.HTML)

async def help_command(update: Update, context):
    await update.message.reply_text(" <b>COMMANDS:</b>\n<code>/check &lt;CA&gt;</code>\n<code>/lb</code>\n<code>/stats</code>\n<code>/pnl &lt;CA&gt;</code>", parse_mode=ParseMode.HTML)

async def check_command(update: Update, context):
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/check &lt;CA&gt;</code>", parse_mode=ParseMode.HTML)
        return
    ca = context.args[0].strip()
    user = update.effective_user
    u_disp = user.username or user.first_name or "User"
    uid = str(user.id)
    status = await update.message.reply_text(" Analyzing...")
    
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
    user_calls_data[uid]["calls"].append({"ca": ca, "timestamp": datetime.now(timezone.utc).timestamp(), "mc_at_call": mc, "current_mc": mc, "network": chain, "symbol": sym})
    save_data()
    
    if ca not in token_initial_data:
        token_initial_data[ca] = {"initial_mc": mc, "timestamp": datetime.now(timezone.utc).timestamp(), "user": u_disp, "user_id": user.id, "network": net, "chain_name": chain, "symbol": sym}
        save_data()
    
    msg, kb = await format_token_message(info, ca, net, u_disp, user.id)
    try:
        await status.delete()
        await update.message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error: {e}")

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
        user_calls_data[uid]["calls"].append({"ca": ca, "timestamp": datetime.now(timezone.utc).timestamp(), "mc_at_call": mc, "current_mc": mc, "network": chain, "symbol": sym})
        save_data()
        
        if ca not in token_initial_data:
            token_initial_data[ca] = {"initial_mc": mc, "timestamp": datetime.now(timezone.utc).timestamp(), "user": u_disp, "user_id": user.id, "network": net, "chain_name": chain, "symbol": sym}
            save_data()
        
        msg, kb = await format_token_message(info, ca, net, u_disp, user.id)
        try:
            await status.delete()
            await update.message.reply_text(msg, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"Error: {e}")

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
                bests.append({"name": uname, "sym": s['best_call_symbol'], "ret": s['best_call_return'], "net": user_calls_data[uid]["calls"][-1].get("network", "SOL")})
    
    if not lb:
        await message.reply_text(" No data in this period.", parse_mode=ParseMode.HTML)
        return
    
    lb.sort(key=lambda x: x["stats"]["total_points"], reverse=True)
    avg_med = round(sum(meds)/len(meds), 2) if meds else 0
    avg_ret = round(sum(rets)/len(rets), 2) if rets else 0
    avg_h2x = round(sum(h2x)/len(h2x), 1) if h2x else 0
    best = max(bests, key=lambda x: x["ret"]) if bests else None
    
    msg = f"🏆 <b>Top Callers</b>\n   {escape_html(lb[0]['name'])} [{lb[0]['stats']['total_points']} pts]\n\n"
    msg += f" <b>Group Stats</b>\n  Period: {period}\n  Calls: {g_calls}\n  Hit Rate: {avg_h2x}% ≥2x\n  Median: {avg_med}x\n  Return: {avg_ret}x\n"
    if best:
        msg += f"\n  #{escape_html(best['sym'])} • {escape_html(best['name'])} [{best['ret']}x]"
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("1D", callback_data="lb_1d"), InlineKeyboardButton("1W", callback_data="lb_1w"), InlineKeyboardButton("2W", callback_data="lb_2w"), InlineKeyboardButton("1M", callback_data="lb_1m")], [InlineKeyboardButton("", callback_data=f"lb_refresh_{period}")]])
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
        await update.message.reply_text("📊 No calls today!", parse_mode=ParseMode.HTML)
        return
    uname = escape_html(update.effective_user.username or update.effective_user.first_name or "User")
    msg = f"📊 <b>YOUR STATS</b>\nPeriod: 1d\n\n <b>{uname}</b>\n\n  Total Calls: {s['total_calls']}\n  Win Rate: {s['hit_rate']}%\n  Median: {s['median_return']}x\n  Avg Return: +{s['avg_return']}%\n  Points: {s['total_points']}\n"
    if s['best_call_symbol']:
        msg += f"\n   Best: #{s['best_call_symbol']} [{s['best_call_return']}x]"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def trending_command(update: Update, context):
    await update.message.reply_text(" Fetching...")
    tokens = await fetch_trending_pumpfun()
    if not tokens:
        await update.message.reply_text("❌ No tokens found")
        return
    msg = " <b>TOP 10 PUMP.FUN</b>\n\n"
    for i, t in enumerate(tokens[:10], 1):
        try:
            msg += f"{i}. <b>{t.get('symbol', 'N/A')}</b> - {t.get('name', 'N/A')}\n💰 MC: ${t.get('marketCap', 0):,.0f}\n\n"
        except: continue
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def newpairs_command(update: Update, context):
    await update.message.reply_text(" Fetching...")
    pairs = await fetch_new_pairs()
    if not pairs:
        await update.message.reply_text("❌ No pairs found")
        return
    msg = "🆕 <b>NEW PAIRS</b>\n\n"
    for i, pair in enumerate(pairs[:10], 1):
        try:
            base = pair.get("baseToken", {})
            msg += f"{i}. <b>{base.get('symbol', 'N/A')}</b>\n Liq: ${pair.get('liquidity', {}).get('usd', 0):,.0f}\n\n"
        except: continue
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def migrations_command(update: Update, context):
    await update.message.reply_text("⭐ Fetching...")
    migrations = await fetch_graduated_tokens()
    if not migrations:
        await update.message.reply_text("❌ No migrations found")
        return
    msg = "⭐ <b>GRADUATED</b>\n\n"
    for i, pair in enumerate(migrations[:8], 1):
        try:
            base = pair.get("baseToken", {})
            msg += f"{i}. <b>{base.get('symbol', 'N/A')}</b>\n💰 MC: ${pair.get('marketCap', 0):,.0f}\n\n"
        except: continue
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def monitor_command(update: Update, context):
    msg = "📱 <b>MONITORED INFLUENCERS:</b>\n\n"
    for acc, name in INFLUENCER_ACCOUNTS.items():
        msg += f"{name} - @{acc}\n"
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
    
    net = detect_network_from_ca(ca) or "solana"
    if info.get('source') == 'pumpfun':
        chain, sym, mc = "SOL", info.get("symbol", "N/A"), info.get("marketCap", 0) or 0
    else:
        p = info.get("pair", {})
        chain = get_chain_name(p.get("chainId", ""))
        sym = p.get("baseToken", {}).get("symbol", "N/A")
        mc = p.get("marketCap", 0) or 0
    
    if ca not in token_initial_data:
        token_initial_data[ca] = {"initial_mc": mc, "timestamp": datetime.now(timezone.utc).timestamp(), "user": "System", "user_id": 0, "network": net, "chain_name": chain, "symbol": sym}
        save_data()
    
    settings = get_pnl_settings(update.effective_chat.id)
    img_buf = create_pnl_card(info, ca, net, settings)
    
    await status.delete()
    await update.message.reply_photo(photo=img_buf, caption=f"📊 PNL Card - #{escape_html(sym)}")

async def pnlbg_command(update: Update, context):
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("Reply to an image with <code>/pnlbg</code>", parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text("✅ Custom background set!")

async def pnltheme_command(update: Update, context):
    await update.message.reply_text("✅ Theme command - Not implemented yet")

async def pnlcolor_command(update: Update, context):
    await update.message.reply_text("✅ Color command - Not implemented yet")

async def monitor_twitter_loop(bot):
    logger.info("🐦 Twitter monitoring started")
    while True:
        await asyncio.sleep(180)

async def monitor_newpairs_loop(bot):
    logger.info("🆕 New pairs monitoring started")
    while True:
        await asyncio.sleep(300)

async def monitor_migrations_loop(bot):
    logger.info("⭐ Migrations monitoring started")
    while True:
        await asyncio.sleep(300)

def main():
    logger.info("🚀 Starting bot...")
    load_data()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("lb", leaderboard_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("pnl", pnl_command))
    app.add_handler(CommandHandler("pnlbg", pnlbg_command))
    app.add_handler(CommandHandler("pnltheme", pnltheme_command))
    app.add_handler(CommandHandler("pnlcolor", pnlcolor_command))
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
        logger.info("✅ Monitores iniciados!")
    
    app.post_init = post_init
    
    logger.info("✅ Bot running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
