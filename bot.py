import os
import logging
import asyncio
import sqlite3
import pickle
from datetime import datetime
from typing import Dict, Tuple, List, Optional
import numpy as np
import pandas as pd
import ccxt
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

# ======================== ИНИЦИАЛИЗАЦИЯ ========================
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------------------- ИНЛАЙН-КЛАВИАТУРА (вставка в поле ввода) ----------------------
def get_main_inline_keyboard() -> InlineKeyboardMarkup:
    """Кнопки, которые вставляют текст команды в поле ввода, не отправляя."""
    buttons = [
        [InlineKeyboardButton(text="📊 /signal BTC/USDT 1h", switch_inline_query_current_chat="/signal BTC/USDT 1h")],
        [InlineKeyboardButton(text="📈 /backtest", switch_inline_query_current_chat="/backtest BTC/USDT 1h 2025-01-01 2025-03-01")],
        [InlineKeyboardButton(text="🧠 /train", switch_inline_query_current_chat="/train")],
        [InlineKeyboardButton(text="❓ /help", switch_inline_query_current_chat="/help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------------------- НАСТРОЙКИ БИРЖ (ФЬЮЧЕРСЫ) ----------------------
EXCHANGES = [
    ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}}),
    ccxt.bybit({'enableRateLimit': True, 'options': {'defaultType': 'linear'}}),
    ccxt.okx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}}),
    ccxt.kucoin({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
]

TIMEFRAMES = {'5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d'}

# ======================== БАЗА ДАННЫХ ========================
def init_db():
    conn = sqlite3.connect('signals.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS signals
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT, symbol TEXT, timeframe TEXT,
                  signal TEXT, entry REAL, sl REAL, tp REAL,
                  rsi REAL, macd_hist REAL, ema9 REAL, ema21 REAL, atr REAL,
                  adx REAL, mfi REAL, stoch_k REAL, volume_above_avg INTEGER,
                  ob_imbalance REAL, ob_pressure TEXT,
                  outcome TEXT, pnl REAL)''')
    conn.commit()
    conn.close()

init_db()

def save_signal(symbol: str, timeframe: str, signal: str, indicators: Dict, levels: Dict, ob_analysis: Dict):
    conn = sqlite3.connect('signals.db')
    c = conn.cursor()
    c.execute('''INSERT INTO signals 
                 (timestamp, symbol, timeframe, signal, entry, sl, tp,
                  rsi, macd_hist, ema9, ema21, atr, adx, mfi, stoch_k, volume_above_avg,
                  ob_imbalance, ob_pressure, outcome, pnl)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (datetime.now().isoformat(), symbol, timeframe, signal,
               levels['entry'], levels['stop_loss'], levels['take_profit'],
               indicators['rsi'], indicators['macd_histogram'],
               indicators['ema9'], indicators['ema21'], indicators['atr'],
               indicators.get('adx', 0), indicators.get('mfi', 0),
               indicators.get('stoch_k', 0), int(indicators.get('volume_above_avg', False)),
               ob_analysis.get('imbalance_pct', 0), ob_analysis.get('pressure', 'NEUTRAL'),
               None, None))
    conn.commit()
    conn.close()

# ======================== ПОЛУЧЕНИЕ ДАННЫХ ========================
async def fetch_live_price(symbol: str) -> Tuple[Optional[float], Optional[str]]:
    for exchange in EXCHANGES:
        try:
            loop = asyncio.get_event_loop()
            ticker = await loop.run_in_executor(None, exchange.fetch_ticker, symbol)
            price = ticker['last']
            if price:
                logger.info(f"✅ Живая цена {symbol} от {exchange.name}: {price}")
                return price, exchange.name
        except Exception as e:
            logger.warning(f"⚠️ {exchange.name} не дал цену: {e}")
            continue
    return None, None

