import os
import sqlite3
import time
import uuid
from contextlib import contextmanager

DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
SQLITE_PATH = (os.getenv("NOTES_DB_PATH") or "/tmp/notes_store.db").strip()

COURSES = {
    "BSC": "B.Sc.",
    "BCOM": "B.Com",
    "MCOM": "M.Com",
    "MSC": "M.Sc",
    "MA": "M.A",
    "BA": "B.A",
}
STREAMS = {"PCM": "PCM", "PCB": "PCB"}
SEMESTERS = range(1, 7)

class DB:
    def __init__(self, conn, pg=False):
        self.conn, self.pg = conn, pg
    def execute(self, sql, params=()):
        return self.conn.cursor().execute(sql.replace("?", "%s") if self.pg else sql, params)
    def commit(self): self.conn.commit()
    def close(self): self.conn.close()

def db():
    if DATABASE_URL:
        try:
            import psycopg2
            c = psycopg2.connect(DATABASE_URL, connect_timeout=8)
            x = DB(c, True); init_db(x); return x
        except Exception:
            pass
    c = sqlite3.connect(SQLITE_PATH, timeout=15)
    x = DB(c, False); init_db(x); return x

def init_db(x):
    id_type = "BIGINT" if x.pg else "INTEGER"
    serial = "BIGSERIAL" if x.pg else "INTEGER"
    x.execute(f"""CREATE TABLE IF NOT EXISTS users (
        chat_id {id_type} PRIMARY KEY, username TEXT, first_name TEXT,
        active INTEGER DEFAULT 1, created_at DOUBLE PRECISION, last_seen DOUBLE PRECISION)""")
    x.execute(f"""CREATE TABLE IF NOT EXISTS courses (
        course_id TEXT PRIMARY KEY, name TEXT NOT NULL, active INTEGER DEFAULT 1, created_at DOUBLE PRECISION)""")
    x.execute(f"""CREATE TABLE IF NOT EXISTS products (
        product_id TEXT PRIMARY KEY, course_id TEXT NOT NULL, stream TEXT DEFAULT '',
        semester INTEGER NOT NULL, subject TEXT NOT NULL, price INTEGER NOT NULL DEFAULT 1,
        telegram_file_id TEXT DEFAULT '', active INTEGER DEFAULT 1, created_at DOUBLE PRECISION,
        UNIQUE(course_id, stream, semester, subject))""")
    x.execute(f"""CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY, chat_id {id_type} NOT NULL, username TEXT,
        course_id TEXT NOT NULL, stream TEXT DEFAULT '', semester INTEGER NOT NULL,
        subject TEXT NOT NULL, product_id TEXT NOT NULL, price INTEGER NOT NULL,
        currency TEXT NOT NULL DEFAULT 'XTR', status TEXT NOT NULL,
        telegram_charge_id TEXT DEFAULT '', created_at DOUBLE PRECISION,
        paid_at DOUBLE PRECISION, delivery_status TEXT DEFAULT 'NOT_SENT')""")
    x.execute(f"""CREATE TABLE IF NOT EXISTS admin_sessions (
        chat_id {id_type} PRIMARY KEY, state TEXT, data TEXT, updated_at DOUBLE PRECISION)""")
    x.execute("CREATE INDEX IF NOT EXISTS idx_products_path ON products(course_id,stream,semester,active)")
    x.execute("CREATE INDEX IF NOT EXISTS idx_orders_chat ON orders(chat_id,status)")
    x.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at)")
    for k,v in COURSES.items():
        if x.pg:
            x.execute("INSERT INTO courses(course_id,name,created_at) VALUES(?,?,?) ON CONFLICT(course_id) DO NOTHING",(k,v,time.time()))
        else:
            x.execute("INSERT OR IGNORE INTO courses(course_id,name,created_at) VALUES(?,?,?)",(k,v,time.time()))
    x.commit()

