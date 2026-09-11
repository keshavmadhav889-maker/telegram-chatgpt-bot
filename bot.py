import os
import time
import logging
import sqlite3
import requests
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

BOT_TOKEN = (os.getenv('TELEGRAM_BOT_TOKEN') or '').strip()
GEMINI_API_KEY = (os.getenv('GEMINI_API_KEY') or '').strip()
GEMINI_MODEL = (os.getenv('GEMINI_MODEL') or 'gemini-3.5-flash-lite').strip()
ADMIN_IDS = {8280167872}
AI_TIMEOUT = 25
MAX_HISTORY = 12
USER_HISTORY = {}
PROMO_EVERY = 5
DB_PATH = (os.getenv('USER_DB_PATH') or '/tmp/users.db').strip()

if not BOT_TOKEN:
    raise RuntimeError('TELEGRAM_BOT_TOKEN missing hai')
if not GEMINI_API_KEY:
    logging.warning('GEMINI_API_KEY missing hai')

TELEGRAM_API = f'https://api.telegram.org/bot{BOT_TOKEN}'

# ================= USER DATABASE =================
def db_connect():
    path = DB_PATH
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(path, timeout=10)
    except (OSError, sqlite3.OperationalError) as exc:
        fallback = '/tmp/users.db'
        logging.warning('Database path unavailable (%s), using %s: %s', path, fallback, exc)
        conn = sqlite3.connect(fallback, timeout=10)
    conn.execute('CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, active INTEGER DEFAULT 1, created_at REAL, last_seen REAL)')
    conn.commit()
    return conn

def register_user(user, chat_id):
    now = time.time()
    try:
        conn = db_connect()
        conn.execute('INSERT INTO users(chat_id, username, first_name, active, created_at, last_seen) VALUES(?,?,?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, active=1, last_seen=excluded.last_seen', (chat_id, user.get('username', ''), user.get('first_name', ''), 1, now, now))
        conn.commit()
        conn.close()
    except Exception:
        logging.exception('User registration failed')

def get_active_users():
    conn = db_connect()
    rows = conn.execute('SELECT chat_id FROM users WHERE active=1').fetchall()
    conn.close()
    return [r[0] for r in rows]

def mark_user_inactive(chat_id):
    try:
        conn = db_connect()
        conn.execute('UPDATE users SET active=0 WHERE chat_id=?', (chat_id,))
        conn.commit()
        conn.close()
    except Exception:
        logging.exception('Could not deactivate user')

def user_count():
    conn = db_connect()
    total = conn.execute('SELECT COUNT(*) FROM users WHERE active=1').fetchone()[0]
    conn.close()
    return total

def total_user_count():
    conn = db_connect()
    total = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    conn.close()
    return total

def user_directory(page=1, per_page=25):
    page = max(1, int(page))
    offset = (page - 1) * per_page
    conn = db_connect()
    rows = conn.execute('SELECT chat_id, username, first_name, active, created_at, last_seen FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?', (per_page, offset)).fetchall()
    conn.close()
    return rows

# ================= UNIRAJ SOURCES =================
UNIRAJ_HOME = 'https://www.uniraj.ac.in/'
UNIRAJ_SYLLABUS = 'https://uniraj.ac.in/index.php?mid=3125'
UNIRAJ_NOTICES = 'https://www.uniraj.ac.in/index.php?mid=196'
UNIRAJ_RESULT = 'https://result.uniraj.ac.in/'
UNIRAJ_ADMISSION = 'https://admissions.uniraj.ac.in/'
GUESS_1 = 'https://t.me/Uniraj_GuessPapers'
GUESS_2 = 'https://t.me/Unirajguesspaper'
RESULT_HELP = 'https://t.me/Unirajresult499'
BSC_MATHS_2025_26_PDF = 'https://uniraj.ac.in/student/syl_N/UP_SYL_2025-26/Maths_UG0803_%28Maths_Group%29%20I%20to%20VI%202025-26%20%20SCiencee.pdf'

