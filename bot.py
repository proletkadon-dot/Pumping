import asyncio
import requests
import time
import math
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== НАСТРОЙКИ TELEGRAM ==========
TELEGRAM_TOKEN = "8590220699:AAG6U7JoOH638P-LhA5Ow-Byr2cgh7thAAE"
CHAT_ID = "694614387"

bot_enabled = True

CHECK_INTERVAL = 900
TOP_COINS = 20
MIN_VOLUME_USDT = 7_500_000
MIN_CHANGE_5M = 0.3
LEVERAGE = 10
MIN_AGREEMENT = 5

RSI_PERIOD = 14; RSI_OVERSOLD = 30; RSI_OVERBOUGHT = 70
EMA_SHORT = 9; EMA_LONG = 21
VOLUME_SURGE_FACTOR = 1.5
ADX_PERIOD = 14; ADX_STRONG = 25
SMA50_PERIOD = 50
BB_PERIOD = 20; BB_STD = 2
REQUIRE_FUNDING = True
MIN_VOL_RATIO = 1.2
RSI_LIMIT_LONG = 55
RSI_LIMIT_SHORT = 45
# =================================

# ---------- ФУНКЦИИ ПОЛУЧЕНИЯ ДАННЫХ ----------
def get_top_coins():
    url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page=50&page=1&sparkline=false"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        if not isinstance(data, list): return []
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
    except:
        return []

def get_klines(symbol, interval='5m', limit=200):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=10).json()
        if not isinstance(data, list) or len(data) < 50:
            return [], [], [], []
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        vols = [float(c[5]) for c in data]
        return closes, highs, lows, vols
    except:
        return [], [], [], []

def get_funding_rate(symbol):
    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}USDT"
    try:
        data = requests.get(url, timeout=10).json()
        return float(data.get('lastFundingRate', 0)) * 100
    except:
        return None

# ---------- ИНДИКАТОРЫ ----------
def calculate_rsi(closes, period=14):
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

def calculate_ema(closes, period):
    if len(closes) < period: return None
    mult = 2/(period+1)
    ema = closes[0]
    for p in closes[1:]: ema = (p-ema)*mult+ema
    return ema

def calculate_sma(closes, period):
    if len(closes) < period: return None
    return sum(closes[-period:])/period

def calculate_bollinger_bands(closes, period=20, std=2):
    if len(closes) < period: return None, None, None
    last = closes[-period:]
    sma = sum(last)/period
    var = sum((p-sma)**2 for p in last)/period
    stdev = math.sqrt(var)
    return sma+std*stdev, sma-std*stdev, sma

def calculate_macd_diff(closes, fast=12, slow=26):
    ema_f = calculate_ema(closes, fast)
    ema_s = calculate_ema(closes, slow)
    return ema_f - ema_s if ema_f and ema_s else None

def calculate_adx(highs, lows, closes, period=14):
    if len(closes) < period+1: return None
    tr, plus, minus = [], [], []
    for i in range(1, len(closes)):
        hl = highs[i]-lows[i]
        hc = abs(highs[i]-closes[i-1])
        lc = abs(lows[i]-closes[i-1])
        tr.append(max(hl, hc, lc))
        high_diff = highs[i]-highs[i-1]
        low_diff = lows[i-1]-lows[i]
        plus.append(high_diff if high_diff>low_diff and high_diff>0 else 0)
        minus.append(low_diff if low_diff>high_diff and low_diff>0 else 0)
    if len(tr) < period: return None
    avg_tr = sum(tr[-period:])/period
    avg_plus = sum(plus[-period:])/period
    avg_minus = sum(minus[-period:])/period
    if avg_tr == 0: return None
    plus_di = avg_plus/avg_tr*100
    minus_di = avg_minus/avg_tr*100
    dx = abs(plus_di-minus_di)/(plus_di+minus_di)*100 if (plus_di+minus_di)!=0 else 0
    return round(dx,1)

def find_fibo_levels(highs, lows, closes):
    if len(closes) < 100: return {}
    segment_highs = highs[-100:]
    segment_lows = lows[-100:]
    local_max = max(segment_highs)
    local_min = min(segment_lows)
    idx_max = segment_highs.index(local_max)
    idx_min = segment_lows.index(local_min)
    if idx_max > idx_min:
        start, end = local_min, local_max
    else:
        start, end = local_max, local_min
    diff = end - start
    levels = {}
    for level in [0.236, 0.382, 0.5, 0.618, 0.786]:
        levels[level] = start + diff * level
    return levels

def find_support_resistance(highs, lows, current_price):
    supports = []
    resistances = []
    for i in range(-100, -1):
        left = max(i-3, -100)
        right = min(i+4, 0)
        if lows[i] == min(lows[left:right]):
            supports.append(lows[i])
        if highs[i] == max(highs[left:right]):
            resistances.append(highs[i])
    supports = sorted(set(supports))
    resistances = sorted(set(resistances))
    nearest_support = max([s for s in supports if s < current_price], default=None)
    nearest_resistance = min([r for r in resistances if r > current_price], default=None)
    return nearest_support, nearest_resistance

