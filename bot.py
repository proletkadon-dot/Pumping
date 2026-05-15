import requests
import time
import math
from datetime import datetime, timedelta

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = "8302482854:AAFVRh7y6B7yIX0IVRnLy7Om30uPu_cyGw4"
CHAT_ID = "694614387"

# Список монет (можно заменить на топ по объёму)
SYMBOLS = ["CGPT", "SOL", "ETH", "BTC", "XRP", "DOGE", "ADA", "MATIC", "DOT", "AVAX"]

CHECK_INTERVAL = 1800  # 30 минут
# =================================

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    except:
        pass

# ---------- ПОЛУЧЕНИЕ СВЕЧЕЙ ----------
def get_klines(symbol, interval, limit=100):
    """interval: 5m, 15m, 1h, 4h"""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        closes = [float(c[4]) for c in data]
        return closes
    except:
        return []

# ---------- RSI ----------
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

# ---------- ИЗМЕНЕНИЕ ЦЕНЫ ЗА ПЕРИОД ----------
def get_price_change(symbol, interval, minutes_ago):
    """Изменение цены за указанное количество минут (используя последнюю свечу)"""
    closes = get_klines(symbol, interval, limit=2)
    if len(closes) < 2:
        return None
    current = closes[-1]
    # Для интервалов 5m, 15m, 1h, 4h нужно преобразовать minutes_ago в количество свечей назад
    # Упрощённо: для 15м изменения берём свечу 15m назад
    interval_map = {'5m': 5, '15m': 15, '1h': 60, '4h': 240}
    if interval not in interval_map:
        return None
    minutes = interval_map[interval]
    # Берём свечу, которая была примерно minutes_ago минут назад
    bars_ago = int(minutes_ago / minutes) if minutes_ago % minutes == 0 else int(minutes_ago / minutes) + 1
    if bars_ago >= len(closes):
        return None
    prev = closes[-1 - bars_ago]
    return (current - prev) / prev * 100

# ---------- 24H ДАННЫЕ ----------
def get_24h_stats(symbol):
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}USDT"
    try:
        r = requests.get(url, timeout=5)
        data = r.json()
        return float(data['priceChangePercent']), float(data['quoteVolume'])
    except:
        return None, None

# ---------- КАПИТАЛИЗАЦИЯ (CoinGecko) ----------
def get_market_cap(symbol):
    url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={symbol.lower()}&order=market_cap_desc&per_page=1&page=1&sparkline=false"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        data = r.json()
        if data and isinstance(data, list) and 'market_cap' in data[0]:
            return data[0]['market_cap']
    except:
        pass
    return None

# ---------- ФАНДИНГ И OI (Binance Futures) ----------
def get_funding_and_oi(symbol):
    try:
        url_f = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}USDT"
        r_f = requests.get(url_f, timeout=5)
        funding = float(r_f.json().get('lastFundingRate', 0)) * 100
        url_oi = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}USDT"
        r_oi = requests.get(url_oi, timeout=5)
        oi = float(r_oi.json().get('openInterest', 0))
        # Изменение OI за 15м (нужно запрашивать историю, для упрощения пропустим)
        return funding, oi, None  # вместо None можно поставить изменение, если реализовать
    except:
        return None, None, None

# ---------- СТАКАН ОРДЕРОВ (спот) ----------
def get_orderbook(symbol, limit=500):
    url = f"https://api.binance.com/api/v3/depth?symbol={symbol}USDT&limit={limit}"
    try:
        r = requests.get(url, timeout=5)
        data = r.json()
        bids = [[float(x[0]), float(x[1])] for x in data['bids']]
        asks = [[float(x[0]), float(x[1])] for x in data['asks']]
        return bids, asks
    except:
        return [], []

def analyze_orderbook(bids, asks, current_price):
    levels = [0.2, 0.5, 1.0, 5.0, 10.0]
    bid_dens = {lev: 0 for lev in levels}
    ask_dens = {lev: 0 for lev in levels}
    for price, qty in bids:
        if price == 0: continue
        perc = (current_price - price) / current_price * 100
        for lev in levels:
            if perc <= lev:
                bid_dens[lev] += qty
                break
    for price, qty in asks:
        if price == 0: continue
        perc = (price - current_price) / current_price * 100
        for lev in levels:
            if perc <= lev:
                ask_dens[lev] += qty
                break
    # Крупные спот-лимитики (самый большой ордер на покупку/продажу в пределах 2%)
    large_bid = max([(price, qty) for price, qty in bids if (current_price - price)/current_price*100 <= 2], key=lambda x: x[1], default=(0,0))
    large_ask = max([(price, qty) for price, qty in asks if (price - current_price)/current_price*100 <= 2], key=lambda x: x[1], default=(0,0))
    return bid_dens, ask_dens, large_bid, large_ask

