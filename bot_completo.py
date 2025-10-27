# -*- coding: utf-8 -*-
"""
PrenotaFacile – Minimal

Dipendenze: vedi requirements.txt
Avvio: scripts/start_polling.ps1 (Windows)
"""
import os, calendar, sqlite3, asyncio, logging
from io import BytesIO, StringIO
import csv
from datetime import datetime, date, time, timedelta
from typing import List
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
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

# Usa un percorso assoluto relativo a questo file per evitare di creare DB in cartelle diverse
DB_PATH = os.path.join(os.path.dirname(__file__), "prenotafacile.db")
SLOT_MINUTES = 30
REMINDER_TEST_SECONDS = 30
try:
    REMINDER_AFTER_CONFIRM_SECONDS = int(os.environ.get("REMINDER_AFTER_CONFIRM_SECONDS", "30"))
except Exception:
    REMINDER_AFTER_CONFIRM_SECONDS = 30
REMINDER_QUICK_TEST = os.environ.get("REMINDER_QUICK_TEST", "1").lower() in {"1","true","yes"}
# In modalità quick test, se non specificato via env, usa 5 secondi per il promemoria post-conferma
if REMINDER_QUICK_TEST and ("REMINDER_AFTER_CONFIRM_SECONDS" not in os.environ):
    REMINDER_AFTER_CONFIRM_SECONDS = 5
# Attesa tra notifiche consecutive della lista d'attesa (secondi)
WAITLIST_STEP_SECONDS = int(os.environ.get("WAITLIST_STEP_SECONDS", "120"))

# Admin
def get_admin_ids() -> set[int]:
    raw = os.environ.get("ADMIN_IDS", "").strip()
    ids: set[int] = set()
    if raw:
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.add(int(part))
            except Exception:
                pass
    return ids

def is_admin(user_id: int) -> bool:
    return user_id in get_admin_ids()

ORARI_SETTIMANA = {
    0: [("09:00","13:00"),("15:00","19:00")],
    1: [("09:00","13:00"),("15:00","19:00")],
    2: [("09:00","13:00"),("15:00","19:00")],
    3: [("09:00","13:00"),("15:00","19:00")],
    4: [("09:00","13:00"),("15:00","19:00")],
    5: [("09:00","13:00")],
    6: []
}

# Operatori: aggiornati per riflettere i nomi proposti dall'utente
OPERATRICI = [
    {"id":"op_sara","name":"Sara"},
    {"id":"op_giulia","name":"Giulia"},
    {"id":"op_martina","name":"Martina"},
]