def calculate_tp_sl_from_levels(price, supports, resistances, fibo_levels, direction):
    if direction == 'long':
        sl = supports * 0.995 if supports else price * 0.985
        sl_percent = (price - sl) / price * 100
        tp_candidates = []
        if resistances:
            tp_candidates.append(resistances)
        for level in [0.382, 0.5]:
            if level in fibo_levels and fibo_levels[level] > price:
                tp_candidates.append(fibo_levels[level])
        tp = min(tp_candidates) if tp_candidates else price * 1.02
        tp_percent = (tp - price) / price * 100
        explanation = f"SL ниже поддержки {supports:.6f}, TP к {tp:.6f}"
    else:
        sl = resistances * 1.005 if resistances else price * 1.015
        sl_percent = (sl - price) / price * 100
        tp_candidates = []
        if supports:
            tp_candidates.append(supports)
        for level in [0.618, 0.5]:
            if level in fibo_levels and fibo_levels[level] < price:
                tp_candidates.append(fibo_levels[level])
        tp = max(tp_candidates) if tp_candidates else price * 0.98
        tp_percent = (price - tp) / price * 100
        explanation = f"SL выше сопротивления {resistances:.6f}, TP к {tp:.6f}"
    return tp, sl, round(tp_percent,2), round(sl_percent,2), explanation

