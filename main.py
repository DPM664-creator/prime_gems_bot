import os
import asyncio
import aiohttp
import logging
import re
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes
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
    raise ValueError("TELEGRAM_TOKEN não encontrado")
if not CHAT_ID:
    raise ValueError("CHAT_ID não encontrado")

logger.info("✅ Prime Gems Bot iniciado!")

# ==========================================
# CONTAS TWITTER
# ==========================================
MONITOR_ACCOUNTS = [
    "OzzyManReview", "MaxCrypto__", "Ansem", "ClownIRL",
    "0xMert", "CryptoGodJohn", "HsakaTrades", "Pentosh1",
    "elonmusk", "CZ_Binance", "VitalikButerin", "WatcherGuru",
    "CryptoKaleo", "rektcapital", "AltcoinSherpa", "MilesDeutscher",
]

NITTER_INSTANCES = ["https://nitter.net", "https://nitter.privacydev.net"]
processed_tweets = set()
alerted_tokens = set()

# ==========================================
# COMANDOS
# ==========================================
async def start(update: Update, context):
    msg = (
        "🚀 *PRIME GEMS BOT ATIVO!*\n\n"
        "📊 *Redes Monitoradas:*\n"
        "• Solana (Pump.fun, Raydium)\n"
        "• Ethereum (Uniswap)\n"
        "• BSC (PancakeSwap)\n"
        "• Base (BaseSwap)\n\n"
        " *Alertas Automáticos:*\n"
        "• Twitter influencers\n"
        "• Novos lançamentos\n"
        "• Migrações\n\n"
        "Use `/help` para comandos"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context):
    msg = (
        " *COMANDOS DISPONÍVEIS*\n\n"
        "🔍 `/pump <CA>` - Info detalhada do token\n"
        "📈 `/trending` - Top tokens Pump.fun\n"
        " `/newpairs` - Pares recém-criados\n"
        "⭐ `/migrations` - Migrações Raydium\n"
        "📱 `/monitor` - Contas Twitter\n"
        "ℹ️ `/help` - Esta ajuda"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def monitor_command(update: Update, context):
    msg = "📱 *CONTAS MONITORADAS:*\n\n"
    for i, acc in enumerate(MONITOR_ACCOUNTS, 1):
        msg += f"{i}. @{acc}\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def pump_command(update: Update, context):
    if not context.args:
        await update.message.reply_text("❌ Uso: `/pump <CA>`", parse_mode=ParseMode.MARKDOWN)
        return
    
    ca = context.args[0]
    await update.message.reply_text(f"🔍 Buscando {ca}...")
    
    info = await fetch_token_info(ca)
    if not info:
        await update.message.reply_text("❌ Token não encontrado")
        return
    
    msg = format_detailed_token_info(info)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def trending_command(update: Update, context):
    await update.message.reply_text("📊 Buscando trending...")
    tokens = await fetch_trending_pumpfun()
    
    if not tokens:
        await update.message.reply_text("❌ Nenhum token encontrado")
        return
    
    msg = " *TOP 10 PUMP.FUN*\n\n"
    for i, t in enumerate(tokens[:10], 1):
        try:
            symbol = t.get("symbol", "N/A")
            name = t.get("name", "N/A")
            mc = t.get("marketCap", 0) or 0
            mint = t.get("mint", "")
            msg += f"{i}. *{symbol}* - {name}\n💰 MC: ${mc:,.0f}\n🔗 [Ver](https://pump.fun/{mint})\n\n"
        except:
            continue
    
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def newpairs_command(update: Update, context):
    await update.message.reply_text("🆕 Buscando novos pares...")
    pairs = await fetch_new_pairs()
    
    if not pairs:
        await update.message.reply_text("❌ Nenhum par recente encontrado")
        return
    
    msg = "🆕 *NOVOS PARES - ÚLTIMAS 24H*\n\n"
    for i, pair in enumerate(pairs[:10], 1):
        try:
            base = pair.get("baseToken", {})
            symbol = base.get("symbol", "N/A")
            name = base.get("name", "N/A")
            chain = pair.get("chainId", "").upper()
            liq = pair.get("liquidity", {}).get("usd", 0) or 0
            vol = pair.get("volume", {}).get("h24", 0) or 0
            pair_url = pair.get("url", "")
            
            msg += f"{i}. *{symbol}* - {name}\n⛓️ {chain}\n💧 Liq: ${liq:,.0f} | Vol: ${vol:,.0f}\n🔗 [Ver]({pair_url})\n\n"
        except:
            continue
    
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def migrations_command(update: Update, context):
    await update.message.reply_text("⭐ Buscando migrações...")
    migrations = await fetch_graduated_tokens()
    
    if not migrations:
        await update.message.reply_text("❌ Nenhuma migração encontrada")
        return
    
    msg = "⭐ *TOKENS GRADUADOS - RAYDIUM*\n\n"
    for i, pair in enumerate(migrations[:8], 1):
        try:
            base = pair.get("baseToken", {})
            symbol = base.get("symbol", "N/A")
            name = base.get("name", "N/A")
            liq = pair.get("liquidity", {}).get("usd", 0) or 0
            vol = pair.get("volume", {}).get("h24", 0) or 0
            mc = pair.get("marketCap", 0) or 0
            pair_url = pair.get("url", "")
            
            msg += f"{i}. *{symbol}* - {name}\n💰 MC: ${mc:,.0f}\n💧 Liq: ${liq:,.0f} | Vol: ${vol:,.0f}\n🔗 [Ver]({pair_url})\n\n"
        except:
            continue
    
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

# ==========================================
# FUNÇÕES DE BUSCA
# ==========================================
async def fetch_token_info(ca):
    """Busca informações completas do token"""
    url = f"https://frontend-api.pump.fun/coins/{ca}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    data['source'] = 'pumpfun'
                    return data
        except:
            pass
        
        try:
            async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}", 
                                  timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        return {"pair": pairs[0], "source": "dexscreener"}
        except:
            pass
    
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
        except:
            pass
    return []

