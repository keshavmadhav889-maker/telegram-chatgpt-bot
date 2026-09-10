import os
import logging
import time
from flask import Flask, request, jsonify
import requests

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = "gemini-3.6-flash"

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Temporary per-process context so the bot understands which menu the student just used.
USER_CONTEXT = {}

SYSTEM_PROMPT = """You are Keshav Study Bot, a helpful Hindi-first assistant for Rajasthan University (Uniraj) students.

Your job:
- Understand Hindi, Hinglish, English, spelling mistakes, and very short/incomplete student messages.
- Help with BSc/BA/BCom/MSc and other Uniraj study, semester, exam, result, admission, fees, dates, timetable and syllabus questions.
- If the student gives a course/semester/subject, use those details in the answer.
- Never give a generic introduction like 'Ram Ram! Main Keshav Study Bot hoon' unless the student is greeting or asking who you are.
- Do NOT repeat the student's question. Answer it directly.
- Give a complete, useful answer. Do not stop after 'B.' or an unfinished sentence.
- If the student's message is genuinely incomplete and you cannot safely infer the exact question, ask ONE short clarification question in Hindi/Hinglish instead of inventing details.
- For syllabus, exam pattern, dates, results, fees, notices or other official/current Uniraj facts, never invent information. If you do not have verified current information, clearly say that it needs verification from the official Uniraj source.
- For study questions, you can explain concepts, make notes, give formulas, important topics, preparation plans and practice questions.
- Prefer simple Hindi with English subject terms where students normally use them.
- Use short headings and bullets when useful. Keep normal answers concise but informative.
- If the student says something like 'BSc 2nd semester Math group me', understand it as context and ask what they want (syllabus, important topics, notes, exam, result, etc.) only if the request is actually incomplete.

Official sources:
Uniraj main: https://www.uniraj.ac.in/
Result: https://result.uniraj.ac.in/
Admission: https://admissions.uniraj.ac.in/

Do not claim that you checked a website unless you actually have access to that information in this request."""


def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": str(text)[:4096],
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def ai_reply(user_text, menu_context=""):
    context_line = f"\n\nThe student recently selected this menu: {menu_context}" if menu_context else ""
    prompt = f"{SYSTEM_PROMPT}{context_line}\n\nStudent's message:\n{user_text}\n\nNow answer the student directly."
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 1000,
        },
    }
    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json",
    }

    last_response = None
    for attempt in range(3):
        try:
            r = requests.post(
                GEMINI_URL,
                headers=headers,
                json=payload,
                timeout=45,
            )
            last_response = r
        except requests.RequestException as exc:
            logging.exception("Gemini network error on attempt %s", attempt + 1)
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Gemini network error: {exc}") from exc

        if r.ok:
            break
        if r.status_code in (408, 429, 500, 502, 503, 504) and attempt < 2:
            logging.warning("Gemini transient error %s; retrying", r.status_code)
            time.sleep(2 ** attempt)
            continue
        break

    if last_response is None:
        raise RuntimeError("Gemini request failed")

    r = last_response
    if not r.ok:
        try:
            error_data = r.json().get("error", {})
            error_message = error_data.get("message", "Unknown Gemini API error")
            error_status = error_data.get("status", "")
        except Exception:
            error_message = r.text[:500]
            error_status = ""
        logging.error("Gemini API error %s %s: %s", r.status_code, error_status, error_message)
        raise RuntimeError(f"Gemini API {r.status_code}: {error_message}")

    try:
        data = r.json()
    except ValueError as exc:
        raise RuntimeError("Gemini returned invalid response") from exc

    candidates = data.get("candidates", [])
    if not candidates:
        logging.error("Gemini returned no candidates: %s", data)
        raise RuntimeError("Gemini returned no answer")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if p.get("text")).strip()
    if not text:
        raise RuntimeError("Gemini returned empty text")
    return text


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
    return jsonify({
        "ok": True,
        "service": "Keshav Study Bot",
        "status": "running",
        "ai": "Gemini REST",
        "model": GEMINI_MODEL,
        "build": "2026-09-10-ai-answer-fix",
    })


@app.post("/telegram/webhook")
def webhook():
    update = request.get_json(silent=True) or {}
    try:
        if "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            data = cb.get("data", "")
            USER_CONTEXT[chat_id] = data
            text = answer_callback(data)
            send_message(chat_id, text)
            requests.post(
                f"{TELEGRAM_API}/answerCallbackQuery",
                json={"callback_query_id": cb["id"]},
                timeout=10,
            )
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
            USER_CONTEXT.pop(chat_id, None)
            welcome = "🎓 Keshav Study Bot में आपका स्वागत है!\n\nRajasthan University की पढ़ाई और updates के लिए अपना सवाल भेजें या नीचे menu चुनें।"
            send_message(chat_id, welcome, menu_keyboard())
            return jsonify({"ok": True})

        try:
            requests.post(
                f"{TELEGRAM_API}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"},
                timeout=5,
            )
        except Exception:
            pass

        try:
            menu_context = USER_CONTEXT.get(chat_id, "")
            reply = ai_reply(text, menu_context)
        except Exception as ai_error:
            logging.exception("AI reply failed")
            error_text = str(ai_error)
            if " 401:" in error_text:
                reply = "❌ Gemini API key invalid/expired है। Render में GEMINI_API_KEY check करें।"
            elif " 403:" in error_text:
                reply = "❌ Gemini API key को इस API/model की permission नहीं मिल रही। Google AI Studio की नई key Render में लगाएँ।"
            elif " 429:" in error_text:
                reply = "⏳ Gemini quota/rate limit अभी पूरी है। थोड़ी देर बाद फिर कोशिश करें।"
            elif " 404:" in error_text:
                reply = "❌ Gemini model उपलब्ध नहीं मिला। Render को latest GitHub commit पर redeploy करें।"
            else:
                reply = f"❌ AI service error: {error_text[:220]}"

        send_message(chat_id, reply)
        return jsonify({"ok": True})
    except Exception:
        logging.exception("Telegram webhook error")
        return jsonify({"ok": False}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
