import os
import logging
from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# ================== CONFIG / KEYS ==================
BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()

# Replit-style primary OpenAI setup.
# Render should receive the same OPENAI_API_KEY that the working Replit bot uses.
OPENAI_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
OPENAI_MODEL = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()

# Backward-compatible support for the previous Render/Replit-compatible variables.
INTEGRATION_KEY = (os.getenv("AI_INTEGRATIONS_OPENAI_API_KEY") or "").strip()
INTEGRATION_BASE_URL = (os.getenv("AI_INTEGRATIONS_OPENAI_BASE_URL") or "").strip().rstrip("/")
INTEGRATION_MODEL = (os.getenv("AI_MODEL") or "").strip()

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-3.8-flash").strip()

NEWS_API_KEY = (os.getenv("NEWS_API_KEY") or "").strip()

ADMIN_IDS = {8280167872}
IGNORED_BOT_IDS = {609517172}

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing hai")
if not OPENAI_KEY and not INTEGRATION_KEY and not GEMINI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY ya GEMINI_API_KEY configure karo")

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

# ================== MEMORY ==================
USER_HISTORY = {}
MAX_HISTORY = 12
WEB_TIMEOUT = 20

SYSTEM_PROMPT = f"""You are Uniraj Information Section, a professional Hindi-first assistant for Rajasthan University students.

Your job:
- Answer in simple Hindi/Hinglish unless the student asks for English.
- Remember the recent conversation and answer the latest question directly.
- Do not restart with an introduction on every message.
- Understand Hindi, Hinglish, spelling mistakes and short student messages.
- Never invent official university information.
- When verified official source data is supplied, use it as the source of truth.
- For syllabus requests, give the direct official PDF link when available, not just the homepage.
- For personal results, never invent marks. Give the official result portal and Result Help group.
- For guess-paper requests, mention the free guess-paper channels.
- If asked who made the bot, say: "यह bot KESHAV MADHAV द्वारा बनाया और powered है।"

Official sources:
University: {UNIRAJ_HOME}
Syllabus: {UNIRAJ_SYLLABUS}
Notices: {UNIRAJ_NOTICES}
Result: {UNIRAJ_RESULT}
Admission: {UNIRAJ_ADMISSION}
Free Guess Papers: {GUESS_1}
Guess Papers: {GUESS_2}
Result Help: {RESULT_HELP}

Do not claim that you personally logged into a student's account. Do not fabricate live data.
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
    r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def answer_callback(data):
    canned = {
        "today": "📌 आज के अपडेट\n\nअपना course/semester या कोई current Uniraj सवाल भेजें।",
        "updates": "📢 All Updates\n\nExam, Result, Admission, Circular, Form, Revaluation और अन्य university updates के बारे में पूछें।",
        "exam": "📝 Exam\n\nCourse और semester बताकर exam की जानकारी पूछें।",
        "result": f"🏆 Result\n\nOfficial Result: {UNIRAJ_RESULT}\n\nResult Help: {RESULT_HELP}\nयहाँ result से जुड़ी मदद मिल सकती है।",
        "admission": f"🎓 Admission\n\nOfficial Admission: {UNIRAJ_ADMISSION}",
        "dates": "📅 Dates\n\nCourse/semester और किस date की जरूरत है, लिखें।",
        "fee": "💰 Fee\n\nCourse + semester बताकर fee पूछें।",
        "marks": "📊 Marks\n\nCourse/semester और marks से जुड़ा सवाल भेजें।",
        "semester": "🗓 Semester Hub\n\nCourse + semester लिखें। मैं official syllabus और study information में मदद करूँगा।",
        "timetable": "🕐 Time Table\n\nCourse + semester और exam/class timetable बताएं।",
        "notifications": f"🔔 Notifications\n\nOfficial notices: {UNIRAJ_NOTICES}",
        "ask": "🤖 Ask Uniraj AI\n\nअपना सवाल सीधे भेजें।",
        "help": "ℹ️ Help\n\nउदाहरण:\n• BSc 3rd semester Maths syllabus PDF भेजो\n• मेरा Uniraj result कहाँ मिलेगा?\n• आज की Uniraj notice बताओ",
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

# ================== OFFICIAL WEBSITE LOOKUP ==================
def fetch_official_page(url):
    r = requests.get(
        url,
        timeout=WEB_TIMEOUT,
        headers={"User-Agent": "UnirajInformationBot/1.0"},
    )
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

    # Prefer direct PDFs and the current 2025-26 syllabus links.
    results.sort(key=lambda x: (
        "pdf" not in x[1].lower(),
        "2025-26" not in x[1].lower(),
        "math" not in (x[0] + x[1]).lower(),
    ))

    unique = []
    seen = set()
    for item in results:
        if item[1] not in seen:
            seen.add(item[1])
            unique.append(item)
    return unique[:8]


def official_context(user_text):
    q = user_text.lower()

    syllabus_terms = ["syllabus", "सिलेबस", "पाठ्यक्रम", "course syllabus"]
    result_terms = ["result", "रिजल्ट", "परिणाम"]
    current_terms = [
        "latest", "today", "aaj", "current", "abhi", "update", "notice",
        "notification", "exam date", "exam dates", "date", "timetable",
        "time table", "admission", "fee", "fees", "form", "last date",
        "परीक्षा", "समय सारणी", "नोटिस", "प्रवेश", "फीस", "आज", "अभी",
        "अपडेट", "तिथि", "अंतिम तिथि",
    ]

    if any(t in q for t in syllabus_terms):
        try:
            links = find_official_syllabus(user_text)
            if links:
                lines = ["VERIFIED OFFICIAL UNIRAJ SYLLABUS LINKS:"]
                for title, url in links:
                    lines.append(f"- {title} | {url}")
                return "\n".join(lines)
            return f"OFFICIAL SYLLABUS INDEX: {UNIRAJ_SYLLABUS}\nNo matching direct PDF was extracted. Do not invent details."
        except Exception as exc:
            logging.exception("Syllabus lookup failed")
            return f"OFFICIAL SYLLABUS INDEX: {UNIRAJ_SYLLABUS}\nLookup failed: {exc}. Do not invent details."

    if any(t in q for t in result_terms):
        return (
            f"OFFICIAL RESULT PORTAL: {UNIRAJ_RESULT}\n"
            f"RESULT HELP GROUP: {RESULT_HELP}"
        )

    if any(t in q for t in current_terms):
        try:
            html = fetch_official_page(UNIRAJ_NOTICES)
            soup = BeautifulSoup(html, "html.parser")
            text = " ".join(soup.stripped_strings)
            return (
                "VERIFIED OFFICIAL UNIRAJ SOURCES:\n"
                f"University: {UNIRAJ_HOME}\n"
                f"Notices: {UNIRAJ_NOTICES}\n\n"
                "RECENT OFFICIAL NOTICE PAGE TEXT:\n"
                f"{text[:14000]}"
            )
        except Exception as exc:
            logging.exception("Official notice lookup failed")
            return (
                f"OFFICIAL UNIRAJ: {UNIRAJ_HOME}\n"
                f"OFFICIAL NOTICES: {UNIRAJ_NOTICES}\n"
                f"Lookup failed: {exc}. Do not guess."
            )

    return ""

# ================== NEWS ==================
def needs_latest_info(text):
    keywords = ["latest", "today", "aaj", "news", "current", "abhi", "haal", "update", "breaking"]
    return any(word in text.lower() for word in keywords)


def fetch_latest_news(query):
    if not NEWS_API_KEY:
        return ""
    try:
        url = "https://newsapi.org/v2/everything"
        r = requests.get(
            url,
            params={"q": query, "language": "en", "sortBy": "publishedAt", "apiKey": NEWS_API_KEY},
            timeout=10,
        )
        data = r.json()
        articles = data.get("articles", [])[:3]
        if not articles:
            return ""
        lines = ["📰 Latest Updates:"]
        for article in articles:
            lines.append(f"- {article.get('title', '')}")
        return "\n".join(lines)
    except Exception:
        return ""

# ================== AI ==================
def build_messages(user_text, chat_id, menu_context=""):
    history = USER_HISTORY.get(chat_id, [])
    source = official_context(user_text)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if source:
        messages.append({
            "role": "system",
            "content": "VERIFIED/RETRIEVED OFFICIAL SOURCE DATA:\n" + source,
        })

    if needs_latest_info(user_text):
        latest = fetch_latest_news(user_text)
        if latest:
            messages.append({"role": "system", "content": latest})

    if menu_context:
        messages.append({"role": "system", "content": f"Selected menu: {menu_context}"})

    for role, text in history[-MAX_HISTORY:]:
        messages.append({
            "role": "user" if role == "Student" else "assistant",
            "content": text,
        })
    messages.append({"role": "user", "content": user_text})
    return messages


def openai_client():
    # Exact Replit-style environment first.
    if OPENAI_KEY:
        kwargs = {"api_key": OPENAI_KEY}
        if OPENAI_BASE_URL:
            kwargs["base_url"] = OPENAI_BASE_URL
        return OpenAI(**kwargs), OPENAI_MODEL, "OpenAI SDK"

    # Compatibility with the previous Render setup.
    if INTEGRATION_KEY and INTEGRATION_BASE_URL:
        model = INTEGRATION_MODEL or "gpt-4o-mini"
        return OpenAI(api_key=INTEGRATION_KEY, base_url=INTEGRATION_BASE_URL), model, "OpenAI-compatible integration"

    return None, None, None


def request_openai(messages):
    client, model, provider = openai_client()
    if not client:
        raise RuntimeError("OpenAI provider is not configured")

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=1200,
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError("OpenAI returned empty response")
    return text, provider, model


def request_gemini(messages):
    if not GEMINI_API_KEY:
        raise RuntimeError("Gemini fallback is not configured")

    prompt_parts = []
    for m in messages:
        prompt_parts.append(f"{m['role'].upper()}: {m['content']}")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "\n\n".join(prompt_parts)}]}],
        "generationConfig": {"maxOutputTokens": 1200, "temperature": 0.2},
    }
    r = requests.post(
        url,
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"Gemini API {r.status_code}: {r.text[:500]}")

    data = r.json()
    candidates = data.get("candidates", [])
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    text = "".join(p.get("text", "") for p in parts if p.get("text")).strip()
    if not text:
        raise RuntimeError("Gemini returned empty response")
    return text, "Gemini fallback", GEMINI_MODEL


def ai_reply(user_text, chat_id, menu_context=""):
    messages = build_messages(user_text, chat_id, menu_context)

    # Primary = the same OpenAI SDK style used by the working Replit bot.
    try:
        text, provider, model = request_openai(messages)
        logging.info("AI success provider=%s model=%s", provider, model)
        return text
    except Exception as exc:
        logging.warning("Primary OpenAI provider failed: %s", exc)

    # Fallback = Gemini, if configured.
    try:
        text, provider, model = request_gemini(messages)
        logging.info("AI fallback success provider=%s model=%s", provider, model)
        return text
    except Exception as exc:
        logging.exception("All AI providers failed: %s", exc)
        return (
            "⏳ अभी AI service उपलब्ध नहीं हो पाई। "
            "थोड़ी देर बाद फिर कोशिश करें।"
        )

# ================== WEBHOOK ==================
def configure_webhook():
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        return
    try:
        webhook_url = render_url.rstrip("/") + "/telegram/webhook"
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

# ================== ROUTES ==================
@app.get("/")
def health():
    if OPENAI_KEY:
        provider = "OpenAI SDK"
        model = OPENAI_MODEL
    elif INTEGRATION_KEY and INTEGRATION_BASE_URL:
        provider = "OpenAI-compatible integration"
        model = INTEGRATION_MODEL or "gpt-4o-mini"
    elif GEMINI_API_KEY:
        provider = "Gemini fallback"
        model = GEMINI_MODEL
    else:
        provider = "none"
        model = "none"

    return jsonify({
        "ok": True,
        "service": "Uniraj Information Section",
        "status": "running",
        "ai": provider,
        "model": model,
        "official_web_lookup": True,
        "replit_style_openai": bool(OPENAI_KEY),
        "build": "2026-09-10-replit-openai-plus-uniraj",
    })


@app.post("/telegram/webhook")
def telegram_webhook():
    try:
        update = request.get_json(silent=True) or {}

        # Inline button callback.
        callback = update.get("callback_query")
        if callback:
            callback_id = callback.get("id")
            chat_id = callback.get("message", {}).get("chat", {}).get("id")
            data = callback.get("data", "")
            if callback_id:
                requests.post(
                    f"{TELEGRAM_API}/answerCallbackQuery",
                    json={"callback_query_id": callback_id},
                    timeout=10,
                )
            if chat_id:
                text = answer_callback(data)
                if data in {"ask", "today", "updates", "exam", "dates", "fee", "marks", "semester", "timetable"}:
                    USER_HISTORY.pop(chat_id, None)
                send_message(chat_id, text, menu_keyboard())
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
            welcome = (
                "🎓 Uniraj Information Section में आपका स्वागत है!\n\n"
                "यहाँ आप Rajasthan University से जुड़े syllabus, exam, result, admission, notices और study questions पूछ सकते हैं।\n\n"
                "⚡ Powered by KESHAV MADHAV"
            )
            send_message(chat_id, welcome, menu_keyboard())
            return jsonify({"ok": True})

        if user_text.startswith("/reset"):
            USER_HISTORY.pop(chat_id, None)
            send_message(chat_id, "♻️ आपकी recent chat memory reset कर दी गई है।", menu_keyboard())
            return jsonify({"ok": True})

        if not user_text:
            return jsonify({"ok": True})

        # Typing indicator.
        try:
            requests.post(
                f"{TELEGRAM_API}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"},
                timeout=10,
            )
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
    # Local fallback; Render normally uses gunicorn.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
