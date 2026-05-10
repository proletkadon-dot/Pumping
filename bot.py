import requests
import time
import math
from datetime import datetime

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

MAX_PAIRS = 500                     # максимум USDT пар (Bybit)
MIN_24H_VOLUME_USDT = 100_000       # мин. объём $100k (0 = без фильтра)
CHECK_INTERVAL = 1200               # 20 минут
LOOKBACK_CANDLES = 1000             # сколько 5m свечей для уровней
MIN_TOUCHES = 3
LEVERAGE = 20
RISK_PERCENT = 1.0
TP_PERCENT = 2.0
SL_OFFSET_PERCENT = 0.5
LIMIT_OFFSET_PERCENT = 0.2
TIMEFRAMES = ['5', '15', '30', '60', '240']   # минуты для Bybit (5,15,30,60,240)
# =================================

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

def get_all_usdt_pairs():
    """Список USDT пар с Bybit (по объёму)"""
    url = "https://api.bybit.com/v5/market/tickers?category=spot"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        if data['retCode'] != 0:
            return []
        tickers = data['result']['list']
        usdt_pairs = [t for t in tickers if t['symbol'].endswith('USDT')]
        usdt_pairs.sort(key=lambda x: float(x['turnover24h']), reverse=True)
        coins = []
        for t in usdt_pairs[:MAX_PAIRS]:
            sym = t['symbol'].replace('USDT', '')
            if sym in ['BTC','ETH','USDT','USDC','DAI','BUSD','TUSD','FDUSD']:
                continue
            vol = float(t['turnover24h'])
            if vol >= MIN_24H_VOLUME_USDT:
                coins.append({'symbol': sym, 'volume': vol})
        print(f"Загружено монет: {len(coins)}")
        return coins
    except Exception as e:
        print(f"Ошибка Bybit: {e}")
        return []

def get_klines(symbol, interval='5', limit=1000):
    """Свечи с Bybit (interval в минутах)"""
    url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}USDT&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=15).json()
        if data['retCode'] != 0:
            return [], [], [], []
        klines = data['result']['list']
        closes = [float(k[4]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        volumes = [float(k[5]) for k in klines]
        # Bybit возвращает от новых к старым – разворачиваем
        closes.reverse()
        highs.reverse()
        lows.reverse()
        volumes.reverse()
        return closes, highs, lows, volumes
    except Exception as e:
        print(f"Ошибка свечей {symbol}: {e}")
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

def calculate_fibo_levels(highs, lows, closes):
    if len(closes) < 100:
        return {}
    max_price = max(closes[-100:])
    min_price = min(closes[-100:])
    idx_max = len(closes) - 1 - closes[::-1].index(max_price)
    idx_min = len(closes) - 1 - closes[::-1].index(min_price)
    if idx_max > idx_min:
        start, end = min_price, max_price
    else:
        start, end = max_price, min_price
    diff = end - start
    levels = {}
    for fib in [0.236, 0.382, 0.5, 0.618, 0.786]:
        levels[fib] = start + diff * fib
    return levels

def count_touches(symbol, level_price, interval_min='5', lookback_days=3):
    """Считает касания уровня на заданном таймфрейме (интервал в минутах)"""
    intervals = {'5': 12*24, '15': 4*24, '30': 2*24, '60': 24, '240': 6}
    limit = intervals.get(interval_min, 100) * lookback_days
    _, highs, lows, _ = get_klines(symbol, interval=interval_min, limit=limit)
    if not highs:
        return 0
    touches = 0
    for i in range(len(highs)):
        if abs(highs[i] - level_price) / level_price * 100 < 0.2:
            touches += 1
        if abs(lows[i] - level_price) / level_price * 100 < 0.2:
            touches += 1
    return touches

def get_rsi(symbol, interval_min='5', period=14):
    closes, _, _, _ = get_klines(symbol, interval=interval_min, limit=period+5)
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
    # Фандинг для Bybit (опционально)
    url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}USDT"
    try:
        data = requests.get(url, timeout=5).json()
        if data['retCode'] == 0 and data['result']['list']:
            return float(data['result']['list'][0]['fundingRate']) * 100
    except:
        pass
    return None

def get_24h_volume(symbol):
    url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}USDT"
    try:
        data = requests.get(url, timeout=5).json()
        if data['retCode'] == 0 and data['result']['list']:
            return float(data['result']['list'][0]['turnover24h'])
    except:
        pass
    return 0

