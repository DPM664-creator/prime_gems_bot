import os
import asyncio
import aiohttp
import logging
import re
import json
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Variables not configured")

logger.info("✅ Prime Gems Bot started!")

# Dados dos tokens e calls
token_initial_data = {}
user_calls_data = {}

# Arquivo para salvar dados
DATA_FILE = "user_calls.json"

# Mapeamento de chainId para nome da rede
CHAIN_NAMES = {
    "solana": "SOL",
    "ethereum": "ETH",
    "bsc": "BSC",
    "base": "BASE",
    "hood": "HOOD",
    "polygon": "POLYGON",
    "arbitrum": "ARBITRUM",
    "avalanche": "AVALANCHE",
    "optimism": "OPTIMISM",
    "fantom": "FANTOM"
}

MONITOR_ACCOUNTS = ["OzzyManReview", "MaxCrypto__", "Ansem", "ClownIRL", "0xMert", "CryptoGodJohn", "HsakaTrades", "Pentosh1"]
NITTER_INSTANCES = ["https://nitter.net", "https://nitter.privacydev.net"]
processed_tweets = set()
alerted_tokens = set()
processed_cas = set()

def load_data():
    """Carrega dados do arquivo JSON"""
    global user_calls_data
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                user_calls_data = json.load(f)
            logger.info("📊 Dados carregados do arquivo")
    except Exception as e:
        logger.error(f"Erro ao carregar dados: {e}")
        user_calls_data = {}

