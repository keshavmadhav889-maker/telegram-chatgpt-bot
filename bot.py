import os, json, logging, time
import requests
from flask import Flask, request, jsonify
from notes_store import (
    register_user, get_courses, get_course, get_subjects, get_product,
    find_or_create_product, create_order, mark_paid, mark_delivery,
    my_purchases, admin_products, admin_orders, sales_stats, users_count,
    all_users, deactivate_user, save_session, get_session, clear_session,
    add_course
)

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
ADMIN_CHAT_ID = int((os.getenv("ADMIN_CHAT_ID") or "0").strip() or 0)
ADMIN_USERNAME = (os.getenv("ADMIN_USERNAME") or "").strip().lstrip("@")
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
RENDER_EXTERNAL_URL = (os.getenv("RENDER_EXTERNAL_URL") or "").strip()
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing hai")
if not ADMIN_CHAT_ID:
    logging.warning("ADMIN_CHAT_ID is not configured; admin panel will remain disabled")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_BROADCAST = 4096

def tg(method, payload=None, timeout=15):
    r = requests.post(f"{API}/{method}", json=payload or {}, timeout=timeout)
    data = r.json()
    if not r.ok or not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data}")
    return data["result"]

def send_message(chat_id, text, keyboard=None):
    p = {"chat_id": chat_id, "text": str(text)[:4096], "disable_web_page_preview": True}
    if keyboard is not None:
        p["reply_markup"] = {"inline_keyboard": keyboard}
    return tg("sendMessage", p)

def edit_message(chat_id, message_id, text, keyboard=None):
    p = {"chat_id": chat_id, "message_id": message_id, "text": str(text)[:4096], "disable_web_page_preview": True}
    if keyboard is not None:
        p["reply_markup"] = {"inline_keyboard": keyboard}
    try:
        return tg("editMessageText", p)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise

def answer_callback(query_id, text=""):
    try: tg("answerCallbackQuery", {"callback_query_id": query_id, "text": text[:200]})
    except Exception: pass

def is_admin(chat_id): return bool(ADMIN_CHAT_ID and int(chat_id) == ADMIN_CHAT_ID)

def btn(text, data): return {"text": text, "callback_data": data}
def url_btn(text, url): return {"text": text, "url": url}

def admin_contact_button():
    if ADMIN_USERNAME:
        return url_btn("📩 Admin को Message करें", f"https://t.me/{ADMIN_USERNAME}")
    return url_btn("📩 Admin को Message करें", f"tg://user?id={ADMIN_CHAT_ID}")

def nav(back="home"):
    row = []
    if back != "none": row.append(btn("⬅️ Back", back))
    row.append(btn("🏠 Main Menu", "home"))
    return [row]

def main_menu():
    return [
        [btn("🎓 B.Sc.", "c:BSC"), btn("📗 B.Com", "c:BCOM")],
        [btn("📙 M.Com", "c:MCOM"), btn("🔬 M.Sc", "c:MSC")],
        [btn("📕 M.A", "c:MA"), btn("📘 B.A", "c:BA")],
        [btn("🛒 My Purchases", "purchases")],
    ]

def render_home(chat_id, message_id=None):
    text = "नमस्ते! 📚\n\nयहाँ आप अपने Course, Semester और Subject के अनुसार Notes/PDF खरीद सकते हैं।\nनीचे अपना Course चुनें।"
    if message_id: edit_message(chat_id, message_id, text, main_menu())
    else: send_message(chat_id, text, main_menu())

def render_course(chat_id, message_id, cid):
    course = get_course(cid)
    if not course: return render_home(chat_id, message_id)
    if cid == "BSC":
        kb = [[btn("🧪 B.Sc. PCM", "s:BSC:PCM")],[btn("🧬 B.Sc. PCB", "s:BSC:PCB")]] + nav("home")
    else:
        kb = [[btn(f"📘 {course[1]}", f"s:{cid}:")]] + nav("home")
    edit_message(chat_id, message_id, f"🎓 {course[1]}\n\nअपना stream/course option चुनें।", kb)