SYSTEM_PROMPT = f'''You are Uniraj Information Section, a professional Hindi-first assistant for Rajasthan University students.
Answer in simple Hindi/Hinglish unless English is requested.
Understand spelling mistakes and short student messages.
Use conversation history naturally.
IMPORTANT: For current university information, use only VERIFIED OFFICIAL UNIRAJ SOURCE DATA supplied in the prompt. Never invent dates, marks, notices, syllabus details or results.
IMPORTANT: Give a complete answer to the student question. Do not intentionally shorten or omit useful syllabus, notice, exam, admission or result information merely to respond faster.
IMPORTANT EXAM RULE: If the student uses /exam and then provides a course + semester such as 'BSc 3rd semester', answer the exam question directly. First extract the exact relevant exam date/schedule/status from VERIFIED OFFICIAL UNIRAJ DATA. Do NOT give a general syllabus/result/admission explanation. Do NOT repeat the menu instructions. If the exact date is not present in verified data, say that clearly and provide only the official exam/notice link. Keep exam answers focused, normally within 6-8 lines, while including every verified date/detail that answers the question. When an official PDF or official page is relevant, include its direct official link and summarize the verified relevant data supplied to you.
If official source data is unavailable, clearly say that the official site could not be reached and give the official link instead of guessing.
For personal result questions, give the official result portal and Result Help group; never claim to access private marks.
For guess-paper questions, mention both free guess-paper channels.
Do NOT add any developer credit, Powered by line, KESHAV MADHAV line, signature or footer to normal answers. Developer credit is shown only in the /start welcome message. Only mention the maker if the student specifically asks who made the bot.
Verified sources: University {UNIRAJ_HOME}; Syllabus {UNIRAJ_SYLLABUS}; B.Sc Maths PDF {BSC_MATHS_2025_26_PDF}; Notices {UNIRAJ_NOTICES}; Result {UNIRAJ_RESULT}; Admission {UNIRAJ_ADMISSION}; Guess Papers {GUESS_1} and {GUESS_2}; Result Help {RESULT_HELP}.'''

# ================= TELEGRAM UI =================
MENU_COMMANDS = [('updates', '📢 Uniraj latest updates'), ('exam', '📝 Exam information'), ('result', '🏆 Result portal/help'), ('admission', '🎓 Admission information'), ('syllabus', '📘 Official syllabus'), ('guess', '📚 Free guess papers'), ('ask', '🤖 Ask Uniraj AI'), ('help', 'ℹ️ Help'), ('reset', '♻️ Reset chat memory')]
ADMIN_MENU_COMMANDS = MENU_COMMANDS + [('broadcast', '📢 Send message to all users'), ('users', '👥 User dashboard')]
BROADCAST_WAITING = set()

def send_message(chat_id, text):
    r = requests.post(f'{TELEGRAM_API}/sendMessage', json={'chat_id': chat_id, 'text': str(text)[:4096], 'disable_web_page_preview': False}, timeout=8)
    r.raise_for_status()
    return r.json()

def notify_admin_ai_failure(user_text, chat_id, last_error, tried_models):
    alert = ('🚨 Gemini AI Failure\n\n' + f'👤 Chat ID: {chat_id}\n' + f'❓ Student question:\n{user_text[:2500]}\n\n' + f'🤖 Models tried: {", ".join(tried_models)}\n' + f'⚠️ Error: {str(last_error)[:1200]}')
    for admin_id in ADMIN_IDS:
        try:
            send_message(admin_id, alert)
        except Exception as exc:
            logging.warning('Could not notify admin about AI failure: %s', exc)

def configure_telegram_menu():
    try:
        commands = [{'command': c, 'description': d} for c, d in MENU_COMMANDS]
        requests.post(f'{TELEGRAM_API}/setMyCommands', json={'commands': commands}, timeout=8).raise_for_status()
        admin_commands = [{'command': c, 'description': d} for c, d in ADMIN_MENU_COMMANDS]
        for admin_id in ADMIN_IDS:
            requests.post(f'{TELEGRAM_API}/setMyCommands', json={'commands': admin_commands, 'scope': {'type': 'chat', 'chat_id': admin_id}}, timeout=8).raise_for_status()
        requests.post(f'{TELEGRAM_API}/setChatMenuButton', json={'menu_button': {'type': 'commands'}}, timeout=8).raise_for_status()
        logging.info('Telegram native Menu configured')
    except Exception as exc:
        logging.warning('Telegram Menu setup failed: %s', exc)

