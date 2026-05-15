import requests
import time
from datetime import datetime, timezone, timedelta
import math

# ===================== НАСТРОЙКИ =====================
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

MAX_COINS = 500
MAX_24H_VOLUME_USDT = 500_000
MIN_24H_VOLUME_USDT = 30_000
TIMEFRAMES = ['5m', '15m', '1h', '4h']

# Основные фильтры
RSI_4H_MIN = 65
RSI_1H_MIN = 65
CHANGE_4H_MIN = 2.0
FUNDING_MIN = 0.0
VOLUME_24H_MIN = 3_000_000

# Индикаторы: Bollinger, Stochastic
BB_PERIOD = 20
BB_STD = 2.0
STOCH_K_PERIOD = 14
STOCH_D_PERIOD = 3
STOCH_OVERBOUGHT = 80

# ATR для расчёта SL/TP
ATR_PERIOD = 14
SL_ATR_MULT = 1.5          # стоп-лосс от цены вверх (для шорта)
TP1_ATR_MULT = 2.0         # первый тейк-профит вниз
TP2_ATR_MULT = 4.0         # второй тейк-профит вниз

# Режим работы
WORK_START_HOUR = 08
WORK_END_HOUR = 22
SCAN_INTERVAL_MINUTES = 30

# Резервный список монет (если Binance недоступен)
FALLBACK_COINS = [
    "RARE", "CLV", "DGB", "REI", "ALPACA", "FORTH", "BADGER", "NULS", "QKC",
    "DOCK", "TOMO", "HARD", "SYS", "MIR", "RLC", "OXT", "CTK", "MDX", "FIRO",
    "BURGER", "SANTOS", "MLN", "DIA", "WAN", "UNFI", "RGT", "VIDT", "QSP",
    "DEGO", "LTO", "KMD", "LINA", "FRONT", "LOOM", "STPT", "ARK", "POLYX",
    "BNX", "EPX", "SPELL", "TROY", "WTC", "WAVES", "CELO", "AERGO", "SUN"
]
# =====================================================

def moscow_now():
    return datetime.now(timezone(timedelta(hours=3)))

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

# -------------- Получение рыночных данных --------------
def get_low_volume_coins():
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        r = requests.get(url, timeout=15)
        data = r.json()
        if not isinstance(data, list):
            raise ValueError("Неверный формат данных")
        usdt_pairs = [p for p in data if p['symbol'].endswith('USDT')]
        usdt_pairs.sort(key=lambda x: float(x['quoteVolume']))
        coins = []
        for pair in usdt_pairs:
            sym = pair['symbol'].replace('USDT', '')
            if sym in ['BTC','ETH','USDT','USDC','DAI','BUSD','TUSD','FDUSD']:
                continue
            vol = float(pair['quoteVolume'])
            if MIN_24H_VOLUME_USDT <= vol <= MAX_24H_VOLUME_USDT:
                coins.append(sym)
                if len(coins) >= MAX_COINS:
                    break
        print(f"Загружено {len(coins)} монет с Binance")
        return coins
    except Exception as e:
        print(f"Ошибка Binance: {e}. Использую резервный список.")
        return FALLBACK_COINS[:MAX_COINS]

def get_klines(symbol, interval='5m', limit=100):
    interval_map = {'5m': '5', '15m': '15', '1h': '60', '4h': '240'}
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}USDT&interval={interval_map.get(interval, '5')}&limit={limit}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if data.get('retCode') == 0 and data.get('result', {}).get('list'):
            klines = data['result']['list']
            ohlcv = [[float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in klines]
            ohlcv.reverse()
            return ohlcv
    except:
        pass
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?type={interval}&symbol={symbol}-USDT&limit={limit}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if data.get('code') == '200000' and data.get('data'):
            ohlcv = [[float(c[1]), float(c[3]), float(c[4]), float(c[2]), float(c[5])] for c in data['data']]
            ohlcv.reverse()
            return ohlcv
    except:
        pass
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            ohlcv = [[float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])] for c in data]
            return ohlcv
    except:
        pass
    return []

def get_24h_stats(symbol):
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}USDT"
    try:
        r = requests.get(url, timeout=5)
        data = r.json()
        return float(data['priceChangePercent']), float(data['quoteVolume'])
    except:
        return None, None

def get_funding(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}USDT"
        r = requests.get(url, timeout=5)
        data = r.json()
        return float(data.get('lastFundingRate', 0)) * 100
    except:
        return None

def get_realtime_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
    try:
        r = requests.get(url, timeout=5)
        return float(r.json()['price'])
    except:
        return None

# -------------- Технические индикаторы --------------
def rsi(closes, period=14):
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
        return 100.0
    return 100.0 - 100.0/(1+avg_gain/avg_loss)