async def fetch_ohlcv_any(symbol: str, timeframe: str, limit: int = 150) -> Optional[pd.DataFrame]:
    for exchange in EXCHANGES:
        try:
            loop = asyncio.get_event_loop()
            ohlcv = await loop.run_in_executor(None, exchange.fetch_ohlcv, symbol, timeframe, limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            logger.info(f"📊 Исторические данные от {exchange.name} для {symbol}")
            return df
        except Exception as e:
            logger.warning(f"⚠️ {exchange.name} не дал свечи: {e}")
            continue
    return None

async def fetch_orderbook_analysis(symbol: str, limit: int = 20) -> Optional[Dict]:
    for exchange in EXCHANGES:
        try:
            loop = asyncio.get_event_loop()
            orderbook = await loop.run_in_executor(None, exchange.fetch_order_book, symbol, limit)
            bids_volume = sum([bid[1] for bid in orderbook['bids']])
            asks_volume = sum([ask[1] for ask in orderbook['asks']])
            best_bid = orderbook['bids'][0][0] if orderbook['bids'] else 0
            best_ask = orderbook['asks'][0][0] if orderbook['asks'] else 0
            spread = best_ask - best_bid
            spread_pct = (spread / best_bid) * 100 if best_bid else 0
            max_bid_wall = max(orderbook['bids'], key=lambda x: x[1]) if orderbook['bids'] else (0,0)
            max_ask_wall = max(orderbook['asks'], key=lambda x: x[1]) if orderbook['asks'] else (0,0)
            imbalance = bids_volume - asks_volume
            total_volume = bids_volume + asks_volume
            imbalance_pct = (imbalance / total_volume) * 100 if total_volume > 0 else 0
            pressure = "BULLISH" if imbalance > 0 else "BEARISH" if imbalance < 0 else "NEUTRAL"
            return {
                'bids_volume': bids_volume, 'asks_volume': asks_volume,
                'imbalance': imbalance, 'imbalance_pct': imbalance_pct,
                'best_bid': best_bid, 'best_ask': best_ask, 'spread': spread, 'spread_pct': spread_pct,
                'max_bid_wall_price': max_bid_wall[0], 'max_bid_wall_volume': max_bid_wall[1],
                'max_ask_wall_price': max_ask_wall[0], 'max_ask_wall_volume': max_ask_wall[1],
                'pressure': pressure, 'exchange': exchange.name
            }
        except Exception as e:
            logger.warning(f"⚠️ {exchange.name} не дал стакан: {e}")
            continue
    return None

# ======================== РАСЧЁТ ИНДИКАТОРОВ ========================
def calculate_indicators(df: pd.DataFrame, live_price: float = None) -> Dict:
    df = df.copy()
    if live_price:
        df.iloc[-1, df.columns.get_loc('close')] = live_price
        df.iloc[-1, df.columns.get_loc('high')] = max(df.iloc[-1, df.columns.get_loc('high')], live_price)
        df.iloc[-1, df.columns.get_loc('low')] = min(df.iloc[-1, df.columns.get_loc('low')], live_price)

    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_histogram'] = df['macd'] - df['macd_signal']
    # EMA
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
    # Bollinger
    rolling_mean = df['close'].rolling(20).mean()
    rolling_std = df['close'].rolling(20).std()
    df['bb_upper'] = rolling_mean + (rolling_std * 2)
    df['bb_lower'] = rolling_mean - (rolling_std * 2)
    # ATR
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    # ADX
    plus_dm = df['high'].diff()
    minus_dm = df['low'].diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    tr_ = pd.concat([df['high'] - df['low'],
                     (df['high'] - df['close'].shift()).abs(),
                     (df['low'] - df['close'].shift()).abs()], axis=1).max(axis=1)
    atr_ = tr_.rolling(14).mean()
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr_)
    minus_di = 100 * (abs(minus_dm).rolling(14).mean() / atr_)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    df['adx'] = dx.rolling(14).mean()
    # OBV
    obv = (df['volume'] * (~df['close'].diff().le(0) * 2 - 1)).cumsum()
    df['obv'] = obv
    df['obv_change'] = df['obv'].diff(5)
    df['obv_bullish'] = df['obv_change'] > 0
    # MFI
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    money_flow = typical_price * df['volume']
    positive_flow = money_flow.where(typical_price > typical_price.shift(), 0).rolling(14).sum()
    negative_flow = money_flow.where(typical_price < typical_price.shift(), 0).rolling(14).sum()
    mfi = 100 - (100 / (1 + positive_flow / negative_flow))
    df['mfi'] = mfi
    # Stochastic RSI
    rsi = df['rsi']
    stoch_rsi = (rsi - rsi.rolling(14).min()) / (rsi.rolling(14).max() - rsi.rolling(14).min())
    df['stoch_k'] = stoch_rsi.rolling(3).mean() * 100
    df['stoch_d'] = df['stoch_k'].rolling(3).mean()
    # Ichimoku
    conversion_line = (df['high'].rolling(9).max() + df['low'].rolling(9).min()) / 2
    base_line = (df['high'].rolling(26).max() + df['low'].rolling(26).min()) / 2
    senkou_a = ((conversion_line + base_line) / 2).shift(26)
    df['price_above_cloud'] = df['close'] > senkou_a
    # Volume SMA
    df['volume_sma'] = df['volume'].rolling(20).mean()
    df['volume_above_avg'] = df['volume'] > df['volume_sma']

    current = {
        'price': float(df['close'].iloc[-1]),
        'rsi': float(df['rsi'].iloc[-1]) if pd.notna(df['rsi'].iloc[-1]) else 50,
        'macd_histogram': float(df['macd_histogram'].iloc[-1]) if pd.notna(df['macd_histogram'].iloc[-1]) else 0,
        'ema9': float(df['ema9'].iloc[-1]) if pd.notna(df['ema9'].iloc[-1]) else 0,
        'ema21': float(df['ema21'].iloc[-1]) if pd.notna(df['ema21'].iloc[-1]) else 0,
        'bb_lower': float(df['bb_lower'].iloc[-1]) if pd.notna(df['bb_lower'].iloc[-1]) else 0,
        'bb_upper': float(df['bb_upper'].iloc[-1]) if pd.notna(df['bb_upper'].iloc[-1]) else 0,
        'atr': float(df['atr'].iloc[-1]) if pd.notna(df['atr'].iloc[-1]) else 0,
        'adx': float(df['adx'].iloc[-1]) if pd.notna(df['adx'].iloc[-1]) else 20,
        'obv_bullish': bool(df['obv_bullish'].iloc[-1]) if pd.notna(df['obv_bullish'].iloc[-1]) else False,
        'mfi': float(df['mfi'].iloc[-1]) if pd.notna(df['mfi'].iloc[-1]) else 50,
        'stoch_k': float(df['stoch_k'].iloc[-1]) if pd.notna(df['stoch_k'].iloc[-1]) else 50,
        'stoch_d': float(df['stoch_d'].iloc[-1]) if pd.notna(df['stoch_d'].iloc[-1]) else 50,
        'price_above_cloud': bool(df['price_above_cloud'].iloc[-1]) if pd.notna(df['price_above_cloud'].iloc[-1]) else False,
        'volume_above_avg': bool(df['volume_above_avg'].iloc[-1]) if pd.notna(df['volume_above_avg'].iloc[-1]) else False,
    }
    return current

