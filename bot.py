import requests
import time
import math
from datetime import datetime

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

# Список монет для анализа (можно заменить на свой)
COINS_LIST = [
    "SOL", "XRP", "ADA", "DOGE", "MATIC", "DOT", "AVAX", "SHIB", "LINK", "LTC",
    "NEAR", "ATOM", "FIL", "ALGO", "VET", "ICP", "EGLD", "THETA", "FTM", "SAND",
    "MANA", "AXS", "GALA", "ENJ", "ZIL", "KLAY", "CHZ", "ONE", "ICX", "XTZ"
]

CHECK_INTERVAL = 60                     # проверка каждую минуту
MIN_5MIN_CHANGE = 0.5                   # минимальное изменение за 5 мин (%)
LEVERAGE = 2
VOLUME_SURGE_FACTOR = 1.5
PRICE_ACCELERATION_THRESHOLD = 1.2
MIN_AGREEMENT = 2                       # 2 из 4 факторов
# =======================================

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
        print(f"Ошибка свечей {symbol}: {e}")
        return [], [], [], []

def calculate_ema(closes, period):
    if len(closes) < period:
        return None
    mult = 2/(period+1)
    ema = closes[0]
    for p in closes[1:]:
        ema = (p - ema)*mult + ema
    return ema

def analyze_coin(symbol):
    closes, highs, lows, volumes = get_klines(symbol, '1m', 30)
    if len(closes) < 25:
        return None, None, {}
    
    curr_price = closes[-1]
    avg_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
    curr_volume = volumes[-1]
    volume_surge = (curr_volume > avg_volume * VOLUME_SURGE_FACTOR) if avg_volume > 0 else False
    
    # Ускорение
    if len(closes) >= 4:
        change_1m = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] != 0 else 0
        change_3m = (closes[-1] - closes[-4]) / closes[-4] * 100 if closes[-4] != 0 else 0
        avg_change_3m = change_3m / 3
        if avg_change_3m > 0:
            acc = change_1m / avg_change_3m if avg_change_3m != 0 else 0
            pump_accel = (acc > PRICE_ACCELERATION_THRESHOLD) and change_1m > 0
            dump_accel = False
        elif avg_change_3m < 0:
            acc = abs(change_1m / avg_change_3m) if avg_change_3m != 0 else 0
            dump_accel = (acc > PRICE_ACCELERATION_THRESHOLD) and change_1m < 0
            pump_accel = False
        else:
            pump_accel = dump_accel = False
    else:
        pump_accel = dump_accel = False
    
    # Дивергенция
    if len(closes) >= 5:
        price_range_last_5 = (max(closes[-5:]) - min(closes[-5:])) / closes[-5] * 100 if closes[-5] != 0 else 0
        vol_increase = (volumes[-1] > volumes[-2] > volumes[-3]) if len(volumes) >= 3 else False
        divergence = (price_range_last_5 < 0.2) and vol_increase
    else:
        divergence = False
    
    # Импульс EMA
    ema5 = calculate_ema(closes, 5)
    ema10 = calculate_ema(closes, 10)
    ema5_prev = calculate_ema(closes[:-1], 5)
    ema10_prev = calculate_ema(closes[:-1], 10)
    impulse_up = (ema5_prev <= ema10_prev and ema5 > ema10) if ema5_prev and ema10_prev else False
    impulse_down = (ema5_prev >= ema10_prev and ema5 < ema10) if ema5_prev and ema10_prev else False
    
    pump_factors = volume_surge + pump_accel + divergence + impulse_up
    dump_factors = volume_surge + dump_accel + divergence + impulse_down
    
    # Фильтр по изменению за 5 минут
    if len(closes) >= 5:
        change_5m = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] != 0 else 0
        if abs(change_5m) < MIN_5MIN_CHANGE:
            return None, None, {'pump': pump_factors, 'dump': dump_factors}
    
    # RSI для доп. информации
    def rsi(closes, period=14):
        if len(closes) < period+1: return None
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i]-closes[i-1]
            gains.append(diff if diff>0 else 0)
            losses.append(-diff if diff<0 else 0)
        avg_gain = sum(gains[-period:])/period
        avg_loss = sum(losses[-period:])/period
        if avg_loss == 0: return 100
        return 100 - 100/(1+avg_gain/avg_loss)
    rsi_val = rsi(closes)
    
    if pump_factors >= MIN_AGREEMENT:
        if rsi_val and rsi_val > 80:
            return None, None, {'pump': pump_factors, 'dump': dump_factors}
        entry = curr_price
        tp = entry * 1.02
        sl = entry * 0.995
        msg = f"""
🔥 <b>ПОТЕНЦИАЛЬНЫЙ ПАМП</b> на {symbol} 🔥

💰 Вход: ${entry:.6f} | TP: ${tp:.6f} (+2%) | SL: ${sl:.6f} (-0.5%) | Плечо: {LEVERAGE}x

Факторы: {pump_factors}/4 (объём {volume_surge}, ускорение {pump_accel}, дивергенция {divergence}, импульс {impulse_up}) | RSI: {rsi_val:.1f}
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return 'pump', msg, {}
    elif dump_factors >= MIN_AGREEMENT:
        if rsi_val and rsi_val < 20:
            return None, None, {'pump': pump_factors, 'dump': dump_factors}
        entry = curr_price
        tp = entry * 0.98
        sl = entry * 1.005
        msg = f"""
💀 <b>ПОТЕНЦИАЛЬНЫЙ ДАМП</b> на {symbol} 💀

💰 Вход: ${entry:.6f} | TP: ${tp:.6f} (-2%) | SL: ${sl:.6f} (+0.5%) | Плечо: {LEVERAGE}x

Факторы: {dump_factors}/4 (объём {volume_surge}, ускорение {dump_accel}, дивергенция {divergence}, импульс {impulse_down}) | RSI: {rsi_val:.1f}
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return 'dump', msg, {}
    else:
        return None, None, {'pump': pump_factors, 'dump': dump_factors}

def main():
    send_telegram("🚀 Бот 2 (фиксированный список монет) запущен. Анализ каждую минуту.")
    print(f"Запущено. Монет в списке: {len(COINS_LIST)}. Порог {MIN_AGREEMENT}/4, мин. изменение {MIN_5MIN_CHANGE}%")
    while True:
        total_coins = 0
        signals = 0
        for symbol in COINS_LIST:
            total_coins += 1
            try:
                signal_type, msg, factors = analyze_coin(symbol)
                if msg:
                    send_telegram(msg)
                    signals += 1
                    print(f"Сигнал {signal_type} для {symbol} отправлен")
                    time.sleep(2)
                # else:
                #     print(f"{symbol}: pump={factors.get('pump')}, dump={factors.get('dump')}")
            except Exception as e:
                print(f"Ошибка {symbol}: {e}")
            time.sleep(0.3)
        print(f"{datetime.now()} - Обработано {total_coins} монет, сигналов: {signals}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()