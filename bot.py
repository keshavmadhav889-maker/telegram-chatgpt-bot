import os
import logging
import time
from flask import Flask, request, jsonify
import requests

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-3.8-flash").strip()
GEMINI_FALLBACK_MODELS = [GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-3.6-flash"]

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

USER_CONTEXT = {}
USER_HISTORY = {}
MAX_HISTORY = 12

SYSTEM_PROMPT = """You are Uniraj Information Section, a professional Hindi-first study assistant for Rajasthan University (Uniraj) students.

You must behave like a real conversational assistant, not like a fresh chatbot on every message.
- Understand Hindi, Hinglish, English, spelling mistakes, and short student messages.
- REMEMBER the immediately previous conversation. If you asked the student a clarification question, interpret the student's next reply as the answer to that question.
- NEVER ask again what the student wants when the previous assistant message already asked a specific question and the student answered it.
- Do not restart with an introduction on every message.
- Do not repeat the student's question.
- Give a complete, direct answer.
- If the message is genuinely incomplete and there is no useful context, ask only ONE short clarification question.
- For current/official facts such as result dates, exam dates, fees, notices and syllabus, do not invent information. Use verified official information when available; otherwise clearly say it needs verification.
- For study questions, explain concepts, formulas, notes, important topics and preparation clearly.
- If a student asks for a syllabus, never create a fake syllabus. Only provide verified/current syllabus information or the official PDF when available.
- If a student asks about a personal result, direct them to the official result portal or the configured Result Help service; never fabricate marks or a result.
- If the student is unhappy with an answer, apologize briefly and offer the configured student-help group.
- If asked who made the bot, say it was made/powered by KESHAV MADHAV.
- If asked for guess papers, naturally mention that free guess papers are available through the configured Uniraj Guess Papers channels.
- Keep answers concise but useful, with headings/bullets when helpful.

Official sources:
Uniraj: https://www.uniraj.ac.in/
Result: https://result.uniraj.ac.in/
Admission: https://admissions.uniraj.ac.in/

Do not claim you checked a website unless verified information was actually supplied to you."""


def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": str(text)[:4096], "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def request_gemini(model, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 700},
    }
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

    last_response = None
    for attempt in range(2):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=45)
            last_response = r
        except requests.RequestException as exc:
            logging.exception("Gemini network error model=%s", model)
            if attempt == 0:
                time.sleep(1)
                continue
            raise RuntimeError(f"Gemini network error: {exc}") from exc

        if r.ok:
            break
        if r.status_code in (408, 500, 502, 503, 504) and attempt == 0:
            time.sleep(1)
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
        logging.error("Gemini API error model=%s code=%s status=%s message=%s", model, r.status_code, error_status, error_message)
        raise RuntimeError(f"Gemini API {r.status_code}: {error_message}")

    try:
        data = r.json()
    except ValueError as exc:
        raise RuntimeError("Gemini returned invalid response") from exc

    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no answer")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if p.get("text")).strip()
    if not text:
        raise RuntimeError("Gemini returned empty text")
    return text


