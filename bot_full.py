# -*- coding: utf-8 -*-
"""
PrenotaFacile - Full version (single-file)
Features: DB init, dynamic data, realistic availability, reminders, admin, backup,
UX handlers, waitlist, stats, multi-center support.

Dependencies: python-telegram-bot v20+, APScheduler optional (not used), sqlite3
Start: python bot.py
"""
import os
import sqlite3
import asyncio
import logging
import json
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Any
from io import StringIO

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)

# -------------------------
# Basic logger
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prenotafacile_full")

# -------------------------
# Load token helper
# -------------------------
def load_token() -> str:
    t = os.environ.get("BOT_TOKEN", "").strip()
    if t:
        return t
    candidate = os.path.join(os.path.dirname(__file__), "token.txt")
    if os.path.exists(candidate):
        with open(candidate, "r", encoding="utf-8") as f:
            t = f.read().strip()
            if t:
                return t
    logger.error("BOT token non trovato! Imposta BOT_TOKEN env var o crea token.txt")
    raise SystemExit(1)

TOKEN = load_token()

# -------------------------
# MODE: TEST / PRODUZIONE
# -------------------------
# Semplice switch: cambia qui oppure imposta env MODE=PRODUZIONE
MODE = os.environ.get("MODE", "TEST").strip().upper()  # "TEST" or "PRODUZIONE"
TEST_MODE = (MODE != "PRODUZIONE")

if TEST_MODE:
    REMINDER_TEST_SECONDS = 5           # reminder rapido per test (5s)
    REMINDER_BEFORE_MINUTES = 1         # simulate "minutes before" in tests
    SCAN_INTERVAL_SECONDS = 2           # background scanner interval (fast)
else:
    REMINDER_TEST_SECONDS = 0
    REMINDER_BEFORE_MINUTES = 60 * 24   # 1440 minutes = 24 hours default
    SCAN_INTERVAL_SECONDS = 60          # check every minute in prod

# -------------------------
# Admin & Build info
# -------------------------
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "1235501437"))  # inserito ID fornitoti
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "@Wineorange")
BUILD_VERSION = os.getenv("GITHUB_RUN_ID", "dev-local")

# -------------------------
# Database path & init
# -------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), "prenotafacile_full.db")

