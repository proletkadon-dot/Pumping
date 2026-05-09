import requests
import time
import math
from datetime import datetime

# ========== НАСТРОЙКИ TELEGRAM ==========
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

# ========== ОСНОВНЫЕ ПАРАМЕТРЫ БОТА 2 ==========
CHECK_INTERVAL = 60               # проверка каждую минуту (для быстрого реагирования)
TOP_VOLATILE_COINS = 20           # топ-20 альткоинов по объёму (можно увеличить до 30)
MIN_VOLUME_USDT = 500_000         # мин. объём $500k (меньше, чтобы ловить мелкие пампы)
MIN_PRICE_USD = 0.001             # мин. цена монеты (отсекаем слишком дешёвые)
MIN_5MIN_CHANGE = 1.0             # мин. изменение за 5 минут (%), чтобы не спамить в штиль
LEVERAGE = 2                      # плечо для скальпинга пампа (низкое, рискованно)

# ========== НАСТРОЙКИ ДЕТЕКТОРА ПАМПОВ/ДАМПОВ ==========
VOLUME_SURGE_FACTOR = 2.5         # всплеск объёма в X раз выше среднего за 20 мин
PRICE_ACCELERATION_THRESHOLD = 1.2 # ускорение цены: отношение темпа 3 мин к темпу 1 мин > 1.2
DIVERGENCE_THRESHOLD = 0.7        # дивергенция: рост объёма > 0.7, цена стагнирует
MIN_AGREEMENT = 2                 # сигнал при 2 из 4 факторов
# =====================================================

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

def get_top_volume_coins(limit=50):
    """Топ альткоинов по объёму с CoinGecko (исключая BTC, ETH, стейблкоины)"""
    url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page={limit}&page=1&sparkline=false"
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = response.json()
        exclude = ['BTC', 'ETH', 'USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'USDP', 'FDUSD', 'PAXG', 'XAUT']
        top = []
        for coin in data:
            sym = coin['symbol'].upper()
            if sym in exclude:
                continue
            name = coin['name'].lower()
            if 'stable' in name or 'dollar' in name:
                continue
            price = coin.get('current_price', 0)
            if price < MIN_PRICE_USD:
                continue
            top.append({'symbol': sym, 'volume': coin.get('total_volume', 0), 'price': price})
        return top
    except Exception as e:
        print("Ошибка CoinGecko:", e)
        return []

def get_klines_1m(symbol, limit=30):
    """1-минутные свечи с Binance (для быстрого детекта)"""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=1m&limit={limit}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if not isinstance(data, list) or len(data) < 10:
            return [], [], [], []
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        volumes = [float(c[5]) for c in data]
        return closes, highs, lows, volumes
    except Exception:
        return [], [], [], []

def detect_pump_dump(closes, volumes):
    """
    Анализирует 1-минутные свечи на предмет аномалий, предшествующих пампу/дампу.
    Возвращает (signal, confidence, details), где signal: 'pump', 'dump' или None.
    confidence: количество сработавших факторов (0-4).
    """
    if len(closes) < 20 or len(volumes) < 20:
        return None, 0, {}
    
    # 1. Всплеск объёма (текущий объём vs средний за 20 минут, исключая последний)
    avg_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
    current_volume = volumes[-1]
    volume_surge = (current_volume > avg_volume * VOLUME_SURGE_FACTOR) if avg_volume > 0 else False
    
    # 2. Ускорение цены (сравниваем темп роста за 1 минуту и за 3 минуты)
    if len(closes) >= 4:
        # Изменение за последнюю минуту
        change_1m = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] != 0 else 0
        # Изменение за последние 3 минуты (среднее в минуту)
        change_3m = (closes[-1] - closes[-4]) / closes[-4] / 3 if closes[-4] != 0 else 0
        # Ускорение: темп последней минуты / средний темп за 3 минуты (если темп положительный)
        acceleration = (change_1m / change_3m) if change_3m > 0 else 0
        price_acceleration = (acceleration > PRICE_ACCELERATION_THRESHOLD) and change_1m > 0
        # Для дампа: отрицательное ускорение
        dump_acceleration = (change_1m < 0 and change_3m < 0 and (change_1m / change_3m) > PRICE_ACCELERATION_THRESHOLD)
    else:
        price_acceleration = False
        dump_acceleration = False
    
    # 3. Дивергенция объёма и цены (объём резко растёт, цена почти не меняется -> прорыв)
    if len(volumes) >= 6 and len(closes) >= 6:
        vol_last_5 = sum(volumes[-6:-1]) / 5
        vol_now = volumes[-1]
        price_range_last_5 = (max(closes[-6:-1]) - min(closes[-6:-1])) / closes[-7] if closes[-7] != 0 else 0
        price_change_last_1 = abs(closes[-1] - closes[-2]) / closes[-2] if closes[-2] != 0 else 0
        divergence = (vol_now > 2 * vol_last_5) and (price_range_last_5 < 0.002)  # стагнация цены менее 0.2%
    else:
        divergence = False
    
    # 4. Импульс EMA5/EMA10 (быстрое пересечение)
    def ema(prices, period):
        if len(prices) < period: return None
        mult = 2/(period+1)
        e = prices[0]
        for p in prices[1:]:
            e = (p - e)*mult + e
        return e
    ema5 = ema(closes, 5)
    ema10 = ema(closes, 10)
    ema5_prev = ema(closes[:-1], 5)
    ema10_prev = ema(closes[:-1], 10)
    impulse_up = (ema5_prev <= ema10_prev and ema5 > ema10) if ema5_prev and ema10_prev else False
    impulse_down = (ema5_prev >= ema10_prev and ema5 < ema10) if ema5_prev and ema10_prev else False
    
    # Подсчёт факторов для пампа (рост)
    pump_factors = 0
    if volume_surge: pump_factors += 1
    if price_acceleration: pump_factors += 1
    if divergence: pump_factors += 1
    if impulse_up: pump_factors += 1
    
    # Для дампа (падение)
    dump_factors = 0
    if volume_surge: dump_factors += 1
    if dump_acceleration: dump_factors += 1
    if divergence: dump_factors += 1   # дивергенция может предшествовать и падению
    if impulse_down: dump_factors += 1
    
    details = {
        'volume_surge': volume_surge,
        'price_acceleration': price_acceleration,
        'dump_acceleration': dump_acceleration,
        'divergence': divergence,
        'impulse_up': impulse_up,
        'impulse_down': impulse_down,
        'avg_volume': avg_volume,
        'current_volume': current_volume,
        'change_1m': (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes)>=2 else 0,
        'change_3m': (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes)>=4 else 0
    }
    
    if pump_factors >= MIN_AGREEMENT:
        return 'pump', pump_factors, details
    elif dump_factors >= MIN_AGREEMENT:
        return 'dump', dump_factors, details
    else:
        return None, 0, details

