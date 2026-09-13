import os
import asyncio
import aiohttp
import logging
import re
import json
import math
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

# Dados dos tokens e calls
token_initial_data = {}
user_calls_data = {}
pnl_settings = {}  # Configurações de PNL por grupo

# Arquivo para salvar dados
DATA_FILE = "user_calls.json"
PNL_SETTINGS_FILE = "pnl_settings.json"

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

# Configurações de tema PNL
PNL_THEMES = {
    "dark": {
        "bg": (26, 26, 46),  # #1a1a2e
        "text": (255, 255, 255),
        "accent": (0, 255, 136),  # Verde neon
        "secondary": (139, 148, 158)  # Cinza
    },
    "light": {
        "bg": (245, 245, 247),  # #f5f5f7
        "text": (0, 0, 0),
        "accent": (0, 200, 100),
        "secondary": (100, 100, 100)
    }
}

# Fontes disponíveis
PNL_FONTS = ["default", "bold", "mono"]

# Cores de destaque
PNL_COLORS = {
    "green": (0, 255, 136),
    "cyan": (0, 255, 255),
    "purple": (155, 89, 182),
    "pink": (255, 105, 180),
    "gold": (255, 215, 0),
    "orange": (255, 140, 0)
}

MONITOR_ACCOUNTS = ["OzzyManReview", "MaxCrypto__", "Ansem", "ClownIRL", "0xMert", "CryptoGodJohn", "HsakaTrades", "Pentosh1"]
NITTER_INSTANCES = ["https://nitter.net", "https://nitter.privacydev.net"]
processed_tweets = set()
alerted_tokens = set()
processed_cas = set()

def load_data():
    """Carrega dados do arquivo JSON"""
    global user_calls_data, pnl_settings
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                user_calls_data = json.load(f)
            logger.info(" Dados carregados do arquivo")
        
        if os.path.exists(PNL_SETTINGS_FILE):
            with open(PNL_SETTINGS_FILE, 'r') as f:
                pnl_settings = json.load(f)
            logger.info("🎨 PNL settings carregados")
    except Exception as e:
        logger.error(f"Erro ao carregar dados: {e}")
        user_calls_data = {}
        pnl_settings = {}

def save_data():
    """Salva dados no arquivo JSON"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(user_calls_data, f, indent=2)
        with open(PNL_SETTINGS_FILE, 'w') as f:
            json.dump(pnl_settings, f, indent=2)
    except Exception as e:
        logger.error(f"Erro ao salvar dados: {e}")

def get_pnl_settings(chat_id):
    """Retorna configurações PNL do chat"""
    if chat_id not in pnl_settings:
        pnl_settings[chat_id] = {
            "theme": "dark",
            "font": "default",
            "color": "green",
            "custom_bg": None
        }
    return pnl_settings[chat_id]

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
        return timedelta(days=1)

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
    best_call_symbol = None
    
    for call in calls:
        mc_at_call = call.get("mc_at_call", 0)
        current_mc = call.get("current_mc", 0)
        ca = call.get("ca", "")
        symbol = call.get("symbol", "")
        
        if mc_at_call > 0 and current_mc > 0:
            return_ratio = current_mc / mc_at_call
            returns.append(return_ratio)
            total_return += (return_ratio - 1) * 100
            
            baseline = 1.5
            if return_ratio <= 0:
                points = -10
            else:
                points = math.log2(return_ratio / baseline)
            points_list.append(points)
            
            if return_ratio > 1:
                winning_calls += 1
            
            if return_ratio >= 2:
                calls_2x_or_more += 1
            
            if return_ratio > best_call_return:
                best_call_return = return_ratio
                best_call = ca
                best_call_symbol = symbol
    
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
        "best_call_symbol": best_call_symbol,
        "best_call_return": round(best_call_return, 2)
    }

def create_pnl_card(data, ca, network, settings):
    """Cria imagem PNL minimalista"""
    # Configurações
    theme = PNL_THEMES.get(settings.get("theme", "dark"), PNL_THEMES["dark"])
    color = PNL_COLORS.get(settings.get("color", "green"), PNL_COLORS["green"])
    
    # Tamanho da imagem
    width, height = 1200, 630
    
    # Criar imagem
    if settings.get("custom_bg"):
        try:
            img = Image.open(settings["custom_bg"])
            img = img.resize((width, height))
        except:
            img = Image.new('RGB', (width, height), theme["bg"])
    else:
        img = Image.new('RGB', (width, height), theme["bg"])
    
    draw = ImageDraw.Draw(img)
    
    # Carregar fonte (usar fonte padrão do sistema)
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()
    
    # Extrair dados
    if data.get('source') == 'pumpfun':
        symbol = data.get("symbol", "N/A")
        name = data.get("name", "N/A")
        current_mc = data.get("marketCap", 0) or 0
        vol = data.get("volume", 0) or 0
        liq = data.get("liquidity", 0) or 0
        chain = "SOL"
    else:
        pair = data.get("pair", {})
        symbol = pair.get("baseToken", {}).get("symbol", "N/A")
        name = pair.get("baseToken", {}).get("name", "N/A")
        current_mc = pair.get("marketCap", 0) or 0
        vol = pair.get("volume", {}).get("h24", 0) or 0
        liq = pair.get("liquidity", {}).get("usd", 0) or 0
        chain = get_chain_name(pair.get("chainId", ""))
    
    # Calcular mudança
    initial_data = token_initial_data.get(ca, {})
    initial_mc = initial_data.get("initial_mc", 0)
    
    if initial_mc > 0 and current_mc > 0:
        change_percent = ((current_mc - initial_mc) / initial_mc) * 100
        change_str = f"+{change_percent:.1f}%" if change_percent >= 0 else f"{change_percent:.1f}%"
        change_color = color if change_percent >= 0 else (255, 100, 100)
    else:
        change_str = "0%"
        change_color = theme["secondary"]
    
    # Desenhar conteúdo (layout minimalista)
    y_offset = 80
    
    # Símbolo e nome
    draw.text((80, y_offset), f"#{symbol}", fill=theme["text"], font=font_large)
    y_offset += 80
    draw.text((80, y_offset), name, fill=theme["secondary"], font=font_medium)
    y_offset += 60
    
    # Rede
    draw.text((80, y_offset), chain, fill=color, font=font_medium)
    y_offset += 100
    
    # Métricas principais
    metrics = [
        ("MC", f"${current_mc:,.0f}"),
        ("Vol 24h", f"${vol:,.0f}"),
        ("LP", f"${liq:,.0f}"),
        ("Change", change_str)
    ]
    
    for label, value in metrics:
        draw.text((80, y_offset), label, fill=theme["secondary"], font=font_small)
        y_offset += 40
        
        if label == "Change":
            draw.text((80, y_offset), value, fill=change_color, font=font_large)
        else:
            draw.text((80, y_offset), value, fill=theme["text"], font=font_medium)
        
        y_offset += 70
    
    # Salvar em buffer
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return buffer

def create_pnl_card(data, ca, network, settings):
    """Cria imagem PNL estilo Phanes"""
    # Configurações
    theme = PNL_THEMES.get(settings.get("theme", "dark"), PNL_THEMES["dark"])
    color = PNL_COLORS.get(settings.get("color", "green"), PNL_COLORS["green"])
    
    # Tamanho da imagem
    width, height = 1200, 630
    
    # Criar imagem com background
    if settings.get("custom_bg"):
        try:
            img = Image.open(settings["custom_bg"])
            img = img.resize((width, height))
        except:
            img = Image.new('RGB', (width, height), theme["bg"])
    else:
        img = Image.new('RGB', (width, height), theme["bg"])
    
    draw = ImageDraw.Draw(img)
    
    # Tentar carregar fonte, senão usar padrão
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
        font_tiny = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_tiny = ImageFont.load_default()
    
    # Extrair dados do token
    if data.get('source') == 'pumpfun':
        symbol = data.get("symbol", "N/A")
        name = data.get("name", "N/A")
        current_mc = data.get("marketCap", 0) or 0
        vol = data.get("volume", 0) or 0
        liq = data.get("liquidity", 0) or 0
        chain = "SOL"
    else:
        pair = data.get("pair", {})
        symbol = pair.get("baseToken", {}).get("symbol", "N/A")
        name = pair.get("baseToken", {}).get("name", "N/A")
        current_mc = pair.get("marketCap", 0) or 0
        vol = pair.get("volume", {}).get("h24", 0) or 0
        liq = pair.get("liquidity", {}).get("usd", 0) or 0
        chain = get_chain_name(pair.get("chainId", ""))
    
    # Calcular mudança
    initial_data = token_initial_data.get(ca, {})
    initial_mc = initial_data.get("initial_mc", 0)
    
    if initial_mc > 0 and current_mc > 0:
        change_percent = ((current_mc - initial_mc) / initial_mc) * 100
        change_str = f"+{change_percent:.1f}%" if change_percent >= 0 else f"{change_percent:.1f}%"
        change_color = color if change_percent >= 0 else (255, 100, 100)
    else:
        change_str = "0%"
        change_color = theme["secondary"]
    
    # Layout estilo Phanes - Desenhar elementos
    padding = 60
    y_offset = 60
    
    # Linha superior: Símbolo + Rede
    symbol_text = f"#{symbol}"
    draw.text((padding, y_offset), symbol_text, fill=theme["text"], font=font_large)
    
    # Rede ao lado
    chain_x = padding + 300
    draw.text((chain_x, y_offset + 20), chain, fill=color, font=font_medium)
    
    y_offset += 100
    
    # Nome do token
    draw.text((padding, y_offset), name[:40], fill=theme["secondary"], font=font_small)
    
    y_offset += 80
    
    # Linha divisória
    draw.line([(padding, y_offset), (width - padding, y_offset)], fill=theme["secondary"], width=2)
    
    y_offset += 50
    
    # Métricas em grid
    metrics = [
        ("Market Cap", f"${current_mc:,.0f}"),
        ("Volume 24h", f"${vol:,.0f}"),
        ("Liquidity", f"${liq:,.0f}"),
    ]
    
    for label, value in metrics:
        draw.text((padding, y_offset), label, fill=theme["secondary"], font=font_tiny)
        y_offset += 35
        draw.text((padding, y_offset), value, fill=theme["text"], font=font_medium)
        y_offset += 60
    
    y_offset += 20
    
    # Change em destaque
    draw.text((padding, y_offset), "Change", fill=theme["secondary"], font=font_tiny)
    y_offset += 35
    draw.text((padding, y_offset), change_str, fill=change_color, font=font_large)
    
    # Footer
    footer_y = height - 80
    draw.line([(padding, footer_y), (width - padding, footer_y)], fill=theme["secondary"], width=1)
    
    footer_text = "PRIME GEMS BOT • DYOR"
    draw.text((padding, footer_y + 20), footer_text, fill=theme["secondary"], font=font_tiny)
    
    # Salvar em buffer
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return buffer
async def pnlbg_command(update: Update, context):
    """Define background personalizado para PNL cards"""
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text(
            "📸 Reply to an image with <code>/pnlbg</code> to set custom background",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Baixar imagem
    photo = update.message.reply_to_message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    
    # Salvar localmente
    bg_path = f"pnl_bg_{update.effective_chat.id}.png"
    await file.download_to_drive(bg_path)
    
    # Salvar configurações
    chat_id = str(update.effective_chat.id)
    if chat_id not in pnl_settings:
        pnl_settings[chat_id] = {"theme": "dark", "font": "default", "color": "green"}
    
    pnl_settings[chat_id]["custom_bg"] = bg_path
    save_data()
    
    await update.message.reply_text("✅ Custom background set!")

async def pnltheme_command(update: Update, context):
    """Muda tema do PNL card"""
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/pnltheme dark|light</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    theme = context.args[0].lower()
    if theme not in ["dark", "light"]:
        await update.message.reply_text("❌ Invalid theme. Use: dark or light")
        return
    
    chat_id = str(update.effective_chat.id)
    if chat_id not in pnl_settings:
        pnl_settings[chat_id] = {"theme": "dark", "font": "default", "color": "green"}
    
    pnl_settings[chat_id]["theme"] = theme
    save_data()
    
    await update.message.reply_text(f"✅ Theme set to: {theme}")

async def pnlcolor_command(update: Update, context):
    """Muda cor de destaque do PNL card"""
    if not context.args:
        colors = ", ".join(PNL_COLORS.keys())
        await update.message.reply_text(
            f"Usage: <code>/pnlcolor &lt;color&gt;</code>\nAvailable: {colors}",
            parse_mode=ParseMode.HTML
        )
        return
    
    color = context.args[0].lower()
    if color not in PNL_COLORS:
        await update.message.reply_text(f"❌ Invalid color. Available: {', '.join(PNL_COLORS.keys())}")
        return
    
    chat_id = str(update.effective_chat.id)
    if chat_id not in pnl_settings:
        pnl_settings[chat_id] = {"theme": "dark", "font": "default", "color": "green"}
    
    pnl_settings[chat_id]["color"] = color
    save_data()
    
    await update.message.reply_text(f"✅ Accent color set to: {color}")

async def start(update: Update, context):
    await update.message.reply_text("🚀 <b>PRIME GEMS BOT ACTIVE!</b>\n\nUse <code>/check &lt;CA&gt;</code>\nUse <code>/lb</code> para leaderboard\nUse <code>/pnl &lt;CA&gt;</code> para PNL card", parse_mode=ParseMode.HTML)

async def help_command(update: Update, context):
    await update.message.reply_text("📖 <b>COMMANDS:</b>\n<code>/check &lt;CA&gt;</code> - Token analysis\n<code>/lb</code> - Leaderboard\n<code>/stats</code> - Your stats\n<code>/pnl &lt;CA&gt;</code> - PNL card\n<code>/pnlbg</code> - Set background\n<code>/pnltheme</code> - Set theme\n<code>/pnlcolor</code> - Set color", parse_mode=ParseMode.HTML)

async def leaderboard_callback(update: Update, context):
    """Handler para callback do leaderboard com período"""
    query = update.callback_query
    await query.answer()
    
    period = context.user_data.get('lb_period', '1d')
    
    await show_leaderboard(query.message, context, period)

async def show_leaderboard(message, context, period='1d'):
    """Mostra o leaderboard estilo Phanes"""
    if not user_calls_data:
        await message.reply_text("📊 Nenhum dado ainda. Seja o primeiro a fazer uma call!", parse_mode=ParseMode.HTML)
        return
    
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
    all_best_calls = []
    
    for user_id in user_calls_data:
        stats = get_user_period_stats(user_id, period)
        if stats and stats["total_calls"] >= 1:
            username = user_calls_data[user_id].get("username", f"User_{user_id[-6:]}")
            leaderboard.append({
                "user_id": user_id,
                "username": username,
                "stats": stats
            })
            
            group_stats["total_calls"] += stats["total_calls"]
            group_stats["total_users"] += 1
            medians.append(stats["median_return"])
            returns.append(stats["avg_return"])
            hit_rates_2x.append(stats["hit_rate_2x"])
            
            if stats['best_call_symbol']:
                all_best_calls.append({
                    "username": username,
                    "symbol": stats['best_call_symbol'],
                    "ca": stats['best_call'],
                    "return": stats['best_call_return'],
                    "network": user_calls_data[user_id]["calls"][-1].get("network", "SOL")
                })
    
    if not leaderboard:
        await message.reply_text("📊 Nenhum dado no período selecionado.", parse_mode=ParseMode.HTML)
        return
    
    leaderboard.sort(key=lambda x: x["stats"]["total_points"], reverse=True)
    
    group_stats["avg_median"] = round(sum(medians) / len(medians), 2) if medians else 0
    group_stats["avg_return"] = round(sum(returns) / len(returns), 2) if returns else 0
    group_stats["avg_hit_rate_2x"] = round(sum(hit_rates_2x) / len(hit_rates_2x), 1) if hit_rates_2x else 0
    
    best_call_overall = max(all_best_calls, key=lambda x: x["return"]) if all_best_calls else None
    
    msg = f"🏆 <b>Top Callers</b>\n"
    
    if leaderboard:
        top_user = leaderboard[0]
        top_username = escape_html(top_user["username"])
        msg += f"  🏆 {top_username} [{top_user['stats']['total_points']} pts]\n\n"
    
    msg += f"📊 <b>Group Stats</b>\n"
    msg += f"  Period: {period}\n"
    msg += f"  Calls: {group_stats['total_calls']}\n"
    msg += f"  Hit Rate: {group_stats['avg_hit_rate_2x']}% ≥2x\n"
    msg += f"  Median: {group_stats['avg_median']}x\n"
    msg += f"  Return: {group_stats['avg_return']}x (Avg: {group_stats['avg_return']}x)\n"
    
    if best_call_overall:
        best_username = escape_html(best_call_overall["username"])
        best_symbol = escape_html(best_call_overall["symbol"])
        network_flag = {
            "SOL": "🟢",
            "ETH": "",
            "BSC": "",
            "BASE": "🔷",
            "HOOD": "🟠"
        }.get(best_call_overall["network"], "")
        
        msg += f"\n  {network_flag} #{best_symbol} • {best_username} [{best_call_overall['return']}x]"
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1D", callback_data="lb_1d"),
            InlineKeyboardButton("1W", callback_data="lb_1w"),
            InlineKeyboardButton("2W", callback_data="lb_2w"),
            InlineKeyboardButton("1M", callback_data="lb_1m")
        ],
        [
            InlineKeyboardButton("📱 DApp", url="https://phanes.bot"),
            InlineKeyboardButton("🔄", callback_data=f"lb_refresh_{period}")
        ]
    ])
    
    try:
        await message.edit_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except:
        await message.reply_text(msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)

async def leaderboard_command(update: Update, context):
    """Comando /lb - Mostra leaderboard"""
    period = '1d'
    context.user_data['lb_period'] = period
    await show_leaderboard(update.message, context, period)

async def leaderboard_period_callback(update: Update, context):
    """Callback para mudar período do leaderboard"""
    query = update.callback_query
    await query.answer()
    
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
    msg += f"Period: 1d\n\n"
    msg += f"👤 <b>{username}</b>\n\n"
    msg += f"  Total Calls: {stats['total_calls']}\n"
    msg += f"  Winning Calls: {stats['winning_calls']}\n"
    msg += f"  Win Rate: {stats['hit_rate']}%\n"
    msg += f"  Hit Rate ≥2x: {stats['hit_rate_2x']}%\n"
    msg += f"  Median Return: {stats['median_return']}x\n"
    msg += f"  Avg Return: +{stats['avg_return']}%\n"
    msg += f"  Total Points: {stats['total_points']}\n"
    msg += f"  Avg Points/Call: {stats['avg_points']}\n"
    
    if stats['best_call_symbol']:
        msg += f"\n  📈 Best: #{stats['best_call_symbol']} [{stats['best_call_return']}x]"
    
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
    
    if info.get('source') == 'pumpfun':
        chain_name = "SOL"
        symbol = info.get("symbol", "N/A")
        initial_mc = info.get("marketCap", 0) or 0
        current_mc = initial_mc
    else:
        pair = info.get("pair", {})
        chain_id = pair.get("chainId", "")
        chain_name = get_chain_name(chain_id)
        symbol = pair.get("baseToken", {}).get("symbol", "N/A")
        initial_mc = info.get("pair", {}).get("marketCap", 0) or 0
        current_mc = initial_mc
    
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
        "network": chain_name,
        "symbol": symbol
    })
    save_data()
    
    if ca not in token_initial_data:
        token_initial_data[ca] = {
            "initial_mc": initial_mc,
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "user": user_display,
            "user_id": user.id,
            "network": network,
            "chain_name": chain_name,
            "symbol": symbol
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
        status_msg = await update.message.reply_text("🔍 Analyzing...")
        
        info = await fetch_token_info(text)
        if not info:
            await status_msg.edit_text("❌ Token not found")
            return
        
        ca = text
        
        if info.get('source') == 'pumpfun':
            chain_name = "SOL"
            symbol = info.get("symbol", "N/A")
            initial_mc = info.get("marketCap", 0) or 0
            current_mc = initial_mc
        else:
            pair = info.get("pair", {})
            chain_id = pair.get("chainId", "")
            chain_name = get_chain_name(chain_id)
            symbol = pair.get("baseToken", {}).get("symbol", "N/A")
            initial_mc = info.get("pair", {}).get("marketCap", 0) or 0
            current_mc = initial_mc
        
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
            "network": chain_name,
            "symbol": symbol
        })
        save_data()
        
        if ca not in token_initial_data:
            token_initial_data[ca] = {
                "initial_mc": initial_mc,
                "timestamp": datetime.now(timezone.utc).timestamp(),
                "user": user_display,
                "user_id": user.id,
                "network": network,
                "chain_name": chain_name,
                "symbol": symbol
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
    
    msg = f" <b>#{symbol}</b> - {name}\n"
    msg += f"<b>{chain_name}</b>\n\n"
    
    msg += f"💵 <b>MC:</b> ${current_mc:,.0f}\n"
    msg += f"📊 <b>Vol 24h:</b> ${vol:,.0f}\n"
    msg += f"💧 <b>LP:</b> ${liq:,.0f}\n"
    msg += f"{change_str} <i>since post</i>\n\n"
    
    if data.get('source') == 'pumpfun':
        msg += f"<a href='https://dexscreener.com/solana/{mint}'>📊 DexScreener</a> | "
        msg += f"<a href='https://www.dextools.io/app/solana/pair/explorer/{mint}'>📈 DexTools</a> | "
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
        
        msg += f"<a href='https://www.dextools.io/app/{dextools_chain}/pair/explorer/{mint}'>📈 DexTools</a> | "
        msg += f"<a href='https://gmgn.ai/{chain_id_lower}/token/{mint}'>🤖 GMGN</a>\n"
    
    social_links = []
    if twitter:
        social_links.append(f"<a href='{twitter}'>𝕏</a>")
    if telegram:
        social_links.append(f"<a href='{telegram}'>✈️ TG</a>")
    if website:
        social_links.append(f"<a href='{website}'>🌐 Site</a>")
    
    if social_links:
        msg += "\n" + " | ".join(social_links) + "\n"
    
    msg += f"\n<i>⚠️ DYOR</i>\n\n"
    
    msg += f"👤 {caller_html} • {initial_mc_str} • ⏱️ {time_ago}"
    
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
    
    load_data()
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("lb", leaderboard_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("pnl", pnl_command))
    application.add_handler(CommandHandler("pnlbg", pnlbg_command))
    application.add_handler(CommandHandler("pnltheme", pnltheme_command))
    application.add_handler(CommandHandler("pnlcolor", pnlcolor_command))
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
                "📊 Use <code>/stats</code> for your stats\n"
                "🎨 Use <code>/pnl &lt;CA&gt;</code> for PNL card"
            ),
            parse_mode=ParseMode.HTML
        ))
        logger.info("✅ Welcome message sent!")
    except Exception as e:
        logger.error(f"Error: {e}")
    
    logger.info("✅ Bot running with PNL cards!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
