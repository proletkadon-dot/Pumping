import requests
import time
from datetime import datetime, timezone, timedelta

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

MAX_COINS = 500
MAX_24H_VOLUME_USDT = 500_000
MIN_24H_VOLUME_USDT = 30_000
TIMEFRAMES_RSI = ['5m', '15m', '1h', '4h']

RSI_4H_MIN = 65
RSI_1H_MIN = 65
CHANGE_4H_MIN = 2.0
FUNDING_MIN = 0.0
VOLUME_24H_MIN = 3_000_000

# Время работы (МСК)
WORK_START_HOUR = 10
WORK_END_HOUR = 22
SCAN_INTERVAL_MINUTES = 60  # интервал между сканированиями в минутах (можно 30, 45, 60 и т.д.)

# Резервный список монет
FALLBACK_COINS = [
    "RARE", "CLV", "DGB", "REI", "ALPACA", "FORTH", "BADGER", "NULS", "QKC",
    "DOCK", "TOMO", "HARD", "SYS", "MIR", "RLC", "OXT", "CTK", "MDX", "FIRO",
    "BURGER", "SANTOS", "MLN", "DIA", "WAN", "UNFI", "RGT", "VIDT", "QSP",
    "DEGO", "LTO", "KMD", "LINA", "FRONT", "LOOM", "STPT", "ARK", "POLYX",
    "BNX", "EPX", "SPELL", "TROY", "WTC", "WAVES", "CELO", "AERGO", "SUN"
]
# =================================

def moscow_now():
    """Текущее время в Москве (UTC+3)."""
    return datetime.now(timezone(timedelta(hours=3)))

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

def get_low_volume_coins():
    """Список низколиквидных монет с fallback."""
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
    # Bybit
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}USDT&interval={interval_map.get(interval, '5')}&limit={limit}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if data.get('retCode') == 0 and data.get('result', {}).get('list'):
            closes = [float(k[4]) for k in data['result']['list']]
            closes.reverse()
            return closes
    except:
        pass
    # KuCoin
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?type={interval}&symbol={symbol}-USDT&limit={limit}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if data.get('code') == '200000' and data.get('data'):
            return [float(c[2]) for c in data['data']]
    except:
        pass
    # Binance
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            return [float(c[4]) for c in data]
    except:
        pass
    return []

def calculate_rsi(closes, period=14):
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
    return round(100 - 100/(1+avg_gain/avg_loss), 2)

def get_price_change(symbol, interval, back_minutes):
    closes = get_klines(symbol, interval, 2)
    if len(closes) < 2:
        return None
    return (closes[-1] - closes[-2]) / closes[-2] * 100

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

def analyze_coin(symbol):
    rsis = {}
    for tf in TIMEFRAMES_RSI:
        closes = get_klines(symbol, tf, 50)
        if not closes:
            return None
        rsis[tf] = calculate_rsi(closes)
        if rsis[tf] is None:
            return None

    change_24h, volume_24h = get_24h_stats(symbol)
    if change_24h is None:
        return None
    change_15m = get_price_change(symbol, '15m', 15) or 0
    change_1h = get_price_change(symbol, '1h', 60) or 0
    change_4h = get_price_change(symbol, '4h', 240) or 0
    funding = get_funding(symbol)

    if (rsis['4h'] >= RSI_4H_MIN and rsis['1h'] >= RSI_1H_MIN and
        change_4h >= CHANGE_4H_MIN and funding is not None and funding >= FUNDING_MIN and
        volume_24h >= VOLUME_24H_MIN):

        reasons = []
        if rsis['4h'] >= RSI_4H_MIN:
            reasons.append(f"RSI 4h = {rsis['4h']} (выше {RSI_4H_MIN}) – перекупленность")
        if rsis['1h'] >= RSI_1H_MIN:
            reasons.append(f"RSI 1h = {rsis['1h']} (выше {RSI_1H_MIN}) – подтверждение")
        if change_4h >= CHANGE_4H_MIN:
            reasons.append(f"рост за 4ч = {change_4h:.2f}% (выше {CHANGE_4H_MIN}%) – импульс исчерпан")
        if funding >= FUNDING_MIN:
            reasons.append(f"фандинг = {funding:.2f}% – лонгисты платят шортистам")
        if volume_24h >= VOLUME_24H_MIN:
            reasons.append(f"объём 24ч = {volume_24h/1e6:.2f}M USDT – ликвидность достаточна")
        explanation = " ".join(reasons)

        real_price = get_realtime_price(symbol)
        if real_price is None:
            return None

        return f"""
🔻 <b>SHORT СИГНАЛ</b> <b>{symbol}</b> | {real_price:.4f}

<b>RSI:</b> 5m {rsis['5m']} | 15m {rsis['15m']} | 1h {rsis['1h']} | 4h {rsis['4h']}
<b>Изменение:</b> 24h {change_24h:+.2f}% | 15m {change_15m:+.2f}% | 1h {change_1h:+.2f}% | 4h {change_4h:+.2f}%
<b>Объём 24h:</b> {volume_24h/1e6:.2f}M
<b>Фандинг:</b> {funding:+.4f}% ✅

💡 <b>Обоснование:</b> {explanation}. Вероятна коррекция вниз.

⏰ {moscow_now().strftime('%Y-%m-%d %H:%M')} (МСК)
"""
    return None

def scan_market():
    print(f"[{moscow_now().strftime('%H:%M')} МСК] Начинаю анализ...")
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
    """Проверяет, находимся ли в рабочем окне (10–22 МСК)."""
    now = moscow_now()
    return WORK_START_HOUR <= now.hour < WORK_END_HOUR

if __name__ == "__main__":
    print(f"Бот запущен. Работает по МСК с {WORK_START_HOUR}:00 до {WORK_END_HOUR}:00, интервал {SCAN_INTERVAL_MINUTES} мин.")
    last_scan_time = None

    while True:
        if is_working_hours():
            now = moscow_now()
            # Если сканирование ещё не было, или прошло SCAN_INTERVAL_MINUTES минут
            if last_scan_time is None or (now - last_scan_time) >= timedelta(minutes=SCAN_INTERVAL_MINUTES):
                print(f"Запуск сканирования в {now.strftime('%H:%M')} МСК")
                scan_market()
                last_scan_time = moscow_now()
        else:
            if last_scan_time is not None:
                print(f"Нерабочее время. Ожидание {WORK_START_HOUR}:00 МСК.")
                last_scan_time = None
        time.sleep(60)