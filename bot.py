import os
import logging
from functools import lru_cache
from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# ================== CONFIG ==================
BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
OPENAI_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
OPENAI_MODEL = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()

# Legacy/Replit-compatible variables are supported but are no longer preferred.
INTEGRATION_KEY = (os.getenv("AI_INTEGRATIONS_OPENAI_API_KEY") or "").strip()
INTEGRATION_BASE_URL = (os.getenv("AI_INTEGRATIONS_OPENAI_BASE_URL") or "").strip().rstrip("/")
INTEGRATION_MODEL = (os.getenv("AI_MODEL") or "").strip()

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
NEWS_API_KEY = (os.getenv("NEWS_API_KEY") or "").strip()

ADMIN_IDS = {8280167872}
IGNORED_BOT_IDS = {609517172}

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing hai")
if not OPENAI_KEY and not INTEGRATION_KEY and not GEMINI_API_KEY:
    logging.warning("No AI provider configured. Offline Uniraj fallback will still work.")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ================== UNIRAJ SOURCES ==================
UNIRAJ_HOME = "https://www.uniraj.ac.in/"
UNIRAJ_SYLLABUS = "https://uniraj.ac.in/index.php?mid=3125"
UNIRAJ_NOTICES = "https://www.uniraj.ac.in/index.php?mid=196"
UNIRAJ_RESULT = "https://result.uniraj.ac.in/"
UNIRAJ_ADMISSION = "https://admissions.uniraj.ac.in/"
GUESS_1 = "https://t.me/Uniraj_GuessPapers"
GUESS_2 = "https://t.me/Unirajguesspaper"
RESULT_HELP = "https://t.me/Unirajresult499"

# Verified direct syllabus PDF supplied from the official Uniraj syllabus index.
BSC_MATHS_2025_26_PDF = (
    "https://uniraj.ac.in/student/syl_N/UP_SYL_2025-26/"
    "Maths_UG0803_%28Maths_Group%29%20I%20to%20VI%202025-26%20%20SCiencee.pdf"
)

MAX_HISTORY = 12
WEB_TIMEOUT = 5
AI_TIMEOUT = 35
USER_HISTORY = {}

SYSTEM_PROMPT = f"""You are Uniraj Information Section, a professional Hindi-first assistant for Rajasthan University students.

Rules:
- Answer in simple Hindi/Hinglish unless English is requested.
- Use recent conversation context; do not restart unnecessarily.
- Understand Hindi, Hinglish, spelling mistakes and short student messages.
- Never invent official university information or marks.
- For official information, prefer verified source data supplied below.
- For syllabus, give direct official PDF links when available.
- For personal results, never invent marks or claim login access. Give the official portal and Result Help group.
- For guess-paper requests, mention both free guess-paper channels.
- If asked who made the bot, say: यह bot KESHAV MADHAV द्वारा बनाया और powered है।

Official sources:
University: {UNIRAJ_HOME}
Syllabus index: {UNIRAJ_SYLLABUS}
B.Sc. Maths Group 2025-26 PDF: {BSC_MATHS_2025_26_PDF}
Notices: {UNIRAJ_NOTICES}
Result: {UNIRAJ_RESULT}
Admission: {UNIRAJ_ADMISSION}
Free Guess Papers: {GUESS_1}
Guess Papers: {GUESS_2}
Result Help: {RESULT_HELP}
"""

# ================== TELEGRAM ==================
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


