import requests
import time
import math
from datetime import datetime

TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

def get_klines(symbol, interval='5m', limit=500):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=10).json()
        if not isinstance(data, list) or len(data) < 100:
            return [], [], []
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        return closes, highs
    except:
        return [], []

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

def get_rsi(symbol, timeframe='5m', period=14):
    closes, _ = get_klines(symbol, interval=timeframe, limit=period+5)
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

def count_touches(symbol, level, timeframe='5m', days=3):
    intervals = {'5m': 12*24, '15m': 4*24, '30m': 2*24, '1h': 24}
    limit = intervals.get(timeframe, 100) * days
    _, highs = get_klines(symbol, interval=timeframe, limit=limit)
    touches = 0
    for h in highs:
        if abs(h - level) / level * 100 < 0.3:
            touches += 1
    return touches

def main():
    symbol = "SOL"
    send_telegram(f"🔍 Диагностика {symbol} запущена. Отчёт каждые 5 мин.")
    while True:
        closes, highs = get_klines(symbol, '5m', 500)
        if len(closes) < 300:
            send_telegram("Недостаточно данных")
        else:
            price = closes[-1]
            res = find_resistance(highs, price)
            dist = (res - price) / price * 100 if res else None
            rsi5 = get_rsi(symbol, '5m')
            rsi1h = get_rsi(symbol, '1h')
            touches = count_touches(symbol, res, '5m', 3) if res else 0
            msg = f"📊 {symbol}\nЦена: {price:.4f}\nСопротивление: {res:.4f} (+{dist:.2f}%)" if res else f"Сопротивление не найдено"
            msg += f"\nRSI 5m: {rsi5:.1f}, RSI 1h: {rsi1h:.1f}\nКасаний: {touches}"
            send_telegram(msg)
        time.sleep(300)

if __name__ == "__main__":
    main()