def render_semesters(chat_id, message_id, cid, stream):
    course = get_course(cid)
    if not course: return render_home(chat_id, message_id)
    kb=[]
    icons=["📘","📗","📕","📙","📒","📔"]
    for i in range(1,7):
        kb.append([btn(f"{icons[i-1]} Semester {i}", f"m:{cid}:{stream}:{i}")])
    kb += nav(f"c:{cid}")
    edit_message(chat_id, message_id, f"🎓 {course[1]}{(' • '+stream) if stream else ''}\n\nSemester चुनें:", kb)

def render_subjects(chat_id, message_id, cid, stream, sem):
    course = get_course(cid)
    rows = get_subjects(cid, stream, sem)
    kb=[]
    for pid, subject, price, file_id, active in rows:
        kb.append([btn(("📚 " if file_id else "📄 ") + subject, f"p:{pid}")])
    if not rows:
        text=f"📚 {course[1]}{(' • '+stream) if stream else ''} • Semester {sem}\n\nइस semester में अभी कोई Subject नहीं जोड़ा गया है।"
    else:
        text=f"📚 {course[1]}{(' • '+stream) if stream else ''} • Semester {sem}\n\nSubject चुनें:"
    kb += nav(f"s:{cid}:{stream}")
    edit_message(chat_id, message_id, text, kb)

def render_product(chat_id, message_id, pid):
    p=get_product(pid)
    if not p or not p[7]:
        edit_message(chat_id,message_id,"❌ यह product उपलब्ध नहीं है।",nav("home")); return
    course=get_course(p[1]); stream=p[2]; sem=p[3]; subject=p[4]; price=p[5]; file_id=p[6]
    if not file_id:
        kb=[[admin_contact_button()]]+nav(f"m:{p[1]}:{stream}:{sem}")
        text=f"📚 इस Subject के Notes अभी उपलब्ध नहीं हैं।\n\nयदि आपको इस Subject के Notes चाहिए तो आप इस Admin ID पर message कर सकते हैं।"
    else:
        kb=[[btn("💳 Buy Now","buy:"+pid)],[admin_contact_button()]]+nav(f"m:{p[1]}:{stream}:{sem}")
        text=(f"📚 Complete Notes\n\nCourse: {course[1]}\n"
              f"{('Stream: '+stream+'\\n') if stream else ''}Semester: {sem}\nSubject: {subject}\n\n"
              f"⭐ Price: {price} Stars\n\nPDF उपलब्ध है।\n\nनीचे Buy Now दबाकर खरीदें।")
    edit_message(chat_id,message_id,text,kb)

def render_purchases(chat_id, message_id=None):
    rows=my_purchases(chat_id)
    if not rows:
        text="🛒 My Purchases\n\nअभी आपकी कोई खरीदी हुई PDF नहीं है।"
        kb=nav("home")
    else:
        text="🛒 My Purchases\n\nआपकी खरीदी हुई PDFs:"
        kb=[]
        for oid,pid,cid,stream,sem,subject,price,paid_at in rows:
            kb.append([btn(f"📥 {subject} • Sem {sem}", "own:"+pid)])
        kb += nav("home")
    if message_id: edit_message(chat_id,message_id,text,kb)
    else: send_message(chat_id,text,kb)

def render_admin(chat_id, message_id=None):
    kb=[
        [btn("👤 Users","a:users"),btn("📚 Products / Notes","a:products")],
        [btn("➕ Add Subject","a:addsub"),btn("📄 Upload PDF","a:upload")],
        [btn("💰 Change Price","a:price"),btn("📦 Orders","a:orders")],
        [btn("📊 Sales","a:sales"),btn("📢 Broadcast","a:broadcast")],
        [btn("➕ Add Course","a:addcourse"),btn("⚙️ Settings","a:settings")],
        [btn("🏠 Main Menu","home")],
    ]
    text="🔐 Admin Panel\n\nTelegram के अंदर से Notes Store manage करें।"
    if message_id: edit_message(chat_id,message_id,text,kb)
    else: send_message(chat_id,text,kb)

def admin_course_buttons(prefix):
    rows=get_courses(); kb=[]
    for cid,name in rows: kb.append([btn(name, f"{prefix}:{cid}")])
    return kb

def admin_stream_buttons(prefix,cid):
    return [[btn("🧪 PCM",f"{prefix}:{cid}:PCM")],[btn("🧬 PCB",f"{prefix}:{cid}:PCB")]]+nav("admin")

