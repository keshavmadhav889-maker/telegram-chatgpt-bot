# Telegram ChatGPT Bot

A Telegram-only information bot. No PWA, website, student web interface, notes store, PDF catalog, payment, or product-selling system is included.

## Features

- Telegram /start menu
- Telegram user ID with /id
- Webhook support for Render
- Health-check endpoint
- Simple Telegram message handling
- Admin chat ID and bot token configuration through environment variables

## Environment variables

Set these as hosting-provider secrets; never commit them:

- TELEGRAM_BOT_TOKEN
- ADMIN_CHAT_ID
- RENDER_EXTERNAL_URL
- PORT (normally 10000)

## Deploy

```
pip install -r requirements.txt
gunicorn bot:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120
```

Webhook endpoint: /telegram/webhook

GitHub stores the source; it does not run the bot by itself.