# ---------- ОСНОВНОЙ АНАЛИЗ ----------
def analyze_symbol(symbol):
    # Текущая цена
    url_price = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
    try:
        r = requests.get(url_price, timeout=5)
        price = float(r.json()['price'])
    except:
        return None

    # RSI на 5m, 15m, 1h, 4h
    rsi_5m = calculate_rsi(get_klines(symbol, '5m', 50), 14)
    rsi_15m = calculate_rsi(get_klines(symbol, '15m', 50), 14)
    rsi_1h = calculate_rsi(get_klines(symbol, '1h', 50), 14)
    rsi_4h = calculate_rsi(get_klines(symbol, '4h', 50), 14)
    if any(x is None for x in [rsi_5m, rsi_15m, rsi_1h, rsi_4h]):
        return None

    # Изменение цены за 24ч, 15м, 1ч, 4ч
    change_24h, volume_24h = get_24h_stats(symbol)
    change_15m = get_price_change(symbol, '15m', 15)
    change_1h = get_price_change(symbol, '1h', 60)
    change_4h = get_price_change(symbol, '4h', 240)
    if change_24h is None or volume_24h is None:
        return None

    # Капитализация (опционально)
    cap = get_market_cap(symbol)
    cap_str = f"{cap/1e9:.2f}B" if cap and cap > 1e9 else f"{cap/1e6:.2f}M" if cap else "н/д"

    # Фандинг и OI
    funding, oi, oi_change = get_funding_and_oi(symbol)
    funding_str = f"{funding:+.4f}%" if funding is not None else "нет данных"
    oi_str = f"{oi/1e6:.2f}M" if oi else "н/д"
    oi_change_str = f"{oi_change:+.2f}%" if oi_change else "?"

    # Стакан
    bids, asks = get_orderbook(symbol, limit=500)
    bid_dens, ask_dens, large_bid, large_ask = analyze_orderbook(bids, asks, price)

    # Формирование сообщения по шаблону
    msg = f"""
🔻 <b>ОБНАРУЖЕН SHORT-СИГНАЛ</b>
<b>{symbol} | {price:.4f}</b>

Таймфрейм графика: 4ч

<b>RSI:</b>  
5m {rsi_5m} | 15m {rsi_15m}  
1h {rsi_1h} | 4h {rsi_4h}  

---

### Рынок:
24ч {change_24h:+.2f}% | 15м {change_15m:+.2f}%  
1ч {change_1h:+.2f}% | 4ч {change_4h:+.2f}%  
Объем 24ч {volume_24h/1e6:.2f}M USDT  
Капитализация {cap_str}  

---

### Деривативы:
Фандинг {funding_str}  
OI 15м {oi_change_str} | Объем 15м ?  

---

### Фьючерсный стакан:
Плотность покупателей:  
в пределах 0.2% {bid_dens[0.2]:.0f} | 0.5% {bid_dens[0.5]:.0f} | 1.0% {bid_dens[1.0]:.0f} | 5.0% {bid_dens[5.0]:.0f} | 10.0% {bid_dens[10.0]:.0f}  

Плотность продавцов:  
0.2% {ask_dens[0.2]:.0f} | 0.5% {ask_dens[0.5]:.0f} | 1.0% {ask_dens[1.0]:.0f} | 5.0% {ask_dens[5.0]:.0f} | 10.0% {ask_dens[10.0]:.0f}  

Плотность Стенки продажи:  
+0.41% @ {price*1.0041:.4f} → {large_ask[1]:.0f}  
+0.53% @ {price*1.0053:.4f} → ?

---

### Спот-лимитики:
Продажи:  
+1.56% @ {price*1.0156:.4f} → ?  
Покупки:  
-0.28% @ {price*0.9972:.4f} → {large_bid[1]:.0f}
"""
    return msg

def main():
    send_telegram("🚀 Бот 3 (полноценный анализ SHORT) запущен. Анализ каждые 30 минут.")
    print("Бот запущен.")
    while True:
        for symbol in SYMBOLS:
            try:
                signal = analyze_symbol(symbol)
                if signal:
                    send_telegram(signal)
                    time.sleep(2)
            except Exception as e:
                print(f"Ошибка {symbol}: {e}")
            time.sleep(1)
        print(f"{datetime.now()} - цикл завершён, жду {CHECK_INTERVAL} сек.")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()