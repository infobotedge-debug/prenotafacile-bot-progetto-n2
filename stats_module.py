# stats_module.py
import sqlite3
import datetime
from telegram import Update
from telegram.ext import ContextTypes

DB_PATH = "prenotafacile.db"
ADMIN_ID = 1235501437  # il tuo ID Telegram

def _make_bar(value, max_value):
    if max_value == 0:
        return "▫️"
    filled = int((value / max_value) * 10)
    return "🟩" * filled + "⬜️" * (10 - filled)

async def stat_giorno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    today = datetime.date.today().strftime("%Y-%m-%d")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT hour, COUNT(*) FROM bookings WHERE date=? GROUP BY hour", (today,))
    data = cur.fetchall()
    con.close()
    if not data:
        await update.message.reply_text("📅 Nessuna prenotazione oggi.")
        return
    maxv = max(x[1] for x in data)
    msg = f"📊 *Statistiche prenotazioni – Oggi {today}*\n\n"
    for hour, count in data:
        bar = _make_bar(count, maxv)
        msg += f"{hour}:00  {bar}  ({count})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def stat_settimana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    today = datetime.date.today()
    start = today - datetime.timedelta(days=today.weekday())
    end = start + datetime.timedelta(days=6)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        SELECT date, COUNT(*) FROM bookings
        WHERE date BETWEEN ? AND ?
        GROUP BY date ORDER BY date
    """, (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
    data = cur.fetchall()
    con.close()
    if not data:
        await update.message.reply_text("📅 Nessuna prenotazione questa settimana.")
        return
    maxv = max(x[1] for x in data)
    msg = f"📈 *Statistiche prenotazioni – Settimana {start} → {end}*\n\n"
    for d, count in data:
        bar = _make_bar(count, maxv)
        msg += f"{d[-2:]}/{d[5:7]}  {bar}  ({count})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")
