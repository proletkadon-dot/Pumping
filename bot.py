import asyncio
import aiohttp
import schedule
import time
import math
import json
import requests
from datetime import datetime
from collections import deque
from telegram import Bot
from telegram.constants import ParseMode
from asgiref.sync import sync_to_async
from dotenv import load_dotenv
import os

# ========== НАСТРОЙКИ ==========
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

MAX_COINS = 800                         # анализируем максимум монет
MIN_24H_VOLUME_USDT = 300_000           # мин. объём $300k
TIMEFRAMES_RSI = ['5m', '15m', '1h', '4h']
# Пороги для сигнала (SHORT)
RSI_4H_MIN = 65                         # RSI 4h > 65
RSI_1H_MIN = 65                         # RSI 1h > 65
CHANGE_4H_MIN = 2.0                     # рост за 4ч > 2%
FUNDING_MIN = 0.0                       # фандинг > 0 (положительный)
VOLUME_24H_MIN = 5_000_000              # мин. объём $5M
# =================================

bot = Bot(token=TELEGRAM_TOKEN)

# ---------- ФУНКЦИИ ПОЛУЧЕНИЯ ДАННЫХ ----------
async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=10) as response:
            return await response.json()
    except Exception as e:
        print(f"Ошибка запроса {url}: {e}")
        return None

async def get_klines(session, symbol, interval='5m', limit=100):
    # 1. Bybit
    interval_map = {'5m': '5', '15m': '15', '1h': '60', '4h': '240'}
    url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}USDT&interval={interval_map.get(interval, '5')}&limit={limit}"
    data = await fetch_json(session, url)
    if data and data.get('retCode') == 0 and data.get('result', {}).get('list'):
        klines = data['result']['list']
        closes = [float(k[4]) for k in klines]
        closes.reverse()
        return closes
    
    # 2. KuCoin
    url = f"https://api.kucoin.com/api/v1/market/candles?type={interval}&symbol={symbol}-USDT&limit={limit}"
    data = await fetch_json(session, url)
    if data and data.get('code') == '200000' and data.get('data'):
        candles = data['data']
        return [float(c[2]) for c in candles]
    
    # 3. Binance (fallback)
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
    data = await fetch_json(session, url)
    if data and isinstance(data, list) and len(data) > 0:
        return [float(c[4]) for c in data]
    return []

async def get_price_change(session, symbol, interval, back_minutes):
    closes = await get_klines(session, symbol, interval, 2)
    if len(closes) < 2:
        return None
    return (closes[-1] - closes[-2]) / closes[-2] * 100

async def get_24h_stats(session, symbol):
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}USDT"
    data = await fetch_json(session, url)
    if data and 'priceChangePercent' in data:
        return float(data['priceChangePercent']), float(data['quoteVolume'])
    return None, None

async def get_funding(session, symbol):
    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}USDT"
    data = await fetch_json(session, url)
    if data and 'lastFundingRate' in data:
        return float(data['lastFundingRate']) * 100
    return None

