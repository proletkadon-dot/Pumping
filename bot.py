import requests
import time
import math
from datetime import datetime

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

MAX_PAIRS = 200                     # максимум монет для анализа (по объёму)
MIN_24H_VOLUME_USDT = 200_000       # мин. объём $200k
CHECK_INTERVAL = 600                # 10 минут (уменьшил для частоты)
LOOKBACK_CANDLES = 500              # сколько 5m свечей для уровней (~2 дня)
MIN_TOUCHES = 2                     # минимальное количество касаний (ослаблено)
LEVERAGE = 20
RISK_PERCENT = 1.0
TP_PERCENT = 2.0
SL_OFFSET_PERCENT = 0.5
LIMIT_OFFSET_PERCENT = 0.2
TIMEFRAMES = ['5', '15', '30', '60', '240']   # минуты
DISTANCE_TO_RESISTANCE_PERCENT = 2.0          # цена ближе 2% к сопротивлению (ослаблено)
RSI_MIN_FOR_SHORT = 35                         # RSI не ниже 35
# =================================

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

# ---------- ПОЛУЧЕНИЕ СПИСКА МОНЕТ (KuCoin + Gate.io + резерв) ----------
def get_all_usdt_pairs():
    # Пробуем KuCoin
    try:
        url = "https://api.kucoin.com/api/v1/symbols"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data['code'] == '200000':
            symbols = [s['symbol'] for s in data['data'] if s['symbol'].endswith('-USDT')]
            # Сортировка по объёму – нет прямого поля, берём первые MAX_PAIRS
            coins = []
            for sym in symbols[:MAX_PAIRS]:
                base = sym.replace('-USDT', '')
                if base in ['BTC','ETH','USDT','USDC','DAI','BUSD','TUSD']:
                    continue
                coins.append({'symbol': base, 'volume': 0})
            if coins:
                print(f"Список монет с KuCoin: {len(coins)}")
                return coins[:MAX_PAIRS]
    except Exception as e:
        print(f"KuCoin список не удался: {e}")
    
    # Пробуем Gate.io
    try:
        url = "https://api.gateio.ws/api/v4/spot/currency_pairs"
        r = requests.get(url, timeout=10)
        data = r.json()
        symbols = [p['id'] for p in data if p['id'].endswith('_USDT')]
        coins = []
        for sym in symbols[:MAX_PAIRS]:
            base = sym.replace('_USDT', '')
            if base in ['BTC','ETH','USDT','USDC','DAI','BUSD','TUSD']:
                continue
            coins.append({'symbol': base, 'volume': 0})
        if coins:
            print(f"Список монет с Gate.io: {len(coins)}")
            return coins[:MAX_PAIRS]
    except Exception as e:
        print(f"Gate.io список не удался: {e}")
    
    # Резервный список
    fallback = ["SOL","XRP","ADA","DOGE","MATIC","DOT","AVAX","LINK","LTC","NEAR","ATOM","FIL","VET","ALGO","ICP","FTM","SAND","MANA","ENJ","CHZ","AAVE","EOS","TRX","XLM","NEO","PEPE","WIF","FLOKI","TON","OP","ARB","SUI","APT","INJ","SEI","TIA","ONDO","STRK","ETHFI"]
    print(f"Использую резервный список из {len(fallback)} монет")
    return [{'symbol': s, 'volume': 0} for s in fallback[:MAX_PAIRS]]

# ---------- ПОЛУЧЕНИЕ КЛИНОВ (5m) с трёх источников с fallback ----------
def get_klines(symbol, interval_minutes=5, limit=500):
    # Пробуем KuCoin
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?type={interval_minutes}min&symbol={symbol}-USDT&limit={limit}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if data['code'] == '200000' and data['data']:
            candles = data['data']
            closes = [float(c[2]) for c in candles]
            highs = [float(c[1]) for c in candles]
            lows = [float(c[0]) for c in candles]
            volumes = [float(c[5]) for c in candles]
            # KuCoin возвращает от старых к новым, порядок правильный
            return closes, highs, lows, volumes
    except Exception as e:
        pass
    
    # Пробуем Gate.io
    try:
        url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={symbol}_USDT&interval={interval_minutes}m&limit={limit}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            closes = [float(c[2]) for c in data]
            highs = [float(c[3]) for c in data]
            lows = [float(c[4]) for c in data]
            volumes = [float(c[5]) for c in data]
            # Gate.io возвращает от старых к новым
            return closes, highs, lows, volumes
    except Exception as e:
        pass
    
    # Пробуем Binance (если повезёт)
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval_minutes}m&limit={limit}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            closes = [float(c[4]) for c in data]
            highs = [float(c[2]) for c in data]
            lows = [float(c[3]) for c in data]
            volumes = [float(c[5]) for c in data]
            return closes, highs, lows, volumes
    except:
        pass
    
    print(f"Не удалось получить свечи для {symbol}")
    return [], [], [], []

