import requests
import time
import math
from datetime import datetime

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

CHECK_INTERVAL = 180            # 3 минуты
TOP_COINS = 150
MIN_VOLUME_USDT = 400_000
MIN_5MIN_CHANGE = 2.0
LEVERAGE = 2

VOLUME_SURGE_FACTOR = 2.5
PRICE_ACCELERATION_THRESHOLD = 1.5
MIN_AGREEMENT = 3               # 3 из 4 факторов

# ===== НОВЫЕ ФИЛЬТРЫ =====
ENABLE_1H_TREND_FILTER = True   # включить фильтр по 1h тренду
ENABLE_ATR_FILTER = True        # включить фильтр ATR
MIN_ATR_PERCENT = 0.5           # минимальный ATR в процентах от цены (0.5%)
# =========================

def send_telegram(text):
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

def get_top_coins_by_volume(limit=50):
    url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page={limit}&page=1&sparkline=false"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        if not isinstance(data, list):
            return []
        exclude = ['BTC','ETH','USDT','USDC','DAI','BUSD','TUSD','FDUSD']
        coins = []
        for coin in data:
            sym = coin['symbol'].upper()
            if sym in exclude: continue
            if 'stable' in coin['name'].lower(): continue
            vol = coin.get('total_volume', 0)
            if vol >= MIN_VOLUME_USDT:
                coins.append({'symbol': sym, 'volume': vol})
        return coins[:TOP_COINS]
    except Exception as e:
        print("Ошибка CoinGecko:", e)
        return []

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
    except:
        return [], [], [], []

def calculate_atr_percent(highs, lows, closes, period=14):
    """Возвращает ATR в процентах от текущей цены"""
    if len(closes) < period+1:
        return None
    tr = []
    for i in range(1, len(closes)):
        hl = highs[i]-lows[i]
        hc = abs(highs[i]-closes[i-1])
        lc = abs(lows[i]-closes[i-1])
        tr.append(max(hl, hc, lc))
    if len(tr) < period:
        return None
    atr_abs = sum(tr[-period:]) / period
    return (atr_abs / closes[-1]) * 100 if closes[-1] != 0 else None

def calculate_ema(closes, period):
    if len(closes) < period:
        return None
    mult = 2/(period+1)
    ema = closes[0]
    for p in closes[1:]:
        ema = (p - ema) * mult + ema
    return ema

def get_1h_sma20(symbol):
    """Возвращает SMA20 на 1-часовом таймфрейме и текущую цену"""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=1h&limit=30"
    try:
        data = requests.get(url, timeout=10).json()
        if not isinstance(data, list) or len(data) < 20:
            return None, None
        closes = [float(c[4]) for c in data]
        sma20 = sum(closes[-20:]) / 20
        return closes[-1], sma20
    except:
        return None, None

def detect_pump_dump(symbol):
    closes, highs, lows, volumes = get_klines(symbol, '1m', 30)
    if len(closes) < 25:
        return None, {}
    curr_price = closes[-1]
    
    # 1. Всплеск объёма
    avg_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
    curr_volume = volumes[-1]
    volume_surge = (curr_volume > avg_volume * VOLUME_SURGE_FACTOR) if avg_volume > 0 else False
    
    # 2. Ускорение цены
    if len(closes) >= 4:
        change_1m = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] != 0 else 0
        change_3m = (closes[-1] - closes[-4]) / closes[-4] * 100 if closes[-4] != 0 else 0
        avg_change_3m = change_3m / 3
        if avg_change_3m > 0:
            acceleration = change_1m / avg_change_3m if avg_change_3m != 0 else 0
            pump_accel = (acceleration > PRICE_ACCELERATION_THRESHOLD) and change_1m > 0
            dump_accel = False
        elif avg_change_3m < 0:
            acceleration = abs(change_1m / avg_change_3m) if avg_change_3m != 0 else 0
            dump_accel = (acceleration > PRICE_ACCELERATION_THRESHOLD) and change_1m < 0
            pump_accel = False
        else:
            pump_accel = dump_accel = False
    else:
        pump_accel = dump_accel = False
    
    # 3. Дивергенция объёма и цены
    if len(closes) >= 5:
        price_range_last_5 = (max(closes[-5:]) - min(closes[-5:])) / closes[-5] * 100 if closes[-5] != 0 else 0
        vol_increase = (volumes[-1] > volumes[-2] > volumes[-3]) if len(volumes) >= 3 else False
        divergence = (price_range_last_5 < 0.2) and vol_increase
    else:
        divergence = False
    
    # 4. Импульс EMA5/10
    ema5 = calculate_ema(closes, 5)
    ema10 = calculate_ema(closes, 10)
    ema5_prev = calculate_ema(closes[:-1], 5)
    ema10_prev = calculate_ema(closes[:-1], 10)
    impulse_up = (ema5_prev <= ema10_prev and ema5 > ema10) if ema5_prev and ema10_prev else False
    impulse_down = (ema5_prev >= ema10_prev and ema5 < ema10) if ema5_prev and ema10_prev else False
    
    pump_factors = sum([volume_surge, pump_accel, divergence, impulse_up])
    dump_factors = sum([volume_surge, dump_accel, divergence, impulse_down])
    
    # Доп. фильтр: изменение за 5 минут
    if len(closes) >= 5:
        change_5m = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] != 0 else 0
        if abs(change_5m) < MIN_5MIN_CHANGE:
            return None, {}
    
    # RSI для доп. осторожности
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
    
    # ------------------------------------
    # НОВЫЕ ФИЛЬТРЫ (1h тренд и ATR)
    # ------------------------------------
    # Получаем 1h данные и ATR
    price_1h, sma20_1h = get_1h_sma20(symbol) if ENABLE_1H_TREND_FILTER else (None, None)
    atr_percent = calculate_atr_percent(highs, lows, closes, 14) if ENABLE_ATR_FILTER else None
    
    # Определяем направление сигнала
    signal_type = None
    if pump_factors >= MIN_AGREEMENT:
        signal_type = 'pump'
    elif dump_factors >= MIN_AGREEMENT:
        signal_type = 'dump'
    else:
        return None, {}
    
    # Применяем фильтры
    if signal_type == 'pump':
        # Фильтр 1h: цена выше SMA20
        if ENABLE_1H_TREND_FILTER and (price_1h is None or sma20_1h is None or price_1h <= sma20_1h):
            print(f"Отклонён {symbol} (pump): цена 1h {price_1h:.4f} <= SMA20 {sma20_1h:.4f}")
            return None, {}
        # Фильтр ATR: минимальная волатильность
        if ENABLE_ATR_FILTER and (atr_percent is None or atr_percent < MIN_ATR_PERCENT):
            print(f"Отклонён {symbol} (pump): ATR {atr_percent:.2f}% < {MIN_ATR_PERCENT}%")
            return None, {}
        if rsi_val and rsi_val > 80:
            return None, {}
        entry = curr_price
        tp = entry * 1.02
        sl = entry * 0.995
        msg = f"""
🔥 <b>ПОТЕНЦИАЛЬНЫЙ ПАМП</b> на {symbol} 🔥

💰 <b>Вход:</b> ${entry:.6f}
🎯 <b>TP:</b> ${tp:.6f} (+2%)
🛑 <b>SL:</b> ${sl:.6f} (-0.5%)
⚙️ <b>Плечо:</b> {LEVERAGE}x

📊 <b>Факторы ({pump_factors}/4):</b>
• Объём: {'✅' if volume_surge else '❌'} | Ускорение: {'✅' if pump_accel else '❌'}
• Дивергенция: {'✅' if divergence else '❌'} | Импульс EMA: {'✅' if impulse_up else '❌'}

📈 <b>RSI 14:</b> {rsi_val:.1f if rsi_val else '?'}
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return 'pump', msg
    
    elif signal_type == 'dump':
        if ENABLE_1H_TREND_FILTER and (price_1h is None or sma20_1h is None or price_1h >= sma20_1h):
            print(f"Отклонён {symbol} (dump): цена 1h {price_1h:.4f} >= SMA20 {sma20_1h:.4f}")
            return None, {}
        if ENABLE_ATR_FILTER and (atr_percent is None or atr_percent < MIN_ATR_PERCENT):
            print(f"Отклонён {symbol} (dump): ATR {atr_percent:.2f}% < {MIN_ATR_PERCENT}%")
            return None, {}
        if rsi_val and rsi_val < 20:
            return None, {}
        entry = curr_price
        tp = entry * 0.98
        sl = entry * 1.005
        msg = f"""
💀 <b>ПОТЕНЦИАЛЬНЫЙ ДАМП</b> на {symbol} 💀

💰 <b>Вход:</b> ${entry:.6f}
🎯 <b>TP:</b> ${tp:.6f} (-2%)
🛑 <b>SL:</b> ${sl:.6f} (+0.5%)
⚙️ <b>Плечо:</b> {LEVERAGE}x

📊 <b>Факторы ({dump_factors}/4):</b>
• Объём: {'✅' if volume_surge else '❌'} | Ускорение: {'✅' if dump_accel else '❌'}
• Дивергенция: {'✅' if divergence else '❌'} | Импульс EMA: {'✅' if impulse_down else '❌'}

📉 <b>RSI 14:</b> {rsi_val:.1f if rsi_val else '?'}
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return 'dump', msg

def main():
    send_telegram("🚀 Бот 2 (pump/dump) с фильтрами 1h тренда и ATR запущен.")
    print("Бот запущен. Проверка каждые 3 минуты.")
    while True:
        coins = get_top_coins_by_volume(TOP_COINS * 2)
        if not coins:
            print("Нет монет, повтор через 30 сек")
            time.sleep(30)
            continue
        for coin in coins[:TOP_COINS]:
            try:
                signal_type, msg = detect_pump_dump(coin['symbol'])
                if msg:
                    send_telegram(msg)
                    time.sleep(2)
            except Exception as e:
                print(f"Ошибка {coin['symbol']}: {e}")
            time.sleep(0.5)
        print(f"{datetime.now()} - цикл завершён")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()