def ai_reply(user_text, chat_id, menu_context=""):
    history = USER_HISTORY.get(chat_id, [])
    context_line = f"\n\nRecently selected menu: {menu_context}" if menu_context else ""
    history_text = "".join(f"{role}: {text}\n" for role, text in history[-MAX_HISTORY:])
    prompt = f"""{SYSTEM_PROMPT}{context_line}

Conversation so far:
{history_text}
Student's latest message:
{user_text}

Answer the latest message using the conversation context. If the previous assistant asked a question and this message is the student's answer, continue from that exact point. Do not ask 'aapko kya chahiye?' again unless the student's latest message is actually unrelated or incomplete."""

    last_error = None
    seen = set()
    for model in GEMINI_FALLBACK_MODELS:
        if not model or model in seen:
            continue
        seen.add(model)
        try:
            return request_gemini(model, prompt)
        except RuntimeError as exc:
            last_error = exc
            if " 429:" in str(exc):
                logging.warning("Quota/rate limit on %s; trying fallback model", model)
                continue
            raise
    raise last_error or RuntimeError("Gemini request failed")


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
        "today": "📌 आज के अपडेट\n\nअपना course/semester लिखकर पूछें। मैं उपलब्ध जानकारी के आधार पर मदद करूँगा।",
        "updates": "📢 All Updates\n\nExam, Result, Admission, Circular, Form, Reval और अन्य विश्वविद्यालय अपडेट के बारे में पूछें।",
        "exam": "📝 Exam\n\nआपका course और semester बताइए। फिर exam से जुड़ी जानकारी पूछें।",
        "result": "🏆 Result\n\nअपना course + semester बताइए। अगर personal result देखना है तो Roll Number और DOB वाले Result Help विकल्प का उपयोग करें।",
        "admission": "🎓 Admission\n\nCourse और session बताइए, फिर admission से जुड़ा सवाल पूछें।",
        "dates": "📅 Dates\n\nCourse + semester और किस चीज की date चाहिए, इतना लिखें।",
        "fee": "💰 Fee\n\nCourse + semester बताइए और fee से जुड़ा सवाल पूछें।",
        "marks": "📊 Marks\n\nCourse/semester और marks से जुड़ा सवाल भेजें।",
        "semester": "🗓 Semester Hub\n\nCourse + semester लिखें। मैं syllabus, topics, notes और preparation में मदद करूँगा।",
        "timetable": "🕐 Time Table\n\nCourse + semester लिखें और बताएं कि exam या class timetable चाहिए।",
        "notifications": "🔔 Notifications\n\nमहत्वपूर्ण Uniraj updates के लिए bot में अपना सवाल भेजें।",
        "ask": "🤖 Ask Uniraj AI\n\nअपना सवाल सीधे भेजें। मैं बातचीत का context याद रखकर जवाब दूँगा।",
        "help": "ℹ️ Help\n\nउदाहरण: 'BSc 2nd semester Maths syllabus बताओ' या 'मेरी पिछली बात के अनुसार exam date बताओ।'",
        "official": "🔗 Official Sources\n\nUniraj: https://www.uniraj.ac.in/\nResult: https://result.uniraj.ac.in/\nAdmission: https://admissions.uniraj.ac.in/",
    }
    return canned.get(data, "अपना सवाल भेजें।")


def configure_webhook():
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        return
    webhook_url = render_url.rstrip("/") + "/telegram/webhook"
    try:
        r = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url}, timeout=15)
        r.raise_for_status()
    except Exception:
        logging.exception("Failed to configure Telegram webhook")


configure_webhook()


@app.get("/")
def health():
    return jsonify({"ok": True, "service": "Uniraj Information Section", "status": "running", "ai": "Gemini REST", "model": GEMINI_MODEL, "fallbacks": GEMINI_FALLBACK_MODELS, "build": "2026-09-10-quota-fallback-fix"})


@app.post("/telegram/webhook")
def webhook():
    update = request.get_json(silent=True) or {}
    try:
        if "callback_query" in update:
            cb = update["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            data = cb.get("data", "")
            USER_CONTEXT[chat_id] = data
            if data in ("result", "exam", "admission", "dates", "fee", "marks", "semester", "timetable", "today", "updates", "ask"):
                USER_HISTORY[chat_id] = []
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
            welcome = "🎓 Uniraj Information Section में आपका स्वागत है!\n\n📚 Rajasthan University की पढ़ाई, syllabus, exam, result, admission और updates के लिए अपना सवाल भेजें।\n\n⚡ Powered by KESHAV MADHAV"
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
        except Exception as ai_error:
            logging.exception("AI reply failed")
            error_text = str(ai_error)
            if " 401:" in error_text:
                reply = "❌ Gemini API key invalid/expired है। Render में GEMINI_API_KEY check करें।"
            elif " 403:" in error_text:
                reply = "❌ Gemini API key को इस API/model की permission नहीं मिल रही। Google AI Studio की key और Render environment variable check करें।"
            elif " 429:" in error_text:
                reply = "⏳ Gemini की सभी configured models पर अभी quota/rate limit लगी हुई है। Google AI Studio में इसी project की quota देखें और थोड़ी देर बाद फिर कोशिश करें।"
            elif " 404:" in error_text:
                reply = "❌ Gemini model उपलब्ध नहीं मिला। Render को latest GitHub commit पर redeploy करें।"
            else:
                reply = "❌ अभी जवाब देने में तकनीकी समस्या आ रही है। थोड़ी देर बाद फिर कोशिश करें।"

        send_message(chat_id, reply)
        return jsonify({"ok": True})
    except Exception:
        logging.exception("Telegram webhook error")
        return jsonify({"ok": False}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
