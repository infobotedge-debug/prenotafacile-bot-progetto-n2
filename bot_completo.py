# -*- coding: utf-8 -*-
"""
PrenotaFacile – Minimal

Dipendenze: vedi requirements.txt
Avvio: scripts/start_polling.ps1 (Windows)
"""
import os, calendar, sqlite3, asyncio, logging
from datetime import datetime, date, time, timedelta
from typing import List
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ITALIAN_MONTHS = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
]
ITALIAN_WEEKDAYS_SHORT = ["Lu","Ma","Me","Gi","Ve","Sa","Do"]
ITALIAN_WEEKDAYS_FULL = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"]

BUILD_VERSION = f"PrenotaFacile minimal ({datetime.now().strftime('%Y-%m-%d %H:%M')})"

# Config token

def load_token() -> str:
    t = os.environ.get("BOT_TOKEN", "").strip()
    if t:
        return "".join(ch for ch in t if ch.isprintable()).strip().strip("\"'\u200b\u200c\u200d")
    candidate = os.path.abspath(os.path.join(os.path.dirname(__file__), "token.txt"))
    if os.path.exists(candidate):
        with open(candidate, "r", encoding="utf-8") as f:
            t = f.read()
            if t:
                return "".join(ch for ch in t if ch.isprintable()).strip().strip("\"'\u200b\u200c\u200d")
    logger.error("BOT token non trovato: imposta BOT_TOKEN o crea token.txt nella root del progetto.")
    raise SystemExit(1)

TOKEN = load_token()

DB_PATH = "prenotafacile.db"
SLOT_MINUTES = 30
REMINDER_TEST_SECONDS = 30
try:
    REMINDER_AFTER_CONFIRM_SECONDS = int(os.environ.get("REMINDER_AFTER_CONFIRM_SECONDS", "30"))
except Exception:
    REMINDER_AFTER_CONFIRM_SECONDS = 30
REMINDER_QUICK_TEST = os.environ.get("REMINDER_QUICK_TEST", "1").lower() in {"1","true","yes"}

ORARI_SETTIMANA = {
    0: [("09:00","13:00"),("15:00","19:00")],
    1: [("09:00","13:00"),("15:00","19:00")],
    2: [("09:00","13:00"),("15:00","19:00")],
    3: [("09:00","13:00"),("15:00","19:00")],
    4: [("09:00","13:00"),("15:00","19:00")],
    5: [("09:00","13:00")],
    6: []
}

OPERATRICI = [
    {"id":"op_anna","name":"Anna"},
    {"id":"op_luca","name":"Luca"},
    {"id":"op_maria","name":"Maria"},
]

SERVIZI = {
    "Donna": {
        "Trattamenti Viso": [
            {"code":"d_pulizia_viso","nome":"Pulizia del viso","durata":60,"prezzo":40},
            {"code":"d_antiage","nome":"Trattamento anti-age","durata":75,"prezzo":60},
        ],
        "Unghie": [
            {"code":"d_manicure","nome":"Manicure classica","durata":40,"prezzo":20},
        ],
    },
    "Uomo": {
        "Trattamenti Viso": [
            {"code":"u_pulizia_viso","nome":"Pulizia del viso uomo","durata":60,"prezzo":40},
        ]
    }
}

# DB

