import os
import logging
import time
from datetime import datetime
from typing import List, Dict, Optional

import ccxt
import pandas as pd
import numpy as np
import schedule
from dotenv import load_dotenv
from telegram import Bot

# -------------------- Настройка логирования --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

load_dotenv()

# -------------------- Конфигурация --------------------
class Config:
    TELEGRAM_TOKEN = "8695713035:AAELPJ25J5SMbw2Ed6rEW1fiuAtRZ4L9Abc"
    CHAT_ID = "694614387"

    EXCHANGE_ID = "binance"
    TIMEFRAME = "1h"
    SCAN_INTERVAL_MIN = 15
    SYMBOLS = []  # оставить пустым – будут топ-50 USDT-пар

    RSI_OVERBOUGHT = 70
    RSI_OVERSOLD = 30
    EMA_FAST = 9
    EMA_SLOW = 21
    VOLUME_MA_PERIOD = 20
    ATR_PERIOD = 14
    TP_ATR_MULT = 3.0
    SL_ATR_MULT = 1.5

# -------------------- Самодельные индикаторы --------------------
def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Экспоненциальная скользящая средняя."""
    return series.ewm(span=period, adjust=False).mean()

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI (индекс относительной силы)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    # Используем SMA для первых period значений, затем EWM для остальных
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Средний истинный диапазон (ATR)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean()
    # Первые period-1 значений будут NaN, это нормально
    return atr

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Добавить все индикаторы в DataFrame."""
    if df.empty:
        return df
    df["ema_fast"] = compute_ema(df["close"], Config.EMA_FAST)
    df["ema_slow"] = compute_ema(df["close"], Config.EMA_SLOW)
    df["rsi"] = compute_rsi(df["close"], 14)
    df["atr"] = compute_atr(df, Config.ATR_PERIOD)
    df["volume_ma"] = df["volume"].rolling(window=Config.VOLUME_MA_PERIOD).mean()
    return df

# -------------------- Клиент биржи --------------------
exchange = ccxt.binance({
    "enableRateLimit": True,
    "options": {"defaultType": "spot"}
})

def fetch_top_symbols(limit: int = 50) -> List[str]:
    """Топ-USDT пар по объёму за 24ч."""
    try:
        tickers = exchange.fetch_tickers()
        usdt_pairs = {s: t for s, t in tickers.items() if s.endswith("/USDT")}
        sorted_pairs = sorted(usdt_pairs.items(), key=lambda x: x[1].get("quoteVolume", 0), reverse=True)
        return [s for s, _ in sorted_pairs[:limit]]
    except Exception as e:
        logger.error(f"Ошибка получения тикеров: {e}")
        return []

