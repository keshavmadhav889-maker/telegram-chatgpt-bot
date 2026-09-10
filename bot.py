import os
import logging
import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# ================= CONFIG =================
BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
# Current free-friendly Gemini model. Can be overridden in Render with GEMINI_MODEL.
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite").strip()
AI_TIMEOUT = 35
MAX_HISTORY = 10
USER_HISTORY = {}

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing hai")
if not GEMINI_API_KEY:
    logging.warning("GEMINI_API_KEY missing hai")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ================= UNIRAJ SOURCES =================
UNIRAJ_HOME = "https://www.uniraj.ac.in/"
UNIRAJ_SYLLABUS = "https://uniraj.ac.in/index.php?mid=3125"
UNIRAJ_NOTICES = "https://www.uniraj.ac.in/index.php?mid=196"
UNIRAJ_RESULT = "https://result.uniraj.ac.in/"
UNIRAJ_ADMISSION = "https://admissions.uniraj.ac.in/"
GUESS_1 = "https://t.me/Uniraj_GuessPapers"
GUESS_2 = "https://t.me/Unirajguesspaper"
RESULT_HELP = "https://t.me/Unirajresult499"
BSC_MATHS_2025_26_PDF = (
    "https://uniraj.ac.in/student/syl_N/UP_SYL_2025-26/"
    "Maths_UG0803_%28Maths_Group%29%20I%20to%20VI%202025-26%20%20SCiencee.pdf"
)

SYSTEM_PROMPT = f"""You are Uniraj Information Section, a professional Hindi-first assistant for Rajasthan University students.
Answer in simple Hindi/Hinglish unless English is requested.
Understand spelling mistakes and short student messages.
Use conversation history naturally.
Never invent official dates, marks, notices, syllabus details or results.
For personal result questions, give the official result portal and Result Help group; never claim to access private marks.
For guess-paper questions, mention both free guess-paper channels.
If asked who made the bot, say it was made and powered by KESHAV MADHAV.
Verified sources:
University: {UNIRAJ_HOME}
Syllabus index: {UNIRAJ_SYLLABUS}
B.Sc. Maths Group 2025-26 PDF: {BSC_MATHS_2025_26_PDF}
Notices: {UNIRAJ_NOTICES}
Result: {UNIRAJ_RESULT}
Admission: {UNIRAJ_ADMISSION}
Free Guess Papers: {GUESS_1} and {GUESS_2}
Result Help: {RESULT_HELP}
"""

# ================= TELEGRAM =================
def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": str(text)[:4096],
        "disable_web_page_preview": False,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def menu_keyboard():
    return {"inline_keyboard": [
        [{"text": "📌 आज के अपडेट", "callback_data": "today"}, {"text": "📢 All Updates", "callback_data": "updates"}],
        [{"text": "📝 Exam", "callback_data": "exam"}, {"text": "🏆 Result", "callback_data": "result"}],
        [{"text": "🎓 Admission", "callback_data": "admission"}, {"text": "📘 Syllabus", "callback_data": "syllabus"}],
        [{"text": "📚 Guess Papers", "callback_data": "guess"}, {"text": "🤖 Ask Uniraj AI", "callback_data": "ask"}],
        [{"text": "ℹ️ Help", "callback_data": "help"}, {"text": "🔗 Official Sources", "callback_data": "official"}],
    ]}


def callback_answer(data):
    answers = {
        "today": f"📌 आज के Uniraj updates के लिए official notices देखें:\n{UNIRAJ_NOTICES}\n\nआप अपना course/semester लिखकर भी सवाल पूछ सकते हैं।",
        "updates": f"📢 Uniraj official updates:\n{UNIRAJ_NOTICES}\n\nExam, result, admission और forms से जुड़ा सवाल भी पूछ सकते हैं।",
        "exam": "📝 Exam\n\nअपना course + semester लिखें, जैसे: BSc 3rd semester exam dates",
        "result": f"🏆 Official Result:\n{UNIRAJ_RESULT}\n\n🆘 Result Help Group:\n{RESULT_HELP}",
        "admission": f"🎓 Official Admission:\n{UNIRAJ_ADMISSION}",
        "syllabus": f"📘 Official Syllabus Index:\n{UNIRAJ_SYLLABUS}\n\nB.Sc. Maths Group 2025-26 PDF:\n{BSC_MATHS_2025_26_PDF}",
        "guess": f"📚 Free Uniraj Guess Papers:\n1️⃣ {GUESS_1}\n2️⃣ {GUESS_2}",
        "ask": "🤖 अपना Uniraj सवाल सीधे भेजें।",
        "help": "ℹ️ उदाहरण:\n• BSc 3rd semester Maths syllabus भेजो\n• मेरा Uniraj result कहाँ मिलेगा?\n• आज की Uniraj notice कहाँ है?\n• Guess paper कहाँ मिलेगा?",
        "official": f"🔗 Official Sources\n\nUniversity: {UNIRAJ_HOME}\nSyllabus: {UNIRAJ_SYLLABUS}\nResult: {UNIRAJ_RESULT}\nAdmission: {UNIRAJ_ADMISSION}\nNotices: {UNIRAJ_NOTICES}",
    }
    return answers.get(data, "अपना सवाल भेजें।")

