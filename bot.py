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

# Lightweight per-process context. It helps the bot understand the menu a student just used.
USER_CONTEXT = {}

OFFICIAL_UNIRAJ = "https://www.uniraj.ac.in/"
OFFICIAL_RESULT = "https://result.uniraj.ac.in/"
OFFICIAL_ADMISSION = "https://admissions.uniraj.ac.in/"
OFFICIAL_SYLLABUS = "https://uniraj.ac.in/index.php?mid=3125"
GUESS_CHANNEL_1 = "https://t.me/Uniraj_GuessPapers"
GUESS_CHANNEL_2 = "https://t.me/Unirajguesspaper"
RESULT_HELP_GROUP = "https://t.me/Unirajresult499"

# Official University of Rajasthan B.Sc. Mathematics syllabus, session 2025-26.
BSC_MATHS_SYLLABUS_PDF = "https://uniraj.ac.in/student/syl_N/UP_SYL_2025-26/Maths_UG0803_%28Maths_Group%29%20I%20to%20VI%202025-26%20%20SCiencee.pdf"

SYSTEM_PROMPT = """You are Uniraj Information Section, a Hindi-first study assistant for University of Rajasthan students.

Core rules:
- Understand Hindi, Hinglish, English, spelling mistakes and short student messages.
- Never start ordinary answers with a generic introduction. Answer the student's actual question directly.
- Help with BSc, BA, BCom, MSc and other Uniraj study topics, semesters, exams, results, admission, fees, dates, marks, timetable and syllabus.
- If course + semester + subject are supplied, use them explicitly.
- Never invent an official result, syllabus, date, notice, fee or university fact.
- For current/official information, only state what is verified or clearly say it must be checked against the official University source.
- For academic/study questions, explain concepts, make notes, formulas, revision plans and practice questions.
- If the request is genuinely incomplete, ask only one short clarification question.
- If a student asks for a guess paper, tell them that free Uniraj guess papers/study material are available through the official study-resource channels listed by this bot.
- If asked who made the bot, say it is powered by KESHAV MADHAV.
- If the student is unhappy with an answer, politely offer the Uniraj result/help group for human/community help.
- Never pretend that you personally fetched a student's marks unless a real result lookup was performed.
- Never fabricate a PDF or claim an AI-generated syllabus is an official syllabus. Official syllabus PDFs must come from the University source.
- Keep normal answers concise, useful and student-friendly.

Official University sources:
Uniraj: https://www.uniraj.ac.in/
Result: https://result.uniraj.ac.in/
Admission: https://admissions.uniraj.ac.in/
Syllabus: https://uniraj.ac.in/index.php?mid=3125
"""


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


def send_document(chat_id, document_url, caption):
    payload = {
        "chat_id": chat_id,
        "document": document_url,
        "caption": caption[:1024],
    }
    r = requests.post(f"{TELEGRAM_API}/sendDocument", json=payload, timeout=45)
    r.raise_for_status()
    return r.json()


def resource_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📚 Free Guess Papers", "url": GUESS_CHANNEL_1}],
            [{"text": "📚 More Study Material", "url": GUESS_CHANNEL_2}],
        ]
    }


def result_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🔎 Official Result Portal", "url": OFFICIAL_RESULT}],
            [{"text": "📲 Result Help Group", "url": RESULT_HELP_GROUP}],
        ]
    }


def main_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📌 आज के अपडेट", "callback_data": "today"}, {"text": "📝 Exam", "callback_data": "exam"}],
            [{"text": "🏆 Result", "callback_data": "result"}, {"text": "📚 Syllabus", "callback_data": "syllabus"}],
            [{"text": "🎓 Admission", "callback_data": "admission"}, {"text": "📅 Dates", "callback_data": "dates"}],
            [{"text": "📊 Marks", "callback_data": "marks"}, {"text": "🗓 Semester Hub", "callback_data": "semester"}],
            [{"text": "🕐 Time Table", "callback_data": "timetable"}, {"text": "🤖 Ask AI", "callback_data": "ask"}],
            [{"text": "📚 Free Study", "callback_data": "study"}, {"text": "ℹ️ Help", "callback_data": "help"}],
            [{"text": "🔗 Official Sources", "callback_data": "official"}, {"text": "👨‍💻 Bot Info", "callback_data": "about"}],
        ]
    }