async def fetch_new_pairs():
    """Busca pares recém-criados em todas as redes"""
    url = "https://api.dexscreener.com/latest/dex/pairs/v2?order=createdAt&limit=50"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pairs", [])[:50]
        except:
            pass
    return []

async def fetch_graduated_tokens():
    """Busca tokens que migraram da Pump.fun para Raydium"""
    url = "https://api.dexscreener.com/latest/dex/search?q=marketCap>50000&liquidity>10000&chainId=solana&dexId=raydium"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("pairs", [])[:20]
        except:
            pass
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

def extract_contract_addresses(text):
    solana = re.findall(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b', text)
    ethereum = re.findall(r'\b0x[a-fA-F0-9]{40}\b', text)
    
    solana = [s for s in solana if 'http' not in s.lower() and 'www' not in s.lower()]
    ethereum = [e for e in ethereum if 'http' not in e.lower()]
    
    return {"solana": solana, "ethereum": ethereum}

def format_detailed_token_info(data):
    """Formata mensagem detalhada estilo bots da imagem"""
    if data.get('source') == 'pumpfun':
        name = data.get("name", "N/A")
        symbol = data.get("symbol", "N/A")
        mint = data.get("mint", "N/A")
        mc = data.get("marketCap", 0) or 0
        vol = data.get("volume", 0) or 0
        liq = data.get("liquidity", 0) or 0
        desc = data.get("description", "Sem descrição")[:150]
        
        twitter = data.get("twitter", "")
        telegram = data.get("telegram", "")
        website = data.get("website", "")
        
        msg = f"🚀 *PUMP.FUN: {symbol}*\n\n"
        msg += f"💎 *Nome:* {name}\n"
        msg += f"📄 *CA:* `{mint}`\n"
        msg += f"💰 *Market Cap:* ${mc:,.0f}\n"
        msg += f" *Volume:* ${vol:,.0f}\n"
        msg += f"💧 *Liquidez:* ${liq:,.0f}\n\n"
        msg += f" *Descrição:*\n_{desc}_\n\n"
        
        socials = []
        if twitter:
            socials.append(f"[Twitter]({twitter})")
        if telegram:
            socials.append(f"[Telegram]({telegram})")
        if website:
            socials.append(f"[Site]({website})")
        
        if socials:
            msg += f"🔗 *Redes:* {' | '.join(socials)}\n"
        
        msg += f"\n [Pump.fun](https://pump.fun/{mint})\n\n"
        msg += "⚠️ _DYOR_"
        return msg
    else:
        pair = data.get("pair", {})
        base = pair.get("baseToken", {})
        quote = pair.get("quoteToken", {})
        
        symbol = base.get("symbol", "N/A")
        name = base.get("name", "N/A")
        address = base.get("address", "N/A")
        price = float(pair.get("priceUsd", 0))
        mc = pair.get("marketCap", 0) or 0
        liq = pair.get("liquidity", {}).get("usd", 0) or 0
        vol24h = pair.get("volume", {}).get("h24", 0) or 0
        chain = pair.get("chainId", "N/A").upper()
        dex = pair.get("dexId", "N/A").upper()
        pair_url = pair.get("url", "")
        
        msg = f"📊 *{chain} - {symbol}*\n\n"
        msg += f"💎 *Nome:* {name}\n"
        msg += f" *CA:* `{address}`\n"
        msg += f"💵 *Preço:* ${price:.8f}\n"
        msg += f"💰 *Market Cap:* ${mc:,.0f}\n"
        msg += f"📈 *Volume 24h:* ${vol24h:,.0f}\n"
        msg += f"💧 *Liquidez:* ${liq:,.0f}\n"
        msg += f"⛓️ *Rede:* {chain}\n"
        msg += f"🏪 *DEX:* {dex}\n\n"
        
        if pair_url:
            msg += f"🔗 [DexScreener]({pair_url})\n\n"
        
        msg += "⚠️ _DYOR_"
        return msg

def format_twitter_alert(account, tweet_text, tweet_link, ca, token_info):
    """Formata alerta do Twitter"""
    msg = f"🚨 *ALERTA TWITTER: @{account}*\n\n"
    msg += f"📄 *CA Detectado:*\n`{ca}`\n\n"
    
    if tweet_text:
        msg += f"📝 *Tweet:*\n_{tweet_text[:200]}..._\n\n"
    
    if token_info:
        if token_info.get('source') == 'pumpfun':
            symbol = token_info.get("symbol", "N/A")
            mc = token_info.get("marketCap", 0) or 0
            msg += f"💎 *Token:* {symbol}\n"
            msg += f"💰 *MC:* ${mc:,.0f}\n\n"
        else:
            pair = token_info.get("pair", {})
            symbol = pair.get("baseToken", {}).get("symbol", "N/A")
            price = float(pair.get("priceUsd", 0))
            msg += f"💎 *Token:* {symbol}\n"
            msg += f"💵 *Preço:* ${price:.8f}\n\n"
    
    msg += f"🔗 [Ver Tweet]({tweet_link})\n\n"
    msg += "️ _DYOR - Cuidado com scams!_"
    
    return msg

# ==========================================
# MONITORAMENTO AUTOMÁTICO
# ==========================================
async def monitor_twitter_loop(bot):
    """Loop de monitoramento do Twitter"""
    logger.info("🐦 Iniciando monitoramento Twitter...")
    
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
                        addresses = extract_contract_addresses(tweet["text"])
                        all_cas = addresses.get("solana", []) + addresses.get("ethereum", [])
                        
                        if all_cas:
                            logger.info(f"🚨 CA detectado por @{account}")
                            
                            for ca in all_cas[:2]:
                                if ca in alerted_tokens:
                                    continue
                                
                                token_info = await fetch_token_info(ca)
                                
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
                                    alerted_tokens.add(ca)
                                    logger.info(f"✅ Alerta Twitter enviado: {ca[:10]}...")
                                except Exception as e:
                                    logger.error(f"Erro ao enviar: {e}")
                                
                                await asyncio.sleep(2)
                    
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Erro monitorando @{account}: {e}")
                    continue
            
            if len(processed_tweets) > 1000:
                processed_tweets.clear()
            
            await asyncio.sleep(180)
            
        except Exception as e:
            logger.error(f"Erro no loop Twitter: {e}")
            await asyncio.sleep(60)

async def monitor_newpairs_loop(bot):
    """Monitora novos pares automaticamente"""
    logger.info("🆕 Iniciando monitoramento de novos pares...")
    alerted_pairs = set()
    
    while True:
        try:
            pairs = await fetch_new_pairs()
            
            for pair in pairs:
                try:
                    base = pair.get("baseToken", {})
                    mint = base.get("address", "")
                    symbol = base.get("symbol", "N/A")
                    chain = pair.get("chainId", "")
                    
                    if chain not in ["solana", "ethereum", "bsc", "base"]:
                        continue
                    
                    liq = pair.get("liquidity", {}).get("usd", 0) or 0
                    vol = pair.get("volume", {}).get("h24", 0) or 0
                    mc = pair.get("marketCap", 0) or 0
                    
                    if mint and mint not in alerted_pairs and liq > 5000 and vol > 10000:
                        pair_url = pair.get("url", "")
                        
                        msg = (
                            f" *NOVO PAR DETECTADO!*\n\n"
                            f"🔥 *{symbol}*\n"
                            f"⛓️ *Rede:* {chain.upper()}\n"
                            f"💰 *MC:* ${mc:,.0f}\n"
                            f"💧 *Liquidez:* ${liq:,.0f}\n"
                            f"📈 *Volume:* ${vol:,.0f}\n\n"
                            f"🔗 [Ver]({pair_url})\n\n"
                            f"⚠️ _DYOR_"
                        )
                        
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=msg,
                            parse_mode=ParseMode.MARKDOWN,
                            disable_web_page_preview=True
                        )
                        
                        alerted_pairs.add(mint)
                        logger.info(f" Novo par alertado: {symbol}")
                        await asyncio.sleep(2)
                        
                except Exception as e:
                    logger.error(f"Erro processando par: {e}")
                    continue
            
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"Erro no loop novos pares: {e}")
            await asyncio.sleep(60)