def compute_atr(highs, lows, closes, period=14):
    if len(closes) < period+1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    atr = sum(trs[-period:])/period
    return atr

def bollinger_bands(closes, period=20, std=2.0):
    if len(closes) < period:
        return None, None, None
    sma = sum(closes[-period:])/period
    variance = sum((c-sma)**2 for c in closes[-period:])/period
    std_dev = math.sqrt(variance)
    upper = sma + std * std_dev
    lower = sma - std * std_dev
    return upper, sma, lower

def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow+signal:
        return None, None, None
    def ema(data, period):
        k = 2/(period+1)
        ema_val = sum(data[:period])/period
        for price in data[period:]:
            ema_val = price*k + ema_val*(1-k)
        return ema_val
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = ema_fast - ema_slow
    # signal line
    macd_vals = []
    for i in range(slow-1, len(closes)):
        e_f = ema(closes[:i+1], fast)
        e_s = ema(closes[:i+1], slow)
        macd_vals.append(e_f - e_s)
    if len(macd_vals) < signal:
        return None, None, None
    signal_line = ema(macd_vals, signal)
    histogram = macd_vals[-1] - signal_line
    return macd_vals[-1], signal_line, histogram

def stochastic(highs, lows, closes, k_period=14, d_period=3):
    if len(closes) < k_period:
        return None, None
    highest = max(highs[-k_period:])
    lowest = min(lows[-k_period:])
    if highest == lowest:
        return 50.0, 50.0
    k = 100.0 * (closes[-1] - lowest) / (highest - lowest)
    # для %D нужен список K, но для фильтра используем последний K
    # упрощённо: D = SMA(K, d_period) – посчитаем по последним k_period свечам
    ks = []
    for i in range(k_period, 0, -1):
        h = max(highs[-i:])
        l = min(lows[-i:])
        if h!=l:
            ks.append(100*(closes[-i]-l)/(h-l))
    if len(ks) >= d_period:
        d = sum(ks[-d_period:])/d_period
    else:
        d = k
    return k, d

def detect_candle_pattern(open_, high, low, close, prev_open, prev_close):
    """Возвращает True, если обнаружен медвежий разворотный паттерн."""
    # Медвежье поглощение
    if prev_close > prev_open and close < open_ and close < prev_open and open_ > prev_close:
        return True
    # Падающая звезда
    body = abs(close-open_)
    if body > 0:
        upper_wick = high - max(open_, close)
        lower_wick = min(open_, close) - low
        if upper_wick > body*2 and lower_wick < body*0.5:
            return True
    return False