def ai_reply(user_text, menu_context=""):
    context_line = f"\n\nThe student recently selected this menu: {menu_context}" if menu_context else ""
    prompt = f"{SYSTEM_PROMPT}{context_line}\n\nStudent's message:\n{user_text}\n\nAnswer directly in simple Hindi/Hinglish."
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 1000},
    }
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

    last_response = None
    for attempt in range(3):
        try:
            r = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=45)
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


def answer_callback(data):
    canned = {
        "today": "📌 आज के अपडेट\n\nमैं Uniraj के current notices और exam updates में मदद कर सकता हूँ। किसी भी notice/date के लिए course + semester लिखें।\n\n🔎 Official source: " + OFFICIAL_UNIRAJ,
        "exam": "📝 Exam\n\nExam form, timetable, admit card, practical या exam pattern पूछें। Course + semester लिखने पर मैं उसी हिसाब से जवाब दूँगा।",
        "result": "🏆 Result\n\nअपना course + semester लिखें। अगर personal result देखना है तो official result portal इस्तेमाल करें या Result Help Group में roll number + DOB भेजकर सहायता लें।",
        "syllabus": "📚 Syllabus\n\nCourse + semester + subject लिखें। जहाँ official PDF उपलब्ध है, मैं वही PDF दूँगा—AI से बनाया हुआ fake syllabus नहीं।",
        "admission": "🎓 Admission\n\nCourse + session लिखकर admission से जुड़ा सवाल भेजें।",
        "dates": "📅 Dates\n\nExam/form/result की date पूछने के लिए course + semester लिखें। Current official date verify करके ही बताई जाएगी।",
        "marks": "📊 Marks\n\nMarks, grade, passing marks या result से जुड़ा सवाल भेजें।",
        "semester": "🗓 Semester Hub\n\nअपना course + semester लिखें। मैं syllabus, study plan, important topics और exam preparation में मदद करूँगा।",
        "timetable": "🕐 Time Table\n\nCourse + semester लिखकर timetable पूछें। Official timetable उपलब्ध होने पर उसी source को प्राथमिकता दी जाएगी।",
        "ask": "🤖 Ask AI\n\nअपना study या Uniraj-related सवाल सीधे लिखें।",
        "study": "📚 Free Study Resources\n\nFree guess papers और study material के लिए हमारे study-resource channels देखें।\n\nनीचे buttons से खोल सकते हैं।",
        "help": "ℹ️ Help\n\nबस सवाल लिखें। उदाहरण:\n• BSc 2nd semester Maths syllabus\n• BSc 2nd semester result\n• Exam form date\n• Important questions\n• Guess paper",
        "official": "🔗 Official Sources\n\nUniraj: " + OFFICIAL_UNIRAJ + "\nResult: " + OFFICIAL_RESULT + "\nAdmission: " + OFFICIAL_ADMISSION + "\nSyllabus: " + OFFICIAL_SYLLABUS,
        "about": "👨‍💻 Bot Info\n\nयह Uniraj Information Section है, जो students को study, syllabus, exam, result और university information समझने में मदद करता है।\n\n⚡ Powered by KESHAV MADHAV",
    }
    return canned.get(data, "अपना सवाल भेजें।")