def admin_sem_buttons(prefix,cid,stream):
    return [[btn(f"Semester {i}",f"{prefix}:{cid}:{stream}:{i}")] for i in range(1,7)] + nav("admin")

def product_admin_buttons(action):
    rows=admin_products(80); kb=[]
    for pid,cid,stream,sem,subject,price,file_id,active,cname in rows:
        label=f"{cname}{('/'+stream) if stream else ''} S{sem} • {subject}"
        kb.append([btn(label[:60],f"{action}:{pid}")])
    kb += nav("admin")
    return kb

def process_admin_state(chat_id, message):
    sess=get_session(chat_id)
    if not sess: return False
    state,data=sess
    text=(message.get("text") or "").strip()
    if state=="broadcast":
        if text.lower()=="/cancel": clear_session(chat_id); send_message(chat_id,"❌ Broadcast cancel कर दिया गया।"); return True
        sent=failed=0
        for uid in all_users():
            try: send_message(uid,text[:MAX_BROADCAST]); sent+=1
            except Exception as e:
                failed+=1
                if any(x in str(e).lower() for x in ["blocked","forbidden","chat not found"]): deactivate_user(uid)
        clear_session(chat_id); send_message(chat_id,f"📢 Broadcast complete\n\n✅ Sent: {sent}\n❌ Failed: {failed}"); return True
    if state=="subject_name":
        if text.lower()=="/cancel": clear_session(chat_id); send_message(chat_id,"❌ Cancelled.",[ ]); return True
        d=json.loads(data); pid=find_or_create_product(d["cid"],d["stream"],d["sem"],text[:150])
        clear_session(chat_id)
        send_message(chat_id,"✅ Subject successfully added.\n\nअब PDF upload करने के लिए Admin Panel में 📄 Upload PDF चुनें।\nDefault price: 1 Star.", [[btn("💰 Change Price",f"price:{pid}")],[btn("📄 Upload PDF",f"upload:{pid}")], [btn("🔐 Admin Panel","admin")]])
        return True
    if state=="course_name":
        if text.lower()=="/cancel": clear_session(chat_id); send_message(chat_id,"❌ Cancelled."); return True
        cid=(data.split("|")[0]).upper()[:20]
        name=text[:100]
        if not cid or not name or not add_course(cid,name):
            send_message(chat_id,"❌ Course add नहीं हुआ। Code unique होना चाहिए। फिर /admin से कोशिश करें।")
        else: send_message(chat_id,f"✅ Course added: {name}")
        clear_session(chat_id); return True
    if state=="pdf_upload":
        pid=data
        doc=message.get("document")
        if not doc:
            send_message(chat_id,"📄 कृपया PDF को Telegram में Document के रूप में भेजें। /cancel से cancel करें।"); return True
        name=(doc.get("file_name") or "").lower()
        if not name.endswith(".pdf"):
            send_message(chat_id,"❌ केवल PDF document स्वीकार किया जाएगा।"); return True
        from notes_store import set_file_id
        set_file_id(pid,doc["file_id"]); clear_session(chat_id)
        send_message(chat_id,"✅ PDF successfully uploaded.\nअब students यह Notes खरीद सकते हैं।",[[btn("📚 Products","a:products")],[btn("🔐 Admin Panel","admin")]])
        return True
    return False

def send_invoice(chat_id,user,pid):
    order=create_order(chat_id,user,pid)
    if not order:
        send_message(chat_id,"❌ यह Notes अभी खरीदने के लिए उपलब्ध नहीं हैं।")
        return
    oid,p=order
    course=get_course(p[1]); desc=f"{course[1]} {p[3]} • {p[4]}"+(f" • {p[2]}" if p[2] else "")
    tg("sendInvoice",{
        "chat_id":chat_id,"title":p[4][:32],"description":desc[:255],
        "payload":"order:"+oid,"currency":"XTR",
        "prices":[{"label":"Notes PDF","amount":int(p[5])}],
        "start_parameter":"buy_"+p[0]
    })
    send_message(chat_id,f"🧾 Order ID: {oid}\n\nTelegram Stars invoice भेज दिया गया है। Payment सफल होने के बाद PDF automatically इसी chat में भेजी जाएगी।")

