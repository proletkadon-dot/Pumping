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

def get_klines(symbol, interval='1m', limit=30):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=10).json()
        if not isinstance(data, list) or len(data) < 25:
            return [], [], [], []
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        volumes = [float(c[5]) for c in data]
        return closes, highs, lows, volumes
    except Exception as e:
        print(f"Ошибка: {e}")
        return [], [], [], []

def calculate_ema(closes, period):
    if len(closes) < period:
        return None
    mult = 2/(period+1)
    ema = closes[0]
    for p in closes[1:]:
        ema = (p - ema)*mult + ema
    return ema

def diagnostics():
    symbol = "SOL"
    closes, highs, lows, volumes = get_klines(symbol, '1m', 30)
    if len(closes) < 25:
        send_telegram(f"Диагностика {symbol}: недостаточно свечей ({len(closes)})")
        return
    curr_price = closes[-1]
    avg_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
    curr_volume = volumes[-1]
    volume_surge = (curr_volume > avg_volume * 1.5) if avg_volume > 0 else False
    
    if len(closes) >= 4:
        change_1m = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] != 0 else 0
        change_3m = (closes[-1] - closes[-4]) / closes[-4] * 100 if closes[-4] != 0 else 0
        avg_change_3m = change_3m / 3
        if avg_change_3m > 0:
            acc = change_1m / avg_change_3m if avg_change_3m != 0 else 0
            pump_accel = (acc > 1.2) and change_1m > 0
            dump_accel = False
        elif avg_change_3m < 0:
            acc = abs(change_1m / avg_change_3m) if avg_change_3m != 0 else 0
            dump_accel = (acc > 1.2) and change_1m < 0
            pump_accel = False
        else:
            pump_accel = dump_accel = False
    else:
        pump_accel = dump_accel = False
    
    if len(closes) >= 5:
        price_range_last_5 = (max(closes[-5:]) - min(closes[-5:])) / closes[-5] * 100 if closes[-5] != 0 else 0
        vol_increase = (volumes[-1] > volumes[-2] > volumes[-3]) if len(volumes) >= 3 else False
        divergence = (price_range_last_5 < 0.2) and vol_increase
    else:
        divergence = False
    
    ema5 = calculate_ema(closes, 5)
    ema10 = calculate_ema(closes, 10)
    ema5_prev = calculate_ema(closes[:-1], 5)
    ema10_prev = calculate_ema(closes[:-1], 10)
    impulse_up = (ema5_prev <= ema10_prev and ema5 > ema10) if ema5_prev and ema10_prev else False
    impulse_down = (ema5_prev >= ema10_prev and ema5 < ema10) if ema5_prev and ema10_prev else False
    
    pump_factors = sum([volume_surge, pump_accel, divergence, impulse_up])
    dump_factors = sum([volume_surge, dump_accel, divergence, impulse_down])
    
    msg = f"""
Диагностика {symbol} в {datetime.now().strftime('%H:%M:%S')}
Цена: ${curr_price:.2f}
Объём: {curr_volume:.0f} (средний {avg_volume:.0f}) → всплеск {volume_surge}
Изм. 1м: {change_1m:.2f}%, 3м ср: {avg_change_3m:.2f}% → ускорение вверх {pump_accel}, вниз {dump_accel}
Дивергенция: {divergence}
Импульс: вверх {impulse_up}, вниз {impulse_down}
ИТОГО: PUMP факторы = {pump_factors}, DUMP факторы = {dump_factors}
"""
    send_telegram(msg)

def main():
    send_telegram("🚀 Диагностический режим запущен. Отчёт каждую минуту.")
    while True:
        diagnostics()
        time.sleep(60)

if __name__ == "__main__":
    main()