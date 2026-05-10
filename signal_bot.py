import logging
from telegram.ext import Application, CommandHandler
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = "8590220699:AAG6U7JoOH638P-LhA5Ow-Byr2cgh7thAAE"  # Замените на токен от @BotFather

# База данных сигналов (в реальном проекте используйте БД)
SIGNALS_DATA = [
    {
        "symbol": "DRIFT",
        "type": "SHORT",
        "decision": "ШОРТ ПО РЫНКУ",
        "confidence": "Сильный",
        "reason": "Сильная зона сопротивления сверху, ждём откат вниз от диапазона $0.03806–$0.03923 (по 60+H4+M30, подтверждён на 3 ТФ)",
        "timeframe": "60+H4+M30",
        "rsi_5m": 80.0,
        "rsi_1h": 58.6,
        "volume": "1.52M",
        "funding": "0.0050%",
        "entry_type": "По рынку",
        "entry_price": 0.03933,
        "position_size": "1.0% депозита",
        "leverage": "20x",
        "tp_percent": -2.0,
        "tp_price": 0.038543,
        "fib_target": 0.03885,
        "sl_price": 0.047196,
        "risk_percent": "4.0%",
        "remarks": [
            "✅ Зона на старшем ТФ + реакция на M5 (REJECTION): Отбой от уровня (свеча с тенью) на M5",
            "Уровень подтверждён на 60+H4+M30 (3 ТФ)",
            "Отбой от уровня (свеча с тенью 69%), 2 св. назад"
        ]
    },
    {
        "symbol": "ALCH",
        "type": "SHORT",
        "decision": "ЖДАТЬ ЛИМИТНЫЙ ВХОД",
        "confidence": "Лимитный ордер у зоны",
        "reason": "Уровень, от которого цену несколько раз отбивали, ждём новую реакцию вниз от $0.09193 (~7 касаний) (по 60+H4, подтверждён на 2 ТФ)",
        "timeframe": "60+H4",
        "rsi_5m": 80.1,
        "rsi_1h": 54.2,
        "volume": "3.46M",
        "funding": "0.0050%",
        "entry_type": "Лимитный",
        "entry_price": 0.09193,
        "position_size": "1.0% депозита",
        "leverage": "20x",
        "distance_to_zone": "+10.0%",
        "tp_percent": -2.0,
        "tp_price": 0.090091,
        "fib_target": 0.08155,
        "sl_price": 0.110316,
        "risk_percent": "4.0%",
        "remarks": [
            "Зона на старшем ТФ найдена, до неё +10.0% — лимитный ордер (реакцию проверить при подходе)",
            "Уровень подтверждён на 60+H4 (2 ТФ)"
        ]
    }
]

def format_signal(signal_data):
    """Форматирует сигнал в заданном стиле"""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    color = "🔴" if signal_data["type"] == "SHORT" else "🟢"

    signal_text = f"[{now}] Gringo: {color} {signal_data['type']}: {signal_data['symbol']}\n"
    signal_text += f"🎯 РЕШЕНИЕ: {'✅' if 'ПО РЫНКУ' in signal_data['decision'] else '⚠️'} {signal_data['decision']}\n"
    signal_text += f"💭 Оценка: {signal_data['confidence']}\n\n"

    signal_text += "🔍 Анализ:\n"
    signal_text += f"• RSI 5m: {signal_data['rsi_5m']}\n"
    signal_text += f"• RSI 1h: {signal_data['rsi_1h']}\n"
    signal_text += f"• Объём: {signal_data['volume']} ✅\n"
    signal_text += f"• Фандинг: {signal_data['funding']} ✅\n\n"

    signal_text += f"📍 Причина входа: {signal_data['reason']}\n"
    signal_text += f"Таймфрейм: {signal_data['timeframe']}\n\n"

    signal_text += "💰 Точки входа:\n"
    signal_text += f"• Вход: {signal_data['entry_type']} ({signal_data['entry_price']})\n"
    signal_text += f"• Размер: {signal_data['position_size']}\n"
    signal_text += f"• Плечо: {signal_data['leverage']}\n"
    if 'distance_to_zone' in signal_data:
        signal_text += f"• До зоны: {signal_data['distance_to_zone']}\n"

    signal_text += "\n🎯 Тейк-профит:\n"
    signal_text += f"• TP {signal_data['tp_percent']}% ({signal_data['tp_price']}) — полное закрытие\n"
    signal_text += f"• Цель отката (Фибо 0.5): {signal_data['fib_target']}\n\n"

    signal_text += "🛑 Стоп-лосс:\n"
    signal_text += f"• SL: {signal_data['sl_price']} (+20% движ.)\n"
    signal_text += f"• Оценка к депозиту: ~{signal_data['risk_percent']} (при 1.0% позиции и 20x)\n\n"

    signal_text += "⚠️ Замечания:\n"
    for remark in signal_data['remarks']:
        signal_text += f"• {remark}\n"

    return signal_text

async def start(update, context):
    await update.message.reply_text("Бот сигналов запущен! Используйте /signals для получения торговых сигналов.")


async def get_signals(update, context):
    for signal_data in SIGNALS_DATA:
        signal_text = format_signal(signal_data)
        await update.message.reply_text(signal_text)

def main():
    try:
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("signals", get_signals))
        print("Бот запущен. Ожидаю команд...")
        application.run_polling()
    except Exception as e:
        logging.error(f"Ошибка запуска бота: {e}")

if __name__ == '__main__':
    main()
