import requests
import time
import math
from datetime import datetime

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

MAX_COINS = 500                         # количество монет
MIN_24H_VOLUME_USDT = 500_000           # мин. объём $500k (отсев мусора)
CHECK_INTERVAL = 3600                   # 1 час (чтобы успеть обработать 500 монет)
TIMEFRAMES_RSI = ['5m', '15m', '1h', '4h']
# =================================

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

# ---------- ПОЛУЧЕНИЕ СПИСКА 500 МОНЕТ (сортировка по объёму) ----------
def get_top_500_coins():
    # Пробуем KuCoin (список всех USDT пар)
    try:
        url = "https://api.kucoin.com/api/v1/symbols"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data['code'] == '200000':
            # Получаем все USDT пары
            symbols = [s['symbol'] for s in data['data'] if s['symbol'].endswith('-USDT')]
            # Нужно отсортировать по объёму – у KuCoin нет прямого поля, поэтому делаем запрос на тикеры
            tickers_url = "https://api.kucoin.com/api/v1/market/allTickers"
            tickers_r = requests.get(tickers_url, timeout=10)
            tickers_data = tickers_r.json()
            if tickers_data['code'] == '200000':
                tickers = {t['symbol']: float(t['volValue']) for t in tickers_data['data']['ticker'] if 'volValue' in t}
                # Сортируем по объёму
                sorted_symbols = sorted(symbols, key=lambda s: tickers.get(s, 0), reverse=True)
                coins = []
                for sym in sorted_symbols[:MAX_COINS]:
                    base = sym.replace('-USDT', '')
                    if base in ['BTC','ETH','USDT','USDC','DAI','BUSD','TUSD']:
                        continue
                    vol = tickers.get(sym, 0)
                    if vol >= MIN_24H_VOLUME_USDT:
                        coins.append({'symbol': base, 'volume': vol})
                if coins:
                    print(f"Загружено {len(coins)} монет с KuCoin")
                    return coins[:MAX_COINS]
    except Exception as e:
        print(f"KuCoin список не удался: {e}")

    # Fallback: Binance (если доступен)
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        r = requests.get(url, timeout=15)
        data = r.json()
        usdt_pairs = [p for p in data if p['symbol'].endswith('USDT')]
        usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
        coins = []
        for pair in usdt_pairs[:MAX_COINS]:
            sym = pair['symbol'].replace('USDT', '')
            if sym in ['BTC','ETH','USDT','USDC','DAI','BUSD','TUSD']:
                continue
            vol = float(pair['quoteVolume'])
            if vol >= MIN_24H_VOLUME_USDT:
                coins.append({'symbol': sym, 'volume': vol})
        if coins:
            print(f"Загружено {len(coins)} монет с Binance")
            return coins[:MAX_COINS]
    except Exception as e:
        print(f"Binance список не удался: {e}")

    # Резервный список (первые 500 из известных)
    fallback = ["BTC","ETH","SOL","XRP","ADA","DOGE","MATIC","DOT","AVAX","LINK","LTC","NEAR","ATOM","FIL","ALGO","VET","ICP","EGLD","THETA","FTM","SAND","MANA","AXS","ENJ","ZIL","KLAY","CHZ","ONE","ICX","XTZ","AAVE","BCH","EOS","TRX","XLM","ZEC","DASH","NEO","ONT","QTUM","WAVES","KSM","RUNE","PEPE","WIF","BONK","FLOKI","NOT","TON","OP","ARB","SUI","APT","INJ","SEI","TIA","PYTH","JUP","ONDO","STRK","ENA","ETHFI","1000LUNC","LUNA2","USTC","ANC","MIR","BAT","ZRX","REP","SNX","COMP","MKR","YFI","CRV","UNI","SUSHI","CAKE","BAKE","ALPHA","BETA","GALA","MANA","SAND","CHZ","OGN","STORJ","BLZ","COTI","HOT","IOST","IOTX","KNC","LRC","NKN","NMR","POLS","RARE","REQ","RLC","STMX","SXP","TWT","VIDT","WAN","WAXP","ZEN","ZKS"]  # продолжение
    coins = [{'symbol': s, 'volume': 0} for s in fallback[:MAX_COINS]]
    print(f"Использую резервный список из {len(coins)} монет")
    return coins