async def get_realtime_price(session, symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
    data = await fetch_json(session, url)
    if data and 'price' in data:
        return float(data['price'])
    return None

async def get_all_usdt_pairs(session):
    # 1. KuCoin
    url = "https://api.kucoin.com/api/v1/symbols"
    data = await fetch_json(session, url)
    if data and data.get('code') == '200000':
        symbols = [s['symbol'] for s in data['data'] if s['symbol'].endswith('-USDT')]
        tickers_url = "https://api.kucoin.com/api/v1/market/allTickers"
        tickers_data = await fetch_json(session, tickers_url)
        if tickers_data and tickers_data.get('code') == '200000':
            tickers = {t['symbol']: float(t['volValue']) for t in tickers_data['data']['ticker'] if 'volValue' in t}
            sorted_symbols = sorted(symbols, key=lambda s: tickers.get(s, 0), reverse=True)
            coins = []
            for sym in sorted_symbols[:MAX_COINS]:
                base = sym.replace('-USDT', '')
                vol = tickers.get(sym, 0)
                if vol >= MIN_24H_VOLUME_USDT:
                    coins.append(base)
            return coins
    return None

def calculate_rsi(closes, period=14):
    if len(closes) < period+1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(diff if diff>0 else 0)
        losses.append(-diff if diff<0 else 0)
    avg_gain = sum(gains[-period:])/period
    avg_loss = sum(losses[-period:])/period
    if avg_loss == 0:
        return 100
    return round(100 - 100/(1+avg_gain/avg_loss), 2)

# ---------- АНАЛИЗ МОНЕТЫ ----------
async def analyze_coin(session, symbol):
    # Получаем RSI
    rsis = {}
    for tf in TIMEFRAMES_RSI:
        closes = await get_klines(session, symbol, tf, 50)
        if not closes:
            return None
        rsis[tf] = calculate_rsi(closes)
        if rsis[tf] is None:
            return None

    # Получаем изменения цены
    change_24h, volume_24h = await get_24h_stats(session, symbol)
    if change_24h is None:
        return None
    change_15m = await get_price_change(session, symbol, '15m', 15) or 0
    change_1h = await get_price_change(session, symbol, '1h', 60) or 0
    change_4h = await get_price_change(session, symbol, '4h', 240) or 0

    # Получаем фандинг
    funding = await get_funding(session, symbol)

    # Проверка условий
    if (rsis['4h'] >= RSI_4H_MIN and rsis['1h'] >= RSI_1H_MIN and
        change_4h >= CHANGE_4H_MIN and funding is not None and funding >= FUNDING_MIN and
        volume_24h >= VOLUME_24H_MIN):
        
        # Формируем логическое обоснование
        reasons = []
        if rsis['4h'] >= RSI_4H_MIN:
            reasons.append(f"RSI 4h = {rsis['4h']} (выше {RSI_4H_MIN}) – сильная перекупленность")
        if rsis['1h'] >= RSI_1H_MIN:
            reasons.append(f"RSI 1h = {rsis['1h']} (выше {RSI_1H_MIN}) – подтверждение перекупленности")
        if change_4h >= CHANGE_4H_MIN:
            reasons.append(f"рост за 4ч = {change_4h:.2f}% (выше {CHANGE_4H_MIN}%) – импульс исчерпан")
        if funding >= FUNDING_MIN:
            reasons.append(f"фандинг = {funding:.2f}% – лонгисты платят шортистам")
        if volume_24h >= VOLUME_24H_MIN:
            reasons.append(f"объём 24ч = {volume_24h/1e6:.2f}M USDT – высокая ликвидность")
        explanation = " ".join(reasons)

        # Получаем актуальную цену
        real_price = await get_realtime_price(session, symbol)
        if real_price is None:
            return None

        msg = f"""
🔻 <b>SHORT СИГНАЛ</b> <b>{symbol}</b> | {real_price:.4f}

<b>RSI:</b> 5m {rsis['5m']} | 15m {rsis['15m']} | 1h {rsis['1h']} | 4h {rsis['4h']}
<b>Изменение:</b> 24h {change_24h:+.2f}% | 15m {change_15m:+.2f}% | 1h {change_1h:+.2f}% | 4h {change_4h:+.2f}%
<b>Объём 24h:</b> {volume_24h/1e6:.2f}M
<b>Фандинг:</b> {funding:+.4f}% ✅

💡 <b>Логическое обоснование:</b> {explanation}. Совокупность факторов указывает на высокую вероятность коррекции вниз.

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return msg
    return None

# ---------- ОСНОВНАЯ ФУНКЦИЯ АНАЛИЗА ВСЕГО РЫНКА ----------
async def scan_market():
    async with aiohttp.ClientSession() as session:
        print(f"[{datetime.now()}] Начинаю анализ всего рынка...")
        try:
            coins = await get_all_usdt_pairs(session)
            if not coins:
                print("Не удалось получить список монет")
                return
            
            signals = []
            for idx, symbol in enumerate(coins):
                try:
                    msg = await analyze_coin(session, symbol)
                    if msg:
                        signals.append(msg)
                        print(f"✅ Сигнал для {symbol}")
                except Exception as e:
                    print(f"Ошибка {symbol}: {e}")
                await asyncio.sleep(0.2)
                if idx % 50 == 0:
                    print(f"Обработано {idx}/{len(coins)} монет")
            
            for msg in signals:
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.HTML)
                await asyncio.sleep(2)
            print(f"✅ Анализ завершён. Сигналов: {len(signals)}")
        except Exception as e:
            print(f"Ошибка сканирования: {e}")

def run_scan():
    asyncio.run(scan_market())

# ---------- ЗАПУСК ПО РАСПИСАНИЮ ----------
if __name__ == "__main__":
    # Запускаем первое сканирование сразу
    run_scan()
    
    # Настраиваем расписание: каждые 4 часа (можно изменить)
    schedule.every(4).hours.do(run_scan)
    
    print("Бот запущен. Анализ всего рынка каждые 4 часа.")
    while True:
        schedule.run_pending()
        time.sleep(60)