import requests
import time
import math
from datetime import datetime

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

# Список монет (можете заменить на свой)
SYMBOLS = [
    "1000LUNC", "SOL", "XRP", "ADA", "DOGE", "MATIC", "DOT", "AVAX",
    "LINK", "LTC", "NEAR", "ATOM", "FIL", "ALGO", "VET", "FTM"
]

CHECK_INTERVAL = 600                # 10 минут (можно меньше)
LOOKBACK_CANDLES = 2000             # сколько 5m свечей для поиска уровней (~7 дней)
MIN_TOUCHES = 3                     # минимальное количество касаний уровня для подтверждения
LEVERAGE = 20                       # плечо
RISK_PERCENT = 1.0                  # % депозита на сделку
TP_PERCENT = 2.0                    # тейк-профит в % (для первого TP)
SL_OFFSET_PERCENT = 0.5             # отступ стоп-лосса от уровня (в %)
LIMIT_OFFSET_PERCENT = 0.2          # отступ лимитного ордера от уровня (в %)

TIMEFRAMES = ['5m', '15m', '30m', '1h', '4h']   # таймфреймы для подтверждения
# ===============================================

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
        if not isinstance(data, list) or len(data) < 50:
            return [], [], [], []
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        volumes = [float(c[5]) for c in data]
        return closes, highs, lows, volumes
    except Exception as e:
        print(f"Ошибка свечей {symbol}: {e}")
        return [], [], [], []

def find_support_resistance(highs, lows, current_price, lookback=100):
    """Находит ближайшие поддержку и сопротивление"""
    # Берём последние lookback свечей
    highs_seg = highs[-lookback:]
    lows_seg = lows[-lookback:]
    # Находим локальные минимумы (поддержки)
    supports = []
    for i in range(2, len(lows_seg)-2):
        if lows_seg[i] <= lows_seg[i-1] and lows_seg[i] <= lows_seg[i-2] and \
           lows_seg[i] <= lows_seg[i+1] and lows_seg[i] <= lows_seg[i+2]:
            supports.append(lows_seg[i])
    # Находим локальные максимумы (сопротивления)
    resistances = []
    for i in range(2, len(highs_seg)-2):
        if highs_seg[i] >= highs_seg[i-1] and highs_seg[i] >= highs_seg[i-2] and \
           highs_seg[i] >= highs_seg[i+1] and highs_seg[i] >= highs_seg[i+2]:
            resistances.append(highs_seg[i])
    # Убираем дубликаты и сортируем
    supports = sorted(set(supports))
    resistances = sorted(set(resistances))
    # Находим ближайшие уровни
    nearest_support = max([s for s in supports if s < current_price], default=None)
    nearest_resistance = min([r for r in resistances if r > current_price], default=None)
    return nearest_support, nearest_resistance

def calculate_fibo_levels(highs, lows, closes):
    """Возвращает уровни Фибоначчи от последнего значимого движения"""
    if len(closes) < 100:
        return {}
    # Находим последний максимум и минимум за 100 свечей
    max_price = max(closes[-100:])
    min_price = min(closes[-100:])
    # Определяем направление последнего тренда
    idx_max = len(closes) - 1 - closes[::-1].index(max_price)
    idx_min = len(closes) - 1 - closes[::-1].index(min_price)
    if idx_max > idx_min:
        start, end = min_price, max_price   # восходящий
    else:
        start, end = max_price, min_price   # нисходящий
    diff = end - start
    levels = {}
    for fib in [0.236, 0.382, 0.5, 0.618, 0.786]:
        levels[fib] = start + diff * fib
    return levels

def count_touches(symbol, level_price, timeframe='5m', lookback_days=3):
    """Считает, сколько раз цена касалась уровня за последние lookback_days дней"""
    # Переводим дни в количество свечей (приблизительно)
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
    closes, _, _, _ = get_klines(symbol, interval=timeframe, limit=period+1)
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

