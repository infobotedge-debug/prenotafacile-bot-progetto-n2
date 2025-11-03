# stats_module.py
import datetime
import os
import sqlite3
from telegram import Update
from telegram.ext import ContextTypes


def _resolve_db_path() -> str:
    explicit = os.environ.get("STATS_DB_PATH")
    if explicit:
        return explicit
    return "prenotafacile.db"


def _resolve_admin_id() -> int:
    raw = os.environ.get("ADMIN_CHAT_ID") or os.environ.get("ADMIN_ID")
    try:
        return int(raw) if raw else 1235501437
    except ValueError:
        return 1235501437


DB_PATH = _resolve_db_path()
ADMIN_ID = _resolve_admin_id()
BAR_WIDTH = max(5, int(os.environ.get("STATS_BAR_WIDTH", "10")))


def _make_bar(value: int, max_value: int) -> str:
    if max_value <= 0:
        return "[{}]".format("-" * BAR_WIDTH)
    filled = int(round((value / max_value) * BAR_WIDTH))
    filled = min(max(filled, 0), BAR_WIDTH)
    return "[{}{}]".format("#" * filled, "-" * (BAR_WIDTH - filled))

async def stat_giorno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    today = datetime.date.today().strftime("%Y-%m-%d")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        SELECT SUBSTR(time, 1, 2) AS hour_bucket, COUNT(*)
        FROM bookings
        WHERE date=?
        GROUP BY hour_bucket
        ORDER BY hour_bucket
        """,
        (today,),
    )
    data = cur.fetchall()
    con.close()
    if not data:
        await update.message.reply_text("Nessuna prenotazione oggi.")
        return
    maxv = max(x[1] for x in data)
    msg = f"*Statistiche prenotazioni - Oggi {today}*\n\n"
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
        await update.message.reply_text("Nessuna prenotazione questa settimana.")
        return
    maxv = max(x[1] for x in data)
    msg = f"*Statistiche prenotazioni - Settimana {start} -> {end}*\n\n"
    for d, count in data:
        bar = _make_bar(count, maxv)
        msg += f"{d[-2:]}/{d[5:7]}  {bar}  ({count})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")
