import os
import logging
from flask import Flask, request, jsonify
import requests
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_IDS = {8280167872}

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing")

client = OpenAI(api_key=OPENAI_API_KEY)
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

SYSTEM_PROMPT = """You are Keshav Study Bot for Rajasthan University students.
Answer in clear Hindi/Hinglish. Help with Uniraj exams, results, dates, fees, marks, semester, timetable, admission and study questions.
Never invent official university dates or notices. If current official information is not available in the supplied context, clearly say that it should be verified on the official Uniraj website.
Keep answers useful, concise and well formatted with emojis when appropriate."""


def configure_telegram_webhook():
    """Automatically point Telegram to this Render service after deployment."""
    base_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not base_url:
        logging.info("RENDER_EXTERNAL_URL not set; webhook auto-configuration skipped")
        return
    webhook_url = f"{base_url}/telegram/webhook"
    try:
        response = requests.post(
            f"{TELEGRAM_API}/setWebhook",
            json={"url": webhook_url, "drop_pending_updates": True},
            timeout=20,
        )
        response.raise_for_status()
        logging.info("Telegram webhook configured: %s", webhook_url)
    except Exception:
        logging.exception("Could not configure Telegram webhook")


def send_message(chat_id, text):
    r = requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }, timeout=20)
    r.raise_for_status()
    return r.json()


def ai_reply(user_text):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


def menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📌 आज के अपडेट", "callback_data": "today"}, {"text": "📢 All Updates", "callback_data": "updates"}],
            [{"text": "📝 Exam", "callback_data": "exam"}, {"text": "🏆 Result", "callback_data": "result"}],
            [{"text": "🎓 Admission", "callback_data": "admission"}, {"text": "📅 Dates", "callback_data": "dates"}],
            [{"text": "💰 Fee", "callback_data": "fee"}, {"text": "📊 Marks", "callback_data": "marks"}],
            [{"text": "🗓 Semester Hub", "callback_data": "semester"}, {"text": "🕐 Time Table", "callback_data": "timetable"}],
            [{"text": "🔔 Notifications", "callback_data": "notifications"}, {"text": "🤖 Ask Uniraj AI", "callback_data": "ask"}],
            [{"text": "ℹ️ Help", "callback_data": "help"}, {"text": "🔗 Official Sources", "callback_data": "official"}],
        ]
    }


def answer_callback(data):
    canned = {
        "today": "📌 आज के अपडेट\n\nमैं Uniraj के वर्तमान अपडेट उपलब्ध होने पर यहाँ दिखाऊँगा। आधिकारिक सूचना के लिए Uniraj वेबसाइट भी देखें।",
        "updates": "📢 All Updates\n\nExam, Result, Admission, Circular, Form, Reval और अन्य विश्वविद्यालय अपडेट के लिए अपना सवाल भेजें।",
        "exam": "📝 Exam\n\nExam form, timetable, admit card, practical और परीक्षा से जुड़ी जानकारी पूछें।",
        "result": "🏆 Result\n\nअपना course/semester और result से जुड़ा सवाल लिखें।",
        "admission": "🎓 Admission\n\nAdmission से जुड़ी जानकारी के लिए course और session लिखें।",
        "dates": "📅 Dates\n\nExam/form/result की date पूछने के लिए पूरा course और semester लिखें।",
        "fee": "💰 Fee\n\nFee से जुड़ी जानकारी के लिए course, semester और session लिखें।",
        "marks": "📊 Marks\n\nMarks/grade/result से जुड़ा सवाल भेजें।",
        "semester": "🗓 Semester Hub\n\nअपना course और semester लिखें; मैं study planning और उपलब्ध जानकारी में मदद करूँगा।",
        "timetable": "🕐 Time Table\n\nCourse + semester लिखकर timetable से जुड़ा सवाल पूछें।",
        "notifications": "🔔 Notifications\n\nमहत्वपूर्ण updates के लिए notifications सुविधा उपलब्ध है।",
        "ask": "🤖 Ask Uniraj AI\n\nअपना Uniraj या study-related सवाल सीधे भेजें।",
        "help": "ℹ️ Help\n\nबस अपना सवाल लिखें। उदाहरण: 'BSc 2nd semester exam form कब है?'",
        "official": "🔗 Official Sources\n\nUniraj: https://www.uniraj.ac.in/\nResult: https://result.uniraj.ac.in/\nAdmission: https://admissions.uniraj.ac.in/",
    }
    return canned.get(data, "अपना सवाल भेजें।")


@app.get("/")
def health():
    return jsonify({"ok": True, "service": "Keshav Study Bot", "status": "running"})


@app.post("/telegram/webhook")
def webhook():
    update = request.get_json(silent=True) or {}
    try:
        if "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            text = answer_callback(cb.get("data", ""))
            send_message(chat_id, text)
            requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cb["id"]}, timeout=10)
            return jsonify({"ok": True})

        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        user = message.get("from") or {}
        if not chat_id or user.get("is_bot"):
            return jsonify({"ok": True})

        text = (message.get("text") or "").strip()
        if not text:
            return jsonify({"ok": True})

        if text.startswith("/start"):
            welcome = "🎓 Keshav Study Bot में आपका स्वागत है!\n\nRajasthan University की पढ़ाई और updates के लिए अपना सवाल भेजें या नीचे menu चुनें।"
            requests.post(f"{TELEGRAM_API}/sendMessage", json={
                "chat_id": chat_id,
                "text": welcome,
                "reply_markup": menu_keyboard(),
                "disable_web_page_preview": True,
            }, timeout=20).raise_for_status()
            return jsonify({"ok": True})

        if user.get("id") in ADMIN_IDS:
            send_message(chat_id, "👑 Admin mode active.")
            return jsonify({"ok": True})

        reply = ai_reply(text)
        send_message(chat_id, reply)
        return jsonify({"ok": True})
    except Exception:
        logging.exception("Telegram webhook error")
        return jsonify({"ok": False}), 500


configure_telegram_webhook()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