def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 100) -> pd.DataFrame:
    """Загрузить свечные данные."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception as e:
        logger.error(f"Ошибка загрузки {symbol}: {e}")
        return pd.DataFrame()

# -------------------- Стратегии --------------------
class BaseStrategy:
    name = "Base"
    def analyze(self, df: pd.DataFrame, symbol: str) -> Optional[Dict]:
        raise NotImplementedError

class RSIOverheatStrategy(BaseStrategy):
    name = "RSI Overheat"
    def analyze(self, df: pd.DataFrame, symbol: str) -> Optional[Dict]:
        if df.empty or "rsi" not in df.columns:
            return None
        last_rsi = df["rsi"].iloc[-1]
        if pd.isna(last_rsi):
            return None
        signal = None
        if last_rsi > Config.RSI_OVERBOUGHT:
            signal = {"type": "OVERBOUGHT", "rsi": round(last_rsi, 2)}
        elif last_rsi < Config.RSI_OVERSOLD:
            signal = {"type": "OVERSOLD", "rsi": round(last_rsi, 2)}
        if signal:
            signal["symbol"] = symbol
            signal["strategy"] = self.name
            signal["price"] = df["close"].iloc[-1]
        return signal

class AdvancedSignalStrategy(BaseStrategy):
    name = "Advanced TP/SL"
    def analyze(self, df: pd.DataFrame, symbol: str) -> Optional[Dict]:
        if df.empty or len(df) < 2:
            return None
        prev = df.iloc[-2]
        last = df.iloc[-1]
        # Проверка наличия индикаторов
        if any(pd.isna(x) for x in [last["ema_fast"], last["ema_slow"], last["rsi"], last["atr"], last["volume_ma"]]):
            return None

        cross_up = (prev["ema_fast"] <= prev["ema_slow"]) and (last["ema_fast"] > last["ema_slow"])
        rsi_rising = last["rsi"] > 40 and prev["rsi"] <= 40
        high_volume = last["volume"] > last["volume_ma"]

        if cross_up and rsi_rising and high_volume:
            entry = last["close"]
            atr = last["atr"]
            sl = entry - Config.SL_ATR_MULT * atr
            tp = entry + Config.TP_ATR_MULT * atr
            return {
                "symbol": symbol, "strategy": self.name, "type": "BUY",
                "entry": round(entry, 6), "sl": round(sl, 6), "tp": round(tp, 6),
                "rsi": round(last["rsi"], 2),
                "volume_ratio": round(last["volume"] / last["volume_ma"], 2) if last["volume_ma"] else 0
            }

        cross_down = (prev["ema_fast"] >= prev["ema_slow"]) and (last["ema_fast"] < last["ema_slow"])
        rsi_falling = last["rsi"] < 60 and prev["rsi"] >= 60
        if cross_down and rsi_falling and high_volume:
            entry = last["close"]
            atr = last["atr"]
            sl = entry + Config.SL_ATR_MULT * atr
            tp = entry - Config.TP_ATR_MULT * atr
            return {
                "symbol": symbol, "strategy": self.name, "type": "SELL",
                "entry": round(entry, 6), "sl": round(sl, 6), "tp": round(tp, 6),
                "rsi": round(last["rsi"], 2),
                "volume_ratio": round(last["volume"] / last["volume_ma"], 2) if last["volume_ma"] else 0
            }
        return None

# -------------------- Telegram-уведомления --------------------
class TelegramNotifier:
    def __init__(self):
        if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
            raise ValueError("TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID должны быть заданы в .env")
        self.bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)
        self.chat_id = Config.TELEGRAM_CHAT_ID
    def send_message(self, text: str, parse_mode: str = "HTML"):
        try:
            self.bot.send_message(chat_id=self.chat_id, text=text, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Ошибка отправки в Telegram: {e}")

def format_signal_message(signal: Dict) -> str:
    if signal["strategy"] == "RSI Overheat":
        t = signal["type"]
        emoji = "🔴" if t == "OVERBOUGHT" else "🟢"
        return (
            f"{emoji} <b>RSI Alert: {signal['symbol']}</b>\n"
            f"Тип: {t}\nЦена: {signal['price']:.6f}\nRSI: {signal['rsi']}\n"
            f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
    elif signal["strategy"] == "Advanced TP/SL":
        direction = "📈 LONG" if signal["type"] == "BUY" else "📉 SHORT"
        return (
            f"{direction} <b>Сигнал: {signal['symbol']}</b>\n"
            f"Тип: {signal['type']}\nВход: {signal['entry']:.6f}\n"
            f"🎯 TP: {signal['tp']:.6f}\n🛑 SL: {signal['sl']:.6f}\n"
            f"RSI: {signal['rsi']}\nОбъём/средний: {signal['volume_ratio']}x\n"
            f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
    return ""

# -------------------- Главный сканер --------------------
class CryptoScanner:
    def __init__(self):
        self.notifier = TelegramNotifier()
        self.strategies = [RSIOverheatStrategy(), AdvancedSignalStrategy()]
        self.symbols = Config.SYMBOLS if Config.SYMBOLS else fetch_top_symbols(50)
        if not self.symbols:
            logger.error("Не удалось получить список монет.")
        else:
            logger.info(f"Загружено {len(self.symbols)} символов для мониторинга.")

    def run_once(self):
        logger.info("Запуск сканирования...")
        for symbol in self.symbols:
            df = fetch_ohlcv(symbol, Config.TIMEFRAME, limit=100)
            if df.empty:
                continue
            df = add_indicators(df)
            for strategy in self.strategies:
                signal = strategy.analyze(df, symbol)
                if signal:
                    logger.info(f"Сигнал: {signal}")
                    msg = format_signal_message(signal)
                    self.notifier.send_message(msg)

    def start(self):
        schedule.every(Config.SCAN_INTERVAL_MIN).minutes.do(self.run_once)
        logger.info(f"Бот запущен. Интервал: {Config.SCAN_INTERVAL_MIN} мин.")
        self.run_once()
        while True:
            schedule.run_pending()
            time.sleep(1)

# -------------------- Точка входа --------------------
if __name__ == "__main__":
    scanner = CryptoScanner()
    scanner.start()