DB_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS centers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    timezone TEXT DEFAULT 'Europe/Rome',
    config_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS operators (
    id TEXT PRIMARY KEY, -- e.g. op_sara
    center_id INTEGER,
    name TEXT,
    work_start TEXT, -- "09:00"
    work_end TEXT,   -- "18:00"
    breaks_json TEXT DEFAULT '[]',
    FOREIGN KEY(center_id) REFERENCES centers(id)
);
CREATE TABLE IF NOT EXISTS services (
    code TEXT PRIMARY KEY, -- svc_manicure
    center_id INTEGER,
    title TEXT,
    duration_minutes INTEGER,
    price REAL,
    FOREIGN KEY(center_id) REFERENCES centers(id)
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE,
    name TEXT,
    phone TEXT,
    last_seen DATETIME
);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center_id INTEGER,
    operator_id TEXT,
    service_code TEXT,
    client_id INTEGER,
    date TEXT, -- YYYY-MM-DD
    time TEXT, -- HH:MM
    duration INTEGER,
    status TEXT DEFAULT 'CONFIRMED', -- CONFIRMED, CANCELLED, COMPLETED, NO_SHOW
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    reminder_sent INTEGER DEFAULT 0,
    FOREIGN KEY(center_id) REFERENCES centers(id),
    FOREIGN KEY(operator_id) REFERENCES operators(id),
    FOREIGN KEY(service_code) REFERENCES services(code),
    FOREIGN KEY(client_id) REFERENCES clients(id)
);
CREATE TABLE IF NOT EXISTS waitlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center_id INTEGER,
    service_code TEXT,
    requested_date TEXT,
    client_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP,
    level TEXT,
    message TEXT
);
CREATE TABLE IF NOT EXISTS stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center_id INTEGER,
    day TEXT,
    bookings_count INTEGER DEFAULT 0,
    cancellations_count INTEGER DEFAULT 0,
    no_shows INTEGER DEFAULT 0
);
"""

def db_conn():
    con = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db_conn()
    cur = con.cursor()
    cur.executescript(DB_SCHEMA)
    con.commit()
    con.close()
    logger.info("DB inizializzato/controllato.")

# -------------------------
# Utility DB helpers
# -------------------------

def create_center_if_missing(name: str = "Default Centro") -> int:
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT id FROM centers WHERE name=?", (name,))
    r = cur.fetchone()
    if r:
        cid = r["id"]
    else:
        cur.execute("INSERT INTO centers(name) VALUES(?)", (name,))
        cid = cur.lastrowid
        con.commit()
    con.close()
    return cid

def ensure_sample_data():
    """Popola DB con esempio (1 centro, 1 operatrice, qualche servizio) se vuoto."""
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM centers")
    if cur.fetchone()[0] == 0:
        cid = create_center_if_missing("Centro Demo")
        # sample operator
        cur.execute("INSERT OR REPLACE INTO operators(id, center_id, name, work_start, work_end) VALUES(?,?,?,?,?)",
                    ("op_sara", cid, "Sara", "09:00", "18:00"))
        # services
        cur.execute("INSERT OR REPLACE INTO services(code, center_id, title, duration_minutes, price) VALUES(?,?,?,?,?)",
                    ("svc_pulizia_viso", cid, "Pulizia viso", 45, 40.0))
        cur.execute("INSERT OR REPLACE INTO services(code, center_id, title, duration_minutes, price) VALUES(?,?,?,?,?)",
                    ("svc_manicure", cid, "Manicure", 30, 20.0))
        con.commit()
        logger.info("Dati di demo inseriti.")
    con.close()

# -------------------------
# Availability / slot generation
# -------------------------

def parse_hhmm(s: str) -> time:
    h, m = map(int, s.split(":"))
    return time(hour=h, minute=m)

def generate_slots_for_operator(operator_id: str, target_date: date) -> List[str]:
    """Genera slot liberi per l'operatrice in quel giorno (HH:MM). Non considera prenotazioni."""
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT * FROM operators WHERE id= ?", (operator_id,))
    op = cur.fetchone()
    if not op:
        con.close(); return []
    start = parse_hhmm(op["work_start"])
    end = parse_hhmm(op["work_end"])
    # default slot 30 min; services vary later when booking chosen
    slot_minutes = 30
    dt_start = datetime.combine(target_date, start)
    dt_end = datetime.combine(target_date, end)
    slots = []
    cur.execute("SELECT DISTINCT time FROM bookings WHERE operator_id=? AND date=? AND status='CONFIRMED'", (operator_id, target_date.isoformat()))
    taken = {r["time"] for r in cur.fetchall()}
    s = dt_start
    while s + timedelta(minutes=slot_minutes) <= dt_end:
        hhmm = s.strftime("%H:%M")
        if hhmm not in taken:
            slots.append(hhmm)
        s += timedelta(minutes=slot_minutes)
    con.close()
    return slots

def is_slot_available(operator_id: str, target_date: str, time_str: str) -> bool:
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM bookings WHERE operator_id=? AND date=? AND time=? AND status='CONFIRMED'",
                (operator_id, target_date, time_str))
    ok = (cur.fetchone()[0] == 0)
    con.close()
    return ok

# -------------------------
# Booking flow helpers
# -------------------------

def find_or_create_client(tg_id: int, name: Optional[str]=None, phone: Optional[str]=None) -> int:
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT id FROM clients WHERE tg_id=?", (tg_id,))
    r = cur.fetchone()
    if r:
        cid = r["id"]
        cur.execute("UPDATE clients SET last_seen=? WHERE id=?", (datetime.now(), cid))
    else:
        cur.execute("INSERT INTO clients(tg_id, name, phone, last_seen) VALUES(?,?,?,?)",
                    (tg_id, name or "", phone or "", datetime.now()))
        cid = cur.lastrowid
    con.commit(); con.close()
    return cid

def add_booking(center_id:int, operator_id:str, service_code:str, client_id:int, dstr:str, tstr:str, duration:int) -> int:
    con = db_conn(); cur = con.cursor()
    cur.execute("INSERT INTO bookings(center_id, operator_id, service_code, client_id, date, time, duration) VALUES(?,?,?,?,?,?,?)",
                (center_id, operator_id, service_code, client_id, dstr, tstr, duration))
    bid = cur.lastrowid
    con.commit(); con.close()
    logger.info(f"Nuova prenotazione {bid} {center_id}/{operator_id} {dstr} {tstr}")
    return bid

