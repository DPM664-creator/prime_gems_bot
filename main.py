import os
import asyncio
import aiohttp
from telegram import Bot
from telegram.constants import ParseMode

# ==========================================
# CONFIGURAÇÕES (Pegando do ambiente/hospedagem)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# ==========================================
# TRADUÇÕES (PT, EN, ES)
# ==========================================
TRANSLATIONS = {
    "pt": {
        "welcome": "✅ *Radar Binance ATIVO*\nMonitorando Solana, ETH e BSC em busca de oportunidades\\.",
        "headline": "🎯 *RADAR BINANCE: ALVO IDENTIFICADO* 🎯",
        "token": "Token", "network": "Rede", "volume": "Volume 24h",
        "liquidity": "Liquidez", "links": "Links",
        "dyor": "Faça sua própria pesquisa \\(DYOR\\)\\."
    },
    "en": {
        "welcome": "✅ *Binance Radar ACTIVE*\nMonitoring Solana, ETH and BSC for opportunities\\.",
        "headline": "🎯 *BINANCE RADAR: TARGET IDENTIFIED* 🎯",
        "token": "Token", "network": "Network", "volume": "24h Volume",
        "liquidity": "Liquidity", "links": "Links",
        "dyor": "Do your own research \\(DYOR\\)\\."
    },
    "es": {
        "welcome": "✅ *Radar Binance ACTIVO*\nMonitoreando Solana, ETH y BSC en busca de oportunidades\\.",
        "headline": "🎯 *RADAR BINANCE: OBJETIVO IDENTIFICADO* ",
        "token": "Token", "network": "Red", "volume": "Volumen 24h",
        "liquidity": "Liquidez", "links": "Enlaces",
        "dyor": "Haz tu propia investigación \\(DYOR\\)\\."
    }
}

LANG = "pt" 

# ==========================================
# BUSCA DE DADOS NA DEXSCREENER
# ==========================================
async def fetch_data():
    url = "https://api.dexscreener.com/token-boosts/latest/v1"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
        except Exception as e:
            print(f"Erro ao buscar dados: {e}")
            return []

# ==========================================
# LOOP DE MONITORAMENTO
# ==========================================
async def monitorar():
    bot = Bot(token=TELEGRAM_TOKEN)
    print("🚀 Bot iniciado. Monitorando Solana, ETH e BSC...")
    
    await bot.send_message(
        chat_id=CHAT_ID,
        text=TRANSLATIONS[LANG]["welcome"],
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    while True:
        try:
            data = await fetch_data()
            for pair in data:
                chain = pair.get("chainId", "")
                vol = pair.get("volume", {}).get("h24", 0) or 0
                liq = pair.get("liquidity", {}).get("usd", 0) or 0
                
                if chain in ["solana", "ethereum", "bsc"] and vol > 500000 and liq > 50000:
                    t = TRANSLATIONS[LANG]
                    
                    symbol = pair.get("baseToken", {}).get("symbol", "N/A")
                    name = pair.get("baseToken", {}).get("name", "N/A")
                    pair_url = pair.get("url", "")
                    
                    msg = (
                        f"{t['headline']}\n\n"
                        f"💎 *{t['token']}:* ${symbol} \\({name}\\)\n"
                        f"🔗 *{t['network']}:* {chain.upper()}\n"
                        f"📈 *{t['volume']}:* \\${vol:,.0f}\n"
                        f"💧 *{t['liquidity']}:* \\${liq:,.0f}\n\n"
                        f"📊 *{t['links']}:* \\[DexScreener\\]\\({pair_url}\\)\n\n"
                        f"⚠️ _{t['dyor']}_"
                    )
                    
                    await bot.send_message(
                        chat_id=CHAT_ID,
                        text=msg,
                        parse_mode=ParseMode.MARKDOWN_V2,
                        disable_web_page_preview=True
                    )
                    await asyncio.sleep(5)
            
            await asyncio.sleep(300) 
            
        except Exception as e:
            print(f"Erro no loop: {e}")
            await asyncio.sleep(60)

# ==========================================
# INÍCIO
# ==========================================
if __name__ == "__main__":
    asyncio.run(monitorar())