def db_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    con = db_conn(); cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            phone TEXT,
            notes TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            service_code TEXT,
            service_name TEXT,
            date TEXT,
            time TEXT,
            duration INTEGER,
            operator_id TEXT,
            price REAL,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            service_code TEXT,
            created_at TEXT
        )
    """)
    con.commit(); con.close()

# Utils calendario

# ------------------------
# LISTA D'ATTESA - helper
# ------------------------
async def join_waitlist(user_id: int, date_str: str, svc_code: str):
    """Aggiunge l'utente alla lista d'attesa per una data e un servizio."""
    con = db_conn()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO waitlist (user_id, date, service_code, created_at) VALUES (?,?,?,?)",
        (user_id, date_str, svc_code, datetime.utcnow().isoformat()),
    )
    con.commit()
    con.close()

# ------------------------
# UTENTE - SALVATAGGIO E AGGIORNAMENTO
# ------------------------
def save_or_update_user(user_id: int, username: str | None = None, name: str | None = None, phone: str | None = None, notes: str | None = None):
    """Salva o aggiorna i dati utente in modo robusto."""
    con = db_conn()
    cur = con.cursor()
    # Inserisce solo se non esiste
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username, name, phone, notes) VALUES (?,?,?,?,?)",
        (user_id, username, name, phone, notes),
    )
    # Aggiorna dati esistenti
    cur.execute(
        "UPDATE users SET username=?, name=?, phone=?, notes=? WHERE user_id=?",
        (username, name, phone, notes, user_id),
    )
    con.commit()
    con.close()

def parse_time_hhmm(s: str) -> time:
    h, m = map(int, s.split(":")); return time(hour=h, minute=m)

def datetime_from_date_time_str(date_str: str, time_str: str) -> datetime:
    d = datetime.strptime(date_str, "%Y-%m-%d").date(); t = parse_time_hhmm(time_str); return datetime.combine(d, t)

def list_all_slots_for_day(d: date, durata: int) -> List[str]:
    wd = d.weekday(); ranges = ORARI_SETTIMANA.get(wd, []); slots = []
    for start_s, end_s in ranges:
        start_dt = datetime.combine(d, parse_time_hhmm(start_s)); end_dt = datetime.combine(d, parse_time_hhmm(end_s))
        cur = start_dt
        while cur + timedelta(minutes=durata) <= end_dt:
            slots.append(cur.time().strftime("%H:%M")); cur = cur + timedelta(minutes=SLOT_MINUTES)
    return slots

def is_slot_free_for_operator(date_str: str, time_str: str, durata: int, operator_id: str) -> bool:
    con = db_conn()
    try:
        con.execute("BEGIN IMMEDIATE")
    except Exception:
        pass
    cur = con.cursor(); cur.execute("SELECT time, duration, operator_id, date FROM bookings WHERE date=? AND operator_id=?", (date_str, operator_id))
    exs = cur.fetchall(); con.close()
    new_start = datetime_from_date_time_str(date_str, time_str); new_end = new_start + timedelta(minutes=durata)
    for t, d, op, dat in exs:
        ex_start = datetime_from_date_time_str(dat, t); ex_end = ex_start + timedelta(minutes=d)
        if not (new_end <= ex_start or new_start >= ex_end):
            return False
    return True

def free_slots_for_operator(d: date, durata: int, operator_id: str) -> List[str]:
    ds = d.strftime("%Y-%m-%d"); all_slots = list_all_slots_for_day(d, durata); return [s for s in all_slots if is_slot_free_for_operator(ds, s, durata, operator_id)]

def day_status_symbol(d: date, durata: int) -> str:
    ranges = ORARI_SETTIMANA.get(d.weekday(), [])
    if not ranges: return ""
    for op in OPERATRICI:
        if free_slots_for_operator(d, durata, op["id"]): return "🟢"
    return "🔴"

# States
(ASK_GENDER, ASK_CATEGORY, ASK_SERVICE, ASK_OPERATOR, ASK_MONTH, ASK_DAY, ASK_TIME, ASK_NAME, ASK_PHONE, ASK_NOTES, CONFIRM) = range(11)

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user: context.user_data["username"] = getattr(user, "username", None)
    kb = [[InlineKeyboardButton("👩 Donna", callback_data="gender_Donna"), InlineKeyboardButton("👨 Uomo", callback_data="gender_Uomo")],
          [InlineKeyboardButton("📆 Le mie prenotazioni", callback_data="my_bookings")],
          [InlineKeyboardButton("ℹ️ Help", callback_data="help")]]
    await update.message.reply_text("Benvenuto in *PrenotaFacile* — scegli il profilo:", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
    return ASK_GENDER

async def menu_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data
    if data == "ignore": return
    if data == "help":
        await q.edit_message_text("Aiuto: usa /start per ricominciare.\nLegenda: 🟢 giorno con disponibilità · 🔴 giorno pieno · ❌ orario occupato.\nUsa ⬅️ per tornare."); return
    if data == "my_bookings": await show_my_bookings(update, context, via_callback=True); return
    if data.startswith("gender_"):
        gender = data.split("_",1)[1]; context.user_data["gender"] = gender
        cats = list(SERVIZI[gender].keys()); kb = [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in cats]
        kb.append([InlineKeyboardButton("🏠 Menu", callback_data="home")])
        await q.edit_message_text(f"Profilo: *{gender}*\nScegli una categoria:", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN); return ASK_CATEGORY
    if data == "home":
        kb = [[InlineKeyboardButton("👩 Donna", callback_data="gender_Donna"), InlineKeyboardButton("👨 Uomo", callback_data="gender_Uomo")],
              [InlineKeyboardButton("📆 Le mie prenotazioni", callback_data="my_bookings")],
              [InlineKeyboardButton("ℹ️ Help", callback_data="help")]]
        await q.edit_message_text("Menu principale:", reply_markup=InlineKeyboardMarkup(kb)); return ASK_GENDER
    if data.startswith("cat_"):
        cat = data.split("_",1)[1]; context.user_data["category"] = cat; gender = context.user_data.get("gender","Donna")
        items = SERVIZI[gender][cat]; kb = [[InlineKeyboardButton(it["nome"], callback_data=f"svc_{it['code']}")] for it in items]
        kb.append([InlineKeyboardButton("⬅️ Indietro", callback_data=f"gender_{gender}")])
        await q.edit_message_text(f"Categoria: *{cat}*\nScegli un trattamento:", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN); return ASK_SERVICE
    if data.startswith("svc_"):
        code = data.split("_",1)[1]; svc = find_service_by_code(code)
        if not svc: await q.edit_message_text("Servizio non trovato."); return ASK_SERVICE
        context.user_data["service"] = svc
        kb = [[InlineKeyboardButton(op["name"], callback_data=f"op_{op['id']}")] for op in OPERATRICI]
        kb.append([InlineKeyboardButton("⬅️ Indietro", callback_data=f"cat_{context.user_data['category']}")])
        await q.edit_message_text(f"Hai scelto *{svc['nome']}* ({svc['durata']} min)\nSeleziona l'operatrice/operatore:", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN); return ASK_OPERATOR
    if data.startswith("op_"):
        op_id = data.split("_",1)[1]; context.user_data["operator_id"] = op_id
        today = date.today(); await show_calendar_month(q, context, today.year, today.month); return ASK_MONTH
    if data.startswith("cal_"):
        parts = data.split("_")
        if len(parts) >= 3:
            year = int(parts[1])
            month = int(parts[2])
            action = parts[3] if len(parts) > 3 else ""
            if action == "prev":
                m = month - 1
                y = year
                if m < 1:
                    m = 12
                    y -= 1
                await show_calendar_month(q, context, y, m)
                return ASK_MONTH
            elif action == "next":
                m = month + 1
                y = year
                if m > 12:
                    m = 1
                    y += 1
                await show_calendar_month(q, context, y, m)
                return ASK_MONTH
            else:
                await show_calendar_month(q, context, year, month)
                return ASK_MONTH
    if data.startswith("pickmonths_"):
        parts = data.split("_")
        if len(parts) >= 3:
            year = int(parts[1]); month = int(parts[2]); await show_month_picker(q, context, year, month)
        else:
            year = int(parts[1]) if len(parts)>1 else date.today().year; await show_month_picker(q, context, year, 1)
        return ASK_MONTH
    if data.startswith("day_"):
        date_str = data.split("_", 1)[1]
        context.user_data["date"] = date_str
        svc = context.user_data.get("service")
        op_id = context.user_data.get("operator_id")
        if not svc or not op_id:
            await q.edit_message_text("Sessione scaduta. Premi /start")
            return ConversationHandler.END
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        free = free_slots_for_operator(d, svc["durata"], op_id)
        if free:
            kb = [[InlineKeyboardButton(t, callback_data=f"time_{t}")] for t in free]
            kb.append([InlineKeyboardButton("⬅️ Indietro", callback_data=f"cal_{d.year}_{d.month}")])
            # Mantieni i nomi dei giorni in italiano
            weekday_it = ITALIAN_WEEKDAYS_FULL[d.weekday()]
            await q.edit_message_text(
                f"Data: *{weekday_it} {d.strftime('%d/%m/%Y')}*\nScegli un orario disponibile:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode=ParseMode.MARKDOWN,
            )
            return ASK_TIME
        else:
            # Giorno pieno -> proponi la lista d'attesa
            kb = [
                [InlineKeyboardButton("🕰️ Entra in lista d'attesa", callback_data="waitlist_join")],
                [InlineKeyboardButton("⬅️ Indietro", callback_data=f"cal_{d.year}_{d.month}")],
            ]
            await q.edit_message_text(
                "🔴 Questo giorno è pieno per l'operatrice scelta.\nVuoi entrare in lista d'attesa?",
                reply_markup=InlineKeyboardMarkup(kb),
            )
            return ASK_DAY
    if data == "waitlist_join":
        user = q.from_user
        date_str = context.user_data.get("date")
        svc = context.user_data.get("service")
        if not date_str or not svc:
            await q.edit_message_text("Sessione scaduta. Premi /start")
            return ConversationHandler.END
        await join_waitlist(user.id, date_str, svc["code"])  # helper
        await q.edit_message_text("✅ Inserito in lista d'attesa. Ti notificheremo se si libera uno slot.")
        return ConversationHandler.END
    if data.startswith("time_"):
        time_str = data.split("_",1)[1]; context.user_data["time"] = time_str
        await q.edit_message_text("Perfetto. Inserisci *Nome e Cognome*:", parse_mode=ParseMode.MARKDOWN); return ASK_NAME
    if data.startswith("accept_slot_"):
        payload = data[len("accept_slot_"):]
        try:
            date_str, time_str, op_id, svc_code = payload.split("_",3)
        except Exception:
            await q.edit_message_text("Dati slot non validi."); return
        svc = find_service_by_code(svc_code)
        if not svc: await q.edit_message_text("Servizio non valido."); return
        if is_slot_free_for_operator(date_str, time_str, svc["durata"], op_id):
            await finalize_booking_from_accept(q.from_user.id, context, svc, date_str, time_str, op_id)
            await q.edit_message_text("✅ Slot assegnato a te! Controlla le tue prenotazioni.")
        else:
            await q.edit_message_text("❌ Lo slot è già stato preso da un altro.")
        return
    if data.startswith("cancel_"):
        booking_id = int(data.split("_",1)[1]); await cancel_booking(update, context, booking_id); return
    try:
        await q.edit_message_text("Sessione aggiornata. Usa /start per ripartire.")
    except Exception:
        pass

# UI calendario
async def show_calendar_month(q, context, year, month):
    calendar.setfirstweekday(calendar.MONDAY)
    svc = context.user_data.get("service"); durata = svc["durata"] if svc else 30
    m = calendar.monthcalendar(year, month); kb = []
    header = [InlineKeyboardButton(d, callback_data="ignore") for d in ITALIAN_WEEKDAYS_SHORT]; kb.append(header)
    today = date.today()
    for week in m:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                ddate = date(year, month, day); wd = ddate.weekday(); ranges = ORARI_SETTIMANA.get(wd, []); is_closed = not ranges; is_today = (ddate == today)
                symbol = day_status_symbol(ddate, durata) if not is_closed else ""; base_label = f"{day}"; 
                if is_today: base_label = f"[{day}]"; label = f"{base_label} {symbol}".strip()
                if is_closed: row.append(InlineKeyboardButton("—", callback_data="ignore"))
                else: row.append(InlineKeyboardButton(label, callback_data=f"day_{ddate.strftime('%Y-%m-%d')}"))
        kb.append(row)
    prev_month = month-1; prev_year = year; 
    if prev_month < 1: prev_month = 12; prev_year -= 1
    next_month = month+1; next_year = year; 
    if next_month > 12: next_month = 1; next_year += 1
    kb.append([
        InlineKeyboardButton("⬅️ Mese prec.", callback_data=f"cal_{prev_year}_{prev_month}_prev"),
        InlineKeyboardButton("📅 12 mesi", callback_data=f"pickmonths_{year}_{month}"),
        InlineKeyboardButton("Mese succ. ➡️", callback_data=f"cal_{next_year}_{next_month}_next")
    ])
    legend_text = "Legenda: 🟢 giorno con disponibilità · 🔴 giorno pieno"
    month_name_it = ITALIAN_MONTHS[month-1]
    await q.edit_message_text(f"*{month_name_it} {year}*\n\n{legend_text}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def show_month_picker(q, context, year: int, start_month: int | None = None):
    today = date.today()
    if start_month is None: year, start_month = today.year, today.month
    def add_months(y: int, m: int, delta: int) -> tuple[int, int]:
        nm = m + delta; y += (nm - 1) // 12; m2 = ((nm - 1) % 12) + 1; return y, m2
    kb = []; row = []
    for offset in range(12):
        y, m = add_months(year, start_month, offset); label = f"{ITALIAN_MONTHS[m-1]} {y}"
        row.append(InlineKeyboardButton(label, callback_data=f"cal_{y}_{m}"))
        if len(row) == 3: kb.append(row); row = []
    if row: kb.append(row)
    prev_y, prev_m = add_months(year, start_month, -12); next_y, next_m = add_months(year, start_month, +12)
    kb.append([
        InlineKeyboardButton("⬅️ 12 mesi prec.", callback_data=f"pickmonths_{prev_y}_{prev_m}"),
        InlineKeyboardButton("🏠 Menu", callback_data="home"),
        InlineKeyboardButton("12 mesi succ. ➡️", callback_data=f"pickmonths_{next_y}_{next_m}")
    ])
    header = f"Seleziona mese - da {ITALIAN_MONTHS[start_month-1]} {year}"
    await q.edit_message_text(f"*{header}*", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

# Flusso dati
async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    user = update.effective_user
    if user: context.user_data["username"] = getattr(user, "username", None)
    await update.message.reply_text("Inserisci il tuo numero di telefono (o scrivi 'salta'):"); return ASK_PHONE

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip(); 
    if phone.lower() == "salta": phone = None
    context.user_data["phone"] = phone
    await update.message.reply_text("Note (opzionali)? Scrivi 'no' per saltare:"); return ASK_NOTES

async def ask_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = update.message.text.strip(); 
    if notes.lower() == "no": notes = None
    context.user_data["notes"] = notes
    svc = context.user_data["service"]; date_str = context.user_data["date"]; time_str = context.user_data["time"]; op_id = context.user_data.get("operator_id")
    text = (f"Riepilogo:\n• Servizio: *{svc['nome']}* ({svc['durata']} min)\n"
            f"• Operatrice: *{operator_name(op_id)}*\n"
            f"• Data: *{datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')}*\n"
            f"• Ora: *{time_str}*\n"
            f"• Nome: *{context.user_data.get('name')}*\n"
            f"• Tel: *{context.user_data.get('phone') or '—'}*\n"
            f"• Username: *{context.user_data.get('username') or '—'}*\n"
            f"• Note: *{notes or '—'}*\n\nConfermi la prenotazione?")
    kb = [[InlineKeyboardButton("✅ Conferma", callback_data="confirm_yes"), InlineKeyboardButton("❌ Annulla", callback_data="confirm_no")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN); return CONFIRM

async def confirm_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "confirm_no":
        try: await q.edit_message_text("Prenotazione annullata. /start")
        except Exception: pass
        try: await q.answer("Operazione annullata", show_alert=False)
        except Exception: pass
        return ConversationHandler.END
    if q.data == "confirm_yes":
        svc = context.user_data.get("service"); date_str = context.user_data.get("date"); time_str = context.user_data.get("time"); op_id = context.user_data.get("operator_id")
        if not svc or not date_str or not time_str:
            await q.answer("Sessione scaduta o già gestita", show_alert=False)
            try: await q.edit_message_text("Sessione scaduta. /start")
            except Exception: pass
            return ConversationHandler.END
        if not is_slot_free_for_operator(date_str, time_str, svc["durata"], op_id):
            d = datetime.strptime(date_str, "%Y-%m-%d").date(); free = free_slots_for_operator(d, svc["durata"], op_id)
            if free:
                kb = [[InlineKeyboardButton(t, callback_data=f"time_{t}")] for t in free]; kb.append([InlineKeyboardButton("⬅️ Indietro", callback_data=f"cal_{d.year}_{d.month}")])
                weekday_it = ITALIAN_WEEKDAYS_FULL[d.weekday()]
                await q.edit_message_text(
                    f"❌ Ops! Lo slot selezionato è appena stato preso.\n"
                    f"Data: *{weekday_it} {d.strftime('%d/%m/%Y')}*\n"
                    f"Scegli un altro orario disponibile:",
                    reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN,
                )
                return ASK_TIME
            else:
                await q.edit_message_text("❌ Ops! Non ci sono più orari disponibili in questo giorno per l'operatrice scelta.")
                return ConversationHandler.END
        await finalize_booking(q, context, svc, date_str, time_str, op_id, from_waitlist=False)
        await q.edit_message_text("✅ Prenotazione confermata!\nRiceverai un promemoria poco prima.")
        return ConversationHandler.END

async def show_my_bookings(update_or_cb, context: ContextTypes.DEFAULT_TYPE, via_callback=False):
    user = update_or_cb.callback_query.from_user if via_callback else update_or_cb.message.from_user
    con = db_conn(); cur = con.cursor(); cur.execute("SELECT id, service_name, date, time, duration, operator_id FROM bookings WHERE user_id=? ORDER BY date, time", (user.id,)); rows = cur.fetchall(); con.close()
    if not rows:
        if via_callback: await update_or_cb.callback_query.edit_message_text("Non hai prenotazioni attive.")
        else: await update_or_cb.message.reply_text("Non hai prenotazioni attive."); return
    lines = []; kb = []
    for bid, sname, d, t, dur, op in rows:
        lines.append(f"• [{bid}] {sname} – {datetime.strptime(d,'%Y-%m-%d').strftime('%d/%m/%Y')} {t} ({dur} min) - {operator_name(op)}")
        kb.append([InlineKeyboardButton(f"❌ Disdici [{bid}]", callback_data=f"cancel_{bid}")])
    text = "*Le tue prenotazioni:*\n" + "\n".join(lines)
    if via_callback: await update_or_cb.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
    else: await update_or_cb.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

# Operatrici

def operator_name(op_id: str) -> str:
    for op in OPERATRICI:
        if op["id"] == op_id: return op["name"]
    return "—"

# Prenotazione / Disdetta / Waitlist
async def finalize_booking(cb_or_update, context: ContextTypes.DEFAULT_TYPE, svc, date_str, time_str, op_id, from_waitlist=False):
    user_obj = cb_or_update.callback_query.from_user if hasattr(cb_or_update, "callback_query") else cb_or_update
    if isinstance(user_obj, int): user_id = user_obj; username = None
    else: user_id = user_obj.id; username = getattr(user_obj, "username", None) or context.user_data.get("username")
    # Salva/aggiorna dati utente in modo centralizzato
    save_or_update_user(
        user_id=user_id,
        username=username,
        name=context.user_data.get("name"),
        phone=context.user_data.get("phone"),
        notes=context.user_data.get("notes"),
    )
    con = db_conn(); cur = con.cursor()
    cur.execute("""INSERT INTO bookings (user_id, service_code, service_name, date, time, duration, operator_id, price, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""", (user_id, svc["code"], svc["nome"], date_str, time_str, svc["durata"], op_id, svc.get("prezzo", 0.0), datetime.utcnow().isoformat()))
    booking_id = cur.lastrowid; con.commit(); con.close(); logger.info(f"Booking saved: id={booking_id} user={user_id} svc={svc['code']} date={date_str} time={time_str} op={op_id}")
    appt_dt = datetime_from_date_time_str(date_str, time_str); remind_at = appt_dt - timedelta(seconds=REMINDER_TEST_SECONDS); delay = (remind_at - datetime.now()).total_seconds();
    if delay < 1: delay = 1
    try: context.application.job_queue.run_once(send_reminder_job, when=delay, data={"user_id": user_id, "service_name": svc["nome"], "date_str": date_str, "time_str": time_str})
    except Exception: asyncio.create_task(reminder_background(delay, user_id, svc["nome"], date_str, time_str, context))
    if REMINDER_AFTER_CONFIRM_SECONDS and REMINDER_AFTER_CONFIRM_SECONDS > 0:
        try:
            context.application.job_queue.run_once(send_post_confirm_reminder_job, when=REMINDER_AFTER_CONFIRM_SECONDS, data={"user_id": user_id, "service_name": svc['nome'], "date_str": date_str, "time_str": time_str})
        except Exception as e:
            logger.warning("Failed to schedule post-confirm reminder: %s", e)
    if delay > 90 and REMINDER_QUICK_TEST and (not REMINDER_AFTER_CONFIRM_SECONDS or REMINDER_AFTER_CONFIRM_SECONDS <= 0):
        try:
            context.application.job_queue.run_once(send_reminder_job, when=30, data={"user_id": user_id, "service_name": f"{svc['nome']} (TEST)", "date_str": date.today().strftime('%Y-%m-%d'), "time_str": datetime.now().strftime('%H:%M')})
        except Exception as e:
            logger.warning("Failed to schedule quick test reminder: %s", e)
    if from_waitlist:
        con = db_conn(); cur = con.cursor(); cur.execute("DELETE FROM waitlist WHERE user_id=? AND date=? AND service_code= ?", (user_id, date_str, svc["code"]))
        con.commit(); con.close()

async def finalize_booking_from_accept(user_id: int, context: ContextTypes.DEFAULT_TYPE, svc, date_str: str, time_str: str, op_id: str):
    try:
        chat = await context.application.bot.get_chat(user_id); username = getattr(chat, "username", None)
    except Exception: username = None
    con = db_conn(); cur = con.cursor();
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (user_id, username))
    cur.execute("""INSERT INTO bookings (user_id, service_code, service_name, date, time, duration, operator_id, price, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""", (user_id, svc["code"], svc["nome"], date_str, time_str, svc["durata"], op_id, svc.get("prezzo",0.0), datetime.utcnow().isoformat()))
    booking_id = cur.lastrowid; con.commit(); con.close()
    appt_dt = datetime_from_date_time_str(date_str, time_str); remind_at = appt_dt - timedelta(seconds=REMINDER_TEST_SECONDS); delay = (remind_at - datetime.now()).total_seconds();
    if delay < 1: delay = 1
    try: context.application.job_queue.run_once(send_reminder_job, when=delay, data={"user_id": user_id, "service_name": svc["nome"], "date_str": date_str, "time_str": time_str})
    except Exception: asyncio.create_task(reminder_background(delay, user_id, svc["nome"], date_str, time_str, context))
    if REMINDER_AFTER_CONFIRM_SECONDS and REMINDER_AFTER_CONFIRM_SECONDS > 0:
        try:
            context.application.job_queue.run_once(send_post_confirm_reminder_job, when=REMINDER_AFTER_CONFIRM_SECONDS, data={"user_id": user_id, "service_name": svc['nome'], "date_str": date_str, "time_str": time_str})
        except Exception as e:
            logger.warning("Failed to schedule post-confirm reminder (accept): %s", e)
    if delay > 90 and REMINDER_QUICK_TEST and (not REMINDER_AFTER_CONFIRM_SECONDS or REMINDER_AFTER_CONFIRM_SECONDS <= 0):
        try:
            context.application.job_queue.run_once(send_reminder_job, when=30, data={"user_id": user_id, "service_name": f"{svc['nome']} (TEST)", "date_str": date.today().strftime('%Y-%m-%d'), "time_str": datetime.now().strftime('%H:%M')})
        except Exception as e:
            logger.warning("Failed to schedule quick test reminder (accept): %s", e)

async def cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE, booking_id: int):
    q = update.callback_query; con = db_conn(); cur = con.cursor(); cur.execute("SELECT user_id, service_code, service_name, date, time, operator_id FROM bookings WHERE id= ?", (booking_id,)); row = cur.fetchone()
    if not row: await q.edit_message_text("Prenotazione non trovata."); con.close(); return
    user_id_db, svc_code, svc_name, date_str, time_str, op_id = row; cur.execute("DELETE FROM bookings WHERE id=?", (booking_id,)); con.commit(); con.close(); await q.edit_message_text("✅ Prenotazione disdetta."); await notify_waitlist(context, date_str, time_str, op_id, svc_code, svc_name)

async def notify_waitlist(context: ContextTypes.DEFAULT_TYPE, date_str: str, time_str: str, op_id: str, svc_code: str, svc_name: str):
    con = db_conn(); cur = con.cursor(); cur.execute("SELECT DISTINCT user_id FROM waitlist WHERE date=? AND service_code=? ORDER BY id ASC", (date_str, svc_code)); users = [r[0] for r in cur.fetchall()]; con.close()
    if not users: return
    text = (f"ℹ️ Si è liberato uno slot per *{svc_name}*\n" f"📅 {datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')} 🕒 {time_str}\n\n" "Premi il bottone per prenotarlo ora (primo che conferma lo ottiene).")
    kb = [[InlineKeyboardButton("📌 Prenota questo slot", callback_data=f"accept_slot_{date_str}_{time_str}_{op_id}_{svc_code}")]]
    for uid in users:
        try: await context.application.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        except Exception: pass

# Reminder
async def reminder_background(delay_seconds: float, user_id: int, service_name: str, date_str: str, time_str: str, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(delay_seconds)
    text = (f"🔔 Promemoria: tra poco hai *{service_name}*\n" f"📅 {datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')} 🕒 {time_str}")
    try: await context.application.bot.send_message(user_id, text, parse_mode=ParseMode.MARKDOWN)
    except Exception: pass

async def send_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    data = getattr(context.job, 'data', None) or {}; user_id = data.get('user_id'); service_name = data.get('service_name'); date_str = data.get('date_str'); time_str = data.get('time_str')
    if not user_id or not service_name: logger.warning("Reminder job without required data: %s", data); return
    text = (f"🔔 Promemoria: tra poco hai *{service_name}*\n" f"📅 {datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')} 🕒 {time_str}")
    try: await context.application.bot.send_message(user_id, text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e: logger.exception("Failed to send reminder to user=%s: %s", user_id, e)

async def send_post_confirm_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    data = getattr(context.job, 'data', None) or {}; user_id = data.get('user_id'); service_name = data.get('service_name'); date_str = data.get('date_str'); time_str = data.get('time_str')
    if not user_id or not service_name: logger.warning("Post-confirm reminder job without required data: %s", data); return
    text = (f"🔔 Promemoria: prenotazione confermata per *{service_name}*\n" f"📅 {datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')} 🕒 {time_str}")
    try: await context.application.bot.send_message(user_id, text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e: logger.exception("Failed to send post-confirm reminder to user=%s: %s", user_id, e)

async def test_reminder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; when = 10
    try:
        context.application.job_queue.run_once(send_reminder_job, when=when, data={"user_id": user_id, "service_name": "TEST", "date_str": date.today().strftime('%Y-%m-%d'), "time_str": datetime.now().strftime('%H:%M')})
        await update.message.reply_text("🔔 Reminder di test programmato tra 10 secondi.")
    except Exception as e:
        logger.exception("Failed to schedule test reminder: %s", e); await update.message.reply_text("Errore nel programmare il reminder di test.")

async def test_after_confirm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; when = 5
    try:
        context.application.job_queue.run_once(send_post_confirm_reminder_job, when=when, data={"user_id": user_id, "service_name": "TEST-CONFERMA", "date_str": date.today().strftime('%Y-%m-%d'), "time_str": datetime.now().strftime('%H:%M')})
        await update.message.reply_text("🔔 Promemoria post-conferma di test programmato tra 5 secondi.")
    except Exception as e:
        logger.exception("Failed to schedule post-confirm test reminder: %s", e); await update.message.reply_text("Errore nel programmare il promemoria post-conferma di test.")

# Helpers

def find_service_by_code(code: str):
    for gender, cats in SERVIZI.items():
        for cat, items in cats.items():
            for it in items:
                if it["code"] == code: return it
    return None

# Conversation

def build_conversation():
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_GENDER: [CallbackQueryHandler(menu_callback_router)],
            ASK_CATEGORY: [CallbackQueryHandler(menu_callback_router)],
            ASK_SERVICE: [CallbackQueryHandler(menu_callback_router)],
            ASK_OPERATOR: [CallbackQueryHandler(menu_callback_router)],
            ASK_MONTH: [CallbackQueryHandler(menu_callback_router)],
            ASK_DAY: [CallbackQueryHandler(menu_callback_router)],
            ASK_TIME: [CallbackQueryHandler(menu_callback_router)],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_notes)],
            CONFIRM: [CallbackQueryHandler(confirm_router)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )

# Start/main
async def privacy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Privacy: i dati sono usati per gestire prenotazioni.")

async def version_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"{BUILD_VERSION}\npython-telegram-bot: 20.x")

async def debug_config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Config attuale:\n" \
        f"- REMINDER_AFTER_CONFIRM_SECONDS={REMINDER_AFTER_CONFIRM_SECONDS}\n" \
        f"- REMINDER_QUICK_TEST={REMINDER_QUICK_TEST}\n" \
        f"- REMINDER_TEST_SECONDS(before appt)={REMINDER_TEST_SECONDS}"
    )


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(build_conversation())
    app.add_handler(CallbackQueryHandler(confirm_router, pattern=r"^confirm_(yes|no)$"))
    app.add_handler(CommandHandler("help", lambda u,c: asyncio.create_task(u.message.reply_text("Usa /start"))))
    app.add_handler(CommandHandler("mie_prenotazioni", lambda u,c: asyncio.create_task(show_my_bookings(u,c))))
    app.add_handler(CommandHandler("privacy", lambda u,c: asyncio.create_task(privacy_cmd(u,c))))
    app.add_handler(CommandHandler("test_reminder", lambda u,c: asyncio.create_task(test_reminder_cmd(u,c))))
    app.add_handler(CommandHandler("test_after_confirm", lambda u,c: asyncio.create_task(test_after_confirm_cmd(u,c))))
    app.add_handler(CommandHandler("version", lambda u,c: asyncio.create_task(version_cmd(u,c))))
    app.add_handler(CommandHandler("debug_config", lambda u,c: asyncio.create_task(debug_config_cmd(u,c))))

    logger.info("PrenotaFacile minimal avviato. %s", BUILD_VERSION)
    logger.info("Config: AFTER_CONFIRM=%s QUICK_TEST=%s BEFORE_APPT=%ss", REMINDER_AFTER_CONFIRM_SECONDS, REMINDER_QUICK_TEST, REMINDER_TEST_SECONDS)
    app.run_polling()

if __name__ == "__main__":
    main()