def analyze_coin(symbol):
    closes_5m, highs_5m, lows_5m, _ = get_klines(symbol, '5', LOOKBACK_CANDLES)
    if len(closes_5m) < 500:
        return None
    current_price = closes_5m[-1]
    
    support, resistance = find_support_resistance(highs_5m, lows_5m, current_price, lookback=200)
    fibo = calculate_fibo_levels(highs_5m, lows_5m, closes_5m)
    
    if not resistance:
        return None
    dist_to_res = (resistance - current_price) / current_price * 100
    if dist_to_res >= 1.0:   # ближе 1%?
        return None
    
    level_price = resistance
    level_type = 'resistance'
    fibo_level = None
    for f, val in fibo.items():
        if abs(level_price - val) / level_price * 100 < 0.5 and (f == 0.236 or f == 0.382):
            fibo_level = f
            break
    
    # Подтверждение таймфреймов
    confirmed_tfs = []
    for tf in TIMEFRAMES:
        touches = count_touches(symbol, level_price, tf, lookback_days=3)
        if touches >= MIN_TOUCHES:
            confirmed_tfs.append(f"{tf}m")
    if len(confirmed_tfs) < 2:
        return None
    
    rsi_5m = get_rsi(symbol, '5')
    rsi_1h = get_rsi(symbol, '60')
    if rsi_5m is None or rsi_1h is None:
        return None
    if rsi_5m < 40:
        return None
    
    volume_24h = get_24h_volume(symbol)
    volume_status = "🟢" if volume_24h > 50_000_000 else "🟡" if volume_24h > 10_000_000 else "🔴"
    funding = get_funding(symbol)
    funding_str = f"{funding:.4f}%" if funding is not None else "нет данных"
    funding_ok = (funding and funding > 0)
    
    entry_price = level_price * (1 - LIMIT_OFFSET_PERCENT / 100)
    tp1 = entry_price * (1 - TP_PERCENT / 100)
    tp2_candidates = []
    if support and support < entry_price:
        tp2_candidates.append(support)
    for f, val in fibo.items():
        if val < entry_price and (f == 0.5 or f == 0.618):
            tp2_candidates.append(val)
    tp2 = max(tp2_candidates) if tp2_candidates else entry_price * 0.97
    sl_price = level_price * (1 + SL_OFFSET_PERCENT / 100)
    sl_percent = (sl_price - entry_price) / entry_price * 100
    risk_to_deposit = sl_percent * LEVERAGE * (RISK_PERCENT / 100)
    
    side_emoji = "🔴 SHORT"
    level_desc = f"{level_price:.6f} ({level_type}"
    if fibo_level:
        level_desc += f", Фибо {fibo_level}"
    level_desc += ")"
    touches_info = f"~{count_touches(symbol, level_price, '5', 3)} касаний"
    
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
• TP1 {TP_PERCENT}%: {tp1:.6f} (-{TP_PERCENT}%) — полное закрытие
• Цель отката (Фибо 0.5): {tp2:.6f}

🛑 Стоп-лосс:
• SL: {sl_price:.6f} (+{sl_percent:.2f}%)
• Оценка к депозиту: ~{risk_to_deposit:.2f}% (при {RISK_PERCENT}% позиции и {LEVERAGE}x)

⚠️ Замечания:
• Объём за сутки: ${volume_24h/1_000_000:.1f}M
• Зона на старшем ТФ найдена, до неё {abs((entry_price - level_price)/level_price*100):.2f}% — лимитный ордер
• Уровень подтверждён на ТФ: {', '.join(confirmed_tfs)}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    return msg

def main():
    send_telegram("🚀 Бот SHORT (Bybit) запущен. Анализ всего рынка USDT пар.")
    print("Бот запущен. Анализ SHORT сигналов каждые 20 минут.")
    while True:
        coins = get_all_usdt_pairs()
        if not coins:
            print("Нет монет, повтор через 60 сек")
            time.sleep(60)
            continue
        print(f"Начинаю анализ {len(coins)} монет...")
        for coin in coins:
            try:
                signal = analyze_coin(coin['symbol'])
                if signal:
                    send_telegram(signal)
                    time.sleep(2)
            except Exception as e:
                print(f"Ошибка {coin['symbol']}: {e}")
            time.sleep(0.3)
        print(f"{datetime.now()} - цикл завершён, жду {CHECK_INTERVAL} сек.")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()