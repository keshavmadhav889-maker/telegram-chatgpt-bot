import os
import logging
from flask import Flask, request, jsonify
import requests
from google import genai

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_IDS = {8280167872}

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing")

client = genai.Client(api_key=GEMINI_API_KEY)
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """You are Keshav Study Bot for Rajasthan University students.
Answer in clear Hindi/Hinglish. Help with Uniraj exams, results, dates, fees, marks, semester, timetable, admission and study questions.
Never invent official university dates or notices. If current official information is not available in the supplied context, clearly say that it should be verified on the official Uniraj website.
Keep answers useful, concise and well formatted with emojis when appropriate."""


def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def ai_reply(user_text):
    prompt = f"{SYSTEM_PROMPT}\n\nStudent's question:\n{user_text}"
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )
    text = getattr(response, "text", None)
    if not text:
        return "❌ अभी AI जवाब नहीं बना पाया। कृपया थोड़ी देर बाद फिर कोशिश करें।"
    return text.strip()


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


def configure_webhook():
    """Automatically point Telegram updates to this Render service."""
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        logging.info("RENDER_EXTERNAL_URL not available; webhook not auto-configured")
        return
    webhook_url = render_url.rstrip("/") + "/telegram/webhook"
    try:
        r = requests.post(
            f"{TELEGRAM_API}/setWebhook",
            json={"url": webhook_url},
            timeout=15,
        )
        r.raise_for_status()
        logging.info("Telegram webhook configured: %s", webhook_url)
    except Exception:
        logging.exception("Failed to configure Telegram webhook")


configure_webhook()


@app.get("/")
def health():
    return jsonify({"ok": True, "service": "Keshav Study Bot", "status": "running", "ai": "Gemini"})


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
            send_message(chat_id, welcome, menu_keyboard())
            return jsonify({"ok": True})

        # Admin can use the same Gemini AI chat as regular users.
        reply = ai_reply(text)
        send_message(chat_id, reply)
        return jsonify({"ok": True})
    except Exception:
        logging.exception("Telegram webhook error")
        return jsonify({"ok": False}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
