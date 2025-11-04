# stats_module.py
import datetime
import os
import sqlite3
from collections import Counter, defaultdict
from typing import Iterable, Sequence

from telegram import Update
from telegram.ext import ContextTypes


def _resolve_db_path() -> str:
    explicit = os.environ.get("STATS_DB_PATH")
    if explicit:
        return explicit
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "prenotafacile.db")


def _resolve_admin_id() -> int:
    raw = os.environ.get("ADMIN_CHAT_ID") or os.environ.get("ADMIN_ID")
    try:
        return int(raw) if raw else 1235501437
    except ValueError:
        return 1235501437


DB_PATH = _resolve_db_path()
ADMIN_ID = _resolve_admin_id()
BAR_WIDTH = max(5, int(os.environ.get("STATS_BAR_WIDTH", "10")))
LEGEND_TEXT = "Legenda: 🟩 fascia con prenotazioni · ▫ nessuna prenotazione"
GENDER_ORDER = ["Donna", "Uomo"]
GENDER_ICONS = {"Donna": "👩", "Uomo": "👨"}


def _make_bar(value: int, max_value: int) -> str:
    if max_value <= 0:
        return "▫" * BAR_WIDTH
    filled = int(round((value / max_value) * BAR_WIDTH))
    filled = min(max(filled, 0), BAR_WIDTH)
    return "🟩" * filled + "▫" * (BAR_WIDTH - filled)


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _normalize_gender(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"donna", "female", "f"}:
        return "Donna"
    if normalized in {"uomo", "male", "m"}:
        return "Uomo"
    return None


def _gender_heading(gender: str) -> str:
    icon = GENDER_ICONS.get(gender, "❔")
    return f"{icon} {gender}"


def _format_bucket_lines(
    title: str,
    counts: Counter,
    ordered_keys: Sequence[str] | None = None,
    max_reference: int | None = None,
) -> list[str]:
    keys = list(ordered_keys) if ordered_keys is not None else sorted(counts.keys())
    if not keys:
        return [title, "Nessuna prenotazione.", ""]
    inferred_max = max((counts.get(k, 0) for k in keys), default=0)
    effective_max = max_reference if (max_reference is not None and max_reference > 0) else inferred_max
    lines = [title]
    for key in keys:
        value = counts.get(key, 0)
        bar = _make_bar(value, effective_max)
        lines.append(f"{key}  {bar}  ({value})")
    lines.append("")
    return lines