def generate_raw_signal(indicators: Dict, ob_analysis: Dict = None) -> Tuple[str, List[str], List[str]]:
    long_cond = []
    short_cond = []
    price = indicators['price']

    if indicators['rsi'] < 40: long_cond.append(f"RSI={indicators['rsi']:.1f} < 40")
    elif indicators['rsi'] > 60: short_cond.append(f"RSI={indicators['rsi']:.1f} > 60")
    if indicators['macd_histogram'] > 0: long_cond.append("MACD > 0")
    elif indicators['macd_histogram'] < 0: short_cond.append("MACD < 0")
    if indicators['ema9'] > indicators['ema21']: long_cond.append("EMA9 > EMA21")
    elif indicators['ema9'] < indicators['ema21']: short_cond.append("EMA9 < EMA21")
    if price <= indicators['bb_lower'] * 1.01: long_cond.append("Price near lower BB")
    elif price >= indicators['bb_upper'] * 0.99: short_cond.append("Price near upper BB")
    if indicators['adx'] > 25:
        long_cond.append(f"ADX={indicators['adx']:.1f} > 25")
        short_cond.append(f"ADX={indicators['adx']:.1f} > 25")
    if indicators['obv_bullish']: long_cond.append("OBV rising")
    else: short_cond.append("OBV falling")
    if indicators['mfi'] < 20: long_cond.append(f"MFI={indicators['mfi']:.1f} < 20")
    elif indicators['mfi'] > 80: short_cond.append(f"MFI={indicators['mfi']:.1f} > 80")
    if indicators['stoch_k'] < 20: long_cond.append(f"StochK={indicators['stoch_k']:.1f} < 20")
    elif indicators['stoch_k'] > 80: short_cond.append(f"StochK={indicators['stoch_k']:.1f} > 80")
    if indicators['price_above_cloud']: long_cond.append("Price above Ichimoku cloud")
    else: short_cond.append("Price below Ichimoku cloud")
    if indicators['volume_above_avg']:
        long_cond.append("Volume > SMA20")
        short_cond.append("Volume > SMA20")
    if ob_analysis:
        if ob_analysis['pressure'] == 'BULLISH': long_cond.append(f"Order book: {ob_analysis['imbalance_pct']:.1f}% bid imbalance")
        elif ob_analysis['pressure'] == 'BEARISH': short_cond.append(f"Order book: {abs(ob_analysis['imbalance_pct']):.1f}% ask imbalance")

    if len(long_cond) >= 6: return "LONG", long_cond, short_cond
    elif len(short_cond) >= 6: return "SHORT", long_cond, short_cond
    else: return "NEUTRAL", long_cond, short_cond

