import os
import time
import logging
import sqlite3
import requests
import psycopg2
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
BOT_TOKEN=(os.getenv('TELEGRAM_BOT_TOKEN') or '').strip()
GEMINI_API_KEY=(os.getenv('GEMINI_API_KEY') or '').strip()
GEMINI_MODEL=(os.getenv('GEMINI_MODEL') or 'gemini-3.5-flash-lite').strip()
DATABASE_URL=(os.getenv('DATABASE_URL') or '').strip()
ADMIN_IDS={8280167872}
AI_TIMEOUT=18
MAX_HISTORY=20
PROMO_EVERY=5
DB_PATH=(os.getenv('USER_DB_PATH') or '/tmp/users.db').strip()
if not BOT_TOKEN: raise RuntimeError('TELEGRAM_BOT_TOKEN missing hai')
if not GEMINI_API_KEY: logging.warning('GEMINI_API_KEY missing hai')
if DATABASE_URL: logging.info('Persistent PostgreSQL database configured')
else: logging.warning('DATABASE_URL missing: using temporary SQLite memory')
TELEGRAM_API=f'https://api.telegram.org/bot{BOT_TOKEN}'

class PGConnection:
    def __init__(self,url): self.conn=psycopg2.connect(url,connect_timeout=8)
    def execute(self,sql,params=()):
        cur=self.conn.cursor(); cur.execute(sql.replace('?','%s'),params); return cur
    def commit(self): self.conn.commit()
    def close(self): self.conn.close()

def db_connect():
    if DATABASE_URL:
        try:
            conn=PGConnection(DATABASE_URL)
            conn.execute('CREATE TABLE IF NOT EXISTS users (chat_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, active INTEGER DEFAULT 1, created_at DOUBLE PRECISION, last_seen DOUBLE PRECISION)')
            conn.execute('CREATE TABLE IF NOT EXISTS conversation_history (id BIGSERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, role TEXT NOT NULL, message TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_history_chat_id_id ON conversation_history(chat_id,id)')
            conn.commit(); return conn
        except Exception: logging.exception('PostgreSQL unavailable; using temporary SQLite')
    try:
        parent=os.path.dirname(DB_PATH)
        if parent: os.makedirs(parent,exist_ok=True)
        conn=sqlite3.connect(DB_PATH,timeout=10)
    except Exception: conn=sqlite3.connect('/tmp/users.db',timeout=10)
    conn.execute('CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, active INTEGER DEFAULT 1, created_at REAL, last_seen REAL)')
    conn.execute('CREATE TABLE IF NOT EXISTS conversation_history (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, role TEXT NOT NULL, message TEXT NOT NULL, created_at REAL NOT NULL)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_history_chat_id_id ON conversation_history(chat_id,id)')
    conn.commit(); return conn

def register_user(user,chat_id):
    try:
        now=time.time(); conn=db_connect()
        conn.execute('INSERT INTO users(chat_id,username,first_name,active,created_at,last_seen) VALUES(?,?,?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,active=1,last_seen=excluded.last_seen',(chat_id,user.get('username',''),user.get('first_name',''),1,now,now)); conn.commit(); conn.close()
    except Exception: logging.exception('User registration failed')

def save_message(chat_id,role,message):
    try:
        conn=db_connect(); conn.execute('INSERT INTO conversation_history(chat_id,role,message,created_at) VALUES(?,?,?,?)',(chat_id,role,str(message),time.time())); conn.commit(); conn.close()
    except Exception: logging.exception('Conversation memory save failed')

def save_turn(chat_id,user_text,bot_text): save_message(chat_id,'Student',user_text); save_message(chat_id,'Bot',bot_text)

def load_history(chat_id,limit=MAX_HISTORY):
    try:
        conn=db_connect(); rows=conn.execute('SELECT role,message FROM conversation_history WHERE chat_id=? ORDER BY id DESC LIMIT ?',(chat_id,limit)).fetchall(); conn.close(); return list(reversed(rows))
    except Exception: logging.exception('Conversation memory load failed'); return []