def handle_precheckout(q):
    payload=q.get("invoice_payload","")
    if not payload.startswith("order:"):
        tg("answerPreCheckoutQuery",{"pre_checkout_query_id":q["id"],"ok":False,"error_message":"Invalid order."}); return
    oid=payload[6:]
    from notes_store import db
    x=db(); r=x.execute("""SELECT chat_id,product_id,price,status FROM orders WHERE order_id=?""",(oid,)).fetchone(); x.close()
    if not r or int(r[0])!=int(q.get("from",{}).get("id",0)) or r[3]!="PENDING" or int(r[2])!=int(q.get("total_amount",0)) or q.get("currency")!="XTR":
        tg("answerPreCheckoutQuery",{"pre_checkout_query_id":q["id"],"ok":False,"error_message":"Order verification failed. Please create a new order."}); return
    p=get_product(r[1])
    if not p or not p[6]:
        tg("answerPreCheckoutQuery",{"pre_checkout_query_id":q["id"],"ok":False,"error_message":"PDF is currently unavailable. Please try again later."}); return
    tg("answerPreCheckoutQuery",{"pre_checkout_query_id":q["id"],"ok":True})

def handle_successful_payment(message):
    sp=message.get("successful_payment",{}); payload=sp.get("invoice_payload","")
    if not payload.startswith("order:"): return
    oid=payload[6:]; chat_id=message["chat"]["id"]
    from notes_store import db
    x=db(); r=x.execute("""SELECT chat_id,product_id,price,status FROM orders WHERE order_id=?""",(oid,)).fetchone(); x.close()
    if not r or int(r[0])!=int(chat_id) or r[3]=="PAID":
        return
    if sp.get("currency")!="XTR" or int(sp.get("total_amount",0))!=int(r[2]):
        return
    paid=mark_paid(oid,sp.get("telegram_payment_charge_id",""))
    if not paid: return
    p=get_product(r[1])
    if not p or not p[6]:
        mark_delivery(oid,"FAILED_NO_FILE"); send_message(chat_id,"⚠️ Payment successful है, लेकिन PDF अभी उपलब्ध नहीं है। Admin से संपर्क करें।",[ [admin_contact_button()] ]); return
    send_message(chat_id,"✅ Payment Successful!\n\n📚 आपके Notes तैयार हैं।\nनीचे आपकी PDF भेजी जा रही है।\n\nधन्यवाद! 📖")
    try:
        tg("sendDocument",{"chat_id":chat_id,"document":p[6],"caption":f"📚 {p[4]}\nOrder ID: {oid}"})
        mark_delivery(oid,"SENT")
    except Exception:
        mark_delivery(oid,"FAILED")
        send_message(chat_id,"⚠️ Payment सुरक्षित रूप से दर्ज हो गया है, लेकिन PDF भेजने में समस्या आई। My Purchases से फिर कोशिश करें।")