# ======================== НЕЙРОСЕТЬ ========================
class NeuralConfirmer:
    def __init__(self, model_path: str = "model.pkl"):
        self.model_path = model_path
        self.model = None
        self.scaler = None
        self.load_model()
    def load_model(self):
        if os.path.exists(self.model_path):
            with open(self.model_path, 'rb') as f:
                self.model, self.scaler = pickle.load(f)
            logger.info("Neural model loaded")
        else:
            logger.info("No existing model")
    def save_model(self):
        with open(self.model_path, 'wb') as f:
            pickle.dump((self.model, self.scaler), f)
    def train(self, X, y):
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)
        self.model = MLPClassifier(hidden_layer_sizes=(50, 25), max_iter=500, random_state=42)
        self.model.fit(X_scaled, y)
        self.save_model()
    def predict_probability(self, features: np.ndarray) -> float:
        if self.model is None:
            return 0.5
        X_scaled = self.scaler.transform(features.reshape(1, -1))
        return self.model.predict_proba(X_scaled)[0][1]

confirmer = NeuralConfirmer()

def get_feature_vector(indicators: Dict) -> np.ndarray:
    ema_diff = indicators['ema9'] - indicators['ema21']
    bb_pos = (indicators['price'] - indicators['bb_lower']) / (indicators['bb_upper'] - indicators['bb_lower']) if indicators['bb_upper'] != indicators['bb_lower'] else 0.5
    return np.array([indicators['rsi'], indicators['macd_histogram'], ema_diff,
                     indicators['atr'], bb_pos, indicators['adx'], indicators['mfi'], indicators['stoch_k']])

# ======================== ГАЛОЧКИ ========================
def format_conditions_checklist(indicators: Dict, ob_analysis: Dict = None) -> str:
    price = indicators['price']
    rsi_bull = indicators['rsi'] < 40
    macd_bull = indicators['macd_histogram'] > 0
    ema_bull = indicators['ema9'] > indicators['ema21']
    bb_bull = price <= indicators['bb_lower'] * 1.01
    adx_strong = indicators['adx'] > 25
    obv_bull = indicators['obv_bullish']
    mfi_bull = indicators['mfi'] < 20
    stoch_bull = indicators['stoch_k'] < 20
    ichi_bull = indicators['price_above_cloud']
    vol_bull = indicators['volume_above_avg']
    
    rsi_bear = indicators['rsi'] > 60
    macd_bear = indicators['macd_histogram'] < 0
    ema_bear = indicators['ema9'] < indicators['ema21']
    bb_bear = price >= indicators['bb_upper'] * 0.99
    obv_bear = not indicators['obv_bullish']
    mfi_bear = indicators['mfi'] > 80
    stoch_bear = indicators['stoch_k'] > 80
    ichi_bear = not indicators['price_above_cloud']
    vol_bear = indicators['volume_above_avg']
    
    ob_bull = False
    ob_bear = False
    if ob_analysis:
        if ob_analysis['pressure'] == 'BULLISH':
            ob_bull = True
        elif ob_analysis['pressure'] == 'BEARISH':
            ob_bear = True

    checklist = "**📊 Бычьи условия (LONG):**\n"
    checklist += f"{'✅' if rsi_bull else '❌'} RSI < 40 (перепроданность)\n"
    checklist += f"{'✅' if macd_bull else '❌'} MACD > 0 (бычий импульс)\n"
    checklist += f"{'✅' if ema_bull else '❌'} EMA9 > EMA21 (бычий крест)\n"
    checklist += f"{'✅' if bb_bull else '❌'} Цена у нижней полосы BB\n"
    checklist += f"{'✅' if adx_strong else '❌'} ADX > 25 (сильный тренд)\n"
    checklist += f"{'✅' if obv_bull else '❌'} OBV растёт\n"
    checklist += f"{'✅' if mfi_bull else '❌'} MFI < 20 (перепроданность)\n"
    checklist += f"{'✅' if stoch_bull else '❌'} Stoch K < 20 (oversold)\n"
    checklist += f"{'✅' if ichi_bull else '❌'} Цена выше облака Ишимоку\n"
    checklist += f"{'✅' if vol_bull else '❌'} Объём > SMA20\n"
    checklist += f"{'✅' if ob_bull else '❌'} Стакан: давление покупателей\n\n"

    checklist += "**📉 Медвежьи условия (SHORT):**\n"
    checklist += f"{'✅' if rsi_bear else '❌'} RSI > 60 (перекупленность)\n"
    checklist += f"{'✅' if macd_bear else '❌'} MACD < 0 (медвежий импульс)\n"
    checklist += f"{'✅' if ema_bear else '❌'} EMA9 < EMA21 (медвежий крест)\n"
    checklist += f"{'✅' if bb_bear else '❌'} Цена у верхней полосы BB\n"
    checklist += f"{'✅' if adx_strong else '❌'} ADX > 25 (сильный тренд)\n"
    checklist += f"{'✅' if obv_bear else '❌'} OBV падает\n"
    checklist += f"{'✅' if mfi_bear else '❌'} MFI > 80 (перекупленность)\n"
    checklist += f"{'✅' if stoch_bear else '❌'} Stoch K > 80 (overbought)\n"
    checklist += f"{'✅' if ichi_bear else '❌'} Цена ниже облака Ишимоку\n"
    checklist += f"{'✅' if vol_bear else '❌'} Объём > SMA20\n"
    checklist += f"{'✅' if ob_bear else '❌'} Стакан: давление продавцов\n"
    return checklist