def conversation_count(chat_id):
    try:
        conn=db_connect(); n=conn.execute("SELECT COUNT(*) FROM conversation_history WHERE chat_id=? AND role='Student'",(chat_id,)).fetchone()[0]; conn.close(); return n
    except Exception: return 0

def reset_history(chat_id):
    try:
        conn=db_connect(); conn.execute('DELETE FROM conversation_history WHERE chat_id=?',(chat_id,)); conn.commit(); conn.close()
    except Exception: logging.exception('Conversation reset failed')

def get_active_users():
    conn=db_connect(); rows=conn.execute('SELECT chat_id FROM users WHERE active=1').fetchall(); conn.close(); return [r[0] for r in rows]

def mark_user_inactive(chat_id):
    try:
        conn=db_connect(); conn.execute('UPDATE users SET active=0 WHERE chat_id=?',(chat_id,)); conn.commit(); conn.close()
    except Exception: logging.exception('Could not deactivate user')

def user_count():
    conn=db_connect(); n=conn.execute('SELECT COUNT(*) FROM users WHERE active=1').fetchone()[0]; conn.close(); return n

def total_user_count():
    conn=db_connect(); n=conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]; conn.close(); return n

def user_directory(page=1,per_page=25):
    page=max(1,int(page)); offset=(page-1)*per_page; conn=db_connect(); rows=conn.execute('SELECT chat_id,username,first_name,active,created_at,last_seen FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?',(per_page,offset)).fetchall(); conn.close(); return rows

UNIRAJ_HOME='https://www.uniraj.ac.in/'
UNIRAJ_SYLLABUS='https://uniraj.ac.in/index.php?mid=3125'
UNIRAJ_NOTICES='https://www.uniraj.ac.in/index.php?mid=196'
UNIRAJ_RESULT='https://result.uniraj.ac.in/'
UNIRAJ_ADMISSION='https://admissions.uniraj.ac.in/'
GUESS_1='https://t.me/Uniraj_GuessPapers'
GUESS_2='https://t.me/Unirajguesspaper'
RESULT_HELP='https://t.me/Unirajresult499'
BSC_MATHS_2025_26_PDF='https://uniraj.ac.in/student/syl_N/UP_SYL_2025-26/Maths_UG0803_%28Maths_Group%29%20I%20to%20VI%202025-26%20%20SCiencee.pdf'
SYSTEM_PROMPT=f'''You are Uniraj Information Section, a professional Hindi-first assistant for Rajasthan University students.
Answer ONLY the student's latest question. Never dump unrelated information or repeat menu instructions.
Understand spelling mistakes, short messages and follow-up messages. Use SAVED CONVERSATION HISTORY to resolve what words like 'haan', 'iska', 'uska', 'kab', 'kitne', 'phir' and 'aur batao' refer to.
For current university information, use only VERIFIED OFFICIAL UNIRAJ SOURCE DATA. Never invent dates, marks, notices, syllabus details or results.
For exam/current questions, give only the relevant verified answer. Do not add syllabus/result/admission/guess-paper sections unless asked.
For study questions, directly solve or explain what was asked.
Be complete but remove filler, repeated introductions and unrelated links.
If an official PDF/page is relevant, include the direct official link and relevant verified information.
If official data is unavailable, say so and provide the relevant official link instead of guessing.
Do NOT add KESHAV MADHAV or Powered by text to normal answers; that credit appears only in /start.
Verified sources: {UNIRAJ_HOME}; syllabus {UNIRAJ_SYLLABUS}; B.Sc Maths PDF {BSC_MATHS_2025_26_PDF}; notices {UNIRAJ_NOTICES}; result {UNIRAJ_RESULT}; admission {UNIRAJ_ADMISSION}; guess papers {GUESS_1}, {GUESS_2}; result help {RESULT_HELP}.'''
MENU_COMMANDS=[('updates','📢 Uniraj latest updates'),('exam','📝 Exam information'),('result','🏆 Result portal/help'),('admission','🎓 Admission information'),('syllabus','📘 Official syllabus'),('guess','📚 Free guess papers'),('ask','🤖 Ask Uniraj AI'),('help','ℹ️ Help'),('reset','♻️ Reset chat memory')]
ADMIN_MENU_COMMANDS=MENU_COMMANDS+[('broadcast','📢 Send message to all users'),('users','👥 User dashboard')]
BROADCAST_WAITING=set()

