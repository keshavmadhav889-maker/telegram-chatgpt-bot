import os
import sqlite3
import time
from pathlib import Path

NOTES_DB = (os.getenv("NOTES_DB_PATH") or "/tmp/ru_notes.db").strip()
ADMIN_IDS = {8280167872}

STREAMS = {
    "PCM": "Physics • Chemistry • Mathematics",
    "PCB": "Physics • Chemistry • Biology",
}

def db():
    parent = os.path.dirname(NOTES_DB)
    if parent:
        os.makedirs(parent, exist_ok=True)
    c = sqlite3.connect(NOTES_DB, timeout=10)
    c.execute("""CREATE TABLE IF NOT EXISTS products (
        product_id TEXT PRIMARY KEY,
        stream TEXT NOT NULL,
        semester INTEGER NOT NULL,
        title TEXT NOT NULL,
        subjects TEXT NOT NULL,
        price INTEGER NOT NULL,
        telegram_file_id TEXT DEFAULT '',
        active INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        chat_id INTEGER NOT NULL,
        product_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_at REAL NOT NULL
    )""")
    c.commit()
    return c

def seed_products():
    c = db()
    for stream, subjects in STREAMS.items():
        for sem in range(1, 7):
            rows = [
                (f"{stream}-S{sem}-COMPLETE", stream, sem, f"Semester {sem} Complete Notes", subjects, 149),
                (f"{stream}-S{sem}-IMPORTANT", stream, sem, f"Semester {sem} Important Questions", f"Exam-focused set • {subjects}", 79),
            ]
            for row in rows:
                c.execute("""INSERT OR IGNORE INTO products
                    (product_id,stream,semester,title,subjects,price)
                    VALUES (?,?,?,?,?,?)""", row)
    c.commit()
    c.close()

def list_products(stream=None, semester=None):
    c = db()
    q = "SELECT product_id,stream,semester,title,subjects,price,telegram_file_id FROM products WHERE active=1"
    params = []
    if stream:
        q += " AND stream=?"; params.append(stream)
    if semester:
        q += " AND semester=?"; params.append(int(semester))
    q += " ORDER BY stream,semester,price DESC"
    rows = c.execute(q, params).fetchall()
    c.close()
    return rows

def get_product(product_id):
    c = db()
    row = c.execute("SELECT product_id,stream,semester,title,subjects,price,telegram_file_id FROM products WHERE product_id=?", (product_id,)).fetchone()
    c.close()
    return row

def set_file_id(product_id, file_id):
    c = db()
    cur = c.execute("UPDATE products SET telegram_file_id=? WHERE product_id=?", (file_id, product_id))
    c.commit(); c.close()
    return cur.rowcount > 0

def set_price(product_id, price):
    c = db()
    cur = c.execute("UPDATE products SET price=? WHERE product_id=?", (int(price), product_id))
    c.commit(); c.close()
    return cur.rowcount > 0

def create_order(chat_id, product_id):
    product = get_product(product_id)
    if not product:
        return None
    order_id = f"RU{int(time.time()*1000)}{int(chat_id)%10000}"
    c = db()
    c.execute("INSERT INTO orders(order_id,chat_id,product_id,amount,status,created_at) VALUES(?,?,?,?,?,?)",
              (order_id, chat_id, product_id, product[5], "PENDING_PAYMENT", time.time()))
    c.commit(); c.close()
    return order_id, product

def mark_paid(order_id):
    c = db()
    c.execute("UPDATE orders SET status='PAID' WHERE order_id=?", (order_id,))
    c.commit(); c.close()

def recent_orders(chat_id, limit=10):
    c = db()
    rows = c.execute("""SELECT order_id,product_id,amount,status,created_at
                        FROM orders WHERE chat_id=? ORDER BY created_at DESC LIMIT ?""",
                     (chat_id, limit)).fetchall()
    c.close()
    return rows

seed_products()

def notes_help():
    return (
        "📚 RU B.Sc. Notes Store\n\n"
        "Stream चुनें: /pcm या /pcb\n"
        "फिर semester चुनें: /sem1 से /sem6\n\n"
        "उदाहरण: /pcm फिर /sem3"
    )

def notes_for(stream, semester):
    rows = list_products(stream, semester)
    if not rows:
        return "इस selection के लिए अभी कोई package उपलब्ध नहीं है।"
    lines = [f"📘 {stream} • Semester {semester}", ""]
    for product_id, _, _, title, subjects, price, _ in rows:
        lines.append(f"• {title}\n  {subjects}\n  💰 ₹{price}\n  🛒 /buy_{product_id}")
    lines.append("\nPayment gateway merchant approval के बाद /buy flow में secure checkout जोड़ा जाएगा।")
    return "\n".join(lines)

def buy_product(chat_id, product_id):
    order = create_order(chat_id, product_id)
    if not order:
        return "❌ Product नहीं मिला। /notes से फिर चुनें।"
    order_id, product = order
    return (
        f"🧾 Order created\n\n"
        f"Order ID: {order_id}\n"
        f"Product: {product[3]}\n"
        f"Amount: ₹{product[5]}\n\n"
        "🔐 Secure payment checkout अभी PhonePe merchant onboarding के बाद connect होगा।\n"
        "Payment credentials या OTP/PIN कभी bot में नहीं डालें।"
    )