def cancel_booking(booking_id: int) -> bool:
    con = db_conn(); cur = con.cursor()
    cur.execute("UPDATE bookings SET status='CANCELLED' WHERE id=? AND status='CONFIRMED'", (booking_id,))
    ok = cur.rowcount > 0
    con.commit(); con.close()
    return ok

# -------------------------
# Waitlist module
# -------------------------

def add_to_waitlist(center_id:int, service_code:str, requested_date:str, client_id:int):
    con = db_conn(); cur = con.cursor()
    cur.execute("INSERT INTO waitlist(center_id, service_code, requested_date, client_id) VALUES(?,?,?,?)",
                (center_id, service_code, requested_date, client_id))
    con.commit(); con.close()
    logger.info("Cliente aggiunto in lista d'attesa.")

def pop_waitlist_and_notify(center_id:int, requested_date:str, application):
    """Se si libera slot per date, notifica i primi della lista."""
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT * FROM waitlist WHERE center_id=? AND requested_date=? ORDER BY created_at ASC", (center_id, requested_date))
    rows = cur.fetchall()
    notified = 0
    for w in rows:
        # get client tg id
        cur.execute("SELECT tg_id FROM clients WHERE id=?", (w["client_id"],))
        r = cur.fetchone()
        if r and r["tg_id"]:
            tg_id = r["tg_id"]
            try:
                asyncio.create_task(application.bot.send_message(
                    chat_id=int(tg_id),
                    text=f"📣 C'è uno slot libero il {requested_date} per il servizio {w['service_code']}. Vuoi prenotare? Usa /start"
                ))
                notified += 1
            except Exception as e:
                logger.warning("Impossibile notificare waitlist a %s: %s", tg_id, e)
        # after notifying, remove entry
        cur.execute("DELETE FROM waitlist WHERE id= ?", (w["id"],))
    con.commit(); con.close()
    return notified

# -------------------------
# Reminders background scanner
# -------------------------

async def reminder_scanner(application):
    """
    Periodically scans bookings and sends reminders for upcoming appointments.
    Uses REMINDER_BEFORE_MINUTES to determine when to alert (in test it's small).
    """
    while True:
        try:
            now = datetime.now()
            con = db_conn(); cur = con.cursor()
            # select upcoming confirmed bookings where reminder_sent=0
            cur.execute("SELECT b.*, c.tg_id, s.title FROM bookings b "
                        "LEFT JOIN clients c ON b.client_id=c.id "
                        "LEFT JOIN services s ON b.service_code=s.code "
                        "WHERE b.status='CONFIRMED' AND b.reminder_sent=0")
            rows = cur.fetchall()
            for r in rows:
                appt_dt = datetime.strptime(f"{r['date']} {r['time']}", "%Y-%m-%d %H:%M")
                minutes_before = (appt_dt - now).total_seconds() / 60.0
                # in test mode also allow REMINDER_TEST_SECONDS immediate triggers
                send = False
                if TEST_MODE and REMINDER_TEST_SECONDS > 0:
                    # if appointment within REMINDER_TEST_SECONDS seconds, send
                    if (appt_dt - now).total_seconds() <= REMINDER_TEST_SECONDS:
                        send = True
                else:
                    if minutes_before <= REMINDER_BEFORE_MINUTES and minutes_before >= 0:
                        send = True
                if send:
                    # send interactive reminder with confirm/cancel buttons
                    chat_id = r["tg_id"]
                    if chat_id:
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ Confermo", callback_data=f"confirm_{r['id']}"),
                             InlineKeyboardButton("❌ Disdico", callback_data=f"cancel_{r['id']}")]
                        ])
                        try:
                            await application.bot.send_message(
                                chat_id=int(chat_id),
                                text=(f"🔔 Promemoria: hai un appuntamento per *{r['title']}* "
                                      f"il {r['date']} alle {r['time']}. Confermi la presenza?"),
                                parse_mode=ParseMode.MARKDOWN,
                                reply_markup=kb
                            )
                            cur.execute("UPDATE bookings SET reminder_sent=1 WHERE id= ?", (r["id"],))
                            con.commit()
                            logger.info("Reminder inviato per booking %s", r["id"])
                        except Exception as e:
                            logger.warning("Errore invio reminder a %s: %s", chat_id, e)
            con.close()
        except Exception as e:
            logger.exception("Errore scanner reminder: %s", e)
            # notify admin of error
            try:
                await application.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"⚠️ Errore reminder scanner: {e}")
            except Exception:
                pass
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)