def register_user(user, chat_id):
    x=db(); now=time.time()
    if x.pg:
        x.execute("""INSERT INTO users(chat_id,username,first_name,active,created_at,last_seen)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET
                    username=EXCLUDED.username, first_name=EXCLUDED.first_name, active=1,last_seen=EXCLUDED.last_seen""",
                  (chat_id,user.get("username",""),user.get("first_name",""),1,now,now))
    else:
        x.execute("""INSERT INTO users(chat_id,username,first_name,active,created_at,last_seen)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(chat_id) DO UPDATE SET
                    username=excluded.username, first_name=excluded.first_name, active=1,last_seen=excluded.last_seen""",
                  (chat_id,user.get("username",""),user.get("first_name",""),1,now,now))
    x.commit(); x.close()

def get_courses():
    x=db(); rows=x.execute("SELECT course_id,name FROM courses WHERE active=1 ORDER BY created_at").fetchall(); x.close(); return rows

def add_course(course_id,name):
    x=db()
    try:
        x.execute("INSERT INTO courses(course_id,name,created_at) VALUES(?,?,?)",(course_id,name,time.time())); x.commit(); ok=True
    except Exception: x.conn.rollback(); ok=False
    x.close(); return ok

def get_course(course_id):
    x=db(); r=x.execute("SELECT course_id,name FROM courses WHERE course_id=? AND active=1",(course_id,)).fetchone(); x.close(); return r

def get_subjects(course_id,stream,semester):
    x=db(); rows=x.execute("""SELECT product_id,subject,price,telegram_file_id,active
        FROM products WHERE course_id=? AND stream=? AND semester=? AND active=1 ORDER BY subject""",
        (course_id,stream or "",int(semester))).fetchall(); x.close(); return rows

def get_product(pid):
    x=db(); r=x.execute("""SELECT product_id,course_id,stream,semester,subject,price,telegram_file_id,active
                           FROM products WHERE product_id=?""",(pid,)).fetchone(); x.close(); return r

def find_or_create_product(course_id,stream,semester,subject):
    x=db(); r=x.execute("""SELECT product_id FROM products WHERE course_id=? AND stream=? AND semester=? AND subject=?""",
                        (course_id,stream or "",int(semester),subject)).fetchone()
    if r: x.close(); return r[0]
    pid=uuid.uuid4().hex[:12]
    x.execute("""INSERT INTO products(product_id,course_id,stream,semester,subject,price,created_at)
                VALUES(?,?,?,?,?,?,?)""",(pid,course_id,stream or "",int(semester),subject,1,time.time()))
    x.commit(); x.close(); return pid

def set_file_id(product_id,file_id):
    x=db(); cur=x.execute("UPDATE products SET telegram_file_id=? WHERE product_id=?",(file_id,product_id)); x.commit(); ok=cur.rowcount>0; x.close(); return ok

def set_price(product_id,price):
    x=db(); cur=x.execute("UPDATE products SET price=? WHERE product_id=?",(int(price),product_id)); x.commit(); ok=cur.rowcount>0; x.close(); return ok

def mark_failed(order_id):
    x=db(); x.execute("UPDATE orders SET status='FAILED' WHERE order_id=? AND status='PENDING'",(order_id,)); x.commit(); x.close()

