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

def get_klines(symbol, interval='5m', limit=200):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=10).json()
        if not isinstance(data, list) or len(data) < 100:
            return [], []
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        return closes, highs
    except:
        return [], []

def find_resistance(highs, current_price, lookback=150):
    # Находим локальные максимумы
    resistances = []
    for i in range(2, len(highs)-2):
        if highs[i] >= highs[i-1] and highs[i] >= highs[i-2] and highs[i] >= highs[i+1] and highs[i] >= highs[i+2]:
            resistances.append(highs[i])
    resistances = sorted(set(resistances))
    # Ближайшее сопротивление выше цены
    nearest = min([r for r in resistances if r > current_price], default=None)
    return nearest

def main():
    coins = ["SOL", "XRP", "ADA", "DOGE", "MATIC", "DOT", "AVAX", "SHIB", "LINK", "LTC",
             "NEAR", "ATOM", "FIL", "ALGO", "VET", "ICP", "EGLD", "THETA", "FTM", "SAND",
             "AAVE", "BCH", "EOS", "TRX", "XLM", "ZEC", "PEPE", "WIF", "BONK", "FLOKI"]
    send_telegram("🔍 Поиск монет, близких к сопротивлению (отчёт каждые 10 минут)")
    while True:
        report_lines = []
        for sym in coins:
            closes, highs = get_klines(sym, '5m', 200)
            if not closes:
                continue
            price = closes[-1]
            res = find_resistance(highs, price)
            if res:
                dist = (res - price) / price * 100
                if dist < 2.0:
                    report_lines.append(f"{sym}: цена {price:.4f}, сопротивление {res:.4f} (+{dist:.2f}%)")
        if report_lines:
            msg = "📊 Монеты близкие к сопротивлению:\n" + "\n".join(report_lines[:15])
        else:
            msg = "Нет монет на расстоянии <2% от сопротивления."
        send_telegram(msg)
        print(f"{datetime.now()} - отчёт отправлен")
        time.sleep(600)

if __name__ == "__main__":
    main()