# ======================== КОММЕНТАРИЙ ========================
def generate_commentary(symbol: str, final_signal: str, raw_signal: str,
                        indicators: Dict, long_cond_count: int, short_cond_count: int,
                        neural_prob: float, ob_analysis: Dict = None) -> str:
    price = indicators['price']
    rsi = indicators['rsi']
    adx = indicators['adx']
    macd = indicators['macd_histogram']
    ema_cross = "EMA9 выше EMA21" if indicators['ema9'] > indicators['ema21'] else "EMA9 ниже EMA21"
    volume_ok = indicators['volume_above_avg']
    cloud = "выше облака" if indicators['price_above_cloud'] else "ниже облака"

    commentary = f"💬 **Мнение бота по {symbol}**:\n\n"
    if rsi < 30:
        commentary += f"📊 RSI = {rsi:.1f} — монета **сильно перепродана**, что часто предвещает отскок вверх. "
    elif rsi < 40:
        commentary += f"📊 RSI = {rsi:.1f} — монета в зоне перепроданности, возможен разворот вверх. "
    elif rsi > 70:
        commentary += f"📊 RSI = {rsi:.1f} — монета **сильно перекуплена**, велик риск коррекции вниз. "
    elif rsi > 60:
        commentary += f"📊 RSI = {rsi:.1f} — зона перекупленности, давление продавцов растёт. "
    else:
        commentary += f"📊 RSI = {rsi:.1f} — нейтральная зона, нет явного перегрева. "

    if macd > 0:
        commentary += f"📈 MACD гистограмма положительная ({macd:.4f}) — бычий импульс. "
    else:
        commentary += f"📉 MACD гистограмма отрицательная ({macd:.4f}) — медвежий импульс. "
    commentary += f"{ema_cross}. "

    if adx > 25:
        commentary += f"📊 ADX = {adx:.1f} — тренд сильный, движение может продолжиться. "
    else:
        commentary += f"⚠️ ADX = {adx:.1f} — тренд слабый, возможны боковик или ложные пробои. "

    if volume_ok:
        commentary += f"📊 Объём выше среднего — подтверждение интереса. "
    else:
        commentary += f"⚠️ Объём ниже среднего — активность невысокая. "
    commentary += f"☁️ Цена {cloud} облака Ишимоку. "

    if ob_analysis:
        pressure = ob_analysis['pressure']
        imbalance = ob_analysis['imbalance_pct']
        if pressure == 'BULLISH':
            commentary += f"🏛️ Стакан: имбаланс {imbalance:.1f}% в пользу покупателей, крупная стена покупки на ${ob_analysis['max_bid_wall_price']:.2f}. "
        elif pressure == 'BEARISH':
            commentary += f"🏛️ Стакан: имбаланс {abs(imbalance):.1f}% в пользу продавцов, крупная стена продажи на ${ob_analysis['max_ask_wall_price']:.2f}. "
        else:
            commentary += f"🏛️ Стакан: Bid/Ask сбалансированы. "

    commentary += f"\n\n**🎯 Итог**: "
    if final_signal != "NEUTRAL":
        if final_signal == "LONG":
            commentary += f"Набрано **{long_cond_count} бычьих условий** из 11. Рекомендуется рассматривать **лонг**."
            commentary += f"\n\n💡 **План**: вход по текущей цене ${price:.2f}, стоп-лосс на 1.5 ATR ниже, тейк-профит на 2.5 ATR выше. Соотношение риск/прибыль ~1:1.67."
        else:
            commentary += f"Набрано **{short_cond_count} медвежьих условий** из 11. Рекомендуется рассматривать **шорт**."
            commentary += f"\n\n💡 **План**: вход по текущей цене ${price:.2f}, стоп-лосс на 1.5 ATR выше, тейк-профит на 2.5 ATR ниже."
    else:
        if raw_signal != "NEUTRAL":
            commentary += f"**Сигнал {raw_signal} был сгенерирован** (набрано {long_cond_count if raw_signal=='LONG' else short_cond_count} условий), **но нейросеть отклонила его** из-за низкой уверенности ({neural_prob*100:.1f}%).\n"
            commentary += "Рекомендуется воздержаться от сделки или дождаться более явного сигнала, который нейросеть подтвердит.\n"
            commentary += f"Вы можете обучить нейросеть через `/train` на своих размеченных данных, чтобы улучшить фильтрацию."
        else:
            commentary += f"**Нейтрально** — бычьих условий {long_cond_count}, медвежьих {short_cond_count} (требуется минимум 6 для сигнала). Рекомендуется воздержаться от сделки или дождаться более чёткого сигнала."
    return commentary

