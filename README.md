# PrenotaFacile (minimal)

Bot Telegram per prenotazioni (demo) in italiano, con SQLite e promemoria.

## Avvio veloce
1. Crea `token.txt` nella root con il BOT token.
2. (Opzionale) Crea e attiva un virtualenv, poi installa dipendenze: `pip install -r requirements.txt`.
3. Avvia in polling su Windows: `powershell -ExecutionPolicy Bypass -File scripts/start_polling.ps1`.

## File principali
- `bot_completo.py`: bot single-file con calendario e reminder
- `scripts/start_polling.ps1`: avvio in polling con log
- `requirements.txt`: dipendenze
- `token.txt.example`: formato del token
- `.gitignore`: esclude token/db/log

