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

def get_klines(symbol, interval='5m', limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=15).json()
        if not isinstance(data, list) or len(data) < 100:
            return [], [], [], []
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        volumes = [float(c[5]) for c in data]
        return closes, highs, lows, volumes
    except:
        return [], [], [], []

def find_support_resistance(highs, lows, current_price, lookback=200):
    highs_seg = highs[-lookback:]
    lows_seg = lows[-lookback:]
    supports = []
    resistances = []
    for i in range(2, len(lows_seg)-2):
        if lows_seg[i] <= lows_seg[i-1] and lows_seg[i] <= lows_seg[i-2] and \
           lows_seg[i] <= lows_seg[i+1] and lows_seg[i] <= lows_seg[i+2]:
            supports.append(lows_seg[i])
    for i in range(2, len(highs_seg)-2):
        if highs_seg[i] >= highs_seg[i-1] and highs_seg[i] >= highs_seg[i-2] and \
           highs_seg[i] >= highs_seg[i+1] and highs_seg[i] >= highs_seg[i+2]:
            resistances.append(highs_seg[i])
    supports = sorted(set(supports))
    resistances = sorted(set(resistances))
    nearest_support = max([s for s in supports if s < current_price], default=None)
    nearest_resistance = min([r for r in resistances if r > current_price], default=None)
    return nearest_support, nearest_resistance

def count_touches(symbol, level_price, timeframe='5m', lookback_days=3):
    intervals = {'5m': 12*24, '15m': 4*24, '30m': 2*24, '1h': 24, '4h': 6}
    limit = intervals.get(timeframe, 100) * lookback_days
    _, highs, lows, _ = get_klines(symbol, interval=timeframe, limit=limit)
    if not highs:
        return 0
    touches = 0
    for i in range(len(highs)):
        if abs(highs[i] - level_price) / level_price * 100 < 0.2:
            touches += 1
        if abs(lows[i] - level_price) / level_price * 100 < 0.2:
            touches += 1
    return touches

def get_rsi(symbol, timeframe='5m', period=14):
    closes, _, _, _ = get_klines(symbol, interval=timeframe, limit=period+10)
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

def main():
    symbol = "SOL"
    send_telegram(f"🔍 Диагностика {symbol} запущена. Отчёт каждые 5 минут.")
    while True:
        closes_5m, highs_5m, lows_5m, _ = get_klines(symbol, '5m', 1000)
        if len(closes_5m) < 500:
            send_telegram(f"Недостаточно данных для {symbol}")
            time.sleep(300)
            continue
        current_price = closes_5m[-1]
        support, resistance = find_support_resistance(highs_5m, lows_5m, current_price, lookback=200)
        
        report = f"Диагностика {symbol} в {datetime.now().strftime('%H:%M:%S')}\nЦена: {current_price:.4f}\n"
        if resistance:
            dist_to_res = (resistance - current_price) / current_price * 100
            report += f"Ближайшее сопротивление: {resistance:.4f} (+{dist_to_res:.2f}%)\n"
            # Подсчёт касаний на разных ТФ
            touches_info = []
            for tf in ['5m', '15m', '30m', '1h', '4h']:
                touches = count_touches(symbol, resistance, tf, lookback_days=3)
                touches_info.append(f"{tf}:{touches}")
            report += "Касания сопротивления: " + " | ".join(touches_info) + "\n"
        else:
            report += "Сопротивление не найдено\n"
        
        rsi_5m = get_rsi(symbol, '5m')
        rsi_1h = get_rsi(symbol, '1h')
        report += f"RSI 5m: {rsi_5m:.1f}, RSI 1h: {rsi_1h:.1f}\n"
        
        send_telegram(report)
        time.sleep(300)

if __name__ == "__main__":
    main()