# -------------------------
# Backup routine
# -------------------------

async def backup_task():
    """Basic nightly backup: copies sqlite file to /backups folder with timestamp."""
    while True:
        try:
            await asyncio.sleep(60 * 60 * 6)  # every 6 hours
            now = datetime.now().strftime("%Y%m%d%H%M%S")
            backups_dir = os.path.join(os.path.dirname(__file__), "backups")
            os.makedirs(backups_dir, exist_ok=True)
            src = DB_PATH
            dst = os.path.join(backups_dir, f"prenotafacile_backup_{now}.db")
            try:
                with open(src, "rb") as fsrc:
                    with open(dst, "wb") as fdst:
                        fdst.write(fsrc.read())
                logger.info("Backup DB creato: %s", dst)
            except Exception as e:
                logger.warning("Impossibile creare backup DB: %s", e)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Errore backup_task: %s", e)
            await asyncio.sleep(60)

# -------------------------
# Admin notify on startup
# -------------------------

async def notify_admin_startup(application):
    mode_label = "🧪 TEST" if TEST_MODE else "🚀 PRODUZIONE"
    repo_link = os.getenv("GITHUB_REPO_URL", "")  # tu puoi impostare questa env var
    msg = (
        f"✅ *PrenotaFacile avviato!*\n"
        f"👤 Admin: {ADMIN_USERNAME}\n"
        f"⚙️ Modalità: *{mode_label}* (MODE={MODE})\n"
        f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"🏷 Build: `{BUILD_VERSION}`\n"
    )
    if repo_link:
        msg += f"🔗 Repo: {repo_link}\n"
    msg += f"🔔 Reminder test: {REMINDER_TEST_SECONDS}s | pre-appuntamento: {REMINDER_BEFORE_MINUTES} min"
    try:
        await application.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning("Impossibile inviare notifica startup all'admin: %s", e)