def save_data():
    """Salva dados no arquivo JSON"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(user_calls_data, f, indent=2)
    except Exception as e:
        logger.error(f"Erro ao salvar dados: {e}")

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

def get_chain_name(chain_id):
    if not chain_id:
        return "UNKNOWN"
    chain_lower = chain_id.lower()
    return CHAIN_NAMES.get(chain_lower, chain_lower.upper())

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

def parse_period(period_str):
    """Converte string de período em timedelta"""
    period_str = period_str.lower().strip()
    
    if period_str.endswith('d'):
        days = int(period_str[:-1])
        return timedelta(days=days)
    elif period_str.endswith('w'):
        weeks = int(period_str[:-1])
        return timedelta(weeks=weeks)
    elif period_str.endswith('mo') or period_str.endswith('m'):
        months = int(period_str.replace('mo', '').replace('m', ''))
        return timedelta(days=months * 30)
    else:
        return timedelta(days=1)  # Default: 1d

def get_calls_in_period(user_id, period_str):
    """Retorna calls do usuário no período especificado"""
    if user_id not in user_calls_data:
        return []
    
    period = parse_period(period_str)
    now = datetime.now(timezone.utc)
    cutoff = now - period
    
    calls = []
    for call in user_calls_data[user_id].get("calls", []):
        call_time = datetime.fromtimestamp(call["timestamp"], tz=timezone.utc)
        if call_time >= cutoff:
            calls.append(call)
    
    return calls

def calculate_median(values):
    """Calcula mediana de uma lista de valores"""
    if not values:
        return 0
    
    sorted_values = sorted(values)
    n = len(sorted_values)
    mid = n // 2
    
    if n % 2 == 0:
        return (sorted_values[mid - 1] + sorted_values[mid]) / 2
    else:
        return sorted_values[mid]

def get_user_period_stats(user_id, period_str):
    """Calcula estatísticas do usuário para um período específico"""
    calls = get_calls_in_period(user_id, period_str)
    
    if not calls:
        return None
    
    total_calls = len(calls)
    returns = []
    points_list = []
    winning_calls = 0
    calls_2x_or_more = 0
    total_return = 0
    best_call = None
    best_call_return = 0
    
    for call in calls:
        mc_at_call = call.get("mc_at_call", 0)
        current_mc = call.get("current_mc", 0)
        ca = call.get("ca", "")
        
        if mc_at_call > 0 and current_mc > 0:
            return_ratio = current_mc / mc_at_call
            returns.append(return_ratio)
            total_return += (return_ratio - 1) * 100
            
            # Calcular pontos
            baseline = 1.5  # Baseline simplificado
            if return_ratio <= 0:
                points = -10
            else:
                points = math.log2(return_ratio / baseline)
            points_list.append(points)
            
            if return_ratio > 1:
                winning_calls += 1
            
            if return_ratio >= 2:
                calls_2x_or_more += 1
            
            # Melhor call
            if return_ratio > best_call_return:
                best_call_return = return_ratio
                best_call = ca
    
    hit_rate = (winning_calls / total_calls) * 100 if total_calls > 0 else 0
    hit_rate_2x = (calls_2x_or_more / total_calls) * 100 if total_calls > 0 else 0
    avg_return = total_return / total_calls if total_calls > 0 else 0
    median_return = calculate_median(returns) if returns else 0
    total_points = sum(points_list)
    avg_points = total_points / total_calls if total_calls > 0 else 0
    
    return {
        "total_calls": total_calls,
        "winning_calls": winning_calls,
        "hit_rate": round(hit_rate, 1),
        "hit_rate_2x": round(hit_rate_2x, 1),
        "avg_return": round(avg_return, 1),
        "median_return": round(median_return, 2),
        "total_points": round(total_points, 2),
        "avg_points": round(avg_points, 2),
        "best_call": best_call,
        "best_call_return": round(best_call_return, 2)
    }

async def start(update: Update, context):
    await update.message.reply_text("🚀 <b>PRIME GEMS BOT ACTIVE!</b>\n\nUse <code>/check &lt;CA&gt;</code>\nUse <code>/lb</code> para leaderboard", parse_mode=ParseMode.HTML)

async def help_command(update: Update, context):
    await update.message.reply_text("📖 <b>COMMANDS:</b>\n<code>/check &lt;CA&gt;</code> - Token analysis\n<code>/lb</code> - Leaderboard\n<code>/stats</code> - Your stats", parse_mode=ParseMode.HTML)

async def leaderboard_callback(update: Update, context):
    """Handler para callback do leaderboard com período"""
    query = update.callback_query
    await query.answer()
    
    # Extrair período do callback data
    period = context.user_data.get('lb_period', '1d')
    
    await show_leaderboard(query.message, context, period)

async def show_leaderboard(message, context, period='1d'):
    """Mostra o leaderboard com estatísticas do período"""
    if not user_calls_data:
        await message.reply_text("📊 Nenhum dado ainda. Seja o primeiro a fazer uma call!", parse_mode=ParseMode.HTML)
        return
    
    # Calcular stats de todos os usuários no período
    leaderboard = []
    group_stats = {
        "total_calls": 0,
        "total_users": 0,
        "avg_median": 0,
        "avg_return": 0,
        "hit_rate_2x_total": 0
    }
    
    medians = []
    returns = []
    hit_rates_2x = []
    
    for user_id in user_calls_data:
        stats = get_user_period_stats(user_id, period)
        if stats and stats["total_calls"] >= 1:
            username = user_calls_data[user_id].get("username", f"User_{user_id[-6:]}")
            leaderboard.append({
                "user_id": user_id,
                "username": username,
                "stats": stats
            })
            
            # Estatísticas do grupo
            group_stats["total_calls"] += stats["total_calls"]
            group_stats["total_users"] += 1
            medians.append(stats["median_return"])
            returns.append(stats["avg_return"])
            hit_rates_2x.append(stats["hit_rate_2x"])
    
    if not leaderboard:
        await message.reply_text("📊 Nenhum dado no período selecionado.", parse_mode=ParseMode.HTML)
        return
    
    # Ordenar por pontos totais
    leaderboard.sort(key=lambda x: x["stats"]["total_points"], reverse=True)
    
    # Calcular médias do grupo
    group_stats["avg_median"] = round(sum(medians) / len(medians), 2) if medians else 0
    group_stats["avg_return"] = round(sum(returns) / len(returns), 2) if returns else 0
    group_stats["avg_hit_rate_2x"] = round(sum(hit_rates_2x) / len(hit_rates_2x), 1) if hit_rates_2x else 0
    
    # Mensagem do leaderboard
    msg = f" <b>LEADERBOARD - TOP 10</b>\n"
    msg += f"<b>Período:</b> {period}\n\n"
    
    # Group Stats
    msg += f" <b>Group Stats</b>\n"
    msg += f"• Period: {period}\n"
    msg += f"• Calls: {group_stats['total_calls']}\n"
    msg += f"• Hit Rate: {group_stats['avg_hit_rate_2x']}% ≥2x\n"
    msg += f"• Median: {group_stats['avg_median']}x\n"
    msg += f"• Return: {group_stats['avg_return']}x (Avg: {group_stats['avg_return']}x)\n\n"
    
    # Top Callers
    msg += f"🏆 <b>Top Callers</b>\n\n"
    for i, entry in enumerate(leaderboard[:10], 1):
        stats = entry["stats"]
        username = escape_html(entry["username"])
        
        # Emoji para posição
        if i == 1:
            emoji = "🥇"
        elif i == 2:
            emoji = ""
        elif i == 3:
            emoji = "🥉"
        else:
            emoji = f"#{i}"
        
        msg += f"{emoji} <b>{username}</b> [{stats['total_points']} pts]\n"
        msg += f"   Calls: {stats['total_calls']} | Win: {stats['hit_rate']}%\n"
        msg += f"   Median: {stats['median_return']}x | Avg: +{stats['avg_return']}%\n"
        
        # Melhor call
        if stats['best_call']:
            best_ca_short = stats['best_call'][:10] + "..."
            msg += f"   📈 Best: {best_ca_short} [{stats['best_call_return']}x]\n"
        
        msg += "\n"
    
    # Botões de período
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1D", callback_data="lb_1d"),
            InlineKeyboardButton("1W", callback_data="lb_1w"),
            InlineKeyboardButton("2W", callback_data="lb_2w"),
            InlineKeyboardButton("1M", callback_data="lb_1m")
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=f"lb_refresh_{period}")
        ]
    ])
    
    try:
        await message.edit_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except:
        await message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)

async def leaderboard_command(update: Update, context):
    """Comando /lb - Mostra leaderboard"""
    period = '1d'  # Default
    context.user_data['lb_period'] = period
    await show_leaderboard(update.message, context, period)

async def leaderboard_period_callback(update: Update, context):
    """Callback para mudar período do leaderboard"""
    query = update.callback_query
    await query.answer()
    
    # Extrair período do callback
    period = query.data.replace("lb_", "")
    context.user_data['lb_period'] = period
    
    await show_leaderboard(query.message, context, period)

async def stats_command(update: Update, context):
    """Mostra estatísticas do usuário"""
    user = update.effective_user
    user_id = str(user.id)
    
    stats = get_user_period_stats(user_id, '1d')
    if not stats:
        await update.message.reply_text("📊 Você ainda não fez nenhuma call hoje!", parse_mode=ParseMode.HTML)
        return
    
    username = escape_html(user.username or user.first_name or "User")
    
    msg = f"📊 <b>YOUR STATS</b>\n"
    msg += f"<b>Período:</b> 1d\n\n"
    msg += f"👤 <b>{username}</b>\n\n"
    msg += f"📞 Total Calls: {stats['total_calls']}\n"
    msg += f"✅ Winning Calls: {stats['winning_calls']}\n"
    msg += f"🎯 Win Rate: {stats['hit_rate']}%\n"
    msg += f"📈 Hit Rate ≥2x: {stats['hit_rate_2x']}%\n"
    msg += f" Median Return: {stats['median_return']}x\n"
    msg += f" Avg Return: +{stats['avg_return']}%\n"
    msg += f"⭐ Total Points: {stats['total_points']}\n"
    msg += f" Avg Points/Call: {stats['avg_points']}\n"
    
    if stats['best_call']:
        msg += f"\n Best Call: {stats['best_call'][:20]}... [{stats['best_call_return']}x]"
    
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def check_command(update: Update, context):
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/check &lt;CA&gt;</code>", parse_mode=ParseMode.HTML)
        return
    
    ca = context.args[0].strip()
    user = update.effective_user
    user_display = user.username or user.first_name or "User"
    user_id = str(user.id)
    status_msg = await update.message.reply_text("🔍 Analyzing...")
    
    info = await fetch_token_info(ca)
    if not info:
        await status_msg.edit_text("❌ Token not found")
        return
    
    network = detect_network_from_ca(ca) or "solana"
    
    # Determinar nome da rede específico
    if info.get('source') == 'pumpfun':
        chain_name = "SOL"
    else:
        pair = info.get("pair", {})
        chain_id = pair.get("chainId", "")
        chain_name = get_chain_name(chain_id)
    
    if info.get('source') == 'pumpfun':
        initial_mc = info.get("marketCap", 0) or 0
        current_mc = initial_mc
    else:
        initial_mc = info.get("pair", {}).get("marketCap", 0) or 0
        current_mc = initial_mc
    
    # Salvar call do usuário
    if user_id not in user_calls_data:
        user_calls_data[user_id] = {
            "username": user_display,
            "calls": []
        }
    
    user_calls_data[user_id]["calls"].append({
        "ca": ca,
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "mc_at_call": initial_mc,
        "current_mc": current_mc,
        "network": chain_name
    })
    save_data()
    
    # Salvar dados iniciais do token
    if ca not in token_initial_data:
        token_initial_data[ca] = {
            "initial_mc": initial_mc,
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "user": user_display,
            "user_id": user.id,
            "network": network,
            "chain_name": chain_name
        }
    
    msg, keyboard = await format_token_message(info, ca, network, user_display, user.id)
    
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
        user_id = str(user.id)
        status_msg = await update.message.reply_text(" Analyzing...")
        
        info = await fetch_token_info(text)
        if not info:
            await status_msg.edit_text("❌ Token not found")
            return
        
        ca = text
        
        # Determinar nome da rede específico
        if info.get('source') == 'pumpfun':
            chain_name = "SOL"
        else:
            pair = info.get("pair", {})
            chain_id = pair.get("chainId", "")
            chain_name = get_chain_name(chain_id)
        
        if info.get('source') == 'pumpfun':
            initial_mc = info.get("marketCap", 0) or 0
            current_mc = initial_mc
        else:
            initial_mc = info.get("pair", {}).get("marketCap", 0) or 0
            current_mc = initial_mc
        
        # Salvar call do usuário
        if user_id not in user_calls_data:
            user_calls_data[user_id] = {
                "username": user_display,
                "calls": []
            }
        
        user_calls_data[user_id]["calls"].append({
            "ca": ca,
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "mc_at_call": initial_mc,
            "current_mc": current_mc,
            "network": chain_name
        })
        save_data()
        
        if ca not in token_initial_data:
            token_initial_data[ca] = {
                "initial_mc": initial_mc,
                "timestamp": datetime.now(timezone.utc).timestamp(),
                "user": user_display,
                "user_id": user.id,
                "network": network,
                "chain_name": chain_name
            }
        
        msg, keyboard = await format_token_message(info, ca, network, user_display, user.id)
        
        try:
            await status_msg.delete()
            await update.message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            await status_msg.edit_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def refresh_callback(update: Update, context):
    query = update.callback_query
    await query.answer("🔄")
    
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
    chain_name = initial_data.get("chain_name", "UNKNOWN")
    
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
    
    if initial_mc > 0 and current_mc > 0:
        change_percent = ((current_mc - initial_mc) / initial_mc) * 100
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
    
    initial_mc_str = f"${initial_mc:,.0f}"
    
    # Título: #SYMBOL - Name
    msg = f"🔖 <b>#{symbol}</b> - {name}\n"
    # Nome específico da rede em negrito
    msg += f"<b>{chain_name}</b>\n\n"
    
    # Métricas que atualizam ao vivo
    msg += f"💵 <b>MC:</b> ${current_mc:,.0f}\n"
    msg += f"📊 <b>Vol 24h:</b> ${vol:,.0f}\n"
    msg += f"💧 <b>LP:</b> ${liq:,.0f}\n"
    msg += f"{change_str} <i>since post</i>\n\n"
    
    # Links de rastreamento
    if data.get('source') == 'pumpfun':
        msg += f"<a href='https://dexscreener.com/solana/{mint}'>📊 DexScreener</a> | "
        msg += f"<a href='https://www.dextools.io/app/solana/pair/explorer/{mint}'> DexTools</a> | "
        msg += f"<a href='https://gmgn.ai/solana/token/{mint}'>🤖 GMGN</a>\n"
    else:
        pair_url = data.get("pair", {}).get("url", "")
        chain_id_lower = data.get("pair", {}).get("chainId", "").lower()
        
        if pair_url:
            msg += f"<a href='{pair_url}'>📊 DexScreener</a> | "
        
        chain_map = {
            "solana": "solana",
            "ethereum": "ether",
            "bsc": "bsc",
            "base": "base",
            "hood": "hood",
            "arbitrum": "arbitrum",
            "polygon": "polygon",
            "avalanche": "avalanche",
            "optimism": "optimism",
            "fantom": "fantom"
        }
        dextools_chain = chain_map.get(chain_id_lower, chain_id_lower)
        
        msg += f"<a href='https://www.dextools.io/app/{dextools_chain}/pair/explorer/{mint}'> DexTools</a> | "
        msg += f"<a href='https://gmgn.ai/{chain_id_lower}/token/{mint}'>🤖 GMGN</a>\n"
    
    # Redes sociais do projeto
    social_links = []
    if twitter:
        social_links.append(f"<a href='{twitter}'>𝕏</a>")
    if telegram:
        social_links.append(f"<a href='{telegram}'>✈️ TG</a>")
    if website:
        social_links.append(f"<a href='{website}'>🌐 Site</a>")
    
    if social_links:
        msg += "\n" + " | ".join(social_links) + "\n"
    
    msg += f"\n<i>️ DYOR</i>\n\n"
    
    # Rodapé: @ • MC inicial • tempo
    msg += f"👤 {caller_html} • {initial_mc_str} • ⏱️ {time_ago}"
    
    # Botão de atualizar
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
    logger.info(" Starting bot...")
    
    # Carregar dados salvos
    load_data()
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("lb", leaderboard_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CallbackQueryHandler(leaderboard_period_callback, pattern="^lb_(1d|1w|2w|1m)$"))
    application.add_handler(CallbackQueryHandler(leaderboard_callback, pattern="^lb_refresh_"))
    application.add_handler(CallbackQueryHandler(refresh_callback, pattern="^refresh:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    try:
        asyncio.get_event_loop().run_until_complete(application.bot.send_message(
            chat_id=CHAT_ID,
            text=(
                "✅ <b>PRIME GEMS BOT ONLINE!</b>\n\n"
                "🔍 Use <code>/check &lt;CA&gt;</code>\n"
                "🏆 Use <code>/lb</code> for leaderboard\n"
                "📊 Use <code>/stats</code> for your stats"
            ),
            parse_mode=ParseMode.HTML
        ))
        logger.info("✅ Welcome message sent!")
    except Exception as e:
        logger.error(f"Error: {e}")
    
    logger.info("✅ Bot running with advanced leaderboard!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