def _format_service_summary(service_counts: Counter) -> str:
    if not service_counts:
        return "nessun servizio"
    parts = [
        f"{service} x{count}"
        for service, count in sorted(service_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return ", ".join(parts)


def _fetch_waitlist_entries(start_iso: str, end_iso: str) -> list[tuple[str, str]]:
    con = _connect()
    cur = con.cursor()
    cur.execute(
        """
        SELECT w.date, COALESCE(s.title, w.service_code) AS service_title
        FROM waitlist w
        LEFT JOIN services s ON s.code = w.service_code
        WHERE w.date BETWEEN ? AND ?
        ORDER BY w.date, w.id
        """,
        (start_iso, end_iso),
    )
    rows = cur.fetchall()
    con.close()
    return [(row["date"], row["service_title"] or "Servizio") for row in rows]


def _format_waitlist_section(entries: Sequence[tuple[str, str]], heading: str) -> list[str]:
    if not entries:
        return [heading, "Nessuno in lista d'attesa.", ""]
    lines = [heading]
    for day_iso, service in entries:
        day_label = datetime.datetime.strptime(day_iso, "%Y-%m-%d").strftime("%d/%m")
        lines.append(f"- {day_label}: {service}")
    lines.append("")
    return lines

def get_daily_stats_text(target_date: datetime.date | None = None) -> str | None:
    """Restituisce il report testuale delle prenotazioni odierne (o data indicata)."""
    if target_date is None:
        target_date = datetime.date.today()
    date_str = target_date.strftime("%Y-%m-%d")
    con = _connect()
    cur = con.cursor()
    cur.execute(
        """
        SELECT SUBSTR(b.time, 1, 2) AS hour_bucket,
               COALESCE(s.gender, '') AS gender,
               COALESCE(s.title, b.service_name, b.service_code) AS service_title
        FROM bookings b
        LEFT JOIN services s ON s.code = b.service_code
        WHERE b.date = ? AND b.status = 'CONFIRMED'
        """,
        (date_str,),
    )
    rows = cur.fetchall()
    con.close()
    if not rows:
        return None

    hour_counts: Counter[str] = Counter()
    gender_hour_counts: dict[str, Counter[str]] = defaultdict(Counter)
    gender_service_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        raw_hour = (row["hour_bucket"] or "00").strip()
        hour_label = f"{raw_hour.zfill(2)}:00"
        gender = _normalize_gender(row["gender"])
        service_title = (row["service_title"] or "Servizio").strip() or "Servizio"

        hour_counts[hour_label] += 1
        if gender:
            gender_hour_counts[gender][hour_label] += 1
            gender_service_counts[gender][service_title] += 1

    ordered_hours = sorted(hour_counts.keys())
    global_max_hour = max(hour_counts.values()) if hour_counts else 0

    lines: list[str] = [
        f"*Statistiche prenotazioni - Oggi {date_str}*",
        "",
        LEGEND_TEXT,
        "",
    ]

    lines.extend(_format_bucket_lines("*Totale generale*", hour_counts, ordered_hours, global_max_hour))

    for gender in GENDER_ORDER:
        section_counts = gender_hour_counts.get(gender, Counter())
        heading = f"*{_gender_heading(gender)}*"
        lines.extend(_format_bucket_lines(heading, section_counts, ordered_hours, global_max_hour))

    waitlist_entries = _fetch_waitlist_entries(date_str, date_str)
    lines.extend(_format_waitlist_section(waitlist_entries, "*Liste d'attesa*"))

    lines.append("Totale prenotazioni oggi:")
    for gender in GENDER_ORDER:
        services = gender_service_counts.get(gender, Counter())
        total = sum(services.values())
        label = _gender_heading(gender)
        if total == 0:
            lines.append(f"- {label}: 0 prenotazioni")
        else:
            lines.append(f"- {label}: {total} ({_format_service_summary(services)})")

    return "\n".join(lines)


def get_weekly_stats_text(anchor_date: datetime.date | None = None) -> str | None:
    """Restituisce il report delle prenotazioni della settimana dell'anchor data (default oggi)."""
    if anchor_date is None:
        anchor_date = datetime.date.today()
    start = anchor_date - datetime.timedelta(days=anchor_date.weekday())
    end = start + datetime.timedelta(days=6)
    con = _connect()
    cur = con.cursor()
    cur.execute(
        """
        SELECT b.date AS day,
               COALESCE(s.gender, '') AS gender,
               COALESCE(s.title, b.service_name, b.service_code) AS service_title
        FROM bookings b
        LEFT JOIN services s ON s.code = b.service_code
        WHERE b.date BETWEEN ? AND ? AND b.status = 'CONFIRMED'
        """,
        (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
    )
    rows = cur.fetchall()
    con.close()
    if not rows:
        return None

    day_counts: Counter[str] = Counter()
    gender_day_counts: dict[str, Counter[str]] = defaultdict(Counter)
    gender_service_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        date_iso = row["day"]
        day_obj = datetime.datetime.strptime(date_iso, "%Y-%m-%d").date()
        day_label = day_obj.strftime("%d/%m")
        gender = _normalize_gender(row["gender"])
        service_title = (row["service_title"] or "Servizio").strip() or "Servizio"

        day_counts[day_label] += 1
        if gender:
            gender_day_counts[gender][day_label] += 1
            gender_service_counts[gender][service_title] += 1

    ordered_days = [
        (start + datetime.timedelta(days=offset)).strftime("%d/%m")
        for offset in range(7)
    ]
    global_max_day = max(day_counts.values()) if day_counts else 0

    lines: list[str] = [
        f"*Statistiche prenotazioni - Settimana {start.strftime('%d/%m/%Y')} → {end.strftime('%d/%m/%Y')}*",
        "",
        LEGEND_TEXT,
        "",
    ]

    lines.extend(_format_bucket_lines("*Totale generale*", day_counts, ordered_days, global_max_day))

    for gender in GENDER_ORDER:
        section_counts = gender_day_counts.get(gender, Counter())
        heading = f"*{_gender_heading(gender)}*"
        lines.extend(_format_bucket_lines(heading, section_counts, ordered_days, global_max_day))

    waitlist_entries = _fetch_waitlist_entries(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    lines.extend(_format_waitlist_section(waitlist_entries, "*Liste d'attesa*"))

    lines.append("Totale prenotazioni settimana:")
    for gender in GENDER_ORDER:
        services = gender_service_counts.get(gender, Counter())
        total = sum(services.values())
        label = _gender_heading(gender)
        if total == 0:
            lines.append(f"- {label}: 0 prenotazioni")
        else:
            lines.append(f"- {label}: {total} ({_format_service_summary(services)})")

    return "\n".join(lines)


async def stat_giorno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    msg = get_daily_stats_text()
    if not msg:
        await update.message.reply_text("Nessuna prenotazione oggi.")
        return
    await update.message.reply_text(msg, parse_mode="Markdown")

async def stat_settimana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    msg = get_weekly_stats_text()
    if not msg:
        await update.message.reply_text("Nessuna prenotazione questa settimana.")
        return
    await update.message.reply_text(msg, parse_mode="Markdown")