SERVIZI = {
    "Donna": {
        "Trattamenti Viso": [
            {"code":"d_viso_pulizia","nome":"Pulizia del viso","durata":60,"prezzo":40},
            {"code":"d_viso_antiage","nome":"Trattamento anti-age","durata":75,"prezzo":60},
            {"code":"d_viso_trattamento","nome":"Trattamento viso","durata":45,"prezzo":35},
        ],
        "Unghie": [
            {"code":"d_unghie_semipermanente","nome":"Semipermanente mani","durata":60,"prezzo":30},
            {"code":"d_unghie_refill_gel","nome":"Refill gel","durata":75,"prezzo":40},
            {"code":"d_unghie_manicure","nome":"Manicure classica","durata":40,"prezzo":20},
            {"code":"d_unghie_pedicure","nome":"Pedicure","durata":45,"prezzo":25},
        ],
        "Estetica": [
            {"code":"d_estetica_epilazione","nome":"Epilazione completa","durata":60,"prezzo":35},
            {"code":"d_estetica_sopracciglia","nome":"Definizione sopracciglia","durata":15,"prezzo":8},
            {"code":"d_estetica_ceretta_completa","nome":"Ceretta completa","durata":60,"prezzo":40},
            {"code":"d_estetica_extension_ciglia","nome":"Extension ciglia","durata":90,"prezzo":60},
        ],
        "Massaggi": [
            {"code":"d_massaggio_decontr","nome":"Massaggio decontratturante","durata":50,"prezzo":50},
            {"code":"d_massaggio_rilass","nome":"Massaggio rilassante","durata":50,"prezzo":45},
        ],
    },
    "Uomo": {
        "Trattamenti Viso": [
            {"code":"u_viso_pulizia","nome":"Pulizia del viso","durata":60,"prezzo":40},
            {"code":"u_viso_purificante","nome":"Trattamento viso purificante","durata":45,"prezzo":35},
        ],
        "Estetica": [
            {"code":"u_estetica_sopracciglia","nome":"Definizione sopracciglia","durata":15,"prezzo":8},
            {"code":"u_estetica_epilazione_schiena","nome":"Epilazione schiena","durata":40,"prezzo":30},
        ],
    },
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
async def join_waitlist(user_id: int, date_str: str, svc_code: str) -> int:
    """Aggiunge l'utente alla lista d'attesa e restituisce la posizione (1-based)."""
    con = db_conn(); cur = con.cursor()
    cur.execute(
        "INSERT INTO waitlist (user_id, date, service_code, created_at) VALUES (?,?,?,?)",
        (user_id, date_str, svc_code, datetime.utcnow().isoformat()),
    )
    con.commit()
    # Calcola posizione corrente
    cur.execute(
        "SELECT COUNT(*) FROM waitlist WHERE date=? AND service_code=? AND id <= ?",
        (date_str, svc_code, cur.lastrowid),
    )
    row = cur.fetchone()
    pos = row[0] if row else 1
    con.close()
    return int(pos) if pos else 1

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
    """Verifica se uno slot è libero per un operatore.

    Calcola new_start/new_end e controlla sovrapposizioni con le prenotazioni esistenti
    nello stesso giorno e per lo stesso operatore. Ritorna sempre True/False in modo affidabile.
    """
    exs = []
    con = None
    try:
        con = db_conn()
        cur = con.cursor()
        cur.execute(
            "SELECT time, duration, date FROM bookings WHERE date=? AND operator_id=?",
            (date_str, operator_id),
        )
        exs = cur.fetchall()
    except Exception as e:
        logger.debug("Errore DB in is_slot_free_for_operator: %s", e)
        # Conservativo: considera non libero in caso di errore DB
        return False
    finally:
        try:
            if con:
                con.close()
        except Exception:
            pass

    new_start = datetime_from_date_time_str(date_str, time_str)
    new_end = new_start + timedelta(minutes=int(durata))
    for t, d, dat in exs:
        ex_start = datetime_from_date_time_str(dat, t)
        ex_end = ex_start + timedelta(minutes=int(d))
        # Sovrapposizione se gli intervalli [new_start,new_end) e [ex_start,ex_end) si intersecano
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
    text = "Benvenuto in *PrenotaFacile* — scegli il profilo:"
    try:
        # Preferisci reply se è un normale messaggio
        if getattr(update, "message", None):
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        else:
            # Fallback robusto: invia al chat_id effettivo (es. se /start arriva in contesti particolari)
            chat_id = update.effective_chat.id if getattr(update, "effective_chat", None) else (user.id if user else None)
            if chat_id is not None:
                await context.application.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
            else:
                logger.warning("/start: impossibile determinare il chat_id")
    except Exception as e:
        logger.exception("Failed to send /start menu: %s", e)
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
        kb = [[InlineKeyboardButton(op["name"], callback_data=f"opid_{op['id']}")] for op in OPERATRICI]
        kb.append([InlineKeyboardButton("⬅️ Indietro", callback_data=f"cat_{context.user_data['category']}")])
        await q.edit_message_text(f"Hai scelto *{svc['nome']}* ({svc['durata']} min)\nSeleziona l'operatrice/operatore:", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN); return ASK_OPERATOR
    if data.startswith("op_") or data.startswith("opid_"):
        parts = data.split("_", 1)
        op_id = parts[1] if len(parts) > 1 else ""
        logger.info("Operator selected: %s", op_id)
        context.user_data["operator_id"] = op_id
        today = date.today()
        try:
            await show_calendar_month(q, context, today.year, today.month)
        except Exception as e:
            logger.exception("Errore in show_calendar_month: %s", e)
            try:
                await q.edit_message_text("Errore nel mostrare il calendario. Premi /start e riprova.")
            except Exception:
                pass
        return ASK_MONTH
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
        pos = await join_waitlist(user.id, date_str, svc["code"])  # helper
        davanti = max(0, (pos - 1))
        msg = (
            "✅ Inserito in lista d'attesa.\n"
            f"📍 Posizione stimata: {pos} (persone davanti: {davanti}).\n"
            "Ti notificheremo quando si libera uno slot."
        )
        await q.edit_message_text(msg)
        return ConversationHandler.END
    if data.startswith("time_"):
        time_str = data.split("_",1)[1]; context.user_data["time"] = time_str
        await q.edit_message_text("Perfetto. Inserisci *Nome e Cognome*:", parse_mode=ParseMode.MARKDOWN); return ASK_NAME
    if data.startswith("accept_slot_"):
        payload = data[len("accept_slot_"):]
        # Nuovo formato con separatore sicuro '|': date|time|op_id|svc_code
        if "|" in payload:
            try:
                date_str, time_str, op_id, svc_code = payload.split("|", 3)
            except Exception:
                await q.edit_message_text("Dati slot non validi."); return
        else:
            # Back-compat: vecchio formato con '_' che collide con i campi
            try:
                if len(payload) < 17 or payload[10] != '_' or payload[16] != '_':
                    raise ValueError("payload legacy malformato")
                date_str = payload[:10]
                time_str = payload[11:16]
                rest = payload[17:]
                # rest = f"{op_id}_{svc_code}" ma entrambi possono contenere '_'
                # Ricava svc_code facendo match con i codici esistenti (scegli il più lungo)
                svc_code = None
                op_id = None
                svc_codes = []
                for _, cats in SERVIZI.items():
                    for cat_items in cats.values():
                        for s in cat_items:
                            svc_codes.append(s["code"])
                best = None
                for code in svc_codes:
                    if rest.endswith(code) and (best is None or len(code) > len(best)):
                        best = code
                if best is None:
                    raise ValueError("svc_code non riconosciuto nel payload legacy")
                svc_code = best
                # Rimuovi separatore '_' tra op_id e svc_code se presente
                op_part_len = len(rest) - len(svc_code)
                op_id = rest[:max(0, op_part_len - 1)] if op_part_len > 0 and rest[op_part_len-1] == '_' else rest[:op_part_len]
                if not op_id:
                    raise ValueError("op_id vuoto nel payload legacy")
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
                ddate = date(year, month, day)
                wd = ddate.weekday()
                ranges = ORARI_SETTIMANA.get(wd, [])
                is_closed = not ranges
                is_today = (ddate == today)
                symbol = day_status_symbol(ddate, durata) if not is_closed else ""
                base_label = f"{day}"
                if is_today:
                    base_label = f"[{day}]"
                label = f"{base_label} {symbol}".strip()
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
    # Pulsante Indietro per tornare alla scelta operatore del servizio corrente
    try:
        if svc and svc.get("code"):
            kb.append([InlineKeyboardButton("⬅️ Indietro", callback_data=f"svc_{svc['code']}")])
    except Exception:
        pass
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
    # Safeguard: if session keys are missing, end gracefully instead of crashing
    svc = context.user_data.get("service"); date_str = context.user_data.get("date"); time_str = context.user_data.get("time"); op_id = context.user_data.get("operator_id")
    if not svc or not date_str or not time_str or not op_id:
        try:
            await update.message.reply_text("Sessione scaduta o incompleta. Usa /start per ripartire.")
        except Exception:
            pass
        return ConversationHandler.END
    # Format prezzo se disponibile
    prezzo_val = svc.get("prezzo")
    if isinstance(prezzo_val, (int, float)):
        prezzo_txt = f"€{prezzo_val:.2f}"
    else:
        prezzo_txt = "—"
    text = (f"Riepilogo:\n• Servizio: *{svc['nome']}* ({svc['durata']} min) - {prezzo_txt}\n"
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
    con = db_conn(); cur = con.cursor();
    cur.execute("SELECT id, service_name, date, time, duration, operator_id, price FROM bookings WHERE user_id=? ORDER BY date, time", (user.id,))
    rows = cur.fetchall(); con.close()
    if not rows:
        if via_callback:
            await update_or_cb.callback_query.edit_message_text("Non hai prenotazioni attive.")
        else:
            await update_or_cb.message.reply_text("Non hai prenotazioni attive.")
        return
    lines = []
    kb = []
    for bid, sname, d, t, dur, op, price in rows:
        giorno = datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m/%Y')
        prezzo = format_price_eur(price)
        lines.append(f"• [{bid}] {sname} – {giorno} {t} ({dur} min) – {operator_name(op)} – {prezzo}")
        kb.append([InlineKeyboardButton(f"❌ Disdici [{bid}]", callback_data=f"cancel_{bid}")])
    header = f"*Le tue prenotazioni ({len(rows)}):*\n"
    # Aggiunge un tasto per tornare al menu principale
    kb.append([InlineKeyboardButton("🏠 Menu", callback_data="home")])
    text = header + "\n".join(lines)
    if via_callback:
        await update_or_cb.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
    else:
        await update_or_cb.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)


# ------------------------
# ADMIN - comandi e utilità
# ------------------------
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("Accesso negato. ✋")
        return
    # Statistiche rapide
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM bookings")
    tot_book = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM waitlist")
    tot_wait = cur.fetchone()[0]
    con.close()
    kb = [
        [InlineKeyboardButton("📄 Esporta CSV", callback_data="admin_export")],
        [InlineKeyboardButton("📅 Prenotazioni di oggi", callback_data="admin_today")],
    ]
    await update.message.reply_text(
        f"Pannello Admin\n• Prenotazioni: {tot_book}\n• In lista d'attesa: {tot_wait}",
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def admin_cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not is_admin(uid):
        await q.edit_message_text("Accesso negato. ✋")
        return
    data = q.data
    if data == "admin_today":
        await admin_today_impl(q, context)
        return
    if data == "admin_export":
        await admin_export_impl(q, context)
        return
    await q.edit_message_text("Comando admin non riconosciuto.")

async def purge_day_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando admin: /purge_day YYYY-MM-DD op_id

    Esempio: /purge_day 2025-10-25 op_sara
    Elimina tutte le prenotazioni di quella giornata per la specifica operatrice.
    """
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("Accesso negato. ✋")
        return
    args = context.args if hasattr(context, "args") else []
    if len(args) != 2:
        await update.message.reply_text("Uso: /purge_day YYYY-MM-DD op_id\nEsempio: /purge_day 2025-10-25 op_sara")
        return
    date_str, op_id = args[0].strip(), args[1].strip()
    # Valida data
    try:
        _ = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        await update.message.reply_text("Data non valida. Usa formato YYYY-MM-DD")
        return
    # Valida operatrice
    valid_ops = {op["id"] for op in OPERATRICI}
    if op_id not in valid_ops:
        await update.message.reply_text("Operatrice non valida. Usa uno di: " + ", ".join(sorted(valid_ops)))
        return
    # Cancella
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM bookings WHERE date=? AND operator_id=?", (date_str, op_id))
    pre = cur.fetchone()[0]
    cur.execute("DELETE FROM bookings WHERE date=? AND operator_id=?", (date_str, op_id))
    con.commit(); con.close()
    await update.message.reply_text(f"Eliminate {pre} prenotazioni per {operator_name(op_id)} in data {date_str}.")

async def admin_today_impl(q, context: ContextTypes.DEFAULT_TYPE):
    dstr = date.today().strftime('%Y-%m-%d')
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT id, user_id, service_name, date, time, duration, operator_id, price FROM bookings WHERE date=? ORDER BY time", (dstr,))
    rows = cur.fetchall(); con.close()
    if not rows:
        await q.edit_message_text("Oggi non ci sono prenotazioni.")
        return
    lines = []
    for bid, uid, sname, d, t, dur, op, price in rows:
        prezzo = format_price_eur(price)
        lines.append(f"• [{bid}] {t} – {sname} ({dur}min) – {operator_name(op)} – user:{uid} – {prezzo}")
    await q.edit_message_text("Prenotazioni di oggi:\n" + "\n".join(lines))

async def admin_export_impl(q, context: ContextTypes.DEFAULT_TYPE):
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT id, user_id, service_code, service_name, date, time, duration, operator_id, price, created_at FROM bookings ORDER BY date, time")
    rows = cur.fetchall(); con.close()
    buf = BytesIO()
    writer = csv.writer(buf)
    writer.writerow(["id","user_id","service_code","service_name","date","time","duration","operator_id","price","created_at"])
    for r in rows:
        writer.writerow(list(r))
    buf.seek(0)
    filename = f"prenotazioni_{date.today().isoformat()}.csv"
    await context.application.bot.send_document(chat_id=q.message.chat_id, document=InputFile(buf, filename), caption="Esportazione prenotazioni")
    try:
        await q.delete_message()
    except Exception:
        pass

# Operatrici

def operator_name(op_id: str) -> str:
    for op in OPERATRICI:
        if op["id"] == op_id: return op["name"]
    return "—"

# Prenotazione / Disdetta / Waitlist
async def finalize_booking(cb_or_update, context: ContextTypes.DEFAULT_TYPE, svc, date_str, time_str, op_id, from_waitlist=False):
    """Finalizza la prenotazione e pianifica i promemoria.

    cb_or_update può essere:
    - Update (preferito): in tal caso usiamo effective_user
    - CallbackQuery: usiamo from_user (NON il suo id!)
    - int: user_id direttamente
    """
    # Estrai l'oggetto utente in modo robusto
    user_obj = None
    if isinstance(cb_or_update, int):
        user_id = cb_or_update
        username = None
    else:
        try:
            # Caso Update
            if hasattr(cb_or_update, "effective_user") and cb_or_update.effective_user:
                user_obj = cb_or_update.effective_user
            # Caso CallbackQuery
            elif hasattr(cb_or_update, "from_user") and cb_or_update.from_user:
                user_obj = cb_or_update.from_user
            # Caso Update.callback_query
            elif hasattr(cb_or_update, "callback_query") and cb_or_update.callback_query and getattr(cb_or_update.callback_query, "from_user", None):
                user_obj = cb_or_update.callback_query.from_user
        except Exception:
            user_obj = None

        if user_obj is None:
            # Fallback estremo: prova dall'Update nel context, altrimenti abort
            if hasattr(context, "user_data") and "user_id" in context.user_data and isinstance(context.user_data["user_id"], int):
                user_id = context.user_data["user_id"]
                username = context.user_data.get("username")
            else:
                # Non riusciamo a determinare l'utente correttamente
                logger.error("Impossibile determinare l'utente per la prenotazione; abort.")
                return
        else:
            user_id = user_obj.id
            username = getattr(user_obj, "username", None) or context.user_data.get("username")
    # Salva/aggiorna dati utente in modo centralizzato
    save_or_update_user(
        user_id=user_id,
        username=username,
        name=context.user_data.get("name"),
        phone=context.user_data.get("phone"),
        notes=context.user_data.get("notes"),
    )
    con = db_conn(); cur = con.cursor()
    price_val = normalize_price(svc.get("prezzo"))
    cur.execute("""INSERT INTO bookings (user_id, service_code, service_name, date, time, duration, operator_id, price, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""", (user_id, svc["code"], svc["nome"], date_str, time_str, svc["durata"], op_id, price_val, datetime.utcnow().isoformat()))
    booking_id = cur.lastrowid; con.commit(); con.close(); logger.info(f"Booking saved: id={booking_id} user={user_id} svc={svc['code']} date={date_str} time={time_str} op={op_id}")
    appt_dt = datetime_from_date_time_str(date_str, time_str); remind_at = appt_dt - timedelta(seconds=REMINDER_TEST_SECONDS); delay = (remind_at - datetime.now()).total_seconds();
    if delay < 1: delay = 1
    try: context.application.job_queue.run_once(send_reminder_job, when=delay, data={"user_id": user_id, "service_name": svc["nome"], "date_str": date_str, "time_str": time_str})
    except Exception: asyncio.create_task(reminder_background(delay, user_id, svc["nome"], date_str, time_str, context))
    if REMINDER_AFTER_CONFIRM_SECONDS and REMINDER_AFTER_CONFIRM_SECONDS > 0:
        try:
            context.application.job_queue.run_once(send_post_confirm_reminder_job, when=REMINDER_AFTER_CONFIRM_SECONDS, data={"user_id": user_id, "service_name": svc['nome'], "date_str": date_str, "time_str": time_str})
            logger.info("Scheduled post-confirm reminder in %ss for user=%s", REMINDER_AFTER_CONFIRM_SECONDS, user_id)
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
    except Exception:
        username = None
    # Allinea i dati utente
    try:
        save_or_update_user(user_id=user_id, username=username)
    except Exception as e:
        logger.debug("save_or_update_user (accept) fallito: %s", e)
    con = db_conn(); cur = con.cursor();
    price_val = normalize_price(svc.get("prezzo"))
    cur.execute("""INSERT INTO bookings (user_id, service_code, service_name, date, time, duration, operator_id, price, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""", (user_id, svc["code"], svc["nome"], date_str, time_str, svc["durata"], op_id, price_val, datetime.utcnow().isoformat()))
    booking_id = cur.lastrowid; con.commit(); con.close()
    appt_dt = datetime_from_date_time_str(date_str, time_str); remind_at = appt_dt - timedelta(seconds=REMINDER_TEST_SECONDS); delay = (remind_at - datetime.now()).total_seconds();
    if delay < 1: delay = 1
    try: context.application.job_queue.run_once(send_reminder_job, when=delay, data={"user_id": user_id, "service_name": svc["nome"], "date_str": date_str, "time_str": time_str})
    except Exception: asyncio.create_task(reminder_background(delay, user_id, svc["nome"], date_str, time_str, context))
    if REMINDER_AFTER_CONFIRM_SECONDS and REMINDER_AFTER_CONFIRM_SECONDS > 0:
        try:
            context.application.job_queue.run_once(send_post_confirm_reminder_job, when=REMINDER_AFTER_CONFIRM_SECONDS, data={"user_id": user_id, "service_name": svc['nome'], "date_str": date_str, "time_str": time_str})
            logger.info("Scheduled post-confirm reminder in %ss for user=%s (accept)", REMINDER_AFTER_CONFIRM_SECONDS, user_id)
        except Exception as e:
            logger.warning("Failed to schedule post-confirm reminder (accept): %s", e)
    if delay > 90 and REMINDER_QUICK_TEST and (not REMINDER_AFTER_CONFIRM_SECONDS or REMINDER_AFTER_CONFIRM_SECONDS <= 0):
        try:
            context.application.job_queue.run_once(send_reminder_job, when=30, data={"user_id": user_id, "service_name": f"{svc['nome']} (TEST)", "date_str": date.today().strftime('%Y-%m-%d'), "time_str": datetime.now().strftime('%H:%M')})
        except Exception as e:
            logger.warning("Failed to schedule quick test reminder (accept): %s", e)
    # Avvisa gli altri utenti in lista d'attesa che lo slot è stato preso
    try:
        await notify_waitlist_slot_taken(context, date_str, time_str, svc["code"], svc["nome"], exclude_user_id=user_id)
    except Exception as e:
        logger.debug("notify_waitlist_slot_taken fallita: %s", e)

async def cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE, booking_id: int):
    q = update.callback_query; con = db_conn(); cur = con.cursor(); cur.execute("SELECT user_id, service_code, service_name, date, time, operator_id FROM bookings WHERE id= ?", (booking_id,)); row = cur.fetchone()
    if not row: await q.edit_message_text("Prenotazione non trovata."); con.close(); return
    user_id_db, svc_code, svc_name, date_str, time_str, op_id = row; cur.execute("DELETE FROM bookings WHERE id=?", (booking_id,)); con.commit(); con.close(); await q.edit_message_text("✅ Prenotazione disdetta."); await notify_waitlist(context, date_str, time_str, op_id, svc_code, svc_name)

async def notify_waitlist(context: ContextTypes.DEFAULT_TYPE, date_str: str, time_str: str, op_id: str, svc_code: str, svc_name: str):
    """Avvia la notifica sequenziale agli utenti della lista d'attesa."""
    con = db_conn(); cur = con.cursor()
    cur.execute("SELECT DISTINCT user_id FROM waitlist WHERE date=? AND service_code=? ORDER BY id ASC", (date_str, svc_code))
    users = [r[0] for r in cur.fetchall()]
    con.close()
    if not users:
        return
    # Primo step immediato
    try:
        context.application.job_queue.run_once(
            waitlist_step_job,
            when=0,
            data={
                "users": users,
                "index": 0,
                "date_str": date_str,
                "time_str": time_str,
                "op_id": op_id,
                "svc_code": svc_code,
                "svc_name": svc_name,
            },
        )
    except Exception as e:
        logger.warning("Pianificazione waitlist fallita: %s", e)

async def waitlist_step_job(context: ContextTypes.DEFAULT_TYPE):
    data = getattr(context.job, 'data', {}) or {}
    users = data.get("users") or []
    idx = int(data.get("index", 0))
    date_str = data.get("date_str"); time_str = data.get("time_str")
    op_id = data.get("op_id"); svc_code = data.get("svc_code"); svc_name = data.get("svc_name")
    if not users or idx >= len(users) or not all([date_str, time_str, op_id, svc_code]):
        return
    svc = find_service_by_code(svc_code)
    if not svc:
        return
    # Interrompi se lo slot non è più libero
    if not is_slot_free_for_operator(date_str, time_str, svc["durata"], op_id):
        return
    uid = users[idx]
    text = (
        f"ℹ️ Si è liberato uno slot per *{svc_name}*\n"
        f"📅 {datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')} 🕒 {time_str}\n\n"
        "Premi il bottone per prenotarlo ora (primo che conferma lo ottiene).\n"
        f"⏳ Hai {WAITLIST_STEP_SECONDS} secondi prima che venga proposto al prossimo."
    )
    # Usa '|' come separatore per evitare collisioni con '_' nei codici
    kb = [[InlineKeyboardButton("📌 Prenota questo slot", callback_data=f"accept_slot_{date_str}|{time_str}|{op_id}|{svc_code}")]]
    try:
        await context.application.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.debug("Invio notifica waitlist fallito per user=%s: %s", uid, e)
    # Pianifica il prossimo utente se resta libero
    next_idx = idx + 1
    if next_idx < len(users):
        try:
            context.application.job_queue.run_once(
                waitlist_step_job,
                when=max(1, WAITLIST_STEP_SECONDS),
                data={
                    "users": users,
                    "index": next_idx,
                    "date_str": date_str,
                    "time_str": time_str,
                    "op_id": op_id,
                    "svc_code": svc_code,
                    "svc_name": svc_name,
                },
            )
        except Exception as e:
            logger.debug("Pianificazione step waitlist fallita: %s", e)

async def notify_waitlist_slot_taken(context: ContextTypes.DEFAULT_TYPE, date_str: str, time_str: str, svc_code: str, svc_name: str, exclude_user_id: int | None = None):
    """Informa gli altri utenti in lista d'attesa che lo slot è stato preso."""
    con = db_conn(); cur = con.cursor()
    if exclude_user_id is not None:
        cur.execute(
            "SELECT DISTINCT user_id FROM waitlist WHERE date=? AND service_code=? AND user_id<>? ORDER BY id ASC",
            (date_str, svc_code, exclude_user_id),
        )
    else:
        cur.execute(
            "SELECT DISTINCT user_id FROM waitlist WHERE date=? AND service_code=? ORDER BY id ASC",
            (date_str, svc_code),
        )
    others = [r[0] for r in cur.fetchall()]
    con.close()
    if not others:
        return
    msg = (
        f"❕ Lo slot per *{svc_name}* del {datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')} alle {time_str} è stato prenotato da un altro utente.\n"
        "Resterai in lista d'attesa e ti avviseremo se se ne libera un altro."
    )
    for uid in others:
        try:
            await context.application.bot.send_message(uid, msg, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.debug("Notifica 'slot preso' fallita per user=%s: %s", uid, e)

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

def find_service_by_code(code: str) -> dict | None:
    """Restituisce il dizionario del servizio corrispondente al codice."""
    for _, cats in SERVIZI.items():
        for cat_items in cats.values():
            for svc in cat_items:
                if svc["code"] == code:
                    return svc
    return None

def normalize_price(value) -> float:
    """Normalizza il prezzo in un float.

    Accetta numeri, stringhe con simbolo € o virgole, spazi; altrimenti 0.0.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        v = value.strip().replace("€", "").replace(" ", "").replace(",", ".")
        try:
            return float(v)
        except Exception:
            return 0.0
    return 0.0

def format_price_eur(value) -> str:
    """Formatta un prezzo in euro, con fallback a '—'."""
    try:
        if value is None:
            return "—"
        v = float(value)
        return f"€{v:.2f}"
    except Exception:
        return "—"

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
        allow_reentry=True,
    )

# Start/main
async def privacy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Privacy: i dati sono usati per gestire prenotazioni.")

async def version_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"{BUILD_VERSION}\npython-telegram-bot: 22.x")

async def debug_config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Config attuale:\n" \
        f"- REMINDER_AFTER_CONFIRM_SECONDS={REMINDER_AFTER_CONFIRM_SECONDS}\n" \
        f"- REMINDER_QUICK_TEST={REMINDER_QUICK_TEST}\n" \
        f"- REMINDER_TEST_SECONDS(before appt)={REMINDER_TEST_SECONDS}"
    )

async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra la variante attiva e info build (Minimal)."""
    variant = os.environ.get("BOT_VARIANT", "minimal").strip().lower() or "minimal"
    # In minimal non distinguiamo MODE, ma mostriamo comunque eventuale ENV
    mode_env = os.environ.get("MODE", "TEST").strip().upper()
    await update.message.reply_text(f"Variante: {variant} (MODE={mode_env})\nBuild: {BUILD_VERSION}")


# ==============================
# Variante FULL integrata (single file)
# Attiva con: BOT_VARIANT=full
# ==============================

# Admin/Build per FULL
FULL_ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "1235501437"))
FULL_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "@Wineorange")
FULL_BUILD_VERSION = os.getenv("GITHUB_RUN_ID", "dev-local")

# DB per FULL (separato dal minimal)
FULL_DB_PATH = os.path.join(os.path.dirname(__file__), "prenotafacile_full.db")

FULL_DB_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS centers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    timezone TEXT DEFAULT 'Europe/Rome',
    config_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS operators (
    id TEXT PRIMARY KEY,
    center_id INTEGER,
    name TEXT,
    work_start TEXT,
    work_end TEXT,
    breaks_json TEXT DEFAULT '[]',
    FOREIGN KEY(center_id) REFERENCES centers(id)
);
CREATE TABLE IF NOT EXISTS services (
    code TEXT PRIMARY KEY,
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
    date TEXT,
    time TEXT,
    duration INTEGER,
    status TEXT DEFAULT 'CONFIRMED',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    reminder_sent INTEGER DEFAULT 0,
    FOREIGN KEY(center_id) REFERENCES centers(id),
    FOREIGN KEY(operator_id) REFERENCES operators(id),
    FOREIGN KEY(service_code) REFERENCES services(code),
    FOREIGN KEY(client_id) REFERENCES clients(id)
);
CREATE TABLE IF NOT EXISTS waitlist_full (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center_id INTEGER,
    service_code TEXT,
    requested_date TEXT,
    client_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

def FULL_db_conn():
    con = sqlite3.connect(FULL_DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    con.row_factory = sqlite3.Row
    return con

def FULL_init_db():
    con = FULL_db_conn(); cur = con.cursor(); cur.executescript(FULL_DB_SCHEMA); con.commit(); con.close()

def FULL_create_center_if_missing(name: str = "Default Centro") -> int:
    con = FULL_db_conn(); cur = con.cursor(); cur.execute("SELECT id FROM centers WHERE name=?", (name,)); r = cur.fetchone()
    if r:
        cid = r["id"]
    else:
        cur.execute("INSERT INTO centers(name) VALUES(?)", (name,)); cid = cur.lastrowid; con.commit()
    con.close(); return cid

def FULL_ensure_sample_data():
    con = FULL_db_conn(); cur = con.cursor(); cur.execute("SELECT COUNT(*) FROM centers")
    if cur.fetchone()[0] == 0:
        cid = FULL_create_center_if_missing("Centro Demo")
        cur.execute("INSERT OR REPLACE INTO operators(id, center_id, name, work_start, work_end) VALUES(?,?,?,?,?)", ("op_sara", cid, "Sara", "09:00", "18:00"))
        cur.execute("INSERT OR REPLACE INTO services(code, center_id, title, duration_minutes, price) VALUES(?,?,?,?,?)", ("svc_pulizia_viso", cid, "Pulizia viso", 45, 40.0))
        cur.execute("INSERT OR REPLACE INTO services(code, center_id, title, duration_minutes, price) VALUES(?,?,?,?,?)", ("svc_manicure", cid, "Manicure", 30, 20.0))
        con.commit(); logger.info("[FULL] Dati di demo inseriti.")
    con.close()

def FULL_parse_hhmm(s: str) -> time:
    h, m = map(int, s.split(":")); return time(hour=h, minute=m)

def FULL_generate_slots_for_operator(operator_id: str, target_date: date) -> List[str]:
    con = FULL_db_conn(); cur = con.cursor(); cur.execute("SELECT * FROM operators WHERE id=?", (operator_id,)); op = cur.fetchone()
    if not op: con.close(); return []
    start = FULL_parse_hhmm(op["work_start"]); end = FULL_parse_hhmm(op["work_end"])
    slot_minutes = 30; dt_start = datetime.combine(target_date, start); dt_end = datetime.combine(target_date, end); slots = []
    cur.execute("SELECT DISTINCT time FROM bookings WHERE operator_id=? AND date=? AND status='CONFIRMED'", (operator_id, target_date.isoformat()))
    taken = {r["time"] for r in cur.fetchall()}; s = dt_start
    while s + timedelta(minutes=slot_minutes) <= dt_end:
        hhmm = s.strftime("%H:%M");
        if hhmm not in taken: slots.append(hhmm)
        s += timedelta(minutes=slot_minutes)
    con.close(); return slots

def FULL_is_slot_available(operator_id: str, target_date: str, time_str: str) -> bool:
    con = FULL_db_conn(); cur = con.cursor(); cur.execute("SELECT COUNT(*) FROM bookings WHERE operator_id=? AND date=? AND time=? AND status='CONFIRMED'", (operator_id, target_date, time_str)); ok = (cur.fetchone()[0] == 0); con.close(); return ok

def FULL_find_or_create_client(tg_id: int, name: str | None = None, phone: str | None = None) -> int:
    con = FULL_db_conn(); cur = con.cursor(); cur.execute("SELECT id FROM clients WHERE tg_id=?", (tg_id,)); r = cur.fetchone()
    if r:
        cid = r["id"]; cur.execute("UPDATE clients SET last_seen=? WHERE id=?", (datetime.now(), cid))
    else:
        cur.execute("INSERT INTO clients(tg_id, name, phone, last_seen) VALUES(?,?,?,?)", (tg_id, name or "", phone or "", datetime.now())); cid = cur.lastrowid
    con.commit(); con.close(); return cid

def FULL_add_booking(center_id:int, operator_id:str, service_code:str, client_id:int, dstr:str, tstr:str, duration:int) -> int:
    con = FULL_db_conn(); cur = con.cursor(); cur.execute("INSERT INTO bookings(center_id, operator_id, service_code, client_id, date, time, duration) VALUES(?,?,?,?,?,?,?)", (center_id, operator_id, service_code, client_id, dstr, tstr, duration)); bid = cur.lastrowid; con.commit(); con.close(); return bid

def FULL_cancel_booking(booking_id:int) -> bool:
    con = FULL_db_conn(); cur = con.cursor(); cur.execute("UPDATE bookings SET status='CANCELLED' WHERE id=? AND status='CONFIRMED'", (booking_id,)); ok = cur.rowcount > 0; con.commit(); con.close(); return ok

async def FULL_global_error_handler(update_or_none, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("[FULL] Unhandled exception: %s", context.error)
    try:
        await context.bot.send_message(chat_id=FULL_ADMIN_CHAT_ID, text=f"⚠️ Errore non gestito: {context.error}")
    except Exception:
        pass

async def FULL_notify_admin_startup(application):
    mode_label = "🧪 TEST" if os.environ.get("MODE", "TEST").strip().upper() != "PRODUZIONE" else "🚀 PRODUZIONE"
    msg = (
        f"✅ *PrenotaFacile avviato (FULL)!*\n"
        f"👤 Admin: {FULL_ADMIN_USERNAME}\n"
        f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"🏷 Build: `{FULL_BUILD_VERSION}`\n"
    )
    try:
        await application.bot.send_message(chat_id=FULL_ADMIN_CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass

async def FULL_start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; FULL_find_or_create_client(user.id, name=user.full_name)
    kb = [[InlineKeyboardButton("📅 Prenota (FULL)", callback_data="full_book_start")],[InlineKeyboardButton("📋 Le mie prenotazioni", callback_data="full_my_bookings")]]
    await update.message.reply_text(f"Ciao {user.first_name}! Benvenuto in PrenotaFacile (FULL).", reply_markup=InlineKeyboardMarkup(kb))

async def FULL_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data or ""
    if data == "full_book_start":
        con = FULL_db_conn(); cur = con.cursor(); cur.execute("SELECT id FROM centers LIMIT 1"); center = cur.fetchone()
        if not center: await q.edit_message_text("Nessun centro configurato."); con.close(); return
        center_id = center["id"]; cur.execute("SELECT code, title, duration_minutes FROM services WHERE center_id=?", (center_id,)); services = cur.fetchall(); kb = []
        for s in services: kb.append([InlineKeyboardButton(f"{s['title']} ({s['duration_minutes']}m)", callback_data=f"full_svc_{s['code']}")])
        kb.append([InlineKeyboardButton("⬅️ Annulla", callback_data="full_cancel")]); await q.edit_message_text("Scegli il trattamento:", reply_markup=InlineKeyboardMarkup(kb)); con.close(); return
    if data.startswith("full_svc_"):
        svc_code = data.split("full_svc_")[1]; con = FULL_db_conn(); cur = con.cursor(); cur.execute("SELECT * FROM operators LIMIT 5"); ops = cur.fetchall(); kb = []
        for op in ops: kb.append([InlineKeyboardButton(f"{op['name']}", callback_data=f"full_op_{op['id']}_svc_{svc_code}")])
        kb.append([InlineKeyboardButton("⬅️ Indietro", callback_data="full_book_start")]); await q.edit_message_text("Scegli l'operatrice:", reply_markup=InlineKeyboardMarkup(kb)); con.close(); return
    if data.startswith("full_op_") and "_svc_" in data:
        parts = data.split("_svc_"); op_part = parts[0]; svc_code = parts[1]; op_id = op_part[len("full_op_"):]
        slots_kb = []
        for i in range(0,7):
            d = date.today() + timedelta(days=i); slots = FULL_generate_slots_for_operator(op_id, d)
            if slots: slots_kb.append([InlineKeyboardButton(d.strftime('%d %b'), callback_data=f"full_date_{d.isoformat()}_op_{op_id}_svc_{svc_code}")])
        if not slots_kb:
            await q.edit_message_text("Nessuno slot disponibile nei prossimi 7 giorni."); return
        await q.edit_message_text("Scegli giorno:", reply_markup=InlineKeyboardMarkup(slots_kb)); return
    if data.startswith("full_date_") and "_op_" in data and "_svc_" in data:
        left, rest = data.split("_op_"); date_s = left[len("full_date_"):]; op_id, svc_code = rest.split("_svc_")
        slots = FULL_generate_slots_for_operator(op_id, date.fromisoformat(date_s)); kb = []
        for t in slots[:8]: kb.append([InlineKeyboardButton(t, callback_data=f"full_time_{date_s}_{t}_op_{op_id}_svc_{svc_code}")])
        await q.edit_message_text("Scegli orario:", reply_markup=InlineKeyboardMarkup(kb)); return
    if data.startswith("full_time_") and "_op_" in data and "_svc_" in data:
        parts = data.split("_op_"); left = parts[0][len("full_time_"):]; op_id, svc_code = parts[1].split("_svc_"); dpart, tpart = left.split("_")
        user = update.effective_user; client_id = FULL_find_or_create_client(user.id, name=user.full_name); con = FULL_db_conn(); cur = con.cursor(); cur.execute("SELECT duration_minutes FROM services WHERE code=?", (svc_code,)); svc = cur.fetchone(); duration = svc["duration_minutes"] if svc else 30;
        if not FULL_is_slot_available(op_id, dpart, tpart): await update.callback_query.answer("Slot non più disponibile.", show_alert=True); con.close(); return
        center_id = 1; cur.execute("SELECT id FROM centers LIMIT 1"); r = cur.fetchone(); center_id = r["id"] if r else 1; bid = FULL_add_booking(center_id, op_id, svc_code, client_id, dpart, tpart, duration); con.close(); await update.callback_query.edit_message_text(f"✅ Prenotazione confermata per il {dpart} alle {tpart}. ID: {bid}"); return
    if data == "full_my_bookings":
        user = update.effective_user; con = FULL_db_conn(); cur = con.cursor(); cur.execute("SELECT id FROM clients WHERE tg_id=?", (user.id,)); r = cur.fetchone()
        if not r: await update.callback_query.edit_message_text("Non hai prenotazioni."); con.close(); return
        client_id = r["id"]; cur.execute("SELECT * FROM bookings WHERE client_id=? AND status='CONFIRMED' ORDER BY date,time", (client_id,)); rows = cur.fetchall();
        if not rows: await update.callback_query.edit_message_text("Nessuna prenotazione attiva."); con.close(); return
        txt = "Le tue prenotazioni:\n" + "\n".join([f"- ID {b['id']}: {b['date']} {b['time']} (svc:{b['service_code']})" for b in rows]); await update.callback_query.edit_message_text(txt); con.close(); return
    if data == "full_cancel":
        await update.callback_query.edit_message_text("Operazione annullata. Usa /start."); return
    await update.callback_query.answer()

async def FULL_admin_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != FULL_ADMIN_CHAT_ID:
        await update.message.reply_text("Accesso negato."); return
    today = date.today().isoformat(); con = FULL_db_conn(); cur = con.cursor(); cur.execute("SELECT * FROM bookings WHERE date=? ORDER BY time", (today,)); rows = cur.fetchall(); out = f"Prenotazioni oggi ({today}):\n" + "\n".join([f"- ID {r['id']} {r['operator_id']} {r['time']} svc:{r['service_code']} client:{r['client_id']}" for r in rows]); await update.message.reply_text(out); con.close()

async def FULL_export_csv_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != FULL_ADMIN_CHAT_ID:
        await update.message.reply_text("Accesso negato."); return
    con = FULL_db_conn(); cur = con.cursor(); cur.execute("SELECT * FROM bookings ORDER BY date,time"); rows = cur.fetchall(); si = StringIO(); si.write("id,center_id,operator_id,service_code,client_id,date,time,duration,status,created_at\n");
    for r in rows: si.write(f"{r['id']},{r['center_id']},{r['operator_id']},{r['service_code']},{r['client_id']},{r['date']},{r['time']},{r['duration']},{r['status']},{r['created_at']}\n"); si.seek(0); await update.message.reply_document(document=si.getvalue().encode("utf-8"), filename="bookings_export.csv"); con.close()

async def FULL_ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if getattr(update, "message", None):
            await update.message.reply_text("pong")
        else:
            cid = update.effective_chat.id if getattr(update, "effective_chat", None) else None
            if cid is not None:
                await context.application.bot.send_message(cid, "pong")
    except Exception:
        logger.exception("/ping (FULL) failed")

async def FULL_version_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Build: {FULL_BUILD_VERSION}\npython-telegram-bot: 22.x")

async def FULL_mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    variant = "full"
    mode_env = os.environ.get("MODE", "TEST").strip().upper()
    await update.message.reply_text(f"Variante: {variant} (MODE={mode_env})\nBuild: {FULL_BUILD_VERSION}")

def FULL_build_application():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", FULL_start_cmd))
    app.add_handler(CallbackQueryHandler(FULL_callback_router, pattern=r"^full_"))
    app.add_handler(CommandHandler("admin_today", FULL_admin_today))
    app.add_handler(CommandHandler("export_csv", FULL_export_csv_cmd))
    # Allinea comandi di servizio
    app.add_handler(CommandHandler("ping", FULL_ping_cmd))
    app.add_handler(CommandHandler("version", FULL_version_cmd))
    app.add_handler(CommandHandler("mode", FULL_mode_cmd))
    try:
        app.add_error_handler(FULL_global_error_handler)
    except Exception:
        pass
    return app

async def FULL_main_async():
    FULL_init_db()
    FULL_ensure_sample_data()
    app = FULL_build_application()
    await FULL_notify_admin_startup(app)
    # Avvia in polling senza annidare event loops
    logger.info("PrenotaFacile FULL: avvio polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    try:
        # Attendi indefinitamente finché il processo viene terminato dallo script di stop
        await asyncio.Event().wait()
    finally:
        try:
            await app.updater.stop()
        except Exception:
            pass
        await app.stop()


def main():
    # Se richiesto, esegui la variante FULL integrata
    try:
        variant = os.environ.get("BOT_VARIANT", "minimal").strip().lower()
    except Exception:
        variant = "minimal"
    if variant == "full":
        try:
            asyncio.run(FULL_main_async())
        except KeyboardInterrupt:
            logger.info("Arresto manuale (FULL)")
        return
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(build_conversation())
    app.add_handler(CallbackQueryHandler(confirm_router, pattern=r"^confirm_(yes|no)$"))
    # Catch-all di sicurezza per i principali callback se uscissi dalla Conversation
    app.add_handler(CallbackQueryHandler(menu_callback_router, pattern=r"^(gender_|cat_|svc_|op_|cal_|pickmonths_|day_|time_|waitlist_join|accept_slot_|cancel_)"))
    # Admin callback router
    app.add_handler(CallbackQueryHandler(admin_cb_router, pattern=r"^admin_"))
    app.add_handler(CommandHandler("help", lambda u,c: asyncio.create_task(u.message.reply_text("Usa /start"))))
    app.add_handler(CommandHandler("mie_prenotazioni", lambda u,c: asyncio.create_task(show_my_bookings(u,c))))
    app.add_handler(CommandHandler("privacy", lambda u,c: asyncio.create_task(privacy_cmd(u,c))))
    # Ping semplice per testare rapidamente la responsività
    async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if getattr(update, "message", None):
                await update.message.reply_text("pong")
            else:
                cid = update.effective_chat.id if getattr(update, "effective_chat", None) else None
                if cid is not None:
                    await context.application.bot.send_message(cid, "pong")
        except Exception:
            logger.exception("/ping failed")
    app.add_handler(CommandHandler("ping", lambda u,c: asyncio.create_task(ping_cmd(u,c))))
    app.add_handler(CommandHandler("test_reminder", lambda u,c: asyncio.create_task(test_reminder_cmd(u,c))))
    app.add_handler(CommandHandler("test_after_confirm", lambda u,c: asyncio.create_task(test_after_confirm_cmd(u,c))))
    app.add_handler(CommandHandler("version", lambda u,c: asyncio.create_task(version_cmd(u,c))))
    app.add_handler(CommandHandler("mode", lambda u,c: asyncio.create_task(mode_cmd(u,c))))
    app.add_handler(CommandHandler("debug_config", lambda u,c: asyncio.create_task(debug_config_cmd(u,c))))
    app.add_handler(CommandHandler("admin", lambda u,c: asyncio.create_task(admin_cmd(u,c))))
    app.add_handler(CommandHandler("purge_day", lambda u,c: asyncio.create_task(purge_day_cmd(u,c))))
    # Error handler per diagnosticare blocchi imprevisti
    async def _err_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.exception("Unhandled error", exc_info=context.error)
    try:
        app.add_error_handler(_err_handler)
    except Exception:
        pass

    logger.info("PrenotaFacile minimal avviato. %s", BUILD_VERSION)
    logger.info("Config: AFTER_CONFIRM=%s QUICK_TEST=%s BEFORE_APPT=%ss", REMINDER_AFTER_CONFIRM_SECONDS, REMINDER_QUICK_TEST, REMINDER_TEST_SECONDS)
    force_webhook = os.environ.get("FORCE_WEBHOOK", "0").lower() in {"1","true","yes"}
    if force_webhook:
        # Avvio in webhook con ngrok (se disponibile)
        try:
            from pyngrok import ngrok
            port = int(os.environ.get("WEBHOOK_PORT", "8080"))
            # Avvia tunnel
            public_url = os.environ.get("PUBLIC_URL")
            if not public_url:
                auth = os.environ.get("NGROK_AUTHTOKEN")
                if auth:
                    ngrok.set_auth_token(auth)
                tunnel = ngrok.connect(port)
                public_url = tunnel.public_url
            webhook_url = f"{public_url}/{TOKEN}"
            logger.info("Webhook URL: %s", webhook_url)
            app.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=TOKEN,
                webhook_url=webhook_url,
                drop_pending_updates=True,
            )
            return
        except Exception as e:
            logger.warning("Falling back to polling (webhook error): %s", e)
    app.run_polling()

if __name__ == "__main__":
    main()