def send_message(chat_id,text):
    r=requests.post(f'{TELEGRAM_API}/sendMessage',json={'chat_id':chat_id,'text':str(text)[:4096],'disable_web_page_preview':False},timeout=8); r.raise_for_status(); return r.json()

def notify_admin_ai_failure(user_text,chat_id,last_error,tried_models):
    alert='🚨 Gemini AI Failure\n\n'+f'👤 Chat ID: {chat_id}\n❓ Student question:\n{user_text[:2500]}\n\n🤖 Models tried: {", ".join(tried_models)}\n⚠️ Error: {str(last_error)[:1200]}'
    for admin_id in ADMIN_IDS:
        try: send_message(admin_id,alert)
        except Exception: pass

def configure_telegram_menu():
    try:
        requests.post(f'{TELEGRAM_API}/setMyCommands',json={'commands':[{'command':c,'description':d} for c,d in MENU_COMMANDS]},timeout=8).raise_for_status()
        for admin_id in ADMIN_IDS: requests.post(f'{TELEGRAM_API}/setMyCommands',json={'commands':[{'command':c,'description':d} for c,d in ADMIN_MENU_COMMANDS],'scope':{'type':'chat','chat_id':admin_id}},timeout=8).raise_for_status()
        requests.post(f'{TELEGRAM_API}/setChatMenuButton',json={'menu_button':{'type':'commands'}},timeout=8).raise_for_status()
    except Exception as exc: logging.warning('Telegram menu setup failed: %s',exc)

def broadcast_message(text):
    users=get_active_users(); sent=failed=0
    for chat_id in users:
        try: send_message(chat_id,text); sent+=1; time.sleep(0.04)
        except Exception as exc:
            failed+=1; s=str(exc).lower()
            if 'blocked' in s or 'chat not found' in s or 'forbidden' in s: mark_user_inactive(chat_id)
    return sent,failed,len(users)

def quick_reply(text):
    q=' '.join(text.lower().split())
    if q in {'guess','guess paper','guess papers','guesspaper','गेस पेपर','गेस पेपर्स'}: return f'📚 Free Uniraj Guess Papers\n\n1️⃣ {GUESS_1}\n2️⃣ {GUESS_2}'
    if q in {'result','रिजल्ट','परिणाम'}: return f'🏆 Uniraj Official Result\n{UNIRAJ_RESULT}\n\n🆘 Result Help Group:\n{RESULT_HELP}'
    if q in {'admission','प्रवेश'}: return f'🎓 Uniraj Official Admission\n{UNIRAJ_ADMISSION}'
    if q in {'syllabus','सिलेबस','पाठ्यक्रम'}: return f'📘 Official Uniraj Syllabus Index:\n{UNIRAJ_SYLLABUS}'
    if q in {'who made this bot','who made bot','kisne banaya','किसने बनाया'}: return 'यह Uniraj Information Section bot है।'
    return None
OFFICIAL_CACHE={}; CACHE_SECONDS=300

def fetch_official(url,timeout=6):
    now=time.time(); cached=OFFICIAL_CACHE.get(url)
    if cached and now-cached[0]<CACHE_SECONDS: return cached[1]
    r=requests.get(url,timeout=timeout,headers={'User-Agent':'UnirajInformationBot/3.0'}); r.raise_for_status(); OFFICIAL_CACHE[url]=(now,r.text); return r.text

