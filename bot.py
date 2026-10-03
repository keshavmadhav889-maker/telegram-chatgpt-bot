import os
import time
import logging
import sqlite3
import requests
import threading
import hashlib
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
from urllib.parse import urljoin

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
IMPORTANT: For current university information, use only VERIFIED OFFICIAL UNIRAJ SOURCE DATA supplied in the prompt. Never invent dates, marks, notices, syllabus details or results.\nIMPORTANT: Give a complete answer to the student question. Do not intentionally shorten or omit useful syllabus, notice, exam, admission or result information merely to respond faster. When an official PDF or official page is relevant, include its direct official link and summarize the verified relevant data supplied to you.
IMPORTANT: Give a complete answer to the student question. Do not intentionally shorten or omit useful syllabus, notice, exam, admission or result information merely to respond faster.
IMPORTANT EXAM RULE: If the student uses /exam and then provides a course + semester such as 'BSc 3rd semester', answer the exam question directly. First extract the exact relevant exam date/schedule/status from VERIFIED OFFICIAL UNIRAJ DATA. Do NOT give a general syllabus/result/admission explanation. Do NOT repeat the menu instructions. If the exact date is not present in verified data, say that clearly and provide only the official exam/notice link. Keep exam answers focused, normally within 6-8 lines, while including every verified date/detail that answers the question. When an official PDF or official page is relevant, include its direct official link and summarize the verified relevant data supplied to you.
If official source data is unavailable, clearly say that the official site could not be reached and give the official link instead of guessing.
For personal result questions, give the official result portal and Result Help group; never claim to access private marks.
For guess-paper questions, mention both free guess-paper channels.
Do NOT add any developer credit, Powered by line, KESHAV MADHAV line, signature or footer to normal answers. Developer credit is shown only in the /start welcome message. Only mention the maker if the student specifically asks who made the bot.
Verified sources: University {UNIRAJ_HOME}; Syllabus {UNIRAJ_SYLLABUS}; B.Sc Maths PDF {BSC_MATHS_2025_26_PDF}; Notices {UNIRAJ_NOTICES}; Result {UNIRAJ_RESULT}; Admission {UNIRAJ_ADMISSION}; Guess Papers {GUESS_1} and {GUESS_2}; Result Help {RESULT_HELP}.'''

# ================= TELEGRAM UI =================
MENU_COMMANDS = [('updates', '📢 Uniraj latest updates'), ('exam', '📝 Exam information'), ('result', '🏆 Result portal/help'), ('admission', '🎓 Admission information'), ('syllabus', '📘 Official syllabus'), ('guess', '📚 Free guess papers'), ('ask', '🤖 Ask Uniraj AI'), ('help', 'ℹ️ Help'), ('reset', '♻️ Reset chat memory')]
ADMIN_MENU_COMMANDS = MENU_COMMANDS + [('broadcast', '📢 Send message to all users'), ('users', '👥 User dashboard'), ('sync_syllabus', '📥 Sync all syllabus PDFs')]
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
        # Remove stale command scopes left by the old Notes Store bot.
        for scope in [
            {'type': 'default'},
            {'type': 'all_private_chats'},
            {'type': 'all_group_chats'},
            {'type': 'all_chat_administrators'},
        ]:
            try:
                requests.post(f'{TELEGRAM_API}/deleteMyCommands', json={'scope': scope}, timeout=8).raise_for_status()
            except Exception:
                logging.exception('Could not clear Telegram command scope: %s', scope)
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
    current = any(x in q for x in ['latest', 'today', 'aaj', 'current', 'abhi', 'update', 'notice', 'notification', 'exam date', 'exam dates', 'date', 'timetable', 'exam', 'examination', 'परीक्षा', 'exam', 'examination', 'परीक्षा', 'exam', 'examination', 'परीक्षा', 'exam', 'examination', 'परीक्षा', 'time table', 'last date', 'आज', 'अभी', 'अपडेट', 'नोटिस', 'तिथि', 'अंतिम तिथि'])
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


# ================= PROFESSIONAL SYLLABUS =================
SYLLABUS_SESSIONS = [
    ('ugpg-2021-22', '📚 UG & PG 2021-22 — OFFICIAL 3102', 'https://uniraj.ac.in/index.php?mid=3102'),
    ('pg-2025-27', '📚 PG 2025-27 NEW', 'https://uniraj.ac.in/index.php?mid=3127'),
    ('ug-2025-26', '📚 UG NEP 2025-26 NEW', 'https://uniraj.ac.in/index.php?mid=3125'),
    ('ug-2024-25', '📚 UG NEP 2024-25 NEW', 'https://uniraj.ac.in/index.php?mid=3104'),
    ('ug-2023-24', '📚 UG NEP 2023-24 NEW', 'https://uniraj.ac.in/index.php?mid=3103'),
    ('ugpg-2024-26', '📚 UG & PG 2024-26 NEW', 'https://uniraj.ac.in/index.php?mid=3125'),
    ('ugpg-2023-25', '📚 UG & PG 2023-25', 'https://uniraj.ac.in/index.php?mid=3104'),
    ('ugpg-2022-23', '📚 UG & PG 2022-23', 'https://uniraj.ac.in/index.php?mid=3103'),
]
SYLLABUS_PAGE_SIZE = 8
SYLLABUS_CACHE = {}
SYLLABUS_CACHE_SECONDS = 3000
SYLLABUS_STORE = (os.getenv('SYLLABUS_STORE_DIR') or '/tmp/uniraj_syllabus_pdfs').strip()
SYLLABUS_CATALOG_FILE = os.path.join(SYLLABUS_STORE, 'catalog.json')
SYLLABUS_SYNC_LOCK = threading.Lock()
SYLLABUS_SYNC_STATUS = {'running': False, 'done': 0, 'failed': 0, 'total': 0, 'session': 'all'}
os.makedirs(SYLLABUS_STORE, exist_ok=True)

def syllabus_session_map():
    return {key: (label, url) for key, label, url in SYLLABUS_SESSIONS}

def syllabus_store_path(pdf_url):
    digest = hashlib.sha256(pdf_url.encode('utf-8')).hexdigest()
    return os.path.join(SYLLABUS_STORE, digest + '.pdf')

def load_syllabus_catalog():
    try:
        with open(SYLLABUS_CATALOG_FILE, 'r', encoding='utf-8') as fh:
            data = __import__('json').load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_syllabus_catalog(catalog):
    temp = SYLLABUS_CATALOG_FILE + '.part'
    with open(temp, 'w', encoding='utf-8') as fh:
        __import__('json').dump(catalog, fh, ensure_ascii=False, indent=2)
    os.replace(temp, SYLLABUS_CATALOG_FILE)

def cached_rows_for_url(url):
    rows = load_syllabus_catalog().get(url)
    return rows if isinstance(rows, list) else []

def fetch_official_with_fallback(urls, timeout=18):
    last_error = None
    for url in urls:
        try:
            r = requests.get(url, timeout=timeout, headers={'User-Agent': 'UnirajInformationBot/2.0'})
            r.raise_for_status()
            return r.text
        except Exception as exc:
            last_error = exc
            logging.warning('Official syllabus fetch failed %s: %s', url, exc)
    raise RuntimeError(f'Official syllabus site unavailable: {last_error}')

def parse_syllabus_rows(url):
    now = time.time()
    cached = SYLLABUS_CACHE.get(url)
    if cached and now - cached[0] < SYLLABUS_CACHE_SECONDS:
        return cached[1]
    urls = [url, url.replace('https://', 'https://www.') if 'www.' not in url else url.replace('https://www.', 'https://')]
    try:
        html = fetch_official_with_fallback(urls, timeout=18)
        soup = BeautifulSoup(html, 'html.parser')
        rows, seen = [], set()
        for table in soup.find_all('table'):
            for tr in table.find_all('tr'):
                cells = tr.find_all(['td', 'th'])
                if len(cells) < 3:
                    continue
                values = [' '.join(c.stripped_strings).strip() for c in cells]
                if values[0].lower() in {'s.no.', 's.no', 'no.', 'no'}:
                    continue
                pdf_url = ''
                for a in tr.find_all('a', href=True):
                    href = (a.get('href') or '').strip()
                    absolute = urljoin(url, href)
                    low = absolute.lower()
                    if href and not href.lower().startswith(('javascript:', '#', 'mailto:')) and ('.pdf' in low or 'download' in low):
                        pdf_url = absolute
                        break
                if not pdf_url:
                    continue
                row = {
                    'programme': values[1] if len(values) > 1 else '',
                    'discipline': values[2] if len(values) > 2 else '',
                    'scheme': values[3] if len(values) > 3 else '',
                    'years': values[4] if len(values) > 4 else '',
                    'pdf_url': pdf_url,
                }
                key = (row['programme'], row['discipline'], row['pdf_url'])
                if row['programme'] and key not in seen:
                    seen.add(key)
                    rows.append(row)
        if not rows:
            raise RuntimeError('No downloadable PDF rows found')
        SYLLABUS_CACHE[url] = (now, rows)
        data = load_syllabus_catalog()
        data[url] = rows
        save_syllabus_catalog(data)
        return rows
    except Exception as exc:
        offline_rows = cached_rows_for_url(url)
        if offline_rows:
            logging.warning('Using cached official syllabus catalog for %s: %s', url, exc)
            SYLLABUS_CACHE[url] = (now, offline_rows)
            return offline_rows
        raise

def cache_syllabus_pdf(pdf_url):
    path = syllabus_store_path(pdf_url)
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        return path
    response = requests.get(pdf_url, timeout=45, headers={'User-Agent': 'UnirajInformationBot/2.0'}, stream=True)
    response.raise_for_status()
    total = int(response.headers.get('Content-Length') or 0)
    if total and total > 49 * 1024 * 1024:
        raise RuntimeError('PDF is larger than Telegram upload limit')
    temp = path + '.part'
    size = 0
    try:
        with open(temp, 'wb') as fh:
            for chunk in response.iter_content(1024 * 256):
                if not chunk:
                    continue
                size += len(chunk)
                if size > 49 * 1024 * 1024:
                    raise RuntimeError('PDF is larger than Telegram upload limit')
                fh.write(chunk)
        os.replace(temp, path)
        return path
    finally:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass

def archive_pdf_on_telegram(pdf_path, pdf_url, row):
    admin_chat_id = next(iter(ADMIN_IDS))
    caption = f"📚 Uniraj Syllabus Archive\n🎓 {row.get('programme','')[:220]}\n📖 {row.get('discipline','')[:180]}\n🗓 {row.get('years','') or 'Official'}"
    with open(pdf_path, 'rb') as fh:
        r = requests.post(
            f'{TELEGRAM_API}/sendDocument',
            data={'chat_id': admin_chat_id, 'caption': caption[:1024]},
            files={'document': (os.path.basename(pdf_path), fh, 'application/pdf')},
            timeout=60,
        )
    r.raise_for_status()
    return ((r.json().get('result') or {}).get('document') or {}).get('file_id')

def sync_syllabus_sessions(session_keys=None):
    if not SYLLABUS_SYNC_LOCK.acquire(blocking=False):
        return
    try:
        wanted = set(session_keys or [key for key, _, _ in SYLLABUS_SESSIONS])
        SYLLABUS_SYNC_STATUS.update({'running': True, 'done': 0, 'failed': 0, 'total': 0, 'session': ','.join(sorted(wanted))})
        catalog = load_syllabus_catalog()
        items = []
        for session_key, label, url in SYLLABUS_SESSIONS:
            if session_key not in wanted:
                continue
            try:
                rows = parse_syllabus_rows(url)
                catalog[url] = rows
                for row in rows:
                    items.append((url, row))
            except Exception as exc:
                logging.warning('Could not read syllabus session %s: %s', session_key, exc)
        unique = {}
        for url, row in items:
            unique[row['pdf_url']] = (url, row)
        items = list(unique.values())
        SYLLABUS_SYNC_STATUS['total'] = len(items)
        for url, row in items:
            pdf_url = row['pdf_url']
            try:
                pdf_path = cache_syllabus_pdf(pdf_url)
                file_id = row.get('telegram_file_id')
                if not file_id:
                    try:
                        file_id = archive_pdf_on_telegram(pdf_path, pdf_url, row)
                    except Exception as upload_exc:
                        logging.warning('Telegram archive upload failed: %s', upload_exc)
                if file_id:
                    row['telegram_file_id'] = file_id
                SYLLABUS_SYNC_STATUS['done'] += 1
            except Exception as exc:
                SYLLABUS_SYNC_STATUS['failed'] += 1
                logging.warning('Syllabus PDF sync failed %s: %s', pdf_url, exc)
            try:
                save_syllabus_catalog(catalog)
            except Exception:
                logging.exception('Could not save syllabus catalog')
        logging.info('Syllabus sync finished: %s', SYLLABUS_SYNC_STATUS)
    finally:
        SYLLABUS_SYNC_STATUS['running'] = False
        SYLLABUS_SYNC_LOCK.release()

def sync_all_syllabus_pdfs():
    sync_syllabus_sessions()

def sync_2021_22_syllabus_pdfs():
    sync_syllabus_sessions(['ugpg-2021-22'])

def syllabus_home_keyboard():
    rows = []
    for i in range(0, len(SYLLABUS_SESSIONS), 2):
        pair = SYLLABUS_SESSIONS[i:i+2]
        rows.append([{'text': label, 'callback_data': f'sylsess:{key}'} for key, label, _ in pair])
    rows.append([{'text': '🏠 Home', 'callback_data': 'sylhome'}])
    return {'inline_keyboard': rows}

def syllabus_program_keyboard(session_key, page=1):
    mapping = syllabus_session_map()
    if session_key not in mapping:
        return None, None, 1
    label, url = mapping[session_key]
    rows = parse_syllabus_rows(url)
    total_pages = max(1, (len(rows) + SYLLABUS_PAGE_SIZE - 1) // SYLLABUS_PAGE_SIZE)
    page = min(max(1, page), total_pages)
    start = (page - 1) * SYLLABUS_PAGE_SIZE
    buttons = []
    for idx, row in enumerate(rows[start:start + SYLLABUS_PAGE_SIZE], start + 1):
        title = row['programme']
        if row['discipline'] and row['discipline'].lower() not in title.lower():
            title = f"{title} — {row['discipline']}"
        title = title.replace('&amp;', '&')
        if len(title) > 62:
            title = title[:59] + '...'
        buttons.append([{'text': f'{idx}. {title}', 'callback_data': f'sylpdf:{session_key}:{idx}'}])
    nav = []
    if page > 1:
        nav.append({'text': '⬅️ Previous', 'callback_data': f'sylpage:{session_key}:{page-1}'})
    if page < total_pages:
        nav.append({'text': 'Next ➡️', 'callback_data': f'sylpage:{session_key}:{page+1}'})
    if nav:
        buttons.append(nav)
    buttons.append([{'text': '🔙 Sessions', 'callback_data': 'sylhome'}, {'text': '🏠 Home', 'callback_data': 'home'}])
    return rows, {'inline_keyboard': buttons}, total_pages

def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text}
    if reply_markup is not None:
        payload['reply_markup'] = reply_markup
    r = requests.post(f'{TELEGRAM_API}/editMessageText', json=payload, timeout=8)
    r.raise_for_status()
    return r.json()

def answer_callback(callback_id, text=''):
    try:
        requests.post(f'{TELEGRAM_API}/answerCallbackQuery', json={'callback_query_id': callback_id, 'text': text[:200]}, timeout=5)
    except Exception:
        pass

def send_document_from_url(chat_id, pdf_url, caption, file_id=None):
    if not file_id:
        for rows in load_syllabus_catalog().values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if row.get('pdf_url') == pdf_url and row.get('telegram_file_id'):
                    file_id = row['telegram_file_id']
                    break
            if file_id:
                break
    if file_id:
        r = requests.post(f'{TELEGRAM_API}/sendDocument', json={'chat_id': chat_id, 'document': file_id, 'caption': caption[:1024]}, timeout=20)
        if r.ok:
            return r.json()
    path = cache_syllabus_pdf(pdf_url)
    with open(path, 'rb') as fh:
        r = requests.post(f'{TELEGRAM_API}/sendDocument', data={'chat_id': chat_id, 'caption': caption[:1024]}, files={'document': (os.path.basename(path), fh, 'application/pdf')}, timeout=60)
    r.raise_for_status()
    return r.json()

def syllabus_start(chat_id, message_id=None):
    text = '📘 University of Rajasthan — Official Syllabus\n\n📚 Choose an academic session to continue.\n\n⭐ 2021-22 is the official 3102 archive. PDFs are sent directly inside Telegram.'
    if message_id:
        edit_message(chat_id, message_id, text, syllabus_home_keyboard())
    else:
        send_message_with_markup(chat_id, text, syllabus_home_keyboard())

def send_message_with_markup(chat_id, text, reply_markup):
    r = requests.post(f'{TELEGRAM_API}/sendMessage', json={'chat_id': chat_id, 'text': text, 'reply_markup': reply_markup, 'disable_web_page_preview': True}, timeout=8)
    r.raise_for_status()
    return r.json()

def syllabus_session(chat_id, message_id, session_key):
    mapping = syllabus_session_map()
    if session_key not in mapping:
        answer_callback('', 'Session unavailable')
        return
    label, url = mapping[session_key]
    try:
        rows, markup, total_pages = syllabus_program_keyboard(session_key, 1)
        if not rows:
            text = f'📘 University of Rajasthan — Syllabus\n\n{label}\n\n⚠️ इस session में अभी कोई downloadable syllabus entry नहीं मिली।\n\n🔄 बाद में फिर कोशिश करें।'
        else:
            text = f'📘 University of Rajasthan — Syllabus\n\n{label}\n\n📚 Records: {len(rows)} • Page 1/{total_pages}\n\nनीचे programme / discipline चुनें।'
        edit_message(chat_id, message_id, text, markup)
    except Exception as exc:
        logging.warning('Syllabus session failed %s: %s', session_key, exc)
        edit_message(chat_id, message_id, f'📘 University of Rajasthan — Syllabus\n\n{label}\n\n⚠️ Official syllabus list अभी load नहीं हो सकी। कृपया थोड़ी देर बाद फिर कोशिश करें.', syllabus_home_keyboard())

def syllabus_page(chat_id, message_id, session_key, page):
    mapping = syllabus_session_map()
    if session_key not in mapping:
        return
    label, _ = mapping[session_key]
    try:
        rows, markup, total_pages = syllabus_program_keyboard(session_key, page)
        text = f'📘 University of Rajasthan — Syllabus\n\n{label}\n\n📚 Records: {len(rows)} • Page {page}/{total_pages}\n\nनीचे programme / discipline चुनें।'
        edit_message(chat_id, message_id, text, markup)
    except Exception as exc:
        logging.warning('Syllabus page failed: %s', exc)

def syllabus_send_pdf(chat_id, message_id, session_key, index):
    mapping = syllabus_session_map()
    if session_key not in mapping:
        return
    label, _ = mapping[session_key]
    try:
        rows = parse_syllabus_rows(mapping[session_key][1])
        idx = int(index) - 1
        if idx < 0 or idx >= len(rows):
            send_message(chat_id, '⚠️ यह syllabus entry उपलब्ध नहीं है।')
            return
        row = rows[idx]
        caption = (
            '📘 University of Rajasthan — Official Syllabus\n\n'
            f"🎓 Programme: {row.get('programme','')[:300]}\n"
            f"📖 Discipline: {row.get('discipline','')[:200]}\n"
            f"🗓 Session: {row.get('years') or label}\n\n"
            '✅ Official syllabus PDF\n'
            '📄 Telegram में सीधे खोलें।\n\n'
            '⚡ Uniraj Information Section'
        )
        try:
            edit_message(chat_id, message_id, '📥 Official syllabus PDF तैयार किया जा रहा है...\n\n⏳ कृपया एक क्षण प्रतीक्षा करें।')
        except Exception:
            pass
        send_document_from_url(chat_id, row['pdf_url'], caption, row.get('telegram_file_id'))
        send_message_with_markup(chat_id, '📚 अगला syllabus चुनें या वापस Sessions पर जाएँ।', {'inline_keyboard': [[{'text': '🔙 Sessions', 'callback_data': 'sylhome'}, {'text': '🏠 Home', 'callback_data': 'home'}]]})
    except Exception:
        logging.exception('Syllabus PDF send failed')
        try:
            edit_message(chat_id, message_id, '❌ Official PDF भेजने में अभी समस्या आ गई। कृपया थोड़ी देर बाद फिर कोशिश करें।', syllabus_home_keyboard())
        except Exception:
            pass

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
        for delay in [0.0, 0.8, 1.8, 3.5]:
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
        if update.get('callback_query'):
            handle_callback(update)
            return jsonify({'ok': True})
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
        if text.startswith('/sync_syllabus'):
            if chat_id not in ADMIN_IDS:
                return jsonify({'ok': True})
            if SYLLABUS_SYNC_STATUS.get('running'):
                send_message(chat_id, f"📥 Syllabus sync चल रही है.\nDone: {SYLLABUS_SYNC_STATUS.get('done', 0)}\nFailed: {SYLLABUS_SYNC_STATUS.get('failed', 0)}\nTotal: {SYLLABUS_SYNC_STATUS.get('total', 0)}")
            else:
                threading.Thread(target=sync_all_syllabus_pdfs, daemon=True).start()
                send_message(chat_id, '📥 Official syllabus sync शुरू कर दी गई है.\n\nसभी available syllabus PDFs local cache में download होंगे.')
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
            if command == 'sync_syllabus':
                if chat_id in ADMIN_IDS:
                    if not SYLLABUS_SYNC_STATUS.get('running'):
                        threading.Thread(target=sync_all_syllabus_pdfs, daemon=True).start()
                        send_message(chat_id, '📥 Official syllabus sync शुरू कर दी गई है.')
                    else:
                        send_message(chat_id, f"📥 Sync चल रही है — {SYLLABUS_SYNC_STATUS.get('done', 0)}/{SYLLABUS_SYNC_STATUS.get('total', 0)}")
            elif command in {c for c, _ in MENU_COMMANDS}:
                if command == 'syllabus':
                    syllabus_start(chat_id)
                else:
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