def create_order(chat_id,user,product_id):
    p=get_product(product_id)
    if not p or not p[7] or not p[6] or int(p[5]) < 1: return None
    oid="ORD-"+uuid.uuid4().hex[:12].upper()
    x=db(); x.execute("""INSERT INTO orders(order_id,chat_id,username,course_id,stream,semester,subject,product_id,price,currency,status,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (oid,chat_id,user.get("username",""),p[1],p[2],p[3],p[4],p[0],p[5],"XTR","PENDING",time.time()))
    x.commit(); x.close(); return oid,p

def mark_paid(order_id,charge_id):
    x=db(); x.execute("""UPDATE orders SET status='PAID',telegram_charge_id=?,paid_at=?,delivery_status='PENDING'
                         WHERE order_id=? AND status<>'PAID'""",(charge_id,time.time(),order_id)); x.commit()
    r=x.execute("SELECT order_id,chat_id,product_id FROM orders WHERE order_id=?",(order_id,)).fetchone(); x.close(); return r

def mark_delivery(order_id,status):
    x=db(); x.execute("UPDATE orders SET delivery_status=? WHERE order_id=?",(status,order_id)); x.commit(); x.close()

def my_purchases(chat_id):
    x=db(); rows=x.execute("""SELECT order_id,product_id,course_id,stream,semester,subject,price,paid_at
                              FROM orders WHERE chat_id=? AND status='PAID' ORDER BY paid_at DESC""",(chat_id,)).fetchall(); x.close(); return rows

def admin_products(limit=100):
    x=db(); rows=x.execute("""SELECT p.product_id,p.course_id,p.stream,p.semester,p.subject,p.price,
                              p.telegram_file_id,p.active,c.name FROM products p JOIN courses c ON c.course_id=p.course_id
                              ORDER BY c.name,p.semester,p.subject LIMIT ?""",(limit,)).fetchall(); x.close(); return rows

def admin_orders(status=None,day=None,limit=100):
    x=db(); q="""SELECT order_id,chat_id,username,course_id,stream,semester,subject,price,status,telegram_charge_id,created_at,delivery_status
                 FROM orders WHERE 1=1"""; params=[]
    if status: q+=" AND status=?"; params.append(status)
    if day: q+=" AND created_at>=? AND created_at<?"; params.extend(day)
    q+=" ORDER BY created_at DESC LIMIT ?"; params.append(limit)
    rows=x.execute(q,params).fetchall(); x.close(); return rows

def sales_stats():
    x=db()
    total_users=x.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_orders=x.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    paid=x.execute("SELECT COUNT(*) FROM orders WHERE status='PAID'").fetchone()[0]
    total=x.execute("SELECT COALESCE(SUM(price),0) FROM orders WHERE status='PAID'").fetchone()[0]
    start=time.time()-86400; month=time.localtime(); month_start=time.mktime((month.tm_year,month.tm_mon,1,0,0,0,0,0))
    today=x.execute("SELECT COALESCE(SUM(price),0) FROM orders WHERE status='PAID' AND paid_at>=?",(start,)).fetchone()[0]
    month_sales=x.execute("SELECT COALESCE(SUM(price),0) FROM orders WHERE status='PAID' AND paid_at>=?",(month_start,)).fetchone()[0]
    x.close(); return total_users,total_orders,paid,total,today,month_sales

def users_count(): x=db(); n=x.execute("SELECT COUNT(*) FROM users").fetchone()[0]; x.close(); return n

def all_users():
    x=db(); rows=x.execute("SELECT chat_id FROM users WHERE active=1").fetchall(); x.close(); return [r[0] for r in rows]

def deactivate_user(chat_id):
    x=db(); x.execute("UPDATE users SET active=0 WHERE chat_id=?",(chat_id,)); x.commit(); x.close()

def save_session(chat_id,state,data=""):
    x=db()
    if x.pg:
        x.execute("""INSERT INTO admin_sessions(chat_id,state,data,updated_at) VALUES(?,?,?,?)
                     ON CONFLICT(chat_id) DO UPDATE SET state=EXCLUDED.state,data=EXCLUDED.data,updated_at=EXCLUDED.updated_at""",
                  (chat_id,state,data,time.time()))
    else:
        x.execute("""INSERT INTO admin_sessions(chat_id,state,data,updated_at) VALUES(?,?,?,?)
                     ON CONFLICT(chat_id) DO UPDATE SET state=excluded.state,data=excluded.data,updated_at=excluded.updated_at""",
                  (chat_id,state,data,time.time()))
    x.commit(); x.close()

def get_session(chat_id):
    x=db(); r=x.execute("SELECT state,data FROM admin_sessions WHERE chat_id=?",(chat_id,)).fetchone(); x.close(); return r

def clear_session(chat_id):
    x=db(); x.execute("DELETE FROM admin_sessions WHERE chat_id=?",(chat_id,)); x.commit(); x.close()
