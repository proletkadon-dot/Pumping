import requests
import time
import math
from datetime import datetime

TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

# Резервный список монет (60 шт)
SYMBOLS = [
    "SOL", "XRP", "ADA", "DOGE", "MATIC", "DOT", "AVAX", "SHIB", "LINK", "LTC",
    "NEAR", "ATOM", "FIL", "ALGO", "VET", "ICP", "EGLD", "THETA", "FTM", "SAND",
    "MANA", "AXS", "GALA", "ENJ", "ZIL", "KLAY", "CHZ", "ONE", "ICX", "XTZ",
    "AAVE", "BCH", "EOS", "TRX", "XLM", "ZEC", "DASH", "NEO", "ONT", "QTUM",
    "PEPE", "WIF", "BONK", "FLOKI", "NOT", "TON", "OP", "ARB", "SUI", "APT",
    "INJ", "SEI", "TIA", "PYTH", "JUP", "ONDO", "STRK", "ENA", "ETHFI", "1000LUNC"
]

CHECK_INTERVAL = 600               # 10 минут
LOOKBACK_CANDLES = 500             # для 1h свечей ~ 20 дней
MIN_TOUCHES = 3
LEVERAGE = 20
RISK_PERCENT = 1.0
TP_PERCENT = 2.0
SL_OFFSET_PERCENT = 0.5
LIMIT_OFFSET_PERCENT = 0.2
TIMEFRAMES = ['1h']                # упростим, используем только 1h для подтверждения

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

def get_klines_binance(symbol, interval='1h', limit=500):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=10).json()
        if isinstance(data, list) and len(data) > 50:
            closes = [float(c[4]) for c in data]
            highs = [float(c[2]) for c in data]
            lows = [float(c[3]) for c in data]
            return closes, highs, lows
    except:
        pass
    return [], [], []

def get_klines_coingecko(symbol, days=30):
    """Получает дневные свечи с CoinGecko (для поиска уровней)"""
    url = f"https://api.coingecko.com/api/v3/coins/{symbol.lower()}/market_chart?vs_currency=usd&days={days}&interval=daily"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        prices = data.get('prices', [])
        if not prices:
            return [], [], []
        closes = [p[1] for p in prices]
        # эмулируем high/low
        highs = closes[:]
        lows = closes[:]
        return closes, highs, lows
    except:
        return [], [], []

def get_klines(symbol, interval='1h', limit=500):
    # сначала пробуем Binance
    closes, highs, lows = get_klines_binance(symbol, interval, limit)
    if closes:
        return closes, highs, lows
    # fallback: CoinGecko (дневные)
    print(f"Binance недоступен для {symbol}, использую CoinGecko (дневные свечи)")
    return get_klines_coingecko(symbol, days=30)

def find_resistance(highs, current_price, lookback=200):
    highs_seg = highs[-lookback:]
    resistances = []
    for i in range(2, len(highs_seg)-2):
        if highs_seg[i] >= highs_seg[i-1] and highs_seg[i] >= highs_seg[i-2] and \
           highs_seg[i] >= highs_seg[i+1] and highs_seg[i] >= highs_seg[i+2]:
            resistances.append(highs_seg[i])
    resistances = sorted(set(resistances))
    nearest = min([r for r in resistances if r > current_price], default=None)
    return nearest

def count_touches(highs, lows, level_price, lookback=200):
    touches = 0
    for i in range(len(highs)):
        if abs(highs[i] - level_price) / level_price * 100 < 0.3:
            touches += 1
        if abs(lows[i] - level_price) / level_price * 100 < 0.3:
            touches += 1
    return touches

def get_rsi(closes, period=14):
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
    return 100 - 100/(1+avg_gain/avg_loss)

def analyze_coin(symbol):
    # Используем часовые свечи для поиска уровней
    closes, highs, lows = get_klines(symbol, '1h', LOOKBACK_CANDLES)
    if len(closes) < 100:
        return None
    current_price = closes[-1]
    resistance = find_resistance(highs, current_price, lookback=200)
    if not resistance:
        return None
    dist = (resistance - current_price) / current_price * 100
    if dist >= 1.0:
        return None
    
    # Количество касаний на том же таймфрейме (1h)
    touches = count_touches(highs, lows, resistance, lookback=200)
    if touches < MIN_TOUCHES:
        return None
    
    rsi = get_rsi(closes, 14)
    if rsi is None or rsi < 40:
        return None
    
    # Дополнительно: объём за 24h (опционально) – пропустим для простоты
    # Расчёт TP/SL
    entry_price = resistance * (1 - LIMIT_OFFSET_PERCENT / 100)
    tp1 = entry_price * (1 - TP_PERCENT / 100)
    sl_price = resistance * (1 + SL_OFFSET_PERCENT / 100)
    sl_percent = (sl_price - entry_price) / entry_price * 100
    risk_to_deposit = sl_percent * LEVERAGE * (RISK_PERCENT / 100)
    
    msg = f"""
🔴 SHORT: {symbol}

🎯 РЕШЕНИЕ: ⚠️ ЖДАТЬ ЛИМИТНЫЙ ВХОД
💭 Оценка: Лимитный ордер у зоны

🔍 Анализ:
• RSI 1h: {rsi:.1f}
• Касаний уровня: {touches}

📍 Причина входа: Уровень сопротивления {resistance:.6f}, расстояние {dist:.2f}%
Таймфрейм: 1h

💰 Точки входа:
• Вход: Лимитный {entry_price:.6f}
• Размер: {RISK_PERCENT:.1f}% депозита
• Плечо: {LEVERAGE}x
• До зоны: {dist:.2f}%

🎯 Тейк-профит:
• TP1 {TP_PERCENT}%: {tp1:.6f} (-{TP_PERCENT}%) — полное закрытие

🛑 Стоп-лосс:
• SL: {sl_price:.6f} (+{sl_percent:.2f}%)
• Оценка к депозиту: ~{risk_to_deposit:.2f}% (при {RISK_PERCENT}% позиции и {LEVERAGE}x)

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    return msg

def main():
    send_telegram("🚀 Бот SHORT (Binance/CoinGecko) запущен. Анализ списка из 60 монет.")
    print("Бот запущен. Анализ каждые 10 минут.")
    while True:
        for symbol in SYMBOLS:
            try:
                signal = analyze_coin(symbol)
                if signal:
                    send_telegram(signal)
                    time.sleep(2)
            except Exception as e:
                print(f"Ошибка {symbol}: {e}")
            time.sleep(0.5)
        print(f"{datetime.now()} - цикл завершён, жду {CHECK_INTERVAL} сек.")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()