def handle_callback(q):
    chat_id=q["message"]["chat"]["id"]; mid=q["message"]["message_id"]; data=q.get("data","")
    answer_callback(q["id"])
    if data=="home": return render_home(chat_id,mid)
    if data=="purchases": return render_purchases(chat_id,mid)
    if data=="admin":
        if is_admin(chat_id): return render_admin(chat_id,mid)
        return
    if data.startswith("c:"): return render_course(chat_id,mid,data[2:])
    if data.startswith("s:"):
        _,cid,stream=data.split(":",2); return render_semesters(chat_id,mid,cid,stream)
    if data.startswith("m:"):
        _,cid,stream,sem=data.split(":",3); return render_subjects(chat_id,mid,cid,stream,int(sem))
    if data.startswith("p:"): return render_product(chat_id,mid,data[2:])
    if data.startswith("buy:"):
        pid=data[4:]; p=get_product(pid)
        if p and p[6]: send_invoice(chat_id,q["from"],pid)
        else: render_product(chat_id,mid,pid)
        return
    if data.startswith("own:"):
        pid=data[4:]
        rows=[r for r in my_purchases(chat_id) if r[1]==pid]
        p=get_product(pid)
        if not rows or not p or not p[6]:
            send_message(chat_id,"❌ यह PDF आपकी purchase list में नहीं है या अभी उपलब्ध नहीं है."); return
        tg("sendDocument",{"chat_id":chat_id,"document":p[6],"caption":f"📥 {p[4]}\nयह आपकी purchased PDF है।"}); return

    if not is_admin(chat_id): return
    if data=="a:users":
        send_message(chat_id,f"👤 Users\n\nTotal registered Telegram users: {users_count()}"); return
    if data=="a:products":
        rows=admin_products(80); text="📚 Products / Notes\n\n"
        for pid,cid,stream,sem,sub,price,file_id,active,cname in rows:
            text+=f"• {cname}{(' • '+stream) if stream else ''} • Sem {sem}\n  {sub} | ⭐ {price} | {'PDF ✅' if file_id else 'PDF ❌'}\n  ID: {pid}\n"
        send_message(chat_id,text[:4096],product_admin_buttons("edit")); return
    if data=="a:addsub":
        send_message(chat_id,"➕ Add Subject\n\nपहले Course चुनें:",admin_course_buttons("as")); return
    if data.startswith("as:"):
        parts=data.split(":")
        if len(parts)==2:
            cid=parts[1]
            if cid=="BSC": send_message(chat_id,"Stream चुनें:",admin_stream_buttons("asx",cid))
            else: send_message(chat_id,"Semester चुनें:",admin_sem_buttons("asy",cid,""))
        elif len(parts)==3: send_message(chat_id,"Semester चुनें:",admin_sem_buttons("asy",parts[1],parts[2]))
        return
    if data.startswith("asx:"):
        _,cid,stream=data.split(":"); send_message(chat_id,"Semester चुनें:",admin_sem_buttons("asy",cid,stream)); return
    if data.startswith("asy:"):
        _,cid,stream,sem=data.split(":"); save_session(chat_id,"subject_name",json.dumps({"cid":cid,"stream":stream,"sem":int(sem)})); send_message(chat_id,"✍️ अब Subject का नाम भेजें।\nExample: Physics\n/cancel"); return

    if data=="a:upload":
        send_message(chat_id,"📄 Upload PDF\n\nExisting Subject चुनें:",product_admin_buttons("upload")); return
    if data.startswith("upload:"):
        pid=data.split(":",1)[1]; p=get_product(pid)
        if not p: send_message(chat_id,"❌ Product नहीं मिला।"); return
        save_session(chat_id,"pdf_upload",pid); send_message(chat_id,f"📄 {p[4]} के लिए PDF Document भेजें।\n/cancel"); return

    if data=="a:price":
        send_message(chat_id,"💰 Price बदलें\n\nSubject चुनें:",product_admin_buttons("price")); return
    if data.startswith("price:"):
        pid=data.split(":",1)[1]; p=get_product(pid)
        if not p: return
        save_session(chat_id,"price",pid); send_message(chat_id,f"💰 Current price: {p[5]} Stars\n\nनई price केवल पूरा number भेजें।\nExample: 49\n/cancel"); return

    if data=="a:orders":
        kb=[[btn("🕒 Pending","orders:PENDING"),btn("✅ Paid","orders:PAID")],[btn("❌ Failed","orders:FAILED")],[btn("📅 Today","orders:TODAY")]]+nav("admin")
        send_message(chat_id,"📦 Orders\n\nFilter चुनें:",kb); return
    if data.startswith("orders:"):
        filt=data.split(":")[1]; day=None; status=None
        if filt in ("PENDING","PAID","FAILED"): status=filt
        if filt=="TODAY":
            t=time.localtime(); start=time.mktime((t.tm_year,t.tm_mon,t.tm_mday,0,0,0,0,0)); day=(start,start+86400)
        rows=admin_orders(status,day,60); text=f"📦 Orders • {filt}\n\n"
        for r in rows: text+=f"{r[0]}\n👤 {r[1]} @{r[2] or '-'}\n📚 {r[4] or ''} S{r[5]} • {r[6]}\n⭐ {r[7]} • {r[8]} • Delivery {r[11]}\n\n"
        send_message(chat_id,text[:4096],nav("admin")); return

    if data=="a:sales":
        u,o,p,total,today,month=sales_stats()
        send_message(chat_id,f"📊 Sales\n\n👥 Total Users: {u}\n📦 Total Orders: {o}\n✅ Paid Orders: {p}\n⭐ Total Sales: {total} Stars\n📅 आज की Sales: {today} Stars\n🗓️ इस महीने की Sales: {month} Stars",nav("admin")); return
    if data=="a:broadcast":
        save_session(chat_id,"broadcast",""); send_message(chat_id,f"📢 Broadcast\n\nअब message भेजें। यह {users_count()} registered users को भेजा जाएगा।\n/cancel"); return
    if data=="a:addcourse":
        save_session(chat_id,"course_code",""); send_message(chat_id,"➕ New Course\n\nपहले short Course ID भेजें। Example: BTECH\n/cancel"); return
    if data=="a:settings":
        send_message(chat_id,f"⚙️ Settings\n\nAdmin ID: {ADMIN_CHAT_ID}\nAdmin username: @{ADMIN_USERNAME or 'not configured'}\nPayment: Telegram Stars (XTR)\nDatabase: {'PostgreSQL' if DATABASE_URL else 'SQLite fallback'}\n\nNo web/PWA interface is used.",nav("admin")); return
    if data.startswith("edit:"):
        pid=data[5:]; p=get_product(pid)
        if p: send_message(chat_id,f"📚 {p[4]}\n⭐ Price: {p[5]} Stars\n📄 PDF: {'Available' if p[6] else 'Not uploaded'}",[[btn("💰 Change Price",f"price:{pid}")],[btn("📄 Upload/Replace PDF",f"upload:{pid}")],[btn("🔐 Admin Panel","admin")]])
        return