# ================= QUICK OFFLINE REPLIES =================
def quick_reply(text):
    q = text.lower()
    if any(x in q for x in ["guess paper", "guesspaper", "guess papers", "गेस पेपर"]):
        return f"📚 Free Uniraj Guess Papers\n\n1️⃣ {GUESS_1}\n2️⃣ {GUESS_2}"
    if any(x in q for x in ["kisne banaya", "किसने बनाया", "who made", "developer", "owner"]):
        return "⚡ यह bot KESHAV MADHAV द्वारा बनाया और powered है।"
    if any(x in q for x in ["result", "रिजल्ट", "परिणाम"]):
        return f"🏆 Uniraj Official Result\n\n{UNIRAJ_RESULT}\n\n🆘 Result Help Group:\n{RESULT_HELP}"
    if any(x in q for x in ["admission", "प्रवेश"]):
        return f"🎓 Uniraj Official Admission\n\n{UNIRAJ_ADMISSION}"
    if any(x in q for x in ["syllabus", "सिलेबस", "पाठ्यक्रम"]):
        if any(x in q for x in ["math", "mathematics", "गणित"]):
            return f"📘 B.Sc. Maths Group 2025-26 Official PDF:\n{BSC_MATHS_2025_26_PDF}\n\nOfficial Syllabus Index:\n{UNIRAJ_SYLLABUS}"
        return f"📘 Official Uniraj Syllabus Index:\n{UNIRAJ_SYLLABUS}"
    return None

# ================= GEMINI =================
def make_prompt(user_text, chat_id):
    history = USER_HISTORY.get(chat_id, [])[-MAX_HISTORY:]
    parts = [f"SYSTEM: {SYSTEM_PROMPT}"]
    for role, msg in history:
        parts.append(f"{role.upper()}: {msg}")
    parts.append(f"STUDENT: {user_text}")
    return "\n\n".join(parts)


def request_gemini(user_text, chat_id, model):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing hai")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": make_prompt(user_text, chat_id)}]}],
        "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.2},
    }
    r = requests.post(
        url,
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=AI_TIMEOUT,
    )
    if not r.ok:
        raise RuntimeError(f"Gemini {model} HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    candidates = data.get("candidates", [])
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    answer = "".join(p.get("text", "") for p in parts if p.get("text")).strip()
    if not answer:
        raise RuntimeError(f"Gemini {model} returned empty response")
    return answer


def ai_reply(user_text, chat_id):
    quick = quick_reply(user_text)
    if quick:
        return quick

    # Try the configured model first, then known current lightweight models.
    models = []
    for model in [GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]:
        if model and model not in models:
            models.append(model)

    last_error = None
    for model in models:
        try:
            answer = request_gemini(user_text, chat_id, model)
            logging.info("Gemini success model=%s", model)
            return answer
        except Exception as exc:
            last_error = exc
            logging.warning("Gemini model %s failed: %s", model, exc)

    logging.error("All Gemini models failed: %s", last_error)
    return (
        "⚠️ अभी Gemini AI से reply नहीं मिल पाया।\n\n"
        "आप चाहें तो Syllabus, Result, Admission या Guess Paper लिखें—उनके verified links अभी उपलब्ध हैं।"
    )

# ================= WEBHOOK =================
def configure_webhook():
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        return
    try:
        webhook_url = render_url.rstrip("/") + "/telegram/webhook"
        r = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url}, timeout=10)
        r.raise_for_status()
        logging.info("Telegram webhook configured: %s", webhook_url)
    except Exception:
        logging.exception("Failed to configure Telegram webhook")

configure_webhook()

# ================= ROUTES =================
@app.get("/")
def health():
    return jsonify({
        "ok": True,
        "service": "Uniraj Information Section",
        "status": "running",
        "ai": "Gemini",
        "model": GEMINI_MODEL,
        "build": "2026-09-10-gemini-3.5-fix",
    })


@app.post("/telegram/webhook")
def telegram_webhook():
    try:
        update = request.get_json(silent=True) or {}

        callback = update.get("callback_query")
        if callback:
            callback_id = callback.get("id")
            chat_id = callback.get("message", {}).get("chat", {}).get("id")
            data = callback.get("data", "")
            if callback_id:
                try:
                    requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": callback_id}, timeout=5)
                except Exception:
                    pass
            if chat_id:
                send_message(chat_id, callback_answer(data), menu_keyboard())
            return jsonify({"ok": True})

        message = update.get("message")
        if not message:
            return jsonify({"ok": True})
        user = message.get("from", {})
        if user.get("is_bot"):
            return jsonify({"ok": True})

        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return jsonify({"ok": True})

        if text.startswith("/start"):
            USER_HISTORY.pop(chat_id, None)
            send_message(
                chat_id,
                "🎓 Uniraj Information Section में आपका स्वागत है!\n\n"
                "Rajasthan University से जुड़े syllabus, exam, result, admission, notices और study questions पूछें।\n\n"
                "⚡ Powered by KESHAV MADHAV",
                menu_keyboard(),
            )
            return jsonify({"ok": True})

        if text.startswith("/reset"):
            USER_HISTORY.pop(chat_id, None)
            send_message(chat_id, "♻️ आपकी recent chat memory reset कर दी गई है।", menu_keyboard())
            return jsonify({"ok": True})

        try:
            requests.post(f"{TELEGRAM_API}/sendChatAction", json={"chat_id": chat_id, "action": "typing"}, timeout=5)
        except Exception:
            pass

        reply = ai_reply(text, chat_id)
        USER_HISTORY.setdefault(chat_id, []).append(("Student", text))
        USER_HISTORY.setdefault(chat_id, []).append(("Bot", reply))
        USER_HISTORY[chat_id] = USER_HISTORY[chat_id][-MAX_HISTORY:]
        send_message(chat_id, reply, menu_keyboard())
        return jsonify({"ok": True})

    except Exception:
        logging.exception("Telegram webhook failed")
        return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
