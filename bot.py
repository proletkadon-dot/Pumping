import requests
import time
import math
from datetime import datetime

def get_klines(symbol, interval='5m', limit=500):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=10).json()
        if not isinstance(data, list) or len(data) < 100:
            return [], [], []
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        return closes, highs, lows
    except:
        return [], [], []

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

def count_touches(highs, level, tolerance=0.002):
    touches = 0
    for h in highs:
        if abs(h - level) / level < tolerance:
            touches += 1
    return touches

def main():
    test_coins = ["SOL", "XRP", "ADA", "DOGE", "MATIC"]
    print("Диагностика SHORT сигналов. Ожидайте...")
    while True:
        print(f"\n--- {datetime.now().strftime('%H:%M:%S')} ---")
        for sym in test_coins:
            closes, highs, lows = get_klines(sym, '5m', 500)
            if len(closes) < 300:
                print(f"{sym}: недостаточно данных")
                continue
            price = closes[-1]
            res = find_resistance(highs, price)
            if res:
                dist = (res - price) / price * 100
                print(f"{sym}: цена {price:.4f}, сопротивление {res:.4f} (+{dist:.2f}%)")
                # RSI на 5m и 1h
                rsi_5m = get_rsi(closes)
                closes_1h, _, _ = get_klines(sym, '1h', 50)
                rsi_1h = get_rsi(closes_1h) if len(closes_1h) >= 15 else None
                touches = count_touches(highs, res)
                print(f"   RSI 5m: {rsi_5m:.1f}, RSI 1h: {rsi_1h:.1f if rsi_1h else '?'}, касаний: {touches}")
            else:
                print(f"{sym}: сопротивление не найдено")
        time.sleep(600)

if __name__ == "__main__":
    main()