# ======================== ФОРМАТИРОВАНИЕ ОТВЕТА ========================
def format_signal_response(symbol: str, timeframe: str, indicators: Dict,
                           final_signal: str, raw_signal: str, levels: Dict, prob: float,
                           ob_analysis: Dict = None, long_cond_count: int = 0, short_cond_count: int = 0) -> str:
    signal_emoji = {"LONG": "🟢", "SHORT": "🔴", "NEUTRAL": "⚪"}[final_signal]
    response = f"📊 **{symbol} (фьючерс)** | `{timeframe}`\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
    response += "**📈 ТЕХНИЧЕСКИЕ ИНДИКАТОРЫ**\n"
    response += f"💰 Цена: `${indicators['price']:.2f}`\n"
    response += f"📊 RSI: `{indicators['rsi']:.2f}`\n"
    response += f"📉 MACD гист: `{indicators['macd_histogram']:.6f}`\n"
    response += f"📊 EMA9/21: `{indicators['ema9']:.2f}` / `{indicators['ema21']:.2f}`\n"
    response += f"📈 ATR: `{indicators['atr']:.4f}`\n"
    response += f"📈 ADX: `{indicators['adx']:.1f}`\n"
    response += f"💰 MFI: `{indicators['mfi']:.1f}`\n"
    response += f"📊 Stoch K/D: `{indicators['stoch_k']:.1f}` / `{indicators['stoch_d']:.1f}`\n"
    response += f"📈 Объём > SMA20: `{'✅' if indicators['volume_above_avg'] else '❌'}`\n"
    response += f"☁️ Цена выше облака: `{'✅' if indicators['price_above_cloud'] else '❌'}`\n\n"
    
    if ob_analysis:
        response += "**📖 АНАЛИЗ СТАКАНА ЗАЯВОК**\n"
        response += f"🏛️ Биржа: `{ob_analysis['exchange']}`\n"
        response += f"📊 Лучший Bid/Ask: `${ob_analysis['best_bid']:.2f}` / `${ob_analysis['best_ask']:.2f}`\n"
        response += f"📏 Спред: `${ob_analysis['spread']:.2f}` ({ob_analysis['spread_pct']:.4f}%)\n"
        response += f"📊 Суммарный объём Bids: `{ob_analysis['bids_volume']:.0f}`\n"
        response += f"📉 Суммарный объём Asks: `{ob_analysis['asks_volume']:.0f}`\n"
        pressure_emoji = "🟢" if ob_analysis['pressure'] == 'BULLISH' else "🔴" if ob_analysis['pressure'] == 'BEARISH' else "⚪"
        response += f"{pressure_emoji} Давление стакана: `{ob_analysis['pressure']}` (имбаланс {ob_analysis['imbalance_pct']:.1f}%)\n"
        response += f"🧱 Макс. стена покупки: `${ob_analysis['max_bid_wall_price']:.2f}` ({ob_analysis['max_bid_wall_volume']:.0f})\n"
        response += f"🧱 Макс. стена продажи: `${ob_analysis['max_ask_wall_price']:.2f}` ({ob_analysis['max_ask_wall_volume']:.0f})\n\n"
    
    response += f"🤖 Нейросеть: уверенность `{prob*100:.1f}%`\n\n"
    response += f"{signal_emoji} **ИТОГОВЫЙ СИГНАЛ: {final_signal}**\n"
    
    if final_signal != "NEUTRAL":
        response += f"\n**🎯 УРОВНИ**\n"
        response += f"🚪 Вход: `${levels['entry']:.4f}`\n"
        response += f"🛑 Stop-Loss: `${levels['stop_loss']:.4f}`\n"
        response += f"💰 Take-Profit: `${levels['take_profit']:.4f}`\n"
        rr = abs(levels['take_profit'] - levels['entry']) / abs(levels['stop_loss'] - levels['entry'])
        response += f"📐 Risk/Reward: 1 : {rr:.2f}\n"
    else:
        response += "\n⚠️ Нейтрально – недостаточно подтверждений.\n"
    
    response += "\n---\n"
    response += format_conditions_checklist(indicators, ob_analysis)
    response += "\n---\n"
    response += generate_commentary(symbol, final_signal, raw_signal, indicators,
                                    long_cond_count, short_cond_count, prob, ob_analysis)
    response += "\n\n---\n🤖 **Доступные команды** (нажмите кнопку, затем отредактируйте):\n"
    response += "`/signal BTC/USDT 1h`\n"
    response += "`/backtest BTC/USDT 1h 2025-01-01 2025-03-01`\n"
    response += "`/train`\n"
    response += "`/help`"
    return response

