import requests
import schedule
import time
import math
from datetime import datetime

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

MAX_COINS = 500
MIN_24H_VOLUME_USDT = 300_000
TIMEFRAMES_RSI = ['5m', '15m', '1h', '4h']

RSI_4H_MIN = 65
RSI_1H_MIN = 65
CHANGE_4H_MIN = 2.0
FUNDING_MIN = 0.0
VOLUME_24H_MIN = 5_000_000
# =================================

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

# ---------- ФУНКЦИИ ПОЛУЧЕНИЯ ДАННЫХ ----------
def get_klines(symbol, interval='5m', limit=100):
    # Bybit
    interval_map = {'5m': '5', '15m': '15', '1h': '60', '4h': '240'}
    url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}USDT&interval={interval_map.get(interval, '5')}&limit={limit}"
    try:
        r = requests.get(url, timeout=8)
        data = r.json()
        if data.get('retCode') == 0 and data.get('result', {}).get('list'):
            klines = data['result']['list']
            closes = [float(k[4]) for k in klines]
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

def get_top_coins():
    # KuCoin
    try:
        url = "https://api.kucoin.com/api/v1/symbols"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get('code') == '200000':
            symbols = [s['symbol'] for s in data['data'] if s['symbol'].endswith('-USDT')]
            tickers_url = "https://api.kucoin.com/api/v1/market/allTickers"
            tickers_r = requests.get(tickers_url, timeout=10)
            tickers_data = tickers_r.json()
            if tickers_data.get('code') == '200000':
                tickers = {t['symbol']: float(t['volValue']) for t in tickers_data['data']['ticker'] if 'volValue' in t}
                sorted_symbols = sorted(symbols, key=lambda s: tickers.get(s, 0), reverse=True)
                coins = []
                for sym in sorted_symbols[:MAX_COINS]:
                    base = sym.replace('-USDT', '')
                    if base in ['BTC','ETH','USDT','USDC','DAI','BUSD','TUSD']:
                        continue
                    vol = tickers.get(sym, 0)
                    if vol >= MIN_24H_VOLUME_USDT:
                        coins.append(base)
                if coins:
                    print(f"Загружено {len(coins)} монет с KuCoin")
                    return coins
    except Exception as e:
        print(f"KuCoin список не удался: {e}")

    # Резервный список
    fallback = ["SOL","XRP","ADA","DOGE","MATIC","DOT","AVAX","LINK","LTC","NEAR","ATOM","FIL","ALGO","VET","ICP","EGLD","THETA","FTM","SAND","MANA","AXS","ENJ","ZIL","KLAY","CHZ","ONE","ICX","XTZ","AAVE","BCH","EOS","TRX","XLM","ZEC","DASH","NEO","ONT","QTUM","WAVES","KSM","RUNE","PEPE","WIF","BONK","FLOKI","NOT","TON","OP","ARB","SUI","APT","INJ","SEI","TIA","PYTH","JUP","ONDO","STRK","ENA","ETHFI","1000LUNC","LUNA2","USTC","ANC","MIR","BAT","ZRX","REP","SNX","COMP","MKR","YFI","CRV","UNI","SUSHI","CAKE","BAKE","ALPHA","BETA","GALA","CHZ","OGN","STORJ","BLZ","COTI","HOT","IOST","IOTX","KNC","LRC","NKN","NMR","POLS","RARE","REQ","RLC","STMX","SXP","TWT","VIDT","WAN","WAXP","ZEN","ZKS"]
    print(f"Использую резервный список из {len(fallback[:MAX_COINS])} монет")
    return fallback[:MAX_COINS]

def analyze_coin(symbol):
    # RSI
    rsis = {}
    for tf in TIMEFRAMES_RSI:
        closes = get_klines(symbol, tf, 50)
        if not closes:
            return None
        rsis[tf] = calculate_rsi(closes)
        if rsis[tf] is None:
            return None

    # Изменения
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
            reasons.append(f"RSI 4h = {rsis['4h']} (выше {RSI_4H_MIN}) – сильная перекупленность")
        if rsis['1h'] >= RSI_1H_MIN:
            reasons.append(f"RSI 1h = {rsis['1h']} (выше {RSI_1H_MIN}) – подтверждение перекупленности")
        if change_4h >= CHANGE_4H_MIN:
            reasons.append(f"рост за 4ч = {change_4h:.2f}% (выше {CHANGE_4H_MIN}%) – импульс исчерпан")
        if funding >= FUNDING_MIN:
            reasons.append(f"фандинг = {funding:.2f}% – лонгисты платят шортистам")
        if volume_24h >= VOLUME_24H_MIN:
            reasons.append(f"объём 24ч = {volume_24h/1e6:.2f}M USDT – высокая ликвидность")
        explanation = " ".join(reasons)

        real_price = get_realtime_price(symbol)
        if real_price is None:
            return None

        msg = f"""
🔻 <b>SHORT СИГНАЛ</b> <b>{symbol}</b> | {real_price:.4f}

<b>RSI:</b> 5m {rsis['5m']} | 15m {rsis['15m']} | 1h {rsis['1h']} | 4h {rsis['4h']}
<b>Изменение:</b> 24h {change_24h:+.2f}% | 15m {change_15m:+.2f}% | 1h {change_1h:+.2f}% | 4h {change_4h:+.2f}%
<b>Объём 24h:</b> {volume_24h/1e6:.2f}M
<b>Фандинг:</b> {funding:+.4f}% ✅

💡 <b>Логическое обоснование:</b> {explanation}. Совокупность факторов указывает на высокую вероятность коррекции вниз.

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return msg
    return None

def scan_market():
    print(f"[{datetime.now()}] Начинаю анализ...")
    coins = get_top_coins()
    if not coins:
        send_telegram("⚠️ Не удалось получить список монет")
        return
    signals = []
    for idx, symbol in enumerate(coins):
        try:
            msg = analyze_coin(symbol)
            if msg:
                signals.append(msg)
                print(f"✅ Сигнал для {symbol}")
        except Exception as e:
            print(f"Ошибка {symbol}: {e}")
        time.sleep(0.2)
        if idx % 50 == 0:
            print(f"Обработано {idx}/{len(coins)} монет")
    for msg in signals:
        send_telegram(msg)
        time.sleep(2)
    print(f"Готово. Сигналов: {len(signals)}")

if __name__ == "__main__":
    # Первый запуск сразу
    scan_market()
    # Запуск по расписанию (каждые 4 часа)
    schedule.every(4).hours.do(scan_market)
    print("Бот запущен. Анализ каждые 4 часа.")
    while True:
        schedule.run_pending()
        time.sleep(60)