def official_source_for(text):
    q=text.lower(); syllabus=any(x in q for x in ['syllabus','सिलेबस','पाठ्यक्रम']); current=any(x in q for x in ['latest','today','aaj','current','abhi','update','notice','notification','exam date','exam dates','date','timetable','time table','last date','exam','examination','परीक्षा','आज','अभी','अपडेट','नोटिस','तिथि','अंतिम तिथि']); admission=any(x in q for x in ['admission','प्रवेश'])
    if syllabus and any(x in q for x in ['math','mathematics','गणित']): return f'VERIFIED OFFICIAL SOURCE:\nB.Sc. Maths Group 2025-26 PDF: {BSC_MATHS_2025_26_PDF}\nSyllabus index: {UNIRAJ_SYLLABUS}'
    if syllabus:
        try:
            soup=BeautifulSoup(fetch_official(UNIRAJ_SYLLABUS),'html.parser'); matches=[]
            for a in soup.find_all('a',href=True):
                title=' '.join(a.stripped_strings).strip(); href=a.get('href','')
                if title and any(w in (title+' '+href).lower() for w in q.split() if len(w)>2): matches.append(f'- {title}: {href}')
            if matches: return 'VERIFIED OFFICIAL UNIRAJ SYLLABUS PAGE DATA:\n'+'\n'.join(matches[:10])
        except Exception: pass
        return f'OFFICIAL SYLLABUS INDEX: {UNIRAJ_SYLLABUS}\nB.Sc Maths official PDF: {BSC_MATHS_2025_26_PDF}'
    if current:
        try:
            soup=BeautifulSoup(fetch_official(UNIRAJ_NOTICES),'html.parser'); data=' '.join(soup.stripped_strings)
            return f'VERIFIED OFFICIAL UNIRAJ NOTICES PAGE: {UNIRAJ_NOTICES}\nOFFICIAL PAGE TEXT:\n{data[:9000]}'
        except Exception: return f'OFFICIAL UNIRAJ NOTICES: {UNIRAJ_NOTICES}\nOfficial site temporarily unavailable; do not guess current information.'
    if admission: return f'VERIFIED OFFICIAL ADMISSION PORTAL: {UNIRAJ_ADMISSION}'
    return ''

def make_prompt(user_text,chat_id,official_data=''):
    parts=[f'SYSTEM: {SYSTEM_PROMPT}']; history=load_history(chat_id,MAX_HISTORY)
    if history: parts.append('SAVED CONVERSATION HISTORY:\n'+'\n'.join(f'{r.upper()}: {m}' for r,m in history))
    if official_data: parts.append('VERIFIED OFFICIAL UNIRAJ DATA:\n'+official_data)
    parts.append(f'LATEST STUDENT MESSAGE: {user_text}')
    parts.append('Answer ONLY the latest student message. Use history only to resolve context. Do not dump unrelated information.')
    return '\n\n'.join(parts)

def request_gemini(user_text,chat_id,model,official_data=''):
    if not GEMINI_API_KEY: raise RuntimeError('Gemini unavailable')
    url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'; payload={'contents':[{'role':'user','parts':[{'text':make_prompt(user_text,chat_id,official_data)}]}],'generationConfig':{'maxOutputTokens':1800,'temperature':0.2}}
    r=requests.post(url,headers={'x-goog-api-key':GEMINI_API_KEY,'Content-Type':'application/json'},json=payload,timeout=AI_TIMEOUT)
    if not r.ok: raise RuntimeError(f'Gemini {model} HTTP {r.status_code}: {r.text[:500]}')
    data=r.json(); candidates=data.get('candidates',[]); parts=candidates[0].get('content',{}).get('parts',[]) if candidates else []; answer=''.join(p.get('text','') for p in parts if p.get('text')).strip()
    if not answer: raise RuntimeError('Empty Gemini response')
    return answer

def is_transient(exc):
    s=str(exc).lower(); return any(f'http {c}' in s for c in [408,429,500,502,503,504]) or 'timed out' in s or 'timeout' in s

