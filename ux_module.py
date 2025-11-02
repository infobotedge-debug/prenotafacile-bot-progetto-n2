"""
Modulo UX - Messaggi di conferma e notifiche per migliorare l'esperienza utente
"""

from datetime import datetime
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

async def send_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, booking_info, via_callback=False, reply_markup=None, skip_warm_message=False):
    """
    Invia messaggio di conferma prenotazione con dettagli formattati.
    
    Args:
        update: Update di Telegram
        context: Context di Telegram
        booking_info: dict con chiavi 'date', 'time', 'service', opzionale 'operator', 'price', 'booking_id'
        via_callback: True se chiamato da callback_query, False se da messaggio diretto
        reply_markup: InlineKeyboardMarkup opzionale per pulsanti
        skip_warm_message: True per non includere il messaggio caloroso (modalità admin/FULL)
    """
    # Formatta la data in italiano se possibile
    try:
        date_obj = datetime.strptime(booking_info['date'], '%Y-%m-%d')
        date_formatted = date_obj.strftime('%d/%m/%Y')
    except:
        date_formatted = booking_info['date']
    
    msg = f"✅ *Prenotazione confermata!*\n\n"
    msg += f"🗓️ Data: {date_formatted}\n"
    msg += f"⏰ Orario: {booking_info['time']}\n"
    msg += f"💆 Servizio: {booking_info['service']}\n"
    
    # Aggiungi operatore se disponibile
    if booking_info.get('operator'):
        msg += f"👤 Operatore: {booking_info['operator']}\n"
    
    # Aggiungi prezzo se disponibile
    if booking_info.get('price'):
        msg += f"💰 Prezzo: €{booking_info['price']}\n"
    
    # Aggiungi ID prenotazione se disponibile
    if booking_info.get('booking_id'):
        msg += f"🆔 ID prenotazione: {booking_info['booking_id']}\n"
    
    # Aggiungi messaggio caloroso solo se non è modalità admin/FULL
    if not skip_warm_message:
        msg += "\nTi aspettiamo con piacere! ❤️\n"
        msg += "📲 Riceverai un promemoria prima dell'appuntamento."
    
    if via_callback:
        # Chiamato da callback_query
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        # Chiamato da messaggio diretto
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')