def answer_callback(data):
    canned = {
        "today": f"📌 आज के अपडेट\n\nCurrent Uniraj update पूछने के लिए अपना course/semester लिखें।\nOfficial Notices: {UNIRAJ_NOTICES}",
        "updates": f"📢 All Updates\n\nExam, Result, Admission, Circular, Form, Revaluation और अन्य university updates के बारे में पूछें।\nOfficial Notices: {UNIRAJ_NOTICES}",
        "exam": "📝 Exam\n\nCourse और semester बताकर exam से जुड़ा सवाल भेजें।",
        "result": f"🏆 Result\n\nOfficial Result: {UNIRAJ_RESULT}\n\nResult Help: {RESULT_HELP}\nयहाँ result से जुड़ी मदद मिल सकती है।",
        "admission": f"🎓 Admission\n\nOfficial Admission: {UNIRAJ_ADMISSION}",
        "dates": "📅 Dates\n\nCourse/semester और किस date की जरूरत है, लिखें।",
        "fee": "💰 Fee\n\nCourse + semester बताकर fee पूछें।",
        "marks": "📊 Marks\n\nCourse/semester और marks से जुड़ा सवाल भेजें।",
        "semester": f"🗓 Semester Hub\n\nCourse + semester लिखें। Official syllabus index: {UNIRAJ_SYLLABUS}",
        "timetable": "🕐 Time Table\n\nCourse + semester और exam/class timetable बताएं।",
        "notifications": f"🔔 Notifications\n\nOfficial notices: {UNIRAJ_NOTICES}",
        "ask": "🤖 Ask Uniraj AI\n\nअपना सवाल सीधे भेजें।",
        "help": "ℹ️ Help\n\nउदाहरण:\n• BSc 3rd semester Maths syllabus PDF भेजो\n• मेरा Uniraj result कहाँ मिलेगा?\n• आज की Uniraj notice बताओ\n• Guess paper कहाँ मिलेगा?",
        "official": f"🔗 Official Sources\n\nUniraj: {UNIRAJ_HOME}\nSyllabus: {UNIRAJ_SYLLABUS}\nResult: {UNIRAJ_RESULT}\nAdmission: {UNIRAJ_ADMISSION}",
    }
    return canned.get(data, "अपना सवाल भेजें।")


def menu_keyboard():
    return {"inline_keyboard": [
        [{"text": "📌 आज के अपडेट", "callback_data": "today"}, {"text": "📢 All Updates", "callback_data": "updates"}],
        [{"text": "📝 Exam", "callback_data": "exam"}, {"text": "🏆 Result", "callback_data": "result"}],
        [{"text": "🎓 Admission", "callback_data": "admission"}, {"text": "📅 Dates", "callback_data": "dates"}],
        [{"text": "💰 Fee", "callback_data": "fee"}, {"text": "📊 Marks", "callback_data": "marks"}],
        [{"text": "🗓 Semester Hub", "callback_data": "semester"}, {"text": "🕐 Time Table", "callback_data": "timetable"}],
        [{"text": "🔔 Notifications", "callback_data": "notifications"}, {"text": "🤖 Ask Uniraj AI", "callback_data": "ask"}],
        [{"text": "ℹ️ Help", "callback_data": "help"}, {"text": "🔗 Official Sources", "callback_data": "official"}],
    ]}

# ================== OFFICIAL WEBSITE ==================
def fetch_official_page(url, timeout=WEB_TIMEOUT):
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "UnirajInformationBot/1.1"})
    r.raise_for_status()
    return r.text


def find_official_syllabus(query):
    html = fetch_official_page(UNIRAJ_SYLLABUS)
    soup = BeautifulSoup(html, "html.parser")
    q = query.lower()
    results = []
    for a in soup.find_all("a", href=True):
        title = " ".join(a.stripped_strings)
        href = urljoin(UNIRAJ_SYLLABUS, a["href"])
        combined = f"{title} {href}".lower()
        if any(x in q for x in ["math", "mathematics", "गणित"]):
            matched = "math" in combined or "mathematics" in combined
        elif any(x in q for x in ["bsc", "b.sc", "science"]):
            matched = "b.sc" in combined or "bsc" in combined or "science" in combined
        else:
            words = [w for w in q.split() if len(w) > 2]
            matched = any(w in combined for w in words)
        if matched:
            results.append((title or "Official syllabus", href))
    results.sort(key=lambda x: ("pdf" not in x[1].lower(), "2025-26" not in x[1].lower(), "math" not in (x[0] + x[1]).lower()))
    unique, seen = [], set()
    for item in results:
        if item[1] not in seen:
            seen.add(item[1])
            unique.append(item)
    return unique[:8]


