import os
import asyncio
import aiohttp
import logging
import re
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError, InvalidToken
from datetime import datetime

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
    logger.error("❌ TELEGRAM_TOKEN não configurado!")
    raise ValueError("TELEGRAM_TOKEN não encontrado")

if not CHAT_ID:
    logger.error("❌ CHAT_ID não configurado!")
    raise ValueError("CHAT_ID não encontrado")

logger.info(f"✅ Prime Gems Bot iniciado!")

# ==========================================
# CONTAS PARA MONITORAR (TWITTER/X)
# ==========================================
MONITOR_ACCOUNTS = [
    # Meme Coins / Solana
    "OzzyManReview",
    "MaxCrypto__",
    "Ansem",
    "ClownIRL",
    "0xMert",
    "CryptoGodJohn",
    "HsakaTrades",
    "Pentosh1",
    
    # Geral / Grandes
    "elonmusk",
    "CZ_Binance",
    "VitalikButerin",
    "WatcherGuru",
    
    # Análise / Trading
    "CryptoKaleo",
    "rektcapital",
    "AltcoinSherpa",
    "MilesDeutscher",
    "DefiIgnas",
    "TheMoonCarl",
]

# Instâncias Nitter (fallback)
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.projectsegfau.lt",
]

# ==========================================
# COMANDOS
# ==========================================
async def start(update: Update, context):
    """Mensagem de boas-vindas"""
    msg = (
        "🤖 *Prime Gems Bot - Pump.fun + Twitter Radar*\n\n"
        "📌 *Comandos disponíveis:*\n\n"
        "🔍 `/pump <CA>` - Informações detalhadas de um token\n"
        "📈 `/trending` - Top 10 tokens da Pump.fun\n"
        "🚀 `/migrations` - Tokens migrando para Raydium\n"
        " `/monitor` - Ver contas monitoradas no Twitter\n"
        "ℹ️ `/help` - Ajuda detalhada\n\n"
        "🚨 *Alertas automáticos:*\n"
        "- Migrações para Raydium\n"
        "- CAs postados por influencers\n\n"
        "⚠️ *Faça sua própria pesquisa (DYOR)*"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context):
    """Ajuda detalhada"""
    msg = (
        "📖 *Guia Completo de Uso*\n\n"
        
        "🔍 *COMANDO /pump:*\n"
        "Use: `/pump CA_DO_TOKEN`\n"
        "Ex: `/pump 7GCihgDB8fe6KNjn...`\n"
        "Retorna: MC, volume, liq, redes sociais, holders\n\n"
        
        "📊 *COMANDO /trending:*\n"
        "Mostra os top 10 tokens da Pump.fun no momento\n\n"
        
        " *COMANDO /migrations:*\n"
        "Mostra tokens que migraram da Pump.fun para Raydium\n\n"
        
        "📱 *COMANDO /monitor:*\n"
        "Lista todas as contas do Twitter sendo monitoradas\n\n"
        
        "🤖 *MONITORAMENTO AUTOMÁTICO:*\n"
        "O bot verifica a cada 3 minutos:\n"
        "- Tweets das contas listadas\n"
        "- Detecta automaticamente CAs (Solana, ETH, BSC)\n"
        "- Busca dados do token automaticamente\n"
        "- Alerta de migrações para Raydium\n\n"
        
        "⚠️ *SEMPRE FAÇA DYOR!*"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def monitor_command(update: Update, context):
    """Mostra contas sendo monitoradas"""
    msg = "📱 *CONTAS MONITORADAS NO TWITTER:*\n\n"
    
    for i, account in enumerate(MONITOR_ACCOUNTS, 1):
        msg += f"{i}. @{account}\n"
    
    msg += f"\nTotal: {len(MONITOR_ACCOUNTS)} contas\n"
    msg += "🔄 Atualização: a cada 3 minutos"
    
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def pump_command(update: Update, context):
    """Busca informações de um token específico"""
    if not context.args:
        await update.message.reply_text(
            "❌ *Uso correto:*\n"
            "`/pump <CA_DO_TOKEN>`\n\n"
            "Exemplo: `/pump 7GCihgDB8fe6KNjn...`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    ca = context.args[0]
    logger.info(f"🔍 Buscando token: {ca}")
    
    # Buscar informações
    token_info = await fetch_pump_token_info(ca)
    
    if not token_info:
        # Tentar DexScreener como fallback
        token_info = await fetch_dexscreener_token(ca)
    
    if not token_info:
        await update.message.reply_text(
            f"❌ Token não encontrado\nCA: `{ca}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    msg = format_token_message(token_info)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def trending_command(update: Update, context):
    """Mostra top tokens da Pump.fun"""
    await update.message.reply_text("📊 *Buscando tokens em alta...*", parse_mode=ParseMode.MARKDOWN)
    
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
            description = token.get("description", "")[:50]
            mint = token.get("mint", "")
            
            msg += (
                f"{i}\\. *{symbol}* \\- {name}\n"
                f"💰 MC: \\${market_cap:,.0f}\n"
                f"📄 {description}\n"
                f"🔗 \\[Ver\\](https://pump.fun/{mint})\n\n"
            )
        except Exception as e:
            logger.error(f"Erro token {i}: {e}")
            continue
    
    msg += "\n⚠️ _DYOR_"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def migrations_command(update: Update, context):
    """Mostra tokens migrando para Raydium"""
    await update.message.reply_text("🚀 *Buscando migrações...*", parse_mode=ParseMode.MARKDOWN)
    
    migrations = await fetch_graduated_tokens()
    
    if not migrations:
        await update.message.reply_text("❌ Nenhuma migração encontrada.")
        return
    
    msg = "⭐ *TOKENS GRADUADOS - RAYDIUM*\n\n"
    
    for i, pair in enumerate(migrations[:5], 1):
        try:
            symbol = pair.get("baseToken", {}).get("symbol", "N/A")
            name = pair.get("baseToken", {}).get("name", "N/A")
            liq = pair.get("liquidity", {}).get("usd", 0) or 0
            vol = pair.get("volume", {}).get("h24", 0) or 0
            pair_url = pair.get("url", "")
            
            msg += (
                f"{i}\\. *{symbol}* \\- {name}\n"
                f"💧 Liq: \\${liq:,.0f}\n"
                f"📈 Vol: \\${vol:,.0f}\n"
                f"🔗 \\[DexScreener\\]\\({pair_url})\n\n"
            )
        except Exception as e:
            logger.error(f"Erro migração {i}: {e}")
            continue
    
    msg += "\n⚠️ _DYOR_"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

# ==========================================
# FUNÇÕES DE BUSCA - PUMP.FUN
# ==========================================
async def fetch_pump_token_info(ca):
    """Busca informações de token na Pump.fun"""
    url = f"https://frontend-api.pump.fun/coins/{ca}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    data['source'] = 'pumpfun'
                    return data
                return None
        except Exception as e:
            logger.error(f"Erro Pump.fun {ca}: {e}")
            return None

async def fetch_dexscreener_token(ca):
    """Busca informações na DexScreener"""
    url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        return {"pair": pairs[0], "source": "dexscreener"}
                return None
        except Exception as e:
            logger.error(f"Erro DexScreener {ca}: {e}")
            return None

async def fetch_trending_pumpfun():
    """Busca tokens em alta"""
    url = "https://frontend-api.pump.fun/coins?limit=20&offset=0"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", []) if isinstance(data, dict) else data
                return []
        except Exception as e:
            logger.error(f"Erro trending: {e}")
            return []

async def fetch_graduated_tokens():
    """Busca tokens graduados na Raydium"""
    url = "https://api.dexscreener.com/latest/dex/search?q=marketCap>50000%20AND%20liquidity>10000%20AND%20chainId%3Dsolana%20AND%20dexId%3Draydium"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pairs", [])[:10]
                return []
        except Exception as e:
            logger.error(f"Erro graduados: {e}")
            return []

# ==========================================
# FUNÇÕES DE BUSCA - TWITTER (NITTER)
# ==========================================
async def fetch_latest_tweets(account):
    """Busca tweets recentes via Nitter"""
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
            logger.warning(f"Nitter {instance} falhou para @{account}: {e}")
            continue
    
    return []

def parse_rss(xml_content, account):
    """Parse simples de RSS do Nitter"""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_content)
        tweets = []
        
        for item in root.findall(".//item"):
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            
            if title is not None and link is not None:
                tweet_text = title.text
                tweet_link = link.text.replace("nitter.net", "twitter.com")
                
                tweets.append({
                    "account": account,
                    "text": tweet_text,
                    "link": tweet_link,
                    "date": pub_date.text if pub_date is not None else None
                })
        
        return tweets[:5]  # Últimos 5 tweets
    except Exception as e:
        logger.error(f"Erro ao parsear RSS: {e}")
        return []

def extract_contract_addresses(text):
    """Extrai endereços de contrato (CA) do texto"""
    # Padrão para Solana (base58, 32-44 caracteres)
    solana_pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    
    # Padrão para Ethereum/BSC (0x + 40 hex)
    eth_pattern = r'\b0x[a-fA-F0-9]{40}\b'
    
    addresses = {
        "solana": re.findall(solana_pattern, text),
        "ethereum": re.findall(eth_pattern, text),
    }
    
    # Filtrar falsos positivos
    for network in addresses:
        addresses[network] = [addr for addr in addresses[network] 
                             if not any(word in addr.lower() for word in ['http', 'www', 'com'])]
    
    return addresses

# ==========================================
# FORMATAÇÃO DE MENSAGENS
# ==========================================
def format_token_message(token_data):
    """Formata mensagem do token"""
    if token_data.get('source') == 'pumpfun':
        return format_pumpfun_message(token_data)
    else:
        return format_dexscreener_message(token_data)

def format_pumpfun_message(token):
    """Formata mensagem de token Pump.fun"""
    name = token.get("name", "N/A")
    symbol = token.get("symbol", "N/A")
    market_cap = token.get("marketCap", 0) or 0
    description = token.get("description", "Sem descrição")
    mint = token.get("mint", "")
    
    volume_24h = token.get("volume", 0) or 0
    liquidity = token.get("liquidity", 0) or 0
    
    twitter = token.get("twitter", "")
    telegram = token.get("telegram", "")
    website = token.get("website", "")
    
    creator = token.get("creator", "")[:8] + "..." if token.get("creator") else "N/A"
    
    msg = (
        f"🚀 *PUMP.FUN: {symbol}*\n\n"
        f"💎 *Nome:* {name}\n"
        f"📄 *CA:* `{mint}`\n"
        f"💰 *Market Cap:* \\${market_cap:,.0f}\n"
        f"📈 *Volume:* \\${volume_24h:,.0f}\n"
        f"💧 *Liquidez:* \\${liquidity:,.0f}\n\n"
        f"📝 *Descrição:*\n{description}\n\n"
    )
    
    social_links = []
    if twitter:
        social_links.append(f"\\[Twitter\\]({twitter})")
    if telegram:
        social_links.append(f"\\[Telegram\\]({telegram})")
    if website:
        social_links.append(f"\\[Site\\]({website})")
    
    if social_links:
        msg += f"🔗 *Redes:* {' | '.join(social_links)}\n"
    
    msg += f"\n\\[Pump\\.Fun\\](https://pump.fun/{mint})\n"
    msg += f"👤 *Criador:* `{creator}`\n\n"
    msg += "⚠️ _DYOR_"
    
    return msg

def format_dexscreener_message(token_data):
    """Formata mensagem de token DexScreener"""
    pair = token_data.get("pair", {})
    
    base_token = pair.get("baseToken", {})
    quote_token = pair.get("quoteToken", {})
    
    symbol = base_token.get("symbol", "N/A")
    name = base_token.get("name", "N/A")
    address = base_token.get("address", "N/A")
    
    price = pair.get("priceUsd", "0")
    liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
    volume_24h = pair.get("volume", {}).get("h24", 0) or 0
    market_cap = pair.get("marketCap", 0) or 0
    
    chain = pair.get("chainId", "N/A").upper()
    dex = pair.get("dexId", "N/A").upper()
    
    msg = (
        f"📊 *DEXSCREENER: {symbol}*\n\n"
        f"💎 *Nome:* {name}\n"
        f"📄 *CA:* `{address}`\n"
        f"💰 *Preço:* \\${float(price):.8f}\n"
        f" *Market Cap:* \\${market_cap:,.0f}\n"
        f" *Volume 24h:* \\${volume_24h:,.0f}\n"
        f"💧 *Liquidez:* \\${liquidity:,.0f}\n"
        f"⛓️ *Rede:* {chain}\n"
        f"🏪 *DEX:* {dex}\n\n"
    )
    
    pair_url = pair.get("url", "")
    if pair_url:
        msg += f"🔗 \\[DexScreener\\]\\({pair_url})\n"
    
    msg += "\n⚠️ _DYOR_"
    
    return msg

def format_twitter_alert(account, tweet_text, tweet_link, ca, token_info=None):
    """Formata alerta de Twitter com CA"""
    msg = (
        f"🚨 *ALERTA TWITTER: @{account}*\n\n"
        f"📄 *CA Detectado:*\n"
        f"`{ca}`\n\n"
        f" *Tweet:*\n_{tweet_text[:150]}..._\n\n"
    )
    
    if token_info:
        if token_info.get('source') == 'pumpfun':
            symbol = token_info.get("symbol", "N/A")
            market_cap = token_info.get("marketCap", 0) or 0
            msg += f"💎 *Token:* {symbol}\n"
            msg += f"💰 *Market Cap:* \\${market_cap:,.0f}\n\n"
        else:
            pair = token_info.get("pair", {})
            symbol = pair.get("baseToken", {}).get("symbol", "N/A")
            price = pair.get("priceUsd", "0")
            msg += f"💎 *Token:* {symbol}\n"
            msg += f"💵 *Preço:* \\${float(price):.8f}\n\n"
    
    msg += f"🔗 \\[Ver Tweet\\]\\({tweet_link})\n\n"
    msg += "⚠️ _DYOR - Cuidado com scams!_"
    
    return msg

# ==========================================
# MONITORAMENTO AUTOMÁTICO
# ==========================================
async def monitor_twitter(bot):
    """Monitora Twitter por CAs"""
    logger.info("🐦 Iniciando monitoramento do Twitter...")
    last_tweets = {}
    
    while True:
        try:
            for account in MONITOR_ACCOUNTS:
                try:
                    tweets = await fetch_latest_tweets(account)
                    
                    for tweet in tweets:
                        tweet_id = tweet["link"]
                        
                        # Ignorar tweets já processados
                        if tweet_id in last_tweets:
                            continue
                        
                        last_tweets[tweet_id] = True
                        
                        # Extrair CAs do tweet
                        addresses = extract_contract_addresses(tweet["text"])
                        
                        # Verificar se tem CA
                        all_addresses = addresses.get("solana", []) + addresses.get("ethereum", [])
                        
                        if all_addresses:
                            logger.info(f"🚨 CA detectado por @{account}")
                            
                            for ca in all_addresses[:2]:  # Máximo 2 CAs por tweet
                                # Buscar informações do token
                                token_info = await fetch_pump_token_info(ca)
                                if not token_info:
                                    token_info = await fetch_dexscreener_token(ca)
                                
                                # Formatar e enviar alerta
                                msg = format_twitter_alert(
                                    account,
                                    tweet["text"],
                                    tweet["link"],
                                    ca,
                                    token_info
                                )
                                
                                try:
                                    await bot.send_message(
                                        chat_id=CHAT_ID,
                                        text=msg,
                                        parse_mode=ParseMode.MARKDOWN,
                                        disable_web_page_preview=True
                                    )
                                    logger.info(f"✅ Alerta Twitter enviado: {ca[:10]}...")
                                except Exception as e:
                                    logger.error(f"Erro ao enviar alerta: {e}")
                                
                                await asyncio.sleep(2)
                    
                    await asyncio.sleep(1)  # Delay entre contas
                    
                except Exception as e:
                    logger.error(f"Erro ao monitorar @{account}: {e}")
                    continue
            
            # Limpar cache antigo
            if len(last_tweets) > 1000:
                last_tweets.clear()
            
            await asyncio.sleep(180)  # Verificar a cada 3 minutos
            
        except Exception as e:
            logger.error(f"Erro no monitoramento Twitter: {e}")
            await asyncio.sleep(60)

async def monitor_migrations(bot):
    """Monitora migrações para Raydium"""
    logger.info("🚀 Monitorando migrações...")
    alertados = set()
    
    while True:
        try:
            migrations = await fetch_graduated_tokens()
            
            for pair in migrations:
                try:
                    mint = pair.get("baseToken", {}).get("address", "")
                    symbol = pair.get("baseToken", {}).get("symbol", "N/A")
                    name = pair.get("baseToken", {}).get("name", "N/A")
                    liq = pair.get("liquidity", {}).get("usd", 0) or 0
                    vol = pair.get("volume", {}).get("h24", 0) or 0
                    pair_url = pair.get("url", "")
                    
                    if mint and mint not in alertados and liq > 10000:
                        msg = (
                            f"⭐ *NOVA GRADUAÇÃO!*\n\n"
                            f" *{symbol}* \\- {name}\n"
                            f"💧 *Liquidez:* \\${liq:,.0f}\n"
                            f"📈 *Volume:* \\${vol:,.0f}\n"
                            f"🔗 \\[DexScreener\\]\\({pair_url})\n\n"
                            f"⚠️ _DYOR_"
                        )
                        
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=msg,
                            parse_mode=ParseMode.MARKDOWN,
                            disable_web_page_preview=True
                        )
                        logger.info(f"⭐ Graduação: {symbol}")
                        
                        alertados.add(mint)
                        await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Erro migração: {e}")
                    continue
            
            await asyncio.sleep(300)  # 5 minutos
            
        except Exception as e:
            logger.error(f"Erro monitoramento migrações: {e}")
            await asyncio.sleep(60)

# ==========================================
# INÍCIO
# ==========================================
async def main():
    """Função principal"""
    logger.info("🚀 Iniciando Prime Gems Bot...")
    
    # Criar aplicação
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Adicionar handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("pump", pump_command))
    application.add_handler(CommandHandler("trending", trending_command))
    application.add_handler(CommandHandler("migrations", migrations_command))
    application.add_handler(CommandHandler("monitor", monitor_command))
    
    # Iniciar
    await application.initialize()
    
    # Mensagem de boas-vindas
    try:
        bot = application.bot
        await bot.send_message(
            chat_id=CHAT_ID,
            text=(
                "✅ *Prime Gems Bot ATIVO!*\n\n"
                "📱 *Monitorando:*\n"
                f"- {len(MONITOR_ACCOUNTS)} contas no Twitter\n"
                "- Migrações Raydium 24/7\n\n"
                "Use `/help` para comandos"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info("✅ Bot online!")
    except Exception as e:
        logger.error(f"Erro boas-vindas: {e}")
    
    # Iniciar monitoramentos
    asyncio.create_task(monitor_twitter(application.bot))
    asyncio.create_task(monitor_migrations(application.bot))
    
    # Iniciar polling
    await application.start_polling()
    logger.info("✅ Bot rodando!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"💥 Bot falhou: {e}")
        raise