# ======================== ОБРАБОТЧИКИ КОМАНД ========================
@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.reply(
        "🤖 **Крипто-Аналитик Бот (v4.0)**\n\n"
        "📌 **Как пользоваться:**\n"
        "Нажмите на кнопку нужной команды → текст появится в поле ввода.\n"
        "Вы можете **отредактировать** его (например, изменить пару или таймфрейм), затем отправить.\n\n"
        "✅ Добавлен анализ **стакана заявок** (имбаланс, стены, давление).\n"
        "✅ Живая цена фьючерсов через fetch_ticker.\n"
        "✅ **Галочки ✅/❌** напротив каждого бычьего и медвежьего условия.\n"
        "✅ Комментарий бота объясняет, почему сигнал принят или отклонён (в том числе нейросетью).\n\n"
        "👇 **Кнопки команд** (текст появится в поле ввода):",
        parse_mode="Markdown",
        reply_markup=get_main_inline_keyboard()
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.reply(
        "📚 **Справка**\n\n"
        "`/signal BTC/USDT 4h` – анализ пары на таймфрейме\n"
        "Доступные таймфреймы: 5m, 15m, 1h, 4h, 1d\n\n"
        "`/backtest BTC/USDT 1h 2025-01-01 2025-03-01` – бэктестинг\n\n"
        "`/train` – обучение нейросети на размеченных сигналах из БД\n\n"
        "**Что анализируется:**\n"
        "📊 Индикаторы: RSI, MACD, EMA, BB, ATR, ADX, MFI, StochRSI, объём, Ишимоку\n"
        "📖 Стакан: имбаланс, спред, крупные стены\n"
        "🤖 Нейросетевое подтверждение (после обучения)\n"
        "💬 Комментарий бота с объяснением ситуации\n"
        "✅❌ Галочки показывают выполнение каждого условия\n\n"
        "SL/TP = ±1.5 ATR / ±2.5 ATR",
        parse_mode="Markdown",
        reply_markup=get_main_inline_keyboard()
    )

@dp.message(Command("signal"))
async def signal_cmd(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.reply("❌ Пример: `/signal BTC/USDT 1h`\n\nВы можете нажать кнопку ниже, затем отредактировать.", parse_mode="Markdown")
        return
    symbol = args[1].upper()
    if '/' not in symbol:
        if symbol.endswith('USDT'):
            symbol = symbol[:-4] + '/' + symbol[-4:]
    timeframe = args[2] if len(args) > 2 else "1h"
    if timeframe not in TIMEFRAMES:
        await message.reply(f"❌ Таймфрейм {timeframe} не поддерживается.\nДоступны: {', '.join(TIMEFRAMES.keys())}")
        return

    status = await message.reply(f"🔍 Анализирую фьючерс {symbol} {timeframe}...")

    live_price, _ = await fetch_live_price(symbol)
    if live_price is None:
        await status.edit_text("❌ Не удалось получить живую цену ни с одной биржи.")
        return

    df = await fetch_ohlcv_any(symbol, timeframe, limit=150)
    if df is None:
        await status.edit_text(f"⚠️ Нет исторических данных, но текущая цена: `${live_price:.2f}`\nНевозможно рассчитать индикаторы.")
        return

    ob_analysis = await fetch_orderbook_analysis(symbol, limit=20)
    if ob_analysis is None:
        logger.warning("Не удалось получить данные стакана, продолжаем без них")

    indicators = calculate_indicators(df, live_price)
    raw_signal, long_cond, short_cond = generate_raw_signal(indicators, ob_analysis)
    long_cond_count = len(long_cond)
    short_cond_count = len(short_cond)
    prob = confirmer.predict_probability(get_feature_vector(indicators))
    final_signal = raw_signal if prob > 0.6 else "NEUTRAL"

    atr = indicators['atr']
    entry = live_price
    if final_signal == "LONG":
        levels = {'entry': entry, 'stop_loss': entry - 1.5*atr, 'take_profit': entry + 2.5*atr}
    elif final_signal == "SHORT":
        levels = {'entry': entry, 'stop_loss': entry + 1.5*atr, 'take_profit': entry - 2.5*atr}
    else:
        levels = {'entry': entry, 'stop_loss': 0.0, 'take_profit': 0.0}

    if final_signal != "NEUTRAL" and ob_analysis:
        save_signal(symbol, timeframe, final_signal, indicators, levels, ob_analysis)

    response = format_signal_response(symbol, timeframe, indicators, final_signal, raw_signal, levels, prob,
                                      ob_analysis, long_cond_count, short_cond_count)
    await status.edit_text(response, parse_mode="Markdown")

@dp.message(Command("backtest"))
async def backtest_cmd(message: Message):
    args = message.text.split()
    if len(args) < 3:
        await message.reply("❌ Использование: `/backtest BTC/USDT 1h 2025-01-01 2025-03-01`\n(даты необязательны)", parse_mode="Markdown")
        return
    symbol = args[1].upper()
    if '/' not in symbol:
        if symbol.endswith('USDT'):
            symbol = symbol[:-4] + '/' + symbol[-4:]
    timeframe = args[2]
    start = args[3] if len(args) > 3 else None
    end = args[4] if len(args) > 4 else None
    status = await message.reply(f"📊 Запуск бэктестинга {symbol} {timeframe}...")
    await status.edit_text("📈 Бэктестинг в разработке (пока без учёта стакана).\nИспользуйте `/signal` для текущего анализа.")

@dp.message(Command("train"))
async def train_cmd(message: Message):
    await message.reply("🔄 Обучение нейросети на истории сигналов...")
    conn = sqlite3.connect('signals.db')
    df_db = pd.read_sql_query("SELECT * FROM signals WHERE outcome IS NOT NULL", conn)
    conn.close()
    if len(df_db) < 20:
        await message.reply("❌ Недостаточно размеченных сигналов (нужно минимум 20). Вручную проставьте исходы (outcome='win'/'loss') и pnl в БД.")
        return
    features, labels = [], []
    for _, row in df_db.iterrows():
        ema_diff = row['ema9'] - row['ema21']
        bb_pos = 0.5
        feats = [row['rsi'], row['macd_hist'], ema_diff, row['atr'], bb_pos, row['adx'], row['mfi'], row['stoch_k']]
        features.append(feats)
        labels.append(1 if row['outcome'] == 'win' else 0)
    confirmer.train(np.array(features), np.array(labels))
    await message.reply("✅ Нейросеть успешно обучена и сохранена в model.pkl")

# ======================== ЗАПУСК ========================
async def main():
    logger.info("Запуск фьючерсного бота с редактируемыми командами (switch_inline_query_current_chat)")
    # handle_signals=False отключает установку обработчиков сигналов в дочернем потоке
    await dp.start_polling(bot, handle_signals=False)

if __name__ == "__main__":
    asyncio.run(main())