# -------------------------
# Basic commands & handlers (UX)
# -------------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # ensure client exists
    find_or_create_client(user.id, name=user.full_name)
    kb = [
        [InlineKeyboardButton("📅 Prenota un trattamento", callback_data="book_start")],
        [InlineKeyboardButton("📋 Le mie prenotazioni", callback_data="my_bookings")],
        [InlineKeyboardButton("ℹ️ Info centro", callback_data="info_center")],
    ]
    await update.message.reply_text(
        f"Ciao {user.first_name}! Benvenuto in *PrenotaFacile* — il tuo centro a portata di Telegram.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )

# Booking entry - simplified conversation via callback buttons
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "book_start":
        # show services for default center
        con = db_conn(); cur = con.cursor()
        cur.execute("SELECT id FROM centers LIMIT 1")
        center = cur.fetchone()
        if not center:
            await q.edit_message_text("Nessun centro configurato.")
            return
        center_id = center["id"]
        cur.execute("SELECT code, title, duration_minutes FROM services WHERE center_id= ?", (center_id,))
        services = cur.fetchall()
        kb = []
        for s in services:
            kb.append([InlineKeyboardButton(f"{s['title']} ({s['duration_minutes']}m)", callback_data=f"svc_{s['code']}")])
        kb.append([InlineKeyboardButton("⬅️ Annulla", callback_data="cancel_flow")])
        await q.edit_message_text("Scegli il trattamento:", reply_markup=InlineKeyboardMarkup(kb))
        con.close()
        return
    if data.startswith("svc_"):
        svc_code = data.split("svc_")[1]
        # select operators for center
        con = db_conn(); cur = con.cursor()
        cur.execute("SELECT * FROM operators LIMIT 5")
        ops = cur.fetchall()
        kb = []
        for op in ops:
            kb.append([InlineKeyboardButton(f"{op['name']}", callback_data=f"op_{op['id']}_svc_{svc_code}")])
        kb.append([InlineKeyboardButton("⬅️ Indietro", callback_data="book_start")])
        await q.edit_message_text("Scegli l'operatrice:", reply_markup=InlineKeyboardMarkup(kb))
        con.close()
        return
    if data.startswith("op_") and "_svc_" in data:
        parts = data.split("_svc_")
        op_part = parts[0]  # op_opid
        svc_code = parts[1]
        op_id = op_part[len("op_"):]
        # show slots for next 7 days
        slots_kb = []
        for i in range(0, 7):
            d = date.today() + timedelta(days=i)
            slots = generate_slots_for_operator(op_id, d)
            if slots:
                btns = [InlineKeyboardButton(f"{d.strftime('%d %b')}", callback_data=f"date_{d.isoformat()}_op_{op_id}_svc_{svc_code}")]
                slots_kb.append(btns)
        if not slots_kb:
            await q.edit_message_text("Nessuno slot disponibile nei prossimi 7 giorni. Vuoi essere inserita in lista d'attesa?",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Sì, aggiungimi", callback_data=f"wait_{svc_code}")],
                                                                         [InlineKeyboardButton("No, grazie", callback_data="cancel_flow")]]))
            con = db_conn(); con.close(); return
        await q.edit_message_text("Scegli giorno:", reply_markup=InlineKeyboardMarkup(slots_kb))
        return
    if data.startswith("date_") and "_op_" in data and "_svc_" in data:
        # data_{date}_op_{opid}_svc_{svc_code}
        left, rest = data.split("_op_")
        date_s = left[len("date_"):]
        op_and_svc = rest.split("_svc_")
        op_id = op_and_svc[0]
        svc_code = op_and_svc[1]
        # provide available times for that day
        slots = generate_slots_for_operator(op_id, date.fromisoformat(date_s))
        kb = []
        for t in slots[:8]:  # limit choices
            kb.append([InlineKeyboardButton(t, callback_data=f"time_{date_s}_{t}_op_{op_id}_svc_{svc_code}")])
        await q.edit_message_text("Scegli orario:", reply_markup=InlineKeyboardMarkup(kb))
        return
    if data.startswith("time_") and "_op_" in data and "_svc_" in data:
        # time_{date}_{time}_op_{opid}_svc_{svc}
        parts = data.split("_op_")
        left = parts[0][len("time_"):]
        op_and_svc = parts[1].split("_svc_")
        op_id = op_and_svc[0]
        svc_code = op_and_svc[1]
        date_part, time_part = left.split("_")
        # create booking
        user = update.effective_user
        client_id = find_or_create_client(user.id, name=user.full_name)
        # get service duration
        con = db_conn(); cur = con.cursor()
        cur.execute("SELECT duration_minutes FROM services WHERE code= ?", (svc_code,))
        svc = cur.fetchone()
        duration = svc["duration_minutes"] if svc else 30
        # verify slot availability
        if not is_slot_available(op_id, date_part, time_part):
            await update.callback_query.answer("Slot non più disponibile.", show_alert=True)
            con.close(); return
        center_id = 1
        cur.execute("SELECT id FROM centers LIMIT 1")
        r = cur.fetchone()
        if r:
            center_id = r["id"]
        bid = add_booking(center_id, op_id, svc_code, client_id, date_part, time_part, duration)
        con.close()
        # reply confirmation
        await update.callback_query.edit_message_text(f"✅ Prenotazione confermata per il {date_part} alle {time_part}. ID: {bid}")
        # schedule immediate follow-up if test mode small
        return
    if data.startswith("confirm_"):
        bid = int(data.split("confirm_")[1])
        # mark confirmed (already confirmed by default) but we can mark presence upon confirmation
        await update.callback_query.edit_message_text("✅ Grazie! La tua presenza è confermata.")
        return
    if data.startswith("cancel_"):
        bid = int(data.split("cancel_")[1])
        ok = cancel_booking(bid)
        if ok:
            await update.callback_query.edit_message_text("❌ Prenotazione annullata. Se vuoi, ti inserisco in lista d'attesa per questa giornata.")
        else:
            await update.callback_query.edit_message_text("Impossibile annullare (forse era già annullata).")
        return
    if data == "my_bookings":
        # list bookings for user
        user = update.effective_user
        con = db_conn(); cur = con.cursor()
        cur.execute("SELECT id FROM clients WHERE tg_id= ?", (user.id,))
        r = cur.fetchone()
        if not r:
            await update.callback_query.edit_message_text("Non hai prenotazioni.")
            con.close(); return
        client_id = r["id"]
        cur.execute("SELECT * FROM bookings WHERE client_id=? AND status='CONFIRMED' ORDER BY date,time", (client_id,))
        rows = cur.fetchall()
        if not rows:
            await update.callback_query.edit_message_text("Nessuna prenotazione attiva.")
            con.close(); return
        txt = "Le tue prenotazioni:\n"
        for b in rows:
            txt += f"- ID {b['id']}: {b['date']} {b['time']} (svc:{b['service_code']})\n"
        await update.callback_query.edit_message_text(txt)
        con.close()
        return
    if data == "cancel_flow":
        await update.callback_query.edit_message_text("Flow annullato. Usa /start per ripartire.")
        return
    # fallback
    await update.callback_query.answer()

