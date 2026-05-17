import os
import asyncio
import threading
from flask import Flask
from dotenv import load_dotenv
import bot  # Твой основной файл с ботом

load_dotenv()

# Инициализация Flask приложения
app = Flask(__name__)

# Простой эндпоинт для проверки, что сервер жив
@app.route('/')
@app.route('/health')
def health_check():
    return "OK", 200

# Функция для запуска твоего Telegram бота в отдельном потоке
def run_telegram_bot():
    asyncio.run(bot.main())  # Предполагаем, что в bot.py есть main()

if __name__ == '__main__':
    # Запускаем Telegram бота в фоновом потоке
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()

    # Запускаем Flask сервер на порту, который дал Render
    # Render сам назначает порт через переменную окружения PORT
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)