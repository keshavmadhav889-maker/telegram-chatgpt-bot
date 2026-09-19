# Telegram Notes Selling Bot

A Telegram-only Notes/PDF store for university students. There is no PWA, website, student web interface, or external notes store.

## Features

- Student flow entirely through Telegram inline buttons.
- Courses: B.Sc., B.Com, M.Com, M.Sc, M.A, B.A.
- B.Sc. streams: PCM and PCB.
- Semesters 1-6.
- Subjects are database records, not hard-coded.
- Admin can add courses, subjects, PDFs and prices from Telegram.
- PDFs are stored as Telegram file IDs.
- Telegram Stars (XTR) are used for digital goods.
- Server validates pre-checkout and only delivers after successful_payment.
- My Purchases only exposes paid products belonging to that Telegram user.
- Order records include user, product, price, currency, status, Telegram charge ID, dates and delivery status.
- Admin order filters, sales statistics, user count and broadcast.
- Short callback IDs are used to stay within Telegram's 64-byte callback-data limit.
- Navigation uses edited Telegram messages where practical.

## Environment variables

Set these as hosting-provider secrets; never commit them:

- TELEGRAM_BOT_TOKEN
- ADMIN_CHAT_ID
- ADMIN_USERNAME (optional, without @)
- DATABASE_URL (PostgreSQL for persistent production data)
- RENDER_EXTERNAL_URL
- PORT (normally 10000)

## Deploy

    pip install -r requirements.txt
    gunicorn bot:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120

Webhook endpoint: /telegram/webhook

A public HTTPS host is required for the webhook. GitHub stores the source; it does not run the bot by itself.

## Admin

Use /admin from the configured ADMIN_CHAT_ID.

- Users
- Products / Notes
- Add Subject
- Upload PDF
- Change Price
- Orders
- Sales
- Broadcast
- Add Course
- Settings

## Add Subject

Admin -> Add Subject -> Course -> Stream (B.Sc. only) -> Semester -> send subject name.

A new product is created without a PDF initially. Students see Notes unavailable until the PDF is uploaded.

## Upload PDF

Admin -> Upload PDF -> select subject -> send the PDF as a Telegram Document. The bot saves the Telegram file ID.

## Change Price

Admin -> Change Price -> select subject -> send the price in Telegram Stars.

## Payment safety

The bot never sends the PDF merely because Buy Now was pressed or because a pre-checkout request was received. It verifies the pending order, user ID, amount, currency and product availability, answers pre-checkout, then waits for Telegram's successful_payment update before delivery.

For production, use PostgreSQL rather than the local SQLite fallback so products, purchases and sales are not lost when the hosting instance is replaced.