# ================= BROADCAST =================
def broadcast_message(text):
    users = get_active_users()
    sent = failed = 0
    for chat_id in users:
        try:
            send_message(chat_id, text)
            sent += 1
            time.sleep(0.04)
        except Exception as exc:
            failed += 1
            logging.warning('Broadcast failed chat_id=%s: %s', chat_id, exc)
            s = str(exc).lower()
            if 'blocked' in s or 'chat not found' in s or 'forbidden' in s:
                mark_user_inactive(chat_id)
    return sent, failed, len(users)

# ================= QUICK REPLIES =================
def quick_reply(text):
    q = text.lower()
    if any(x in q for x in ['guess paper', 'guesspaper', 'guess papers', 'गेस पेपर']):
        return f'📚 Free Uniraj Guess Papers\n\n1️⃣ {GUESS_1}\n2️⃣ {GUESS_2}'
    if any(x in q for x in ['kisne banaya', 'किसने बनाया', 'who made', 'developer', 'owner']):
        return 'यह Uniraj Information Section bot है।'
    if any(x in q for x in ['result', 'रिजल्ट', 'परिणाम']):
        return f'🏆 Uniraj Official Result\n\n{UNIRAJ_RESULT}\n\n🆘 Result Help Group:\n{RESULT_HELP}'
    if any(x in q for x in ['admission', 'प्रवेश']):
        return f'🎓 Uniraj Official Admission\n\n{UNIRAJ_ADMISSION}'
    if any(x in q for x in ['syllabus', 'सिलेबस', 'पाठ्यक्रम']):
        if any(x in q for x in ['math', 'mathematics', 'गणित']):
            return f'📘 B.Sc. Maths Group 2025-26 Official PDF:\n{BSC_MATHS_2025_26_PDF}\n\nOfficial Syllabus Index:\n{UNIRAJ_SYLLABUS}'
        return f'📘 Official Uniraj Syllabus Index:\n{UNIRAJ_SYLLABUS}'
    return None

# ================= OFFICIAL UNIRAJ LOOKUP =================
OFFICIAL_CACHE = {}
CACHE_SECONDS = 300

def fetch_official(url, timeout=6):
    now = time.time()
    cached = OFFICIAL_CACHE.get(url)
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    r = requests.get(url, timeout=timeout, headers={'User-Agent': 'UnirajInformationBot/2.0'})
    r.raise_for_status()
    OFFICIAL_CACHE[url] = (now, r.text)
    return r.text

def official_source_for(text):
    q = text.lower()
    syllabus = any(x in q for x in ['syllabus', 'सिलेबस', 'पाठ्यक्रम'])
    current = any(x in q for x in ['latest', 'today', 'aaj', 'current', 'abhi', 'update', 'notice', 'notification', 'exam date', 'exam dates', 'date', 'timetable', 'exam', 'examination', 'परीक्षा', 'time table', 'last date', 'आज', 'अभी', 'अपडेट', 'नोटिस', 'तिथि', 'अंतिम तिथि'])
    admission = any(x in q for x in ['admission', 'प्रवेश'])
    if syllabus and any(x in q for x in ['math', 'mathematics', 'गणित']):
        return f'VERIFIED OFFICIAL SOURCE:\nB.Sc. Maths Group 2025-26 PDF: {BSC_MATHS_2025_26_PDF}\nSyllabus index: {UNIRAJ_SYLLABUS}'
    if syllabus:
        try:
            soup = BeautifulSoup(fetch_official(UNIRAJ_SYLLABUS), 'html.parser')
            matches = []
            for a in soup.find_all('a', href=True):
                title = ' '.join(a.stripped_strings).strip()
                href = a.get('href', '')
                if title and any(w in (title + ' ' + href).lower() for w in q.split() if len(w) > 2):
                    matches.append(f'- {title}: {href}')
            if matches:
                return 'VERIFIED OFFICIAL UNIRAJ SYLLABUS PAGE DATA:\n' + '\n'.join(matches[:10])
        except Exception as exc:
            logging.info('Official syllabus lookup unavailable: %s', exc)
        return f'OFFICIAL SYLLABUS INDEX: {UNIRAJ_SYLLABUS}\nB.Sc Maths known official PDF: {BSC_MATHS_2025_26_PDF}'
    if current:
        try:
            soup = BeautifulSoup(fetch_official(UNIRAJ_NOTICES), 'html.parser')
            text_data = ' '.join(soup.stripped_strings)
            return f'VERIFIED OFFICIAL UNIRAJ NOTICES PAGE: {UNIRAJ_NOTICES}\nOFFICIAL PAGE TEXT EXCERPT:\n{text_data[:9000]}'
        except Exception as exc:
            logging.info('Official notices lookup unavailable: %s', exc)
            return f'OFFICIAL UNIRAJ NOTICES: {UNIRAJ_NOTICES}\nThe official website is temporarily slow/unavailable. Do not guess current information.'
    if admission:
        return f'VERIFIED OFFICIAL ADMISSION PORTAL: {UNIRAJ_ADMISSION}'
    return ''