def official_context(user_text):
    q = user_text.lower()
    syllabus_terms = ["syllabus", "सिलेबस", "पाठ्यक्रम", "course syllabus"]
    result_terms = ["result", "रिजल्ट", "परिणाम"]
    current_terms = ["latest", "today", "aaj", "current", "abhi", "update", "notice", "notification", "exam date", "exam dates", "date", "timetable", "time table", "admission", "fee", "fees", "form", "last date", "परीक्षा", "समय सारणी", "नोटिस", "प्रवेश", "फीस", "आज", "अभी", "अपडेट", "तिथि", "अंतिम तिथि"]

    # Fast path: the verified direct B.Sc. Maths PDF should not depend on the slow university website.
    if any(t in q for t in syllabus_terms) and any(x in q for x in ["math", "mathematics", "गणित"]):
        return f"VERIFIED OFFICIAL SOURCE:\nB.Sc. Maths Group 2025-26 PDF: {BSC_MATHS_2025_26_PDF}\nSyllabus index: {UNIRAJ_SYLLABUS}"

    if any(t in q for t in syllabus_terms):
        try:
            links = find_official_syllabus(user_text)
            if links:
                return "VERIFIED OFFICIAL UNIRAJ SYLLABUS LINKS:\n" + "\n".join(f"- {title} | {url}" for title, url in links)
        except requests.RequestException as exc:
            logging.warning("Syllabus website unavailable: %s", exc)
        except Exception:
            logging.exception("Syllabus lookup failed")
        return f"OFFICIAL SYLLABUS INDEX: {UNIRAJ_SYLLABUS}\nNo verified matching PDF was extracted. Do not invent details."

    if any(t in q for t in result_terms):
        return f"OFFICIAL RESULT PORTAL: {UNIRAJ_RESULT}\nRESULT HELP GROUP: {RESULT_HELP}"

    if any(t in q for t in current_terms):
        try:
            html = fetch_official_page(UNIRAJ_NOTICES)
            soup = BeautifulSoup(html, "html.parser")
            text = " ".join(soup.stripped_strings)
            return f"VERIFIED OFFICIAL SOURCES:\nUniversity: {UNIRAJ_HOME}\nNotices: {UNIRAJ_NOTICES}\n\nRECENT NOTICE PAGE TEXT:\n{text[:12000]}"
        except requests.RequestException as exc:
            logging.warning("Official notices unavailable: %s", exc)
            return f"OFFICIAL UNIRAJ: {UNIRAJ_HOME}\nOFFICIAL NOTICES: {UNIRAJ_NOTICES}\nThe official site is temporarily slow/unavailable; do not guess current information."
        except Exception:
            logging.exception("Official notice lookup failed")
            return f"OFFICIAL UNIRAJ: {UNIRAJ_HOME}\nOFFICIAL NOTICES: {UNIRAJ_NOTICES}\nThe official lookup failed; do not guess current information."

    return ""

# ================== NEWS ==================
def needs_latest_info(text):
    return any(word in text.lower() for word in ["latest", "today", "aaj", "news", "current", "abhi", "haal", "update", "breaking"])


def fetch_latest_news(query):
    if not NEWS_API_KEY:
        return ""
    try:
        r = requests.get("https://newsapi.org/v2/everything", params={"q": query, "language": "en", "sortBy": "publishedAt", "apiKey": NEWS_API_KEY}, timeout=5)
        data = r.json()
        articles = data.get("articles", [])[:3]
        return "\n".join(["📰 Latest Updates:"] + [f"- {a.get('title', '')}" for a in articles]) if articles else ""
    except Exception:
        return ""

