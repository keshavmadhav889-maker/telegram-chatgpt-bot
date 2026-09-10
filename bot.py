import os
import logging
import time
from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
OPENAI_API_KEY = (os.getenv("AI_INTEGRATIONS_OPENAI_API_KEY") or "").strip()
OPENAI_BASE_URL = (os.getenv("AI_INTEGRATIONS_OPENAI_BASE_URL") or "").strip().rstrip("/")
OPENAI_MODEL = (os.getenv("AI_MODEL") or "gemini-3.8-flash").strip()
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-3.8-flash").strip()

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
if not OPENAI_API_KEY and not GEMINI_API_KEY:
    raise RuntimeError("Configure an AI API key")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
UNIRAJ_HOME = "https://www.uniraj.ac.in/"
UNIRAJ_SYLLABUS = "https://uniraj.ac.in/index.php?mid=3125"
UNIRAJ_NOTICES = "https://www.uniraj.ac.in/index.php?mid=196"
UNIRAJ_RESULT = "https://result.uniraj.ac.in/"
UNIRAJ_ADMISSION = "https://admissions.uniraj.ac.in/"
GUESS_1 = "https://t.me/Uniraj_GuessPapers"
GUESS_2 = "https://t.me/Unirajguesspaper"
RESULT_HELP = "https://t.me/Unirajresult499"

USER_CONTEXT = {}
USER_HISTORY = {}
MAX_HISTORY = 12
WEB_TIMEOUT = 20

SYSTEM_PROMPT = f"""You are Uniraj Information Section, a professional Hindi-first study assistant for Rajasthan University students.

IMPORTANT SOURCE RULE:
For any question about current/official Rajasthan University information, you MUST use the official University source data supplied in the prompt. Never invent a syllabus, exam date, fee, notice, timetable, admission detail or result.
If official source data is unavailable, clearly say that you could not verify it instead of guessing.

For syllabus requests, give the official PDF/direct PDF URL when one is found. Do not merely tell the student to visit the homepage.
For personal results, never fabricate marks. Direct the student to the official result portal and the configured Result Help group.

Official sources:
University: {UNIRAJ_HOME}
Syllabus: {UNIRAJ_SYLLABUS}
Notices: {UNIRAJ_NOTICES}
Result: {UNIRAJ_RESULT}
Admission: {UNIRAJ_ADMISSION}
Free Guess Papers: {GUESS_1}
Guess Papers: {GUESS_2}
Result Help: {RESULT_HELP}

Understand Hindi, Hinglish and spelling mistakes. Remember the immediately previous conversation. Do not restart with an introduction on every message. Answer the latest question directly and concisely.
If asked who made the bot, say it was made/powered by KESHAV MADHAV.
"""

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": str(text)[:4096], "disable_web_page_preview": False}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def request_openai_compatible(messages):
    if not OPENAI_API_KEY or not OPENAI_BASE_URL:
        raise RuntimeError("OpenAI-compatible integration is not configured")
    url = OPENAI_BASE_URL if OPENAI_BASE_URL.endswith("/chat/completions") else OPENAI_BASE_URL + "/chat/completions"
    payload = {"model": OPENAI_MODEL, "messages": messages, "max_tokens": 1200, "temperature": 0.2}
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    if not r.ok:
        raise RuntimeError(f"OpenAI-compatible API {r.status_code}: {r.text[:500]}")
    data = r.json()
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if not text:
        raise RuntimeError("OpenAI-compatible provider returned empty text")
    return text


def request_gemini(messages):
    model = GEMINI_MODEL
    prompt_parts = []
    for m in messages:
        prompt_parts.append(f"{m['role'].upper()}: {m['content']}")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {"contents": [{"role": "user", "parts": [{"text": "\n\n".join(prompt_parts)}]}], "generationConfig": {"maxOutputTokens": 1200, "temperature": 0.2}}
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Gemini API {r.status_code}: {r.text[:500]}")
    data = r.json()
    candidates = data.get("candidates", [])
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    text = "".join(p.get("text", "") for p in parts if p.get("text")).strip()
    if not text:
        raise RuntimeError("Gemini returned empty text")
    return text


def fetch_official_page(url):
    r = requests.get(url, timeout=WEB_TIMEOUT, headers={"User-Agent": "UnirajInformationBot/1.0"})
    r.raise_for_status()
    return r.text