# -------------- Анализ монеты --------------
def analyze_coin(symbol):
    # Загружаем свечи для 4h (основной фильтр) и 1h (доп. индикаторы)
    ohlcv_4h = get_klines(symbol, '4h', 50)
    ohlcv_1h = get_klines(symbol, '1h', 50)
    ohlcv_15m = get_klines(symbol, '15m', 2)
    ohlcv_5m = get_klines(symbol, '5m', 50)

    if len(ohlcv_4h) < 20 or len(ohlcv_1h) < 20:
        return None

    # Извлекаем цены
    closes_4h = [c[3] for c in ohlcv_4h]
    highs_4h = [c[1] for c in ohlcv_4h]
    lows_4h = [c[2] for c in ohlcv_4h]
    opens_4h = [c[0] for c in ohlcv_4h]

    closes_1h = [c[3] for c in ohlcv_1h]
    highs_1h = [c[1] for c in ohlcv_1h]
    lows_1h = [c[2] for c in ohlcv_1h]
    opens_1h = [c[0] for c in ohlcv_1h]

    # RSI
    rsi_4h = rsi(closes_4h, 14)
    rsi_1h = rsi(closes_1h, 14)
    if rsi_4h is None or rsi_1h is None:
        return None

    # Bollinger Bands (4h)
    bb_upper, bb_mid, bb_lower = bollinger_bands(closes_4h, BB_PERIOD, BB_STD)
    if bb_upper is None:
        return None
    price_above_bb = closes_4h[-1] > bb_upper

    # MACD (1h)
    macd_line, signal_line, histogram = macd(closes_1h, 12, 26, 9)
    macd_bearish = macd_line is not None and signal_line is not None and macd_line < signal_line

    # Stochastic (4h)
    stoch_k, stoch_d = stochastic(highs_4h, lows_4h, closes_4h, STOCH_K_PERIOD, STOCH_D_PERIOD)
    stoch_over = stoch_k is not None and stoch_k > STOCH_OVERBOUGHT

    # ATR (1h для SL/TP)
    atr_val = compute_atr(highs_1h, lows_1h, closes_1h, ATR_PERIOD)
    if atr_val is None:
        return None

    # Ценовые изменения
    change_24h, volume_24h = get_24h_stats(symbol)
    if change_24h is None or volume_24h is None:
        return None
    if len(ohlcv_4h) >= 2:
        change_4h = (closes_4h[-1] - closes_4h[-2]) / closes_4h[-2] * 100
    else:
        return None
    funding = get_funding(symbol)
    real_price = get_realtime_price(symbol)
    if real_price is None:
        return None

    # Свечной паттерн (4h)
    if len(ohlcv_4h) >= 2:
        prev_open = opens_4h[-2]
        prev_close = closes_4h[-2]
        candle_bearish = detect_candle_pattern(opens_4h[-1], highs_4h[-1], lows_4h[-1], closes_4h[-1], prev_open, prev_close)
    else:
        candle_bearish = False

    # Обязательные условия
    if not (rsi_4h >= RSI_4H_MIN and rsi_1h >= RSI_1H_MIN and change_4h >= CHANGE_4H_MIN and
            funding is not None and funding >= FUNDING_MIN and volume_24h >= VOLUME_24H_MIN):
        return None

    # Дополнительные подтверждения (собираем баллы)
    confirmations = []
    if price_above_bb:
        confirmations.append(f"Цена выше верхней полосы Боллинджера (4h) – перекупленность")
    if macd_bearish:
        confirmations.append(f"MACD медвежий (1h) – сигнал разворота")
    if stoch_over:
        confirmations.append(f"Стохастик перекуплен (>80) – возможен откат")
    if candle_bearish:
        confirmations.append(f"Медвежий свечной паттерн (4h) – давление продавцов")

    # Минимум 2 подтверждения
    if len(confirmations) < 2:
        return None

    # Расчёт SL и TP
    entry = real_price
    sl = entry + SL_ATR_MULT * atr_val
    tp1 = entry - TP1_ATR_MULT * atr_val
    tp2 = entry - TP2_ATR_MULT * atr_val

    # Формируем сообщение
    reason_text = "\n".join([f"• {c}" for c in confirmations])

    msg = f"""
🔻 <b>SHORT СИГНАЛ</b> <b>{symbol}</b> | Цена: {entry:.6f}

<b>Вход:</b> {entry:.6f}
<b>Стоп-лосс:</b> {sl:.6f} (ATR × {SL_ATR_MULT})
<b>Тейк-профит 1:</b> {tp1:.6f} (ATR × {TP1_ATR_MULT})
<b>Тейк-профит 2:</b> {tp2:.6f} (ATR × {TP2_ATR_MULT})

<b>Индикаторы:</b>
RSI 4h: {rsi_4h:.1f} | RSI 1h: {rsi_1h:.1f}
Рост за 4ч: {change_4h:+.2f}%
Фандинг: {funding:+.4f}%
Объём 24ч: {volume_24h/1e6:.2f}M USDT

<b>Подтверждения:</b>
{reason_text}

⏰ {moscow_now().strftime('%Y-%m-%d %H:%M')} (МСК)
"""
    return msg

# -------------- Сканер --------------
def scan_market():
    print(f"[{moscow_now().strftime('%H:%M')} МСК] Запуск анализа...")
    coins = get_low_volume_coins()
    if not coins:
        send_telegram("⚠️ Не удалось получить список монет")
        return
    signals = []
    for idx, symbol in enumerate(coins):
        try:
            msg = analyze_coin(symbol)
            if msg:
                signals.append(msg)
                print(f"✅ Сигнал: {symbol}")
        except Exception as e:
            print(f"Ошибка {symbol}: {e}")
        time.sleep(0.3)
        if idx % 50 == 0:
            print(f"Обработано {idx}/{len(coins)}")
    for msg in signals:
        send_telegram(msg)
        time.sleep(2)
    print(f"Готово. Сигналов: {len(signals)}")

def is_working_hours():
    now = moscow_now()
    return WORK_START_HOUR <= now.hour < WORK_END_HOUR

if __name__ == "__main__":
    print(f"Бот запущен с расширенными индикаторами. Работает с {WORK_START_HOUR}:00 до {WORK_END_HOUR}:00 МСК, интервал {SCAN_INTERVAL_MINUTES} мин.")
    last_scan_time = None
    while True:
        if is_working_hours():
            now = moscow_now()
            if last_scan_time is None or (now - last_scan_time) >= timedelta(minutes=SCAN_INTERVAL_MINUTES):
                print(f"Старт в {now.strftime('%H:%M')} МСК")
                scan_market()
                last_scan_time = moscow_now()
        else:
            if last_scan_time is not None:
                print(f"Нерабочее время. Ожидание {WORK_START_HOUR}:00 МСК.")
                last_scan_time = None
        time.sleep(60)