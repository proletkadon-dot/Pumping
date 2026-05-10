import requests
import time
from datetime import datetime

TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

def get_klines(symbol, interval='5m', limit=300):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=10).json()
        if not isinstance(data, list) or len(data) < 100:
            return [], [], []
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        return closes, highs, []
    except:
        return [], [], []

def find_closest_resistance(highs, current_price, lookback=200):
    highs_seg = highs[-lookback:]
    resistances = []
    for i in range(2, len(highs_seg)-2):
        if highs_seg[i] >= highs_seg[i-1] and highs_seg[i] >= highs_seg[i-2] and \
           highs_seg[i] >= highs_seg[i+1] and highs_seg[i] >= highs_seg[i+2]:
            resistances.append(highs_seg[i])
    resistances = sorted(set(resistances))
    nearest = min([r for r in resistances if r > current_price], default=None)
    return nearest

def main():
    coins = ["SOL", "XRP", "ADA", "DOGE", "MATIC", "DOT", "AVAX", "SHIB", "LINK", "LTC",
             "NEAR", "ATOM", "FIL", "ALGO", "VET", "ICP", "EGLD", "THETA", "FTM", "SAND"]
    send_telegram("🔍 Диагностика SHORT: каждые 10 минут список монет с расстоянием до сопротивления.")
    while True:
        report_lines = []
        for sym in coins:
            closes, highs, _ = get_klines(sym, '5m', 300)
            if len(closes) < 100:
                continue
            current = closes[-1]
            resist = find_closest_resistance(highs, current)
            if resist:
                dist = (resist - current) / current * 100
                report_lines.append(f"{sym}: цена {current:.4f}, сопротивление {resist:.4f} (+{dist:.2f}%)")
            else:
                report_lines.append(f"{sym}: сопротивлений не найдено")
        msg = "📊 Отчёт по сопротивлениям:\n" + "\n".join(report_lines[:20])
        send_telegram(msg)
        print(f"{datetime.now()} - отчёт отправлен")
        time.sleep(600)

if __name__ == "__main__":
    main()