def find_official_syllabus(query):
    """Search the official Uniraj syllabus index and return relevant PDF links/snippets."""
    html = fetch_official_page(UNIRAJ_SYLLABUS)
    soup = BeautifulSoup(html, "html.parser")
    query_l = query.lower()
    results = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.stripped_strings)
        href = urljoin(UNIRAJ_SYLLABUS, a["href"])
        combined = f"{text} {href}".lower()
        if "math" in query_l or "गणित" in query_l:
            if "math" in combined or "mathematics" in combined:
                results.append((text or "Mathematics syllabus", href))
        elif any(term in combined for term in query_l.split()):
            results.append((text or "Official syllabus", href))
    # Prefer direct PDF links and 2025-26/NEP links.
    results.sort(key=lambda x: ("pdf" not in x[1].lower(), "2025-26" not in x[1].lower(), "math" not in (x[0]+x[1]).lower()))
    unique = []
    seen = set()
    for item in results:
        if item[1] not in seen:
            seen.add(item[1])
            unique.append(item)
    return unique[:8]


def official_context(user_text):
    """Fetch official data only when the question is likely to need live/current UOR data."""
    q = user_text.lower()
    syllabus_terms = ["syllabus", "सिलेबस", "पाठ्यक्रम", "course syllabus"]
    result_terms = ["result", "रिजल्ट", "परिणाम"]
    official_terms = ["exam date", "exam dates", "timetable", "time table", "notice", "notification", "admission", "fee", "form", "last date", "date", "परीक्षा", "समय सारणी", "नोटिस", "प्रवेश", "फीस"]

    if any(t in q for t in syllabus_terms):
        try:
            links = find_official_syllabus(user_text)
            if links:
                lines = ["OFFICIAL UNIRAJ SYLLABUS SEARCH RESULT:"]
                for title, url in links:
                    lines.append(f"- {title} | {url}")
                return "\n".join(lines)
            return f"OFFICIAL SYLLABUS INDEX: {UNIRAJ_SYLLABUS}\nNo matching PDF link was extracted. Do not invent a PDF."
        except Exception as exc:
            logging.exception("Official syllabus lookup failed")
            return f"OFFICIAL SYLLABUS INDEX: {UNIRAJ_SYLLABUS}\nLookup failed: {exc}. Do not invent syllabus details."

    if any(t in q for t in result_terms):
        return f"OFFICIAL RESULT PORTAL: {UNIRAJ_RESULT}\nRESULT HELP GROUP: {RESULT_HELP}"

    if any(t in q for t in official_terms):
        sources = [UNIRAJ_HOME, UNIRAJ_NOTICES]
        try:
            html = fetch_official_page(UNIRAJ_NOTICES)
            soup = BeautifulSoup(html, "html.parser")
            text = " ".join(soup.stripped_strings)
            # Keep a compact official-site excerpt; AI must distinguish it from verified exact details.
            return "OFFICIAL UNIRAJ SOURCES:\n" + "\n".join(sources) + "\n\nRECENT OFFICIAL NOTICE PAGE EXCERPT:\n" + text[:12000]
        except Exception as exc:
            logging.exception("Official notice lookup failed")
            return "OFFICIAL UNIRAJ SOURCES:\n" + "\n".join(sources) + f"\nLookup failed: {exc}. Do not guess."

    return ""


def ai_reply(user_text, chat_id, menu_context=""):
    history = USER_HISTORY.get(chat_id, [])
    source = official_context(user_text)
    context_line = f"Selected menu: {menu_context}" if menu_context else ""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if source:
        messages.append({"role": "system", "content": "VERIFIED/RETRIEVED OFFICIAL SOURCE DATA:\n" + source})
    if context_line:
        messages.append({"role": "system", "content": context_line})
    for role, text in history[-MAX_HISTORY:]:
        messages.append({"role": "user" if role == "Student" else "assistant", "content": text})
    messages.append({"role": "user", "content": user_text})

    if OPENAI_API_KEY and OPENAI_BASE_URL:
        try:
            return request_openai_compatible(messages)
        except Exception as exc:
            logging.warning("OpenAI-compatible AI failed: %s", exc)
    if GEMINI_API_KEY:
        return request_gemini(messages)
    raise RuntimeError("No AI provider is configured")


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