# ---------- ВСЕ ОСТАЛЬНЫЕ ФУНКЦИИ (анализ, уровни, индикаторы) без изменений ----------
# (см. предыдущие версии – они полностью идентичны, поэтому я их не повторяю,
#  а сразу дам полный код с ними. Ниже идёт продолжение...)

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

def count_touches(symbol, level_price, interval_min, lookback_days=3):
    intervals = {'5': 12*24, '15': 4*24, '30': 2*24, '60': 24, '240': 6}
    limit = intervals.get(str(interval_min), 100) * lookback_days
    _, highs, lows, _ = get_klines(symbol, interval_minutes=interval_min, limit=limit)
    if not highs:
        return 0
    touches = 0
    for i in range(len(highs)):
        if abs(highs[i] - level_price) / level_price * 100 < 0.3:
            touches += 1
        if abs(lows[i] - level_price) / level_price * 100 < 0.3:
            touches += 1
    return touches

def get_rsi(symbol, interval_min, period=14):
    closes, _, _, _ = get_klines(symbol, interval_minutes=interval_min, limit=period+10)
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
    # Пробуем KuCoin фьючерсы
    try:
        url = f"https://api.kucoin.com/api/v1/contracts/{symbol}-USDT"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data['code'] == '200000':
            return float(data['data']['fundingRate']) * 100
    except:
        pass
    return None

def get_24h_volume(symbol):
    # Пробуем KuCoin
    try:
        url = f"https://api.kucoin.com/api/v1/market/stats?symbol={symbol}-USDT"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data['code'] == '200000':
            return float(data['data']['volValue'])
    except:
        pass
    return 0

def analyze_coin(symbol):
    closes, highs, lows, _ = get_klines(symbol, 5, LOOKBACK_CANDLES)
    if len(closes) < 300:
        return None
    current_price = closes[-1]
    
    support, resistance = find_support_resistance(highs, lows, current_price, lookback=200)
    if not resistance:
        return None
    dist_to_res = (resistance - current_price) / current_price * 100
    if dist_to_res > DISTANCE_TO_RESISTANCE_PERCENT:
        return None
    
    fibo = calculate_fibo_levels(highs, lows, closes)
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
        touches = count_touches(symbol, level_price, int(tf), lookback_days=2)
        if touches >= MIN_TOUCHES:
            confirmed_tfs.append(f"{tf}m")
    if len(confirmed_tfs) < 2:
        return None
    
    rsi5 = get_rsi(symbol, 5)
    rsi60 = get_rsi(symbol, 60)
    if rsi5 is None or rsi60 is None:
        return None
    if rsi5 < RSI_MIN_FOR_SHORT:
        return None
    
    volume24h = get_24h_volume(symbol)
    volume_status = "🟢" if volume24h > 50_000_000 else "🟡" if volume24h > 10_000_000 else "🔴"
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
    touches_info = f"~{count_touches(symbol, level_price, 5, 2)} касаний"
    
    msg = f"""
{side_emoji}: {symbol}

🎯 РЕШЕНИЕ: ⚠️ ЖДАТЬ ЛИМИТНЫЙ ВХОД
💭 Оценка: Лимитный ордер у зоны

🔍 Анализ:
• RSI 5m: {rsi5:.1f}
• RSI 1h: {rsi60:.1f}
• Объём 24h: {volume24h/1_000_000:.2f}M {volume_status}
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
• Объём за сутки: ${volume24h/1_000_000:.1f}M
• Зона на старшем ТФ найдена, до неё {abs((entry_price - level_price)/level_price*100):.2f}% — лимитный ордер
• Уровень подтверждён на ТФ: {', '.join(confirmed_tfs)}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    return msg

def main():
    send_telegram("🚀 Бот SHORT (KuCoin + Gate.io) запущен. Анализ каждые 10 минут.")
    print("Бот запущен. Анализ SHORT сигналов.")
    while True:
        coins = get_all_usdt_pairs()
        if not coins:
            print("Нет монет, повтор через 30 сек")
            time.sleep(30)
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