def analyze_coin(symbol):
    closes_5m, highs_5m, lows_5m, vols_5m = get_klines(symbol, '5m', 200)
    if len(closes_5m) < 100:
        return None
    rsi_5m = calculate_rsi(closes_5m, RSI_PERIOD)
    current_price = closes_5m[-1]
    volume_5m = vols_5m[-1]
    avg_vol = sum(vols_5m[-20:-1])/19 if len(vols_5m)>=20 else 0
    vol_ratio = volume_5m/avg_vol if avg_vol>0 else 0

    ind = {}
    desc = {}
    if rsi_5m:
        if rsi_5m < RSI_OVERSOLD: ind['rsi']='long'; desc['rsi']=f"RSI={rsi_5m:.1f} перепродан"
        elif rsi_5m > RSI_OVERBOUGHT: ind['rsi']='short'; desc['rsi']=f"RSI={rsi_5m:.1f} перекуплен"
        else: desc['rsi']=f"RSI={rsi_5m:.1f} нейтр."
    ema_s = calculate_ema(closes_5m, EMA_SHORT)
    ema_l = calculate_ema(closes_5m, EMA_LONG)
    if ema_s and ema_l:
        if ema_s > ema_l: ind['ema']='long'; desc['ema']=f"EMA{EMA_SHORT}>{EMA_LONG}"
        else: ind['ema']='short'; desc['ema']=f"EMA{EMA_SHORT}<{EMA_LONG}"
    bb_up, bb_low, _ = calculate_bollinger_bands(closes_5m, BB_PERIOD, BB_STD)
    if bb_up and bb_low:
        if current_price < bb_low: ind['bb']='long'; desc['bb']="Цена ниже нижней полосы"
        elif current_price > bb_up: ind['bb']='short'; desc['bb']="Цена выше верхней полосы"
        else: desc['bb']="Цена внутри полос"
    macd = calculate_macd_diff(closes_5m, 12, 26)
    if macd:
        if macd>0: ind['macd']='long'; desc['macd']="MACD положительный"
        else: ind['macd']='short'; desc['macd']="MACD отрицательный"
    if vol_ratio > VOLUME_SURGE_FACTOR:
        if len(closes_5m)>=2 and closes_5m[-1]>closes_5m[-2]: ind['volume']='long'; desc['volume']=f"Всплеск объёма x{vol_ratio:.1f} на росте"
        elif closes_5m[-1]<closes_5m[-2]: ind['volume']='short'; desc['volume']=f"Всплеск объёма x{vol_ratio:.1f} на падении"
        else: desc['volume']="Всплеск объёма"
    else: desc['volume']="Объём в норме"
    adx = calculate_adx(highs_5m, lows_5m, closes_5m, ADX_PERIOD)
    if adx and adx > ADX_STRONG:
        if ind.get('ema')=='long': ind['adx']='long'; desc['adx']=f"ADX={adx} сильный тренд вверх"
        elif ind.get('ema')=='short': ind['adx']='short'; desc['adx']=f"ADX={adx} сильный тренд вниз"
        else: desc['adx']=f"ADX={adx} сильный тренд"
    else: desc['adx']=f"ADX={adx if adx else '?'} слабый тренд"
    sma50 = calculate_sma(closes_5m, SMA50_PERIOD)
    if sma50:
        if current_price > sma50: ind['sma50']='long'; desc['sma50']="Цена выше SMA50"
        else: ind['sma50']='short'; desc['sma50']="Цена ниже SMA50"

    votes = [ind.get(k) for k in ['rsi','ema','bb','macd','volume','adx','sma50'] if ind.get(k) is not None]
    long_votes = votes.count('long'); short_votes = votes.count('short')
    direction = None
    if long_votes >= MIN_AGREEMENT: direction = 'long'
    elif short_votes >= MIN_AGREEMENT: direction = 'short'
    if not direction: return None

    funding = get_funding_rate(symbol)
    if REQUIRE_FUNDING and funding is not None:
        if direction == 'long' and funding >= 0: return None
        if direction == 'short' and funding <= 0: return None
    if vol_ratio < MIN_VOL_RATIO: return None
    if direction == 'long' and rsi_5m is not None and rsi_5m > RSI_LIMIT_LONG: return None
    if direction == 'short' and rsi_5m is not None and rsi_5m < RSI_LIMIT_SHORT: return None

    supports, resistances = find_support_resistance(highs_5m, lows_5m, current_price)
    fibo = find_fibo_levels(highs_5m, lows_5m, closes_5m)
    tp_price, sl_price, tp_pct, sl_pct, level_exp = calculate_tp_sl_from_levels(
        current_price, supports, resistances, fibo, direction
    )

    funding_str = f"{funding:.4f}%" if funding is not None else "нет данных"
    msg = f"""
{'🟢 LONG' if direction=='long' else '🔴 SHORT'} СИГНАЛ ({symbol})

• Согласие индикаторов: {long_votes if direction=='long' else short_votes}/7
💰 Вход: ${current_price:.6f}
🎯 TP (уровень): ${tp_price:.6f} ({'+' if direction=='long' else ''}{tp_pct}%)
🛑 SL (уровень): ${sl_price:.6f} ({'-' if direction=='long' else ''}{sl_pct}%)
⚙️ Плечо: {LEVERAGE}x

📊 Индикаторы:
• {desc['rsi']}
• {desc['ema']}
• {desc['bb']}
• {desc['macd']}
• {desc['volume']}
• {desc['adx']}
• {desc['sma50']}

📈 Фандинг: {funding_str}
📊 Объём/средний: {vol_ratio:.1f}x
📍 {level_exp}
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    return msg

# ---------- ФОНОВЫЙ АНАЛИЗ ----------
async def analysis_loop(app: Application):
    global bot_enabled
    while True:
        if bot_enabled:
            coins = get_top_coins()
            for coin in coins:
                try:
                    signal = analyze_coin(coin['symbol'])
                    if signal:
                        await app.bot.send_message(chat_id=CHAT_ID, text=signal, parse_mode='HTML')
                        await asyncio.sleep(1)
                except Exception as e:
                    print(f"Ошибка {coin['symbol']}: {e}")
                await asyncio.sleep(0.5)
            print(f"{datetime.now()} - Цикл анализа завершён")
        await asyncio.sleep(CHECK_INTERVAL)

# ---------- ОБРАБОТЧИКИ КОМАНД И КНОПОК ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("🟢 Включить"), KeyboardButton("🔴 Отключить")],
        [KeyboardButton("🔄 Перезагрузить"), KeyboardButton("ℹ️ Статус")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Управление ботом", reply_markup=reply_markup)

async def enable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_enabled
    bot_enabled = True
    await update.message.reply_text("✅ Бот включён, сигналы будут отправляться.")

async def disable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_enabled
    bot_enabled = False
    await update.message.reply_text("⛔ Бот отключён, сигналы не отправляются.")

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_enabled
    bot_enabled = True
    await update.message.reply_text("🔄 Бот перезагружен, состояние сброшено.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_text = "включён 🟢" if bot_enabled else "отключён 🔴"
    await update.message.reply_text(f"Статус бота: {status_text}")

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🟢 Включить":
        await enable(update, context)
    elif text == "🔴 Отключить":
        await disable(update, context)
    elif text == "🔄 Перезагрузить":
        await restart(update, context)
    elif text == "ℹ️ Статус":
        await status(update, context)

# ---------- ЗАПУСК ----------
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("enable", enable))
    app.add_handler(CommandHandler("disable", disable))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.Text("🟢 Включить"), handle_buttons))
    app.add_handler(MessageHandler(filters.Text("🔴 Отключить"), handle_buttons))
    app.add_handler(MessageHandler(filters.Text("🔄 Перезагрузить"), handle_buttons))
    app.add_handler(MessageHandler(filters.Text("ℹ️ Статус"), handle_buttons))

    loop = asyncio.get_event_loop()
    loop.create_task(analysis_loop(app))

    app.run_polling()

if __name__ == "__main__":
    main()