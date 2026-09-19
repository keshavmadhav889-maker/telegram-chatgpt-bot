# Keshav Study Bot

Telegram + Python bot for Rajasthan University students.

## B.Sc. Notes Store

The bot now includes a built-in B.Sc. notes catalog for:
- PCM: Physics, Chemistry, Mathematics
- PCB: Physics, Chemistry, Biology
- Semester 1 through Semester 6
- Complete Notes and Important Questions packages
- Order creation and order-status storage
- Telegram PDF delivery can be enabled by attaching a Telegram file_id to a product

Useful commands:
- /notes — notes store
- /pcm and /pcb — choose stream
- /pcm1 ... /pcm6 — direct PCM semester packages
- /pcb1 ... /pcb6 — direct PCB semester packages
- /myorders — recent orders
- /products — admin product list

## Payment

The order layer is ready, but live PhonePe checkout is intentionally not hard-coded until the merchant/payment-gateway account is approved and its official credentials/configuration are available. Never commit API keys, salts, passwords, OTPs, UPI PINs, or other secrets to GitHub.

## Existing Uniraj information features

- Official Uniraj notices/result/admission/syllabus links
- Official PDF lookup and Telegram delivery
- Student conversation memory
- Admin broadcast and user dashboard

## Environment variables

Set these as hosting-provider secrets (never commit them):
- TELEGRAM_BOT_TOKEN
- GEMINI_API_KEY
- DATABASE_URL (recommended for persistent bot users)
- RENDER_EXTERNAL_URL (when using Render webhook deployment)

## Run

    pip install -r requirements.txt
    gunicorn bot:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120

Webhook endpoint: /telegram/webhook

GitHub stores the source code. A public web host is required to keep the Telegram webhook online; GitHub Pages alone cannot run this Python backend.