def handle_special_query(chat_id, text):
    """Handle high-value deterministic resources before asking Gemini."""
    t = text.lower().replace("।", " ").strip()
    result_words = ("result", "रिजल्ट", "परिणाम", "marksheet", "मार्कशीट")
    syllabus_words = ("syllabus", "सिलेबस", "पाठ्यक्रम")
    guess_words = ("guess paper", "guesspaper", "गेस पेपर", "important questions", "इम्पोर्टेन्ट क्वेश्चन")
    unhappy_words = ("satisfied नहीं", "satisfied nahi", "गलत जवाब", "wrong answer", "काम नहीं आया", "मदद नहीं मिली", "not satisfied", "समझ नहीं आया")

    if any(w in t for w in unhappy_words):
        send_message(chat_id, "🙏 अगर जवाब आपकी जरूरत के मुताबिक नहीं था, यहाँ अपना सवाल सीधे लिख सकते हैं।\n\nऔर community/help के लिए Result & Student Help Group देखें:", {"inline_keyboard": [[{"text": "📲 Student Help Group", "url": RESULT_HELP_GROUP}]]})
        return True

    if any(w in t for w in guess_words):
        send_message(chat_id, "📚 Free Guess Papers\n\nGuess papers और study material यहाँ उपलब्ध हैं। अपनी तैयारी के लिए course/semester के अनुसार material देखें:", resource_keyboard())
        return True

    if any(w in t for w in syllabus_words):
        if "bsc" in t and ("math" in t or "गणित" in t):
            try:
                send_document(chat_id, BSC_MATHS_SYLLABUS_PDF, "📚 Official B.Sc. Maths Group Syllabus\nSession: 2025-26\nSource: University of Rajasthan\n\n⚠️ यह official University PDF है; AI-generated syllabus नहीं।")
                send_message(chat_id, "अगर आपको किसी दूसरे course/subject का latest official syllabus चाहिए, बस course + subject + semester लिखें।\n\nOfficial syllabus list: " + OFFICIAL_SYLLABUS)
                return True
            except Exception:
                logging.exception("Failed to send BSc Maths syllabus PDF")
                send_message(chat_id, "📚 Official B.Sc. Maths syllabus यहाँ देखें:\n" + BSC_MATHS_SYLLABUS_PDF)
                return True
        send_message(chat_id, "📚 Latest official syllabus University की syllabus section से लिया जाना चाहिए—मैं fake/AI-generated syllabus को official नहीं बताऊँगा.\n\nOfficial Syllabus: " + OFFICIAL_SYLLABUS)
        return True

    if any(w in t for w in result_words):
        # A personal result cannot be fabricated. Give the official portal plus the user's requested help group.
        send_message(chat_id, "🏆 Result Information\n\nअगर आपका result जारी हो चुका है, official University result portal पर course/semester चुनकर Roll Number/DOB से check करें:\n" + OFFICIAL_RESULT + "\n\n📲 अगर result निकालने में मदद चाहिए, यहाँ Result Help Group है:", result_keyboard())
        return True

    if "kisne banaya" in t or "किसने बनाया" in t or "who made" in t or "developer" in t or "bot kisne" in t:
        send_message(chat_id, "👨‍💻 यह Uniraj Information Section bot है।\n\n⚡ Powered by KESHAV MADHAV")
        return True

    return False


def configure_webhook():
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        logging.info("RENDER_EXTERNAL_URL not available; webhook not auto-configured")
        return
    webhook_url = render_url.rstrip("/") + "/telegram/webhook"
    try:
        r = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url}, timeout=15)
        r.raise_for_status()
        logging.info("Telegram webhook configured: %s", webhook_url)
    except Exception:
        logging.exception("Failed to configure Telegram webhook")


configure_webhook()


@app.get("/")
def health():
    return jsonify({
        "ok": True,
        "service": "Uniraj Information Section",
        "status": "running",
        "ai": "Gemini REST",
        "model": GEMINI_MODEL,
        "build": "2026-09-10-uniraj-info-upgrade",
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
            if data == "study":
                send_message(chat_id, text, resource_keyboard())
            elif data == "result":
                send_message(chat_id, text, result_keyboard())
            else:
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
            USER_CONTEXT.pop(chat_id, None)
            welcome = (
                "🎓 <b>Uniraj Information Section में आपका स्वागत है!</b>\n\n"
                "Rajasthan University से जुड़ी पढ़ाई, syllabus, exam, result, dates और study help के लिए अपना सवाल भेजें।\n\n"
                "⚡ <b>Powered by KESHAV MADHAV</b>"
            )
            # HTML is enabled only for this controlled welcome text.
            payload = {"chat_id": chat_id, "text": welcome, "parse_mode": "HTML", "reply_markup": main_keyboard(), "disable_web_page_preview": True}
            r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=20)
            r.raise_for_status()
            return jsonify({"ok": True})

        if handle_special_query(chat_id, text):
            return jsonify({"ok": True})

        try:
            requests.post(f"{TELEGRAM_API}/sendChatAction", json={"chat_id": chat_id, "action": "typing"}, timeout=5)
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