# ================= GEMINI =================
def make_prompt(user_text, chat_id, official_data=''):
    parts = [f'SYSTEM: {SYSTEM_PROMPT}']
    if official_data:
        parts.append('VERIFIED OFFICIAL UNIRAJ DATA:\n' + official_data)
    for role, msg in USER_HISTORY.get(chat_id, [])[-MAX_HISTORY:]:
        parts.append(f'{role.upper()}: {msg}')
    parts.append(f'STUDENT: {user_text}')
    return '\n\n'.join(parts)

def request_gemini(user_text, chat_id, model, official_data=''):
    if not GEMINI_API_KEY:
        raise RuntimeError('Gemini unavailable')
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    payload = {'contents': [{'role': 'user', 'parts': [{'text': make_prompt(user_text, chat_id, official_data)}]}], 'generationConfig': {'maxOutputTokens': 1800, 'temperature': 0.2}}
    r = requests.post(url, headers={'x-goog-api-key': GEMINI_API_KEY, 'Content-Type': 'application/json'}, json=payload, timeout=AI_TIMEOUT)
    if not r.ok:
        raise RuntimeError(f'Gemini {model} HTTP {r.status_code}: {r.text[:500]}')
    data = r.json()
    candidates = data.get('candidates', [])
    parts = candidates[0].get('content', {}).get('parts', []) if candidates else []
    answer = ''.join(p.get('text', '') for p in parts if p.get('text')).strip()
    if not answer:
        raise RuntimeError('Empty Gemini response')
    return answer

def is_transient(exc):
    return any(f'HTTP {code}' in str(exc) for code in [408, 429, 500, 502, 503, 504]) or 'timed out' in str(exc).lower() or 'timeout' in str(exc).lower()