def model_candidates(): return ['gemini-3.5-flash-lite','gemini-3.6-flash','gemini-3.1-flash-lite']

def ai_reply(user_text,chat_id):
    quick=quick_reply(user_text)
    if quick: return quick
    official_data=official_source_for(user_text)
    models=model_candidates(); last_error=None; tried=[]
    for index,model in enumerate(models):
        tried.append(model); attempts=2 if index==0 else 1
        for attempt in range(attempts):
            try:
                return request_gemini(user_text,chat_id,model,official_data)
            except Exception as exc:
                last_error=exc
                if not is_transient(exc) or attempt+1>=attempts: break
                time.sleep(0.6)
    notify_admin_ai_failure(user_text,chat_id,last_error,tried)
    return 'अभी AI service से जवाब नहीं मिल पा रहा है। कृपया थोड़ी देर बाद फिर कोशिश करें।'

def maybe_add_promotion(chat_id,reply):
    count=conversation_count(chat_id)
    if count>0 and count%PROMO_EVERY==0: return reply+f'\n\n📚 Free Study Material: {GUESS_1}\n📖 Guess Papers: {GUESS_2}'
    return reply

def format_time(ts):
    if not ts: return '-'
    try: return time.strftime('%d-%m-%Y %H:%M',time.localtime(ts))
    except Exception: return '-'