# ---------- ПОЛУЧЕНИЕ СВЕЧЕЙ (с fallback) ----------
def get_klines(symbol, interval='5m', limit=100):
    # Пробуем Binance
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
    try:
        r = requests.get(url, timeout=8)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            return [float(c[4]) for c in data]
    except:
        pass
    # Пробуем KuCoin
    try:
        url = f"https://api.kucoin.com/api/v1/market/candles?type={interval}&symbol={symbol}-USDT&limit={limit}"
        r = requests.get(url, timeout=8)
        data = r.json()
        if data['code'] == '200000' and data['data']:
            return [float(c[2]) for c in data['data']]
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
    # Упрощённо: берём две свечи – текущую и через back_minutes
    closes = get_klines(symbol, interval, limit=2)
    if len(closes) < 2:
        return None
    current = closes[-1]
    prev = closes[-2]
    return (current - prev) / prev * 100

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
        return float(r.json().get('lastFundingRate', 0)) * 100
    except:
        return None

def analyze_coin(symbol):
    # Текущая цена
    url_price = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
    try:
        r = requests.get(url_price, timeout=5)
        price = float(r.json()['price'])
    except:
        return None

    # RSI на 5m, 15m, 1h, 4h
    rsis = {}
    for tf in TIMEFRAMES_RSI:
        closes = get_klines(symbol, tf, 50)
        rsis[tf] = calculate_rsi(closes)
        if rsis[tf] is None:
            return None

    # Изменения цены
    change_24h, volume_24h = get_24h_stats(symbol)
    if change_24h is None:
        return None
    change_15m = get_price_change(symbol, '15m', 15) or 0
    change_1h = get_price_change(symbol, '1h', 60) or 0
    change_4h = get_price_change(symbol, '4h', 240) or 0

    # Фандинг
    funding = get_funding(symbol)
    funding_str = f"{funding:+.4f}%" if funding is not None else "нет данных"

    # Формирование сообщения (краткого, т.к. 500 монет – много информации)
    msg = f"""
🔻 <b>SHORT СИГНАЛ</b> <b>{symbol}</b> | {price:.4f}

<b>RSI:</b> 5m {rsis['5m']} | 15m {rsis['15m']} | 1h {rsis['1h']} | 4h {rsis['4h']}
<b>Изменение:</b> 24h {change_24h:+.2f}% | 15m {change_15m:+.2f}% | 1h {change_1h:+.2f}% | 4h {change_4h:+.2f}%
<b>Объём 24h:</b> {volume_24h/1e6:.2f}M
<b>Фандинг:</b> {funding_str}
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    # Дополнительные условия для сигнала (можно настроить)
    if rsis['4h'] > 70 and rsis['1h'] > 70 and change_4h > 2 and (funding and funding > 0):
        return msg
    else:
        return None

def main():
    send_telegram("🚀 Бот анализирует 500 монет. Отчёт о сигналах (SHORT) будет раз в час.")
    print("Бот запущен. Загружаю 500 монет...")
    coins = get_top_500_coins()
    print(f"Загружено {len(coins)} монет. Начинаю цикл.")
    while True:
        signals = []
        for idx, coin in enumerate(coins):
            symbol = coin['symbol']
            try:
                sig = analyze_coin(symbol)
                if sig:
                    signals.append(sig)
            except Exception as e:
                print(f"Ошибка {symbol}: {e}")
            # Задержка между запросами, чтобы не перегружать API
            time.sleep(0.3)
            if idx % 50 == 0:
                print(f"Обработано {idx}/{len(coins)} монет")
        # Отправляем все накопленные сигналы
        for sig in signals:
            send_telegram(sig)
            time.sleep(2)
        print(f"{datetime.now()} - цикл завершён, жду {CHECK_INTERVAL} сек.")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()