# ================== OFFLINE FALLBACK ==================
def offline_reply(user_text):
    q = user_text.lower()
    if any(x in q for x in ["guess paper", "guesspaper", "गेस पेपर", "guess papers"]):
        return f"📚 Free Uniraj Guess Papers\n\n1️⃣ {GUESS_1}\n2️⃣ {GUESS_2}"
    if any(x in q for x in ["who made", "kisne banaya", "किसने बनाया", "owner", "developer"]):
        return "⚡ यह bot KESHAV MADHAV द्वारा बनाया और powered है।"
    if any(x in q for x in ["result", "रिजल्ट", "परिणाम"]):
        return f"🏆 Uniraj Official Result\n\n{UNIRAJ_RESULT}\n\nResult Help Group:\n{RESULT_HELP}"
    if any(x in q for x in ["admission", "प्रवेश"]):
        return f"🎓 Uniraj Official Admission\n\n{UNIRAJ_ADMISSION}"
    if any(x in q for x in ["syllabus", "सिलेबस", "पाठ्यक्रम"]):
        if any(x in q for x in ["math", "mathematics", "गणित"]):
            return f"📘 B.Sc. Maths Group 2025-26 Official PDF:\n{BSC_MATHS_2025_26_PDF}\n\nOfficial Syllabus Index:\n{UNIRAJ_SYLLABUS}"
        return f"📘 Official Uniraj Syllabus Index:\n{UNIRAJ_SYLLABUS}"
    if any(x in q for x in ["notice", "notification", "नोटिस", "नोटिफिकेशन"]):
        return f"🔔 Official Uniraj Notices:\n{UNIRAJ_NOTICES}"
    if any(x in q for x in ["hello", "hi", "नमस्ते", "नमस्कार"]):
        return "नमस्ते! 👋 Uniraj से जुड़ा सवाल भेजें—syllabus, exam, result, admission, notice या guess paper।"
    return "⏳ AI service अभी उपलब्ध नहीं है। आप syllabus, result, admission, notice या guess paper लिखें—इनके verified links मैं अभी दे सकता हूँ।"

# ================== AI ==================
def build_messages(user_text, chat_id, menu_context=""):
    history = USER_HISTORY.get(chat_id, [])
    source = official_context(user_text)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if source:
        messages.append({"role": "system", "content": "VERIFIED/RETRIEVED OFFICIAL SOURCE DATA:\n" + source})
    if needs_latest_info(user_text):
        latest = fetch_latest_news(user_text)
        if latest:
            messages.append({"role": "system", "content": latest})
    if menu_context:
        messages.append({"role": "system", "content": f"Selected menu: {menu_context}"})
    for role, text in history[-MAX_HISTORY:]:
        messages.append({"role": "user" if role == "Student" else "assistant", "content": text})
    messages.append({"role": "user", "content": user_text})
    return messages


def openai_client():
    if OPENAI_KEY:
        kwargs = {"api_key": OPENAI_KEY, "max_retries": 0, "timeout": AI_TIMEOUT}
        if OPENAI_BASE_URL:
            kwargs["base_url"] = OPENAI_BASE_URL
        return OpenAI(**kwargs), OPENAI_MODEL, "OpenAI SDK"
    if INTEGRATION_KEY and INTEGRATION_BASE_URL:
        return OpenAI(api_key=INTEGRATION_KEY, base_url=INTEGRATION_BASE_URL, max_retries=0, timeout=AI_TIMEOUT), INTEGRATION_MODEL or "gpt-4o-mini", "OpenAI-compatible integration"
    return None, None, None


def request_openai(messages):
    client, model, provider = openai_client()
    if not client:
        raise RuntimeError("OpenAI provider is not configured")
    response = client.chat.completions.create(model=model, messages=messages, temperature=0.2, max_tokens=1200)
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError("OpenAI returned empty response")
    return text, provider, model


def request_gemini(messages):
    if not GEMINI_API_KEY:
        raise RuntimeError("Gemini fallback is not configured")
    prompt = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 1200, "temperature": 0.2}}
    r = requests.post(url, headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}, json=payload, timeout=AI_TIMEOUT)
    if not r.ok:
        raise RuntimeError(f"Gemini API {r.status_code}: {r.text[:300]}")
    data = r.json()
    candidates = data.get("candidates", [])
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    text = "".join(p.get("text", "") for p in parts if p.get("text")).strip()
    if not text:
        raise RuntimeError("Gemini returned empty response")
    return text, "Gemini", GEMINI_MODEL