# -------------------------
# Admin commands (basic)
# -------------------------

def is_admin_user(uid: int) -> bool:
    return uid == ADMIN_CHAT_ID

async def admin_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin_user(uid):
        await update.message.reply_text("Accesso negato.")
        return
    today = date.today().isoformat()
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT * FROM bookings WHERE date=? ORDER BY time", (today,))
    rows = cur.fetchall()
    out = f"Prenotazioni oggi ({today}):\n"
    for r in rows:
        out += f"- ID {r['id']} {r['operator_id']} {r['time']} svc:{r['service_code']} client:{r['client_id']}\n"
    await update.message.reply_text(out)
    con.close()

async def export_csv_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin_user(uid):
        await update.message.reply_text("Accesso negato.")
        return
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT * FROM bookings ORDER BY date,time")
    rows = cur.fetchall()
    si = StringIO()
    si.write("id,center_id,operator_id,service_code,client_id,date,time,duration,status,created_at\n")
    for r in rows:
        si.write(f"{r['id']},{r['center_id']},{r['operator_id']},{r['service_code']},{r['client_id']},{r['date']},{r['time']},{r['duration']},{r['status']},{r['created_at']}\n")
    si.seek(0)
    await update.message.reply_document(document=si.getvalue().encode("utf-8"), filename="bookings_export.csv")
    con.close()

# -------------------------
# Error handler: central reporting
# -------------------------

async def global_error_handler(update_or_none, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled exception: %s", context.error)
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"⚠️ Errore non gestito: {context.error}")
    except Exception:
        logger.warning("Impossibile inviare notifica errore all'admin.")

# -------------------------
# Stats & reports generator
# -------------------------

def daily_stats_snapshot():
    con = db_conn(); cur = con.cursor()
    today = date.today().isoformat()
    cur.execute("SELECT COUNT(*) FROM bookings WHERE date=? AND status='CONFIRMED'", (today,))
    bookings = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM bookings WHERE date=? AND status='CANCELLED'", (today,))
    canc = cur.fetchone()[0]
    con.close()
    return {"date": today, "bookings": bookings, "cancellations": canc}

async def send_daily_report(application):
    stats = daily_stats_snapshot()
    text = (f"📊 Report Giornaliero {stats['date']}\n"
            f"Prenotazioni: {stats['bookings']}\n"
            f"Cancellazioni: {stats['cancellations']}\n")
    try:
        await application.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)
    except Exception as e:
        logger.warning("Impossibile inviare report giornaliero: %s", e)

# -------------------------
# Main entry
# -------------------------

async def main():
    init_db()
    ensure_sample_data()

    application = ApplicationBuilder().token(TOKEN).build()

    # register handlers
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(CommandHandler("admin_today", admin_today))
    application.add_handler(CommandHandler("export_csv", export_csv_cmd))
    application.add_error_handler(global_error_handler)

    # notify admin startup
    await notify_admin_startup(application)

    # start background tasks: reminder scanner and backup and daily report
    loop = asyncio.get_running_loop()
    loop.create_task(reminder_scanner(application))
    loop.create_task(backup_task())
    # daily report at 20:00 server time (simple loop)
    async def daily_report_loop():
        while True:
            now = datetime.now()
            target = now.replace(hour=20, minute=0, second=0, microsecond=0)
            if now > target:
                target += timedelta(days=1)
            await asyncio.sleep((target - now).total_seconds())
            await send_daily_report(application)
    loop.create_task(daily_report_loop())

    logger.info("PrenotaFacile full: avvio polling...")
    await application.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Arresto manuale.")