def analyze_and_signal():
    coins = get_top_volume_coins(TOP_VOLATILE_COINS * 2)
    if not coins:
        send_telegram("⚠️ Бот 2: Не удалось получить список альткоинов")
        return
    
    filtered = [c for c in coins if c['volume'] >= MIN_VOLUME_USDT][:TOP_VOLATILE_COINS]
    sig_count = 0
    for coin in filtered:
        symbol = coin['symbol']
        closes, highs, lows, volumes = get_klines_1m(symbol, limit=30)
        if len(closes) < 20:
            continue
        
        # Фильтр по минимальному изменению за 5 минут (можно убрать, если нужно ловить любые пампы)
        if len(closes) >= 5:
            change_5m = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] != 0 else 0
            if abs(change_5m) < MIN_5MIN_CHANGE:
                continue
        
        signal, confidence, details = detect_pump_dump(closes, volumes)
        if not signal:
            continue
        
        price = closes[-1]
        # При сигнале рекомендуем вход через 1 минуту с малым стопом
        if signal == 'pump':
            entry = price
            tp = entry * 1.02   # тейк +2% (быстрый)
            sl = entry * 0.995  # стоп -0.5% (очень жёсткий)
            msg = f"""
🔥 <b>ПОТЕНЦИАЛЬНЫЙ ПАМП</b> на {symbol} 🔥

💰 <b>Вход (рынок):</b> ${entry:.6f}
🎯 <b>Take Profit (быстрый):</b> ${tp:.6f} (+2%)
🛑 <b>Stop Loss:</b> ${sl:.6f} (-0.5%)
⚙️ <b>Плечо:</b> {LEVERAGE}x

📊 <b>Факторы (уверенность {confidence}/4):</b>
• Всплеск объёма: {'✅' if details['volume_surge'] else '❌'}
• Ускорение цены (бычий импульс): {'✅' if details['price_acceleration'] else '❌'}
• Дивергенция объёма/цены: {'✅' if details['divergence'] else '❌'}
• Пересечение EMA5/10 вверх: {'✅' if details['impulse_up'] else '❌'}

📈 <b>Изменение за 1 мин:</b> {details['change_1m']:.2f}%
📈 <b>Изменение за 3 мин:</b> {details['change_3m']:.2f}%
💡 <b>Пояснение:</b> Аномальная активность, возможен резкий рост. Входить с осторожностью.
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        else:  # dump
            entry = price
            tp = entry * 0.98   # тейк -2%
            sl = entry * 1.005  # стоп +0.5%
            msg = f"""
💀 <b>ПОТЕНЦИАЛЬНЫЙ ДАМП</b> на {symbol} 💀

💰 <b>Вход (шорт):</b> ${entry:.6f}
🎯 <b>Take Profit:</b> ${tp:.6f} (падение 2%)
🛑 <b>Stop Loss:</b> ${sl:.6f} (рост 0.5%)
⚙️ <b>Плечо:</b> {LEVERAGE}x

📊 <b>Факторы (уверенность {confidence}/4):</b>
• Всплеск объёма: {'✅' if details['volume_surge'] else '❌'}
• Ускорение падения: {'✅' if details['dump_acceleration'] else '❌'}
• Дивергенция объёма/цены: {'✅' if details['divergence'] else '❌'}
• Пересечение EMA5/10 вниз: {'✅' if details['impulse_down'] else '❌'}

📉 <b>Изменение за 1 мин:</b> {details['change_1m']:.2f}%
📉 <b>Изменение за 3 мин:</b> {details['change_3m']:.2f}%
💡 <b>Пояснение:</b> Аномальная активность, возможен резкий сброс.
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        send_telegram(msg)
        sig_count += 1
        time.sleep(1)
    
    if sig_count == 0:
        print(f"{datetime.now()} - Бот 2: аномалий не обнаружено.")

# ========== ЗАПУСК БОТА 2 ==========
send_telegram("🚀 Бот 2 (детектор пампов/дампов) запущен. Буду искать аномалии на 1-минутных свечах.")
print("Бот 2 запущен. Проверка каждую минуту. Порог 2 из 4 факторов.")
while True:
    try:
        analyze_and_signal()
        time.sleep(CHECK_INTERVAL)
    except Exception as e:
        print("Ошибка Бота 2:", e)
        time.sleep(60)