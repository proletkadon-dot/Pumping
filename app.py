import os
import asyncio
import threading
from flask import Flask
from dotenv import load_dotenv
import bot

load_dotenv()

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return "OK", 200

def run_telegram_bot():
    asyncio.run(bot.main())   # bot.main() теперь с handle_signals=False

if __name__ == '__main__':
    # Запускаем бота в фоне
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    # Запускаем Flask
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)