def handle_message(message):
    chat_id=message["chat"]["id"]; user=message.get("from",{})
    register_user(user,chat_id)
    if message.get("successful_payment"): return handle_successful_payment(message)
    if process_admin_state(chat_id,message): return
    text=(message.get("text") or "").strip()
    if message.get("document") and is_admin(chat_id):
        send_message(chat_id,"❌ पहले Admin Panel → 📄 Upload PDF से Subject चुनें।"); return
    if text.startswith("/start"):
        return render_home(chat_id)
    if text.startswith("/admin"):
        if is_admin(chat_id): return render_admin(chat_id)
        return send_message(chat_id,"⛔ Admin access नहीं है।")
    if text.startswith("/cancel"):
        clear_session(chat_id); return send_message(chat_id,"❌ Cancelled.")
    if text.startswith("/purchases") or text.startswith("/my_purchases"):
        return render_purchases(chat_id)
    if text.startswith("/notes"):
        return render_home(chat_id)
    if text.startswith("/id"):
        return send_message(chat_id,f"Your Telegram User ID: {chat_id}")
    send_message(chat_id,"👇 Notes खरीदने के लिए नीचे menu से Course चुनें।",main_menu())

def configure():
    try:
        tg("setMyCommands",{"commands":[{"command":"start","description":"Open Notes Store"},{"command":"admin","description":"Admin Panel (admin only)"},{"command":"purchases","description":"My Purchases"}]})
        if ADMIN_CHAT_ID:
            tg("setMyCommands",{"commands":[{"command":"start","description":"Open Notes Store"},{"command":"admin","description":"Admin Panel"},{"command":"purchases","description":"My Purchases"}],"scope":{"type":"chat","chat_id":ADMIN_CHAT_ID}})
        if RENDER_EXTERNAL_URL:
            tg("setWebhook",{"url":RENDER_EXTERNAL_URL.rstrip("/")+"/telegram/webhook","allowed_updates":["message","callback_query","pre_checkout_query"]})
    except Exception:
        logging.exception("Telegram configuration failed")

configure()

@app.get("/")
def health():
    return jsonify({"ok":True,"service":"Telegram Notes Selling Bot","telegram_only":True,"payments":"Telegram Stars XTR","database":"postgresql" if DATABASE_URL else "sqlite-fallback","admin_configured":bool(ADMIN_CHAT_ID)})

@app.post("/telegram/webhook")
def webhook():
    try:
        update=request.get_json(silent=True) or {}
        if update.get("pre_checkout_query"):
            handle_precheckout(update["pre_checkout_query"]); return jsonify({"ok":True})
        if update.get("callback_query"):
            handle_callback(update["callback_query"]); return jsonify({"ok":True})
        if update.get("message"):
            handle_message(update["message"])
        return jsonify({"ok":True})
    except Exception:
        logging.exception("Webhook error")
        return jsonify({"ok":True})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