async def monitor_migrations_loop(bot):
    """Monitora migrações automaticamente"""
    logger.info("⭐ Iniciando monitoramento de migrações...")
    
    while True:
        try:
            migrations = await fetch_graduated_tokens()
            
            for pair in migrations:
                try:
                    base = pair.get("baseToken", {})
                    mint = base.get("address", "")
                    symbol = base.get("symbol", "N/A")
                    
                    if mint and mint not in alerted_tokens:
                        liq = pair.get("liquidity", {}).get("usd", 0) or 0
                        vol = pair.get("volume", {}).get("h24", 0) or 0
                        mc = pair.get("marketCap", 0) or 0
                        pair_url = pair.get("url", "")
                        
                        msg = (
                            f"⭐ *NOVA GRADUAÇÃO PUMP.FUN!*\n\n"
                            f" *{symbol}*\n"
                            f"💰 *MC:* ${mc:,.0f}\n"
                            f"💧 *Liquidez:* ${liq:,.0f}\n"
                            f"📈 *Volume:* ${vol:,.0f}\n\n"
                            f"🔗 [DexScreener]({pair_url})\n\n"
                            f"⚠️ _DYOR_"
                        )
                        
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=msg,
                            parse_mode=ParseMode.MARKDOWN,
                            disable_web_page_preview=True
                        )
                        
                        alerted_tokens.add(mint)
                        logger.info(f"⭐ Graduação: {symbol}")
                        await asyncio.sleep(2)
                        
                except Exception as e:
                    logger.error(f"Erro migração: {e}")
                    continue
            
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"Erro no loop migrações: {e}")
            await asyncio.sleep(60)