def ai_reply(user_text, chat_id, menu_context=""):
    # First give reliable deterministic answers for common Uniraj queries.
    quick = offline_reply(user_text)
    generic_offline = quick.startswith("⏳ AI service")
    if not generic_offline:
        return quick

    messages = build_messages(user_text, chat_id, menu_context)
    openai_error = None
    try:
        text, provider, model = request_openai(messages)
        logging.info("AI success provider=%s model=%s", provider, model)
        return text
    except Exception as exc:
        openai_error = str(exc)
        logging.warning("Primary AI provider failed: %s", exc)

    try:
        text, provider, model = request_gemini(messages)
        logging.info("AI fallback success provider=%s model=%s", provider, model)
        return text
    except Exception as exc:
        logging.warning("Gemini fallback failed: %s", exc)

    if "credit_balance_exhausted" in (openai_error or "") or "no credits remaining" in (openai_error or "").lower():
        return "⚠️ AI provider का API credit balance खत्म है।\n\nलेकिन Uniraj के syllabus/result/admission/notice/guess-paper वाले verified links अभी भी उपलब्ध हैं।"
    return offline_reply(user_text)

# ================== WEBHOOK ==================
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

# ================== ROUTES ==================
@app.get("/")
def health():
    if OPENAI_KEY:
        provider, model = "OpenAI SDK", OPENAI_MODEL
    elif INTEGRATION_KEY and INTEGRATION_BASE_URL:
        provider, model = "OpenAI-compatible integration", INTEGRATION_MODEL or "gpt-4o-mini"
    elif GEMINI_API_KEY:
        provider, model = "Gemini", GEMINI_MODEL
    else:
        provider, model = "offline fallback", "none"
    return jsonify({
        "ok": True,
        "service": "Uniraj Information Section",
        "status": "running",
        "ai": provider,
        "model": model,
        "official_web_lookup": True,
        "offline_fallback": True,
        "build": "2026-09-10-hardened",
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
                send_message(chat_id, answer_callback(data), menu_keyboard())
            return jsonify({"ok": True})

        message = update.get("message")
        if not message:
            return jsonify({"ok": True})
        user = message.get("from", {})
        if user.get("is_bot") or user.get("id") in IGNORED_BOT_IDS:
            return jsonify({"ok": True})
        chat_id = message.get("chat", {}).get("id")
        user_text = (message.get("text") or "").strip()
        if not chat_id:
            return jsonify({"ok": True})

        if user_text.startswith("/start"):
            USER_HISTORY.pop(chat_id, None)
            welcome = "🎓 Uniraj Information Section में आपका स्वागत है!\n\nयहाँ आप Rajasthan University से जुड़े syllabus, exam, result, admission, notices और study questions पूछ सकते हैं।\n\n⚡ Powered by KESHAV MADHAV"
            send_message(chat_id, welcome, menu_keyboard())
            return jsonify({"ok": True})

        if user_text.startswith("/reset"):
            USER_HISTORY.pop(chat_id, None)
            send_message(chat_id, "♻️ आपकी recent chat memory reset कर दी गई है।", menu_keyboard())
            return jsonify({"ok": True})

        if not user_text:
            return jsonify({"ok": True})

        try:
            requests.post(f"{TELEGRAM_API}/sendChatAction", json={"chat_id": chat_id, "action": "typing"}, timeout=5)
        except Exception:
            pass

        reply = ai_reply(user_text, chat_id)
        USER_HISTORY.setdefault(chat_id, []).append(("Student", user_text))
        USER_HISTORY.setdefault(chat_id, []).append(("Bot", reply))
        USER_HISTORY[chat_id] = USER_HISTORY[chat_id][-MAX_HISTORY:]
        send_message(chat_id, reply, menu_keyboard())
        return jsonify({"ok": True})
    except Exception:
        logging.exception("Webhook handler failed")
        return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
