# Keshav Study Bot

Telegram + OpenAI webhook bot for Rajasthan University students.

## Environment variables

Set these as hosting-provider secrets (never commit them):

- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`

## Run

```bash
pip install -r requirements.txt
gunicorn bot:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120
```

Webhook endpoint: `/telegram/webhook`

GitHub stores the source code. A public web host is required to keep the Telegram webhook online; GitHub Pages alone cannot run this Python backend.
