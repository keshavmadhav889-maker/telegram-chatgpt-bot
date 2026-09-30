import os, logging, requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

BOT_TOKEN = (os.getenv('TELEGRAM_BOT_TOKEN') or '').strip()
ADMIN_CHAT_ID = int((os.getenv('ADMIN_CHAT_ID') or '0').strip() or 0)
RENDER_EXTERNAL_URL = (os.getenv('RENDER_EXTERNAL_URL') or '').strip()

if not BOT_TOKEN:
    raise RuntimeError('TELEGRAM_BOT_TOKEN missing hai')

API = f'https://api.telegram.org/bot{BOT_TOKEN}'

def tg(method, payload=None, timeout=15):
    r = requests.post(f'{API}/{method}', json=payload or {}, timeout=timeout)
    data = r.json()
    if not r.ok or not data.get('ok'):
        raise RuntimeError(f'Telegram {method} failed: {data}')
    return data['result']

def send_message(chat_id, text):
    return tg('sendMessage', {
        'chat_id': chat_id,
        'text': str(text)[:4096],
        'disable_web_page_preview': True
    })

def configure():
    commands = [
        {'command': 'start', 'description': 'Open Main Menu'},
        {'command': 'id', 'description': 'Show Telegram User ID'}
    ]
    try:
        tg('setMyCommands', {'commands': commands})
        if ADMIN_CHAT_ID:
            tg('setMyCommands', {
                'commands': commands,
                'scope': {'type': 'chat', 'chat_id': ADMIN_CHAT_ID}
            })
        if RENDER_EXTERNAL_URL:
            tg('setWebhook', {
                'url': RENDER_EXTERNAL_URL.rstrip('/') + '/telegram/webhook',
                'allowed_updates': ['message', 'callback_query', 'pre_checkout_query']
            })
    except Exception:
        logging.exception('Telegram configuration failed')

configure()

@app.get('/')
def health():
    return jsonify({
        'ok': True,
        'service': 'Telegram Bot',
        'telegram_only': True
    })

@app.post('/telegram/webhook')
def webhook():
    try:
        update = request.get_json(silent=True) or {}
        message = update.get('message')
        if not message:
            return jsonify({'ok': True})

        chat_id = message['chat']['id']
        text = (message.get('text') or '').strip()

        if text.startswith('/start'):
            send_message(chat_id, 'नमस्ते! 👋\\n\\nTelegram Bot तैयार है।')
        elif text.startswith('/id'):
            send_message(chat_id, f'Your Telegram User ID: {chat_id}')
        else:
            send_message(chat_id, 'Bot तैयार है।\\n\\nआपका संदेश प्राप्त हुआ।')

        return jsonify({'ok': True})
    except Exception:
        logging.exception('Webhook error')
        return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '10000')))