# ==========================================
# INÍCIO
# ==========================================
async def main():
    logger.info("🚀 Iniciando Prime Gems Bot...")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("pump", pump_command))
    application.add_handler(CommandHandler("trending", trending_command))
    application.add_handler(CommandHandler("newpairs", newpairs_command))
    application.add_handler(CommandHandler("migrations", migrations_command))
    application.add_handler(CommandHandler("monitor", monitor_command))
    
    await application.initialize()
    
    try:
        bot = application.bot
        await bot.send_message(
            chat_id=CHAT_ID,
            text=(
                "✅ *PRIME GEMS BOT ONLINE!*\n\n"
                "📊 *Redes:* Solana, ETH, BSC, Base\n"
                " *Alertas automáticos ativos*\n"
                "Use `/help` para comandos"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info("✅ Mensagem de boas-vindas enviada!")
    except Exception as e:
        logger.error(f"Erro boas-vindas: {e}")
    
    bot = application.bot
    asyncio.create_task(monitor_twitter_loop(bot))
    asyncio.create_task(monitor_newpairs_loop(bot))
    asyncio.create_task(monitor_migrations_loop(bot))
    
    logger.info("✅ Todos os monitores iniciados!")
    
    await application.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("✅ Bot rodando!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"💥 Bot falhou: {e}")
        raise