def model_candidates():
    candidates = []
    for model in [GEMINI_MODEL, 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite']:
        if model == 'gemini-2.5-flash-lite':
            logging.warning('Skipping retired Gemini model: %s', model)
            continue
        if model and model not in candidates:
            candidates.append(model)
    return candidates

def ai_reply(user_text, chat_id):
    quick = quick_reply(user_text)
    if quick:
        return quick
    official_data = official_source_for(user_text)
    exam_context = any(x in user_text.lower() for x in ['exam', 'परीक्षा', 'exam date', 'exam dates']) or any('exam' in str(msg).lower() for role, msg in USER_HISTORY.get(chat_id, [])[-4:])
    if exam_context and 'VERIFIED OFFICIAL UNIRAJ NOTICES PAGE' not in official_data and 'OFFICIAL UNIRAJ NOTICES' not in official_data:
        official_data = official_source_for(user_text + ' exam')
    models = [GEMINI_MODEL]
    if "gemini-3.1-flash-lite" not in models:
        models.append("gemini-3.1-flash-lite")
    last_error = None
    for model in models:
        for delay in [0.0, 0.5]:
            if delay:
                time.sleep(delay)
            try:
                answer = request_gemini(user_text, chat_id, model, official_data)
                logging.info("Gemini success model=%s", model)
                return answer
            except Exception as exc:
                last_error = exc
                logging.warning("Gemini request failed model=%s: %s", model, exc)
                if not is_transient(exc):
                    break
    logging.error("AI unavailable after failover: %s", last_error)
    notify_admin_ai_failure(user_text, chat_id, last_error, models)
    return "अभी जवाब तैयार करने में थोड़ी तकनीकी देरी हो रही है। कृपया कुछ सेकंड बाद अपना सवाल फिर भेजें।"

# ================= INDIRECT CHANNEL PROMOTION =================
def maybe_add_promotion(chat_id, reply):
    count = len(USER_HISTORY.get(chat_id, [])) // 2
    if count > 0 and count % PROMO_EVERY == 0:
        return reply + f'\n\n📚 Free Study Material: {GUESS_1}\n📖 Guess Papers: {GUESS_2}'
    return reply

# ================= ADMIN USER DASHBOARD =================
def format_time(ts):
    if not ts:
        return '-'
    try:
        return time.strftime('%d-%m-%Y %H:%M', time.localtime(ts))
    except Exception:
        return '-'

def send_user_dashboard(chat_id, page=1):
    try:
        total = total_user_count()
        active = user_count()
        per_page = 25
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(max(1, page), total_pages)
        rows = user_directory(page, per_page)
    except Exception as exc:
        logging.exception('User dashboard failed')
        send_message(chat_id, '📊 ADMIN USER DASHBOARD\n\nDatabase अभी उपलब्ध नहीं है। Bot के database connection को check किया जा रहा है।')
        return
    lines = ['📊 ADMIN USER DASHBOARD', '', f'👥 Total students started: {total}', f'🟢 Currently active records: {active}', f'📄 Page: {page}/{total_pages}', '', '👤 Recent students:']
    if not rows:
        lines.append('अभी कोई student record नहीं है।')
    else:
        start_no = (page - 1) * per_page + 1
        for i, (chat_id_value, username, first_name, active_flag, created_at, last_seen) in enumerate(rows, start_no):
            display_name = first_name or 'No name'
            username_text = f'@{username}' if username else 'username नहीं है'
            status = '🟢' if active_flag else '⚪'
            lines.append(f'{i}. {status} {display_name} — {username_text}\n   ID: {chat_id_value} | Last: {format_time(last_seen)}')
    if page < total_pages:
        lines.append(f'\n➡️ अगला page: /users {page + 1}')
    if page > 1:
        lines.append(f'⬅️ पिछला page: /users {page - 1}')
    send_message(chat_id, '\n'.join(lines))

# ================= WEBHOOK =================
def configure_webhook():
    render_url = os.getenv('RENDER_EXTERNAL_URL')
    if not render_url:
        return
    try:
        webhook_url = render_url.rstrip('/') + '/telegram/webhook'
        requests.post(f'{TELEGRAM_API}/setWebhook', json={'url': webhook_url}, timeout=8).raise_for_status()
        logging.info('Telegram webhook configured: %s', webhook_url)
    except Exception as exc:
        logging.warning('Webhook setup failed: %s', exc)

configure_webhook()
configure_telegram_menu()

# ================= COMMAND HANDLER =================
def command_reply(command, chat_id):
    answers = {'updates': f'📢 Uniraj Official Notices:\n{UNIRAJ_NOTICES}\n\nCurrent information के लिए अपना course/semester लिखें.', 'exam': '📝 Exam\n\nअपना course + semester लिखें, जैसे: BSc 3rd semester exam dates', 'result': f'🏆 Official Result:\n{UNIRAJ_RESULT}\n\n🆘 Result Help Group:\n{RESULT_HELP}', 'admission': f'🎓 Official Admission:\n{UNIRAJ_ADMISSION}', 'syllabus': f'📘 Official Syllabus Index:\n{UNIRAJ_SYLLABUS}\n\nB.Sc. Maths Group 2025-26 PDF:\n{BSC_MATHS_2025_26_PDF}', 'guess': f'📚 Free Uniraj Guess Papers:\n1️⃣ {GUESS_1}\n2️⃣ {GUESS_2}', 'ask': '🤖 अपना Uniraj सवाल सीधे message में भेजें।', 'help': 'ℹ️ Menu से Exam, Result, Admission, Syllabus, Guess Papers या AI चुन सकते हैं। या सवाल सीधे लिखें।'}
    if command == 'reset':
        USER_HISTORY.pop(chat_id, None)
        return '♻️ आपकी recent chat memory reset कर दी गई है।'
    return answers.get(command, 'अपना सवाल सीधे लिखें।')

# ================= ROUTES =================
@app.get('/')
def health():
    return jsonify({'ok': True, 'service': 'Uniraj Information Section', 'status': 'running', 'ai': 'Gemini', 'model': GEMINI_MODEL, 'telegram_menu': True, 'official_uniraj_lookup': True, 'admin_user_dashboard': True, 'build': '2026-09-11-db-dashboard-branding-fix'})

@app.post('/telegram/webhook')
def telegram_webhook():
    try:
        update = request.get_json(silent=True) or {}
        message = update.get('message')
        if not message:
            return jsonify({'ok': True})
        user = message.get('from', {})
        if user.get('is_bot'):
            return jsonify({'ok': True})
        chat_id = message.get('chat', {}).get('id')
        text = (message.get('text') or '').strip()
        if not chat_id or not text:
            return jsonify({'ok': True})
        register_user(user, chat_id)
        if text.startswith('/start'):
            USER_HISTORY.pop(chat_id, None)
            send_message(chat_id, '🎓 Uniraj Information Section में आपका स्वागत है!\n\nRajasthan University से जुड़े syllabus, exam, result, admission, notices और study questions पूछें।\n\n⚡ Powered by KESHAV MADHAV\n\nMenu से सभी options कभी भी खोल सकते हैं।')
            return jsonify({'ok': True})
        if text.startswith('/cancel'):
            if chat_id in ADMIN_IDS:
                BROADCAST_WAITING.discard(chat_id)
                send_message(chat_id, '❌ Broadcast cancel कर दिया गया।')
            return jsonify({'ok': True})
        if text.startswith('/broadcast'):
            if chat_id not in ADMIN_IDS:
                return jsonify({'ok': True})
            BROADCAST_WAITING.add(chat_id)
            send_message(chat_id, f'📢 Broadcast mode ON\n\nयह message सभी active users को भेजा जाएगा।\n👥 Current users: {user_count()}\n\nअब अपना message भेजें।\nCancel के लिए /cancel भेजें।')
            return jsonify({'ok': True})
        if text.startswith('/users'):
            if chat_id in ADMIN_IDS:
                parts = text.split()
                page = 1
                if len(parts) > 1:
                    try:
                        page = max(1, int(parts[1]))
                    except ValueError:
                        page = 1
                send_user_dashboard(chat_id, page)
            return jsonify({'ok': True})
        if chat_id in ADMIN_IDS and chat_id in BROADCAST_WAITING:
            BROADCAST_WAITING.discard(chat_id)
            sent, failed, total = broadcast_message(text)
            send_message(chat_id, f'📢 Broadcast complete\n\n👥 Total: {total}\n✅ Sent: {sent}\n❌ Failed: {failed}')
            return jsonify({'ok': True})
        if text.startswith('/reset'):
            send_message(chat_id, command_reply('reset', chat_id))
            return jsonify({'ok': True})
        if text.startswith('/'):
            command = text.split()[0][1:].split('@')[0].lower()
            if command in {c for c, _ in MENU_COMMANDS}:
                send_message(chat_id, command_reply(command, chat_id))
            return jsonify({'ok': True})
        try:
            requests.post(f'{TELEGRAM_API}/sendChatAction', json={'chat_id': chat_id, 'action': 'typing'}, timeout=3)
        except Exception:
            pass
        reply = ai_reply(text, chat_id)
        USER_HISTORY.setdefault(chat_id, []).append(('Student', text))
        USER_HISTORY.setdefault(chat_id, []).append(('Bot', reply))
        USER_HISTORY[chat_id] = USER_HISTORY[chat_id][-MAX_HISTORY:]
        reply = maybe_add_promotion(chat_id, reply)
        send_message(chat_id, reply)
        return jsonify({'ok': True})
    except Exception:
        logging.exception('Telegram webhook failed')
        return jsonify({'ok': True})

if __name__ == '__main__':
    port = int(os.getenv('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)