def send_user_dashboard(chat_id,page=1):
    try:
        total=total_user_count(); active=user_count(); per_page=25; total_pages=max(1,(total+per_page-1)//per_page); page=min(max(1,page),total_pages); rows=user_directory(page,per_page)
        lines=['📊 ADMIN USER DASHBOARD','','👥 Total students started: '+str(total),'🟢 Currently active records: '+str(active),f'📄 Page: {page}/{total_pages}','','👤 Recent students:']
        if not rows: lines.append('अभी कोई student record नहीं है।')
        else:
            for i,(cid,username,first_name,active_flag,created_at,last_seen) in enumerate(rows,(page-1)*per_page+1): lines.append(f"{i}. {'🟢' if active_flag else '⚪'} {first_name or 'No name'} — {'@'+username if username else 'username नहीं है'}\n   ID: {cid} | Last: {format_time(last_seen)}")
        if page<total_pages: lines.append(f'\n➡️ अगला page: /users {page+1}')
        if page>1: lines.append(f'⬅️ पिछला page: /users {page-1}')
        send_message(chat_id,'\n'.join(lines))
    except Exception: logging.exception('User dashboard failed'); send_message(chat_id,'📊 ADMIN USER DASHBOARD\n\nDatabase अभी उपलब्ध नहीं है।')

def configure_webhook():
    render_url=os.getenv('RENDER_EXTERNAL_URL')
    if not render_url: return
    try: requests.post(f'{TELEGRAM_API}/setWebhook',json={'url':render_url.rstrip('/')+'/telegram/webhook'},timeout=8).raise_for_status()
    except Exception as exc: logging.warning('Webhook setup failed: %s',exc)

configure_webhook(); configure_telegram_menu()

def command_reply(command,chat_id):
    answers={'updates':f'📢 Uniraj Official Notices:\n{UNIRAJ_NOTICES}\n\nLatest information के लिए अपना सवाल सीधे लिखें.','exam':'📝 Exam\n\nअपना course + semester लिखें, जैसे: BSc 3rd semester exam dates','result':f'🏆 Official Result:\n{UNIRAJ_RESULT}\n\n🆘 Result Help Group:\n{RESULT_HELP}','admission':f'🎓 Official Admission:\n{UNIRAJ_ADMISSION}','syllabus':f'📘 Official Syllabus Index:\n{UNIRAJ_SYLLABUS}\n\nB.Sc. Maths Group 2025-26 PDF:\n{BSC_MATHS_2025_26_PDF}','guess':f'📚 Free Uniraj Guess Papers:\n1️⃣ {GUESS_1}\n2️⃣ {GUESS_2}','ask':'🤖 अपना Uniraj सवाल सीधे message में भेजें।','help':'ℹ️ अपना सवाल सीधे लिखें। Bot पिछली बातचीत का context समझकर follow-up सवालों का जवाब देगा।'}
    if command=='reset': reset_history(chat_id); return '♻️ आपकी saved chat memory reset कर दी गई है।'
    return answers.get(command,'अपना सवाल सीधे लिखें।')

@app.get('/')
def health(): return jsonify({'ok':True,'service':'Uniraj Information Section','status':'running','ai':'Gemini','model':'gemini-3.5-flash-lite','persistent_memory':bool(DATABASE_URL),'telegram_menu':True,'official_uniraj_lookup':True,'admin_user_dashboard':True,'build':'2026-09-11-persistent-memory-focused'})

@app.post('/telegram/webhook')
def telegram_webhook():
    try:
        update=request.get_json(silent=True) or {}; message=update.get('message')
        if not message: return jsonify({'ok':True})
        user=message.get('from',{});
        if user.get('is_bot'): return jsonify({'ok':True})
        chat_id=message.get('chat',{}).get('id'); text=(message.get('text') or '').strip()
        if not chat_id or not text: return jsonify({'ok':True})
        register_user(user,chat_id)
        if text.startswith('/start'):
            send_message(chat_id,'🎓 Uniraj Information Section में आपका स्वागत है!\n\nRajasthan University से जुड़े syllabus, exam, result, admission, notices और study questions पूछें।\n\n⚡ Powered by KESHAV MADHAV\n\nMenu से सभी options कभी भी खोल सकते हैं।'); return jsonify({'ok':True})
        if text.startswith('/cancel'):
            if chat_id in ADMIN_IDS: BROADCAST_WAITING.discard(chat_id); send_message(chat_id,'❌ Broadcast cancel कर दिया गया।')
            return jsonify({'ok':True})
        if text.startswith('/broadcast'):
            if chat_id not in ADMIN_IDS: return jsonify({'ok':True})
            BROADCAST_WAITING.add(chat_id); send_message(chat_id,f'📢 Broadcast mode ON\n\nयह message सभी active users को भेजा जाएगा।\n👥 Current users: {user_count()}\n\nअब अपना message भेजें।\nCancel के लिए /cancel भेजें।'); return jsonify({'ok':True})
        if text.startswith('/users'):
            if chat_id in ADMIN_IDS:
                parts=text.split(); page=1
                if len(parts)>1:
                    try: page=max(1,int(parts[1]))
                    except ValueError: page=1
                send_user_dashboard(chat_id,page)
            return jsonify({'ok':True})
        if chat_id in ADMIN_IDS and chat_id in BROADCAST_WAITING:
            BROADCAST_WAITING.discard(chat_id); sent,failed,total=broadcast_message(text); send_message(chat_id,f'📢 Broadcast complete\n\n👥 Total: {total}\n✅ Sent: {sent}\n❌ Failed: {failed}'); return jsonify({'ok':True})
        if text.startswith('/reset'):
            send_message(chat_id,command_reply('reset',chat_id)); return jsonify({'ok':True})
        if text.startswith('/'):
            command=text.split()[0][1:].split('@')[0].lower()
            if command in {c for c,_ in MENU_COMMANDS}:
                reply=command_reply(command,chat_id); save_turn(chat_id,text,reply); send_message(chat_id,reply)
            return jsonify({'ok':True})
        try: requests.post(f'{TELEGRAM_API}/sendChatAction',json={'chat_id':chat_id,'action':'typing'},timeout=3)
        except Exception: pass
        reply=ai_reply(text,chat_id); save_turn(chat_id,text,reply); reply=maybe_add_promotion(chat_id,reply); send_message(chat_id,reply); return jsonify({'ok':True})
    except Exception:
        logging.exception('Telegram webhook failed'); return jsonify({'ok':True})

if __name__=='__main__':
    port=int(os.getenv('PORT','10000')); app.run(host='0.0.0.0',port=port)