def answer_callback(data):
    canned = {
        "today": "📌 आज के अपडेट\n\nअपना course/semester लिखकर पूछें। मैं official Uniraj information के आधार पर मदद करूँगा।",
        "updates": "📢 All Updates\n\nExam, Result, Admission, Circular, Form, Reval और अन्य विश्वविद्यालय अपडेट के बारे में पूछें।",
        "exam": "📝 Exam\n\nCourse और semester बताकर exam की जानकारी पूछें।",
        "result": f"🏆 Result\n\nOfficial Result: {UNIRAJ_RESULT}\nResult Help: {RESULT_HELP}",
        "admission": f"🎓 Admission\n\nOfficial Admission: {UNIRAJ_ADMISSION}",
        "dates": "📅 Dates\n\nCourse/semester और किस date की जरूरत है, लिखें।",
        "fee": "💰 Fee\n\nCourse + semester बताकर fee पूछें।",
        "marks": "📊 Marks\n\nCourse/semester और marks से जुड़ा सवाल भेजें।",
        "semester": "🗓 Semester Hub\n\nCourse + semester लिखें। मैं official syllabus और study help दूँगा।",
        "timetable": "🕐 Time Table\n\nCourse + semester और exam/class timetable बताएं।",
        "notifications": f"🔔 Notifications\n\nOfficial notices: {UNIRAJ_NOTICES}",
        "ask": "🤖 Ask Uniraj AI\n\nअपना सवाल सीधे भेजें।",
        "help": "ℹ️ Help\n\nउदाहरण: 'BSc 3rd semester Maths syllabus PDF भेजो'।",
        "official": f"🔗 Official Sources\n\nUniraj: {UNIRAJ_HOME}\nSyllabus: {UNIRAJ_SYLLABUS}\nResult: {UNIRAJ_RESULT}\nAdmission: {UNIRAJ_ADMISSION}",
    }
    return canned.get(data, "अपना सवाल भेजें।")


def configure_webhook():
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        return
    try:
        webhook_url = render_url.rstrip("/") + "/telegram/webhook"
        r = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url}, timeout=15)
        r.raise_for_status()
        logging.info("Telegram webhook configured: %s", webhook_url)
    except Exception:
        logging.exception("Failed to configure Telegram webhook")

configure_webhook()

@app.get("/")
def health():
    provider = "Replit-style OpenAI-compatible" if OPENAI_API_KEY and OPENAI_BASE_URL else ("Gemini REST" if GEMINI_API_KEY else "none")
    model = OPENAI_MODEL if OPENAI_API_KEY and OPENAI_BASE_URL else GEMINI_MODEL
    return jsonify({"ok": True, "service": "Uniraj Information Section", "status": "running", "ai": provider, "model": model, "official_web_lookup": True, "build": "2026-09-10-official-uniraj-web-lookup"})

@app.post("/telegram/webhook")
def webhook():
    update = request.get_json(silent=True) or {}
    try:
        if "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            data = cb.get("data", "")
            USER_CONTEXT[chat_id] = data
            send_message(chat_id, answer_callback(data))
            try:
                requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cb["id"]}, timeout=10)
            except Exception:
                pass
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
            USER_HISTORY.pop(chat_id, None)
            welcome = f"🎓 Uniraj Information Section में आपका स्वागत है!\n\n📚 Rajasthan University की पढ़ाई, syllabus, exam, result, admission और updates के लिए अपना सवाल भेजें।\n\n📝 Free Guess Papers: {GUESS_1}\n📢 Guess Papers: {GUESS_2}\n\n⚡ Powered by KESHAV MADHAV"
            send_message(chat_id, welcome, menu_keyboard())
            return jsonify({"ok": True})

        try:
            requests.post(f"{TELEGRAM_API}/sendChatAction", json={"chat_id": chat_id, "action": "typing"}, timeout=5)
        except Exception:
            pass

        try:
            reply = ai_reply(text, chat_id, USER_CONTEXT.get(chat_id, ""))
            USER_HISTORY.setdefault(chat_id, []).append(("Student", text))
            USER_HISTORY[chat_id].append(("Assistant", reply))
            USER_HISTORY[chat_id] = USER_HISTORY[chat_id][-MAX_HISTORY:]
        except Exception as exc:
            logging.exception("AI reply failed")
            msg = str(exc)
            if "429" in msg:
                reply = "⏳ AI service पर अभी rate limit/credit limit है। थोड़ी देर बाद फिर कोशिश करें।"
            elif "401" in msg or "403" in msg:
                reply = "❌ AI API key/permission में समस्या है। Render Environment में key और endpoint check करें।"
            else:
                reply = "⚠️ अभी जवाब नहीं मिल पाया। कृपया थोड़ी देर बाद फिर कोशिश करें।"
        send_message(chat_id, reply, menu_keyboard())
        return jsonify({"ok": True})
    except Exception:
        logging.exception("Telegram webhook error")
        return jsonify({"ok": False}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