def get_funding(symbol):
    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}USDT"
    try:
        data = requests.get(url, timeout=5).json()
        return float(data.get('lastFundingRate', 0)) * 100
    except:
        return None

def get_24h_volume(symbol):
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}USDT"
    try:
        data = requests.get(url, timeout=5).json()
        return float(data.get('quoteVolume', 0))
    except:
        return 0

def analyze_coin(symbol):
    # Получаем 5-минутные свечи для поиска уровней
    closes_5m, highs_5m, lows_5m, vols_5m = get_klines(symbol, '5m', LOOKBACK_CANDLES)
    if len(closes_5m) < 500:
        return None
    current_price = closes_5m[-1]
    
    # Поддержка/сопротивление
    support, resistance = find_support_resistance(highs_5m, lows_5m, current_price, lookback=200)
    # Фибоначчи
    fibo = calculate_fibo_levels(highs_5m, lows_5m, closes_5m)
    
    # Определяем, к какому уровню ближе цена (поддержка или сопротивление)
    dist_to_support = abs(current_price - support) / current_price * 100 if support else 100
    dist_to_resistance = abs(current_price - resistance) / current_price * 100 if resistance else 100
    
    # Если цена близка к поддержке (расстояние < 1%) – потенциальный LONG
    is_long = None
    level_price = None
    level_type = None
    fibo_level = None
    if support and dist_to_support < 1.0:
        is_long = True
        level_price = support
        level_type = 'support'
        # Проверяем Фибо: если уровень совпадает с Фибо 0.618/0.786, отмечаем
        for f, val in fibo.items():
            if abs(level_price - val) / level_price * 100 < 0.5:
                fibo_level = f
                break
    elif resistance and dist_to_resistance < 1.0:
        is_long = False
        level_price = resistance
        level_type = 'resistance'
        for f, val in fibo.items():
            if abs(level_price - val) / level_price * 100 < 0.5:
                fibo_level = f
                break
    else:
        return None   # цена далеко от уровней
    
    # Подтверждение на нескольких таймфреймах
    confirmed_tfs = []
    for tf in TIMEFRAMES:
        touches = count_touches(symbol, level_price, tf, lookback_days=3)
        if touches >= MIN_TOUCHES:
            confirmed_tfs.append(tf.upper())
    if len(confirmed_tfs) < 2:
        return None   # недостаточно касаний
    
    # RSI
    rsi_5m = get_rsi(symbol, '5m')
    rsi_1h = get_rsi(symbol, '1h')
    if rsi_5m is None or rsi_1h is None:
        return None
    
    # Дополнительные проверки для качества
    # Для LONG: RSI 5m не выше 60, для SHORT: RSI 5m не ниже 40
    if is_long and rsi_5m > 60:
        return None
    if not is_long and rsi_5m < 40:
        return None
    
    # Объём за 24ч
    volume_24h = get_24h_volume(symbol)
    volume_status = "🟢" if volume_24h > 50_000_000 else "🟡" if volume_24h > 10_000_000 else "🔴"
    
    # Фандинг
    funding = get_funding(symbol)
    funding_str = f"{funding:.4f}%" if funding is not None else "нет данных"
    funding_ok = (is_long and funding and funding < 0) or (not is_long and funding and funding > 0)
    
    # Расчёт уровней входа, TP, SL
    if is_long:
        direction = "LONG"
        entry_price = level_price * (1 + LIMIT_OFFSET_PERCENT / 100)  # чуть выше поддержки
        tp1 = entry_price * (1 + TP_PERCENT / 100)
        # Второй тейк: ближайшее сопротивление или Фибо 0.5
        tp2_candidates = []
        if resistance and resistance > entry_price:
            tp2_candidates.append(resistance)
        for f, val in fibo.items():
            if val > entry_price and (f == 0.5 or f == 0.618):
                tp2_candidates.append(val)
        tp2 = min(tp2_candidates) if tp2_candidates else entry_price * 1.03
        sl_price = level_price * (1 - SL_OFFSET_PERCENT / 100)   # ниже поддержки
        sl_percent = (entry_price - sl_price) / entry_price * 100
    else:
        direction = "SHORT"
        entry_price = level_price * (1 - LIMIT_OFFSET_PERCENT / 100)  # чуть ниже сопротивления
        tp1 = entry_price * (1 - TP_PERCENT / 100)
        tp2_candidates = []
        if support and support < entry_price:
            tp2_candidates.append(support)
        for f, val in fibo.items():
            if val < entry_price and (f == 0.5 or f == 0.618):
                tp2_candidates.append(val)
        tp2 = max(tp2_candidates) if tp2_candidates else entry_price * 0.97
        sl_price = level_price * (1 + SL_OFFSET_PERCENT / 100)   # выше сопротивления
        sl_percent = (sl_price - entry_price) / entry_price * 100
    
    # Риск на депозит
    risk_to_deposit = sl_percent * LEVERAGE * (RISK_PERCENT / 100)
    
    # Формируем сообщение по шаблону
    side_emoji = "🔴 SHORT" if not is_long else "🟢 LONG"
    level_desc = f"{level_price:.6f} ({level_type}"
    if fibo_level:
        level_desc += f", Фибо {fibo_level}"
    level_desc += ")"
    touches_info = f"~{count_touches(symbol, level_price, '5m', 3)} касаний"
    
    msg = f"""
{side_emoji}: {symbol}

🎯 РЕШЕНИЕ: ⚠️ ЖДАТЬ ЛИМИТНЫЙ ВХОД
💭 Оценка: Лимитный ордер у зоны

🔍 Анализ:
• RSI 5m: {rsi_5m:.1f}
• RSI 1h: {rsi_1h:.1f}
• Объём 24h: {volume_24h/1_000_000:.2f}M {volume_status}
• Фандинг: {funding_str} {'✅' if funding_ok else ''}

📍 Причина входа: Уровень {level_desc}, {touches_info} (по {','.join(confirmed_tfs[:4])}, подтверждён на {len(confirmed_tfs)} ТФ)
Таймфрейм: {'+'.join(confirmed_tfs[:4])}

💰 Точки входа:
• Вход: Лимитный {entry_price:.6f}
• Размер: {RISK_PERCENT:.1f}% депозита
• Плечо: {LEVERAGE}x
• До зоны: {abs((entry_price - level_price)/level_price*100):.2f}%

🎯 Тейк-профит:
• TP1 {TP_PERCENT}%: {tp1:.6f} ({'+' if is_long else '-'}{TP_PERCENT}%) — частичное
• Цель отката (Фибо 0.5): {tp2:.6f}

🛑 Стоп-лосс:
• SL: {sl_price:.6f} ({'+' if not is_long else '-'}{sl_percent:.2f}%)
• Оценка к депозиту: ~{risk_to_deposit:.2f}% (при {RISK_PERCENT}% позиции и {LEVERAGE}x)

⚠️ Замечания:
• Объём за сутки: ${volume_24h/1_000_000:.1f}M
• Зона на старшем ТФ найдена, до неё {abs((entry_price - level_price)/level_price*100):.2f}% — лимитный ордер
• Уровень подтверждён на ТФ: {', '.join(confirmed_tfs)}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    return msg

def main():
    send_telegram("🚀 Бот 2 (уровневый, мульти-ТФ) запущен.")
    print("Бот запущен. Анализ каждые 10 минут.")
    while True:
        for symbol in SYMBOLS:
            try:
                signal = analyze_coin(symbol)
                if signal:
                    send_telegram(signal)
                    time.sleep(2)
            except Exception as e:
                print(f"Ошибка {symbol}: {e}")
            time.sleep(1)  # пауза между монетами
        print(f"{datetime.now()} - цикл завершён, жду {CHECK_INTERVAL} сек.")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()