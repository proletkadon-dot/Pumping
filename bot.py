import requests
import time
import math
from datetime import datetime

# ========== НАСТРОЙКИ TELEGRAM ==========
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

# ========== ПАРАМЕТРЫ БОТА ==========
CHECK_INTERVAL = 180            # 3 минуты
TOP_COINS = 20                  # 20 лучших альткоинов по объёму
MIN_VOLUME_USDT = 2_000_000     # мин. 24h объём $2M (отсекаем мусор)
MIN_5MIN_CHANGE = 2.0           # мин. изменение за 5 минут (%) – ловим только сильные движения
LEVERAGE = 2                    # плечо (низкое, т.к. высокий риск)

# Настройки детектора
VOLUME_SURGE_FACTOR = 2.5       # всплеск объёма в X раз выше среднего за 20 мин
PRICE_ACCELERATION_THRESHOLD = 1.5 # ускорение цены (отношение темпа 3 мин к темпу 1 мин)
MIN_AGREEMENT = 3               # нужно 3 из 4 факторов
# =========================================

def send_telegram(text):
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

def get_top_coins_by_volume(limit=50):
    """Топ альткоинов по объёму с CoinGecko (без BTC, ETH, стейблкоинов)"""
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

def get_klines_1m(symbol, limit=30):
    """1-минутные свечи с Binance"""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=1m&limit={limit}"
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

def calculate_ema(closes, period):
    if len(closes) < period:
        return None
    mult = 2/(period+1)
    ema = closes[0]
    for p in closes[1:]:
        ema = (p - ema) * mult + ema
    return ema

def detect_pump_dump(symbol):
    """Возвращает 'pump', 'dump' или None, а также словарь с деталями"""
    closes, highs, lows, volumes = get_klines_1m(symbol, limit=30)
    if len(closes) < 25:
        return None, {}
    curr_price = closes[-1]
    # 1. Всплеск объёма
    avg_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
    curr_volume = volumes[-1]
    volume_surge = (curr_volume > avg_volume * VOLUME_SURGE_FACTOR) if avg_volume > 0 else False
    
    # 2. Ускорение цены (положительное для pump, отрицательное для dump)
    if len(closes) >= 4:
        change_1m = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] != 0 else 0
        change_3m = (closes[-1] - closes[-4]) / closes[-4] * 100 if closes[-4] != 0 else 0
        # Среднее изменение за минуту за 3 минуты
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
    
    # 3. Дивергенция объёма и цены (цена стоит, объём растёт)
    if len(closes) >= 5:
        price_range_last_5 = (max(closes[-5:]) - min(closes[-5:])) / closes[-5] * 100 if closes[-5] != 0 else 0
        vol_increase = (volumes[-1] > volumes[-2] > volumes[-3]) if len(volumes) >= 3 else False
        divergence = (price_range_last_5 < 0.2) and vol_increase
    else:
        divergence = False
    
    # 4. Импульс (пересечение EMA5 и EMA10)
    ema5 = calculate_ema(closes, 5)
    ema10 = calculate_ema(closes, 10)
    ema5_prev = calculate_ema(closes[:-1], 5)
    ema10_prev = calculate_ema(closes[:-1], 10)
    impulse_up = (ema5_prev <= ema10_prev and ema5 > ema10) if ema5_prev and ema10_prev else False
    impulse_down = (ema5_prev >= ema10_prev and ema5 < ema10) if ema5_prev and ema10_prev else False
    
    # Подсчёт факторов для pump (вверх)
    pump_factors = 0
    if volume_surge: pump_factors += 1
    if pump_accel: pump_factors += 1
    if divergence: pump_factors += 1
    if impulse_up: pump_factors += 1
    
    # Для dump (вниз)
    dump_factors = 0
    if volume_surge: dump_factors += 1
    if dump_accel: dump_factors += 1
    if divergence: dump_factors += 1
    if impulse_down: dump_factors += 1
    
    # Дополнительный фильтр: минимальное изменение за 5 минут
    if len(closes) >= 5:
        change_5m = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] != 0 else 0
        if abs(change_5m) < MIN_5MIN_CHANGE:
            return None, {}
    
    # Фильтр RSI (чтобы не входить на экстремумах)
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
        # Доп. проверка: RSI не выше 80 (не перекуплен)
        if rsi_val and rsi_val > 80:
            return None, {}
        entry = curr_price
        tp = entry * 1.02   # +2%
        sl = entry * 0.995  # -0.5%
        msg = f"""
🔥 <b>ПОТЕНЦИАЛЬНЫЙ ПАМП</b> на {symbol} 🔥

💰 <b>Вход (рынок):</b> ${entry:.6f}
🎯 <b>Take Profit:</b> ${tp:.6f} (+2%)
🛑 <b>Stop Loss:</b> ${sl:.6f} (-0.5%)
⚙️ <b>Плечо:</b> {LEVERAGE}x

📊 <b>Факторы (уверенность {pump_factors}/4):</b>
• Всплеск объёма: {'✅' if volume_surge else '❌'}
• Ускорение цены вверх: {'✅' if pump_accel else '❌'}
• Дивергенция объёма/цены: {'✅' if divergence else '❌'}
• Пересечение EMA5/10 вверх: {'✅' if impulse_up else '❌'}

📈 <b>RSI 14:</b> {rsi_val:.1f if rsi_val else '?'}
💡 <b>Пояснение:</b> Аномальная активность, возможен резкий рост. Входить с осторожностью.
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return 'pump', msg
    elif dump_factors >= MIN_AGREEMENT:
        if rsi_val and rsi_val < 20:
            return None, {}
        entry = curr_price
        tp = entry * 0.98   # -2%
        sl = entry * 1.005  # +0.5%
        msg = f"""
💀 <b>ПОТЕНЦИАЛЬНЫЙ ДАМП</b> на {symbol} 💀

💰 <b>Вход (шорт):</b> ${entry:.6f}
🎯 <b>Take Profit:</b> ${tp:.6f} (-2%)
🛑 <b>Stop Loss:</b> ${sl:.6f} (+0.5%)
⚙️ <b>Плечо:</b> {LEVERAGE}x

📊 <b>Факторы (уверенность {dump_factors}/4):</b>
• Всплеск объёма: {'✅' if volume_surge else '❌'}
• Ускорение падения: {'✅' if dump_accel else '❌'}
• Дивергенция объёма/цены: {'✅' if divergence else '❌'}
• Пересечение EMA5/10 вниз: {'✅' if impulse_down else '❌'}

📉 <b>RSI 14:</b> {rsi_val:.1f if rsi_val else '?'}
💡 <b>Пояснение:</b> Аномальная активность, возможен резкий сброс.
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return 'dump', msg
    else:
        return None, {}

def main():
    send_telegram("🚀 Бот 2 (качественный детектор пампов/дампов) запущен. Анализ каждые 3 минуты.")
    print("Бот 2 запущен. Проверка каждые 3 минуты. Требуется 3/4 факторов.")
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