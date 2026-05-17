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

def run_bot():
    asyncio.run(bot.main())

if __name__ == '__main__':
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)