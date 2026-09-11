import os
import asyncio
import aiohttp
import logging
import re
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURAÇÕES
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN não encontrado")
if not CHAT_ID:
    raise ValueError("CHAT_ID não encontrado")

logger.info(f"✅ Prime Gems Bot iniciado!")

# ==========================================
# CONTAS TWITTER
# ==========================================
MONITOR_ACCOUNTS = [
    "OzzyManReview", "MaxCrypto__", "Ansem", "ClownIRL",
    "0xMert", "CryptoGodJohn", "HsakaTrades", "Pentosh1",
    "elonmusk", "CZ_Binance", "VitalikButerin", "WatcherGuru",
    "CryptoKaleo", "rektcapital", "AltcoinSherpa", "MilesDeutscher",
    "DefiIgnas", "TheMoonCarl",
]

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
]

# Cache
processed_tweets = set()
alerted_migrations = set()

# ==========================================
# COMANDOS
# ==========================================
async def start(update: Update, context):
    msg = (
        "🤖 *Prime Gems Bot ATIVO!*\n\n"
        "📱 *Monitorando:*\n"
        f"- {len(MONITOR_ACCOUNTS)} contas no Twitter\n"
        "- Migrações Raydium 24/7\n\n"
        "Use `/help` para comandos"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context):
    msg = (
        "📖 *Comandos:*\n\n"
        "`/pump <CA>` - Info do token\n"
        "`/trending` - Top Pump.fun\n"
        "`/migrations` - Tokens graduados\n"
        "`/monitor` - Contas monitoradas\n"
        "`/help` - Esta ajuda"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def monitor_command(update: Update, context):
    msg = "📱 *CONTAS MONITORADAS:*\n\n"
    for i, account in enumerate(MONITOR_ACCOUNTS, 1):
        msg += f"{i}. @{account}\n"
    msg += f"\nTotal: {len(MONITOR_ACCOUNTS)} contas"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def pump_command(update: Update, context):
    if not context.args:
        await update.message.reply_text("❌ Uso: `/pump <CA>`", parse_mode=ParseMode.MARKDOWN)
        return
    
    ca = context.args[0]
    await update.message.reply_text(f"🔍 Buscando {ca}...")
    
    token_info = await fetch_pump_token_info(ca)
    if not token_info:
        token_info = await fetch_dexscreener_token(ca)
    
    if not token_info:
        await update.message.reply_text(f"❌ Token não encontrado: `{ca}`", parse_mode=ParseMode.MARKDOWN)
        return
    
    msg = format_token_message(token_info)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def trending_command(update: Update, context):
    await update.message.reply_text("📊 Buscando...")
    tokens = await fetch_trending_pumpfun()
    
    if not tokens:
        await update.message.reply_text("❌ Nenhum token encontrado.")
        return
    
    msg = "🔥 *TOP 10 PUMP.FUN*\n\n"
    for i, token in enumerate(tokens[:10], 1):
        try:
            name = token.get("name", "N/A")
            symbol = token.get("symbol", "N/A")
            market_cap = token.get("marketCap", 0) or 0
            mint = token.get("mint", "")
            msg += f"{i}. *{symbol}* - {name}\n💰 MC: ${market_cap:,.0f}\n🔗 [Ver](https://pump.fun/{mint})\n\n"
        except:
            continue
    
    msg += "⚠️ _DYOR_"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def migrations_command(update: Update, context):
    await update.message.reply_text("🚀 Buscando migrações...")
    migrations = await fetch_graduated_tokens()
    
    if not migrations:
        await update.message.reply_text("❌ Nenhuma migração encontrada.")
        return
    
    msg = "⭐ *TOKENS GRADUADOS*\n\n"
    for i, pair in enumerate(migrations[:5], 1):
        try:
            symbol = pair.get("baseToken", {}).get("symbol", "N/A")
            name = pair.get("baseToken", {}).get("name", "N/A")
            liq = pair.get("liquidity", {}).get("usd", 0) or 0
            pair_url = pair.get("url", "")
            msg += f"{i}. *{symbol}* - {name}\n💧 Liq: ${liq:,.0f}\n🔗 [DexScreener]({pair_url})\n\n"
        except:
            continue
    
    msg += "️ _DYOR_"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

# ==========================================
# FUNÇÕES DE BUSCA
# ==========================================
async def fetch_pump_token_info(ca):
    url = f"https://frontend-api.pump.fun/coins/{ca}"
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    data['source'] = 'pumpfun'
                    return data
        except Exception as e:
            logger.error(f"Erro Pump.fun: {e}")
    return None

async def fetch_dexscreener_token(ca):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        return {"pair": pairs[0], "source": "dexscreener"}
        except Exception as e:
            logger.error(f"Erro DexScreener: {e}")
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
        except Exception as e:
            logger.error(f"Erro trending: {e}")
    return []

async def fetch_graduated_tokens():
    url = "https://api.dexscreener.com/latest/dex/search?q=marketCap>50000&liquidity>10000&chainId=solana&dexId=raydium"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pairs", [])[:10]
        except Exception as e:
            logger.error(f"Erro graduados: {e}")
    return []

async def fetch_latest_tweets(account):
    for instance in NITTER_INSTANCES:
        try:
            url = f"{instance}/{account}/rss"
            headers = {"User-Agent": "Mozilla/5.0"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        xml_content = await resp.text()
                        tweets = parse_rss(xml_content, account)
                        if tweets:
                            return tweets
        except Exception as e:
            logger.warning(f"Nitter falhou para @{account}: {e}")
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

def extract_contract_addresses(text):
    solana_pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    eth_pattern = r'\b0x[a-fA-F0-9]{40}\b'
    addresses = {
        "solana": re.findall(solana_pattern, text),
        "ethereum": re.findall(eth_pattern, text),
    }
    for network in addresses:
        addresses[network] = [addr for addr in addresses[network] 
                             if not any(word in addr.lower() for word in ['http', 'www', 'com'])]
    return addresses

def format_token_message(token_data):
    if token_data.get('source') == 'pumpfun':
        name = token_data.get("name", "N/A")
        symbol = token_data.get("symbol", "N/A")
        market_cap = token_data.get("marketCap", 0) or 0
        mint = token_data.get("mint", "")
        volume = token_data.get("volume", 0) or 0
        liquidity = token_data.get("liquidity", 0) or 0
        
        msg = f"🚀 *PUMP.FUN: {symbol}*\n\n"
        msg += f"💎 *Nome:* {name}\n"
        msg += f" *CA:* `{mint}`\n"
        msg += f"💰 *MC:* ${market_cap:,.0f}\n"
        msg += f"📈 *Vol:* ${volume:,.0f}\n"
        msg += f" *Liq:* ${liquidity:,.0f}\n\n"
        msg += f" [Pump.fun](https://pump.fun/{mint})\n\n"
        msg += "️ _DYOR_"
        return msg
    else:
        pair = token_data.get("pair", {})
        symbol = pair.get("baseToken", {}).get("symbol", "N/A")
        name = pair.get("baseToken", {}).get("name", "N/A")
        address = pair.get("baseToken", {}).get("address", "N/A")
        price = pair.get("priceUsd", "0")
        market_cap = pair.get("marketCap", 0) or 0
        liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
        pair_url = pair.get("url", "")
        
        msg = f" *DEXSCREENER: {symbol}*\n\n"
        msg += f"💎 *Nome:* {name}\n"
        msg += f"📄 *CA:* `{address}`\n"
        msg += f"💵 *Preço:* ${float(price):.8f}\n"
        msg += f"💰 *MC:* ${market_cap:,.0f}\n"
        msg += f"💧 *Liq:* ${liquidity:,.0f}\n\n"
        if pair_url:
            msg += f"🔗 [DexScreener]({pair_url})\n\n"
        msg += "⚠️ _DYOR_"
        return msg

# ==========================================
# TAREFAS PERIÓDICAS
# ==========================================
async def check_twitter(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🐦 Verificando Twitter...")
    bot = context.bot
    
    for account in MONITOR_ACCOUNTS:
        try:
            tweets = await fetch_latest_tweets(account)
            for tweet in tweets:
                tweet_id = tweet["link"]
                if tweet_id in processed_tweets:
                    continue
                
                processed_tweets.add(tweet_id)
                addresses = extract_contract_addresses(tweet["text"])
                all_addresses = addresses.get("solana", []) + addresses.get("ethereum", [])
                
                if all_addresses:
                    logger.info(f"🚨 CA detectado por @{account}")
                    for ca in all_addresses[:2]:
                        token_info = await fetch_pump_token_info(ca)
                        if not token_info:
                            token_info = await fetch_dexscreener_token(ca)
                        
                        msg = f"🚨 *ALERTA: @{account}*\n\n📄 *CA:*\n`{ca}`\n\n"
                        if token_info:
                            if token_info.get('source') == 'pumpfun':
                                symbol = token_info.get("symbol", "N/A")
                                mc = token_info.get("marketCap", 0) or 0
                                msg += f"💎 *Token:* {symbol}\n💰 *MC:* ${mc:,.0f}\n\n"
                            else:
                                pair = token_info.get("pair", {})
                                symbol = pair.get("baseToken", {}).get("symbol", "N/A")
                                msg += f"💎 *Token:* {symbol}\n\n"
                        
                        msg += f"🔗 [Tweet]({tweet['link']})\n\n️ _DYOR_"
                        
                        try:
                            await bot.send_message(
                                chat_id=CHAT_ID,
                                text=msg,
                                parse_mode=ParseMode.MARKDOWN,
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            logger.error(f"Erro ao enviar alerta: {e}")
                        
                        await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Erro @{account}: {e}")
        
        await asyncio.sleep(1)
    
    if len(processed_tweets) > 1000:
        processed_tweets.clear()

async def check_migrations(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🚀 Verificando migrações...")
    bot = context.bot
    
    migrations = await fetch_graduated_tokens()
    for pair in migrations:
        try:
            mint = pair.get("baseToken", {}).get("address", "")
            symbol = pair.get("baseToken", {}).get("symbol", "N/A")
            name = pair.get("baseToken", {}).get("name", "N/A")
            liq = pair.get("liquidity", {}).get("usd", 0) or 0
            pair_url = pair.get("url", "")
            
            if mint and mint not in alerted_migrations and liq > 10000:
                msg = (
                    f"⭐ *NOVA GRADUAÇÃO!*\n\n"
                    f"🔥 *{symbol}* - {name}\n"
                    f"💧 *Liq:* ${liq:,.0f}\n"
                    f"🔗 [DexScreener]({pair_url})\n\n"
                    f"⚠️ _DYOR_"
                )
                
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
                logger.info(f"⭐ Graduação: {symbol}")
                alerted_migrations.add(mint)
                await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Erro migração: {e}")

# ==========================================
# INÍCIO
# ==========================================
def main():
    logger.info("🚀 Iniciando Prime Gems Bot...")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("pump", pump_command))
    application.add_handler(CommandHandler("trending", trending_command))
    application.add_handler(CommandHandler("migrations", migrations_command))
    application.add_handler(CommandHandler("monitor", monitor_command))
    
    # JobQueue
    job_queue = application.job_queue
    job_queue.run_repeating(check_twitter, interval=180, first=10)
    job_queue.run_repeating(check_migrations, interval=300, first=15)
    
    logger.info("✅ Bot rodando com JobQueue!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
