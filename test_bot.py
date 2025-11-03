#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test bot minimale per verificare connessione Telegram"""

import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per il comando /start"""
    user = update.effective_user
    logger.info(f"✅ Comando /start ricevuto da: {user.id} (@{user.username})")
    await update.message.reply_text(f"✅ Bot funziona! Ciao {user.first_name}!")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per il comando /test"""
    logger.info(f"✅ Comando /test ricevuto")
    await update.message.reply_text("✅ Test OK!")

def main():
    """Avvia il bot"""
    with open("token.txt") as f:
        token = f.read().strip()
    
    logger.info("🚀 Avvio bot di test...")
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    
    logger.info("✅ Bot di test avviato correttamente!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
