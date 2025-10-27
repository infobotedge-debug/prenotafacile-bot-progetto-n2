# PrenotaFacile (minimal + full)

Bot Telegram per prenotazioni (demo) in italiano, con SQLite, promemoria, pannello admin ed avvio opzionale in webhook via ngrok.

Sono disponibili due varianti:
- Minimal (file `bot_completo.py`): flusso conversazionale con calendario e JobQueue.
- Full (file `bot_full.py`): multi-centro, operatori/servizi dinamici su DB, reminder scanner, backup, report giornaliero.

## Avvio veloce
1. Crea `token.txt` nella root con il BOT token.
2. (Opzionale) Crea e attiva un virtualenv, poi installa dipendenze: `pip install -r requirements.txt`.
3. Avvio in polling (Windows): `powershell -ExecutionPolicy Bypass -File scripts/start_polling.ps1`.
4. Avvio in webhook (ngrok) opzionale: `powershell -ExecutionPolicy Bypass -File scripts/start_webhook.ps1`

## File principali
- `bot_completo.py`: bot single-file (minimal) con calendario e reminder
- `bot_full.py`: versione completa con DB normalizzato (centers/operators/services/clients/bookings), waitlist e scanner reminder
- `scripts/start_polling.ps1`: avvio in polling con log
- `scripts/start_webhook.ps1`: avvio in webhook con ngrok (URL pubblico automatico)
- `requirements.txt`: dipendenze
- `token.txt.example`: formato del token
- `.gitignore`: esclude token/db/log

## Admin
- Imposta variabile d'ambiente `ADMIN_IDS` con gli ID Telegram degli admin (separati da virgola):
	- PowerShell: `$env:ADMIN_IDS="123456,987654"`
- Comandi:
	- `/admin` apre il pannello admin (statistiche e bottoni)
	- Bottoni: "📄 Esporta CSV" e "📅 Prenotazioni di oggi"
	- Le prenotazioni si possono comunque disdire dagli utenti dal menu "Le mie prenotazioni"

Per la versione full sono disponibili anche:
- `/admin_today` per riepilogo prenotazioni del giorno
- `/export_csv` per esportare le prenotazioni in CSV

## Lista d'attesa (waitlist)
- Quando un giorno è pieno, il bot propone "🕰️ Entra in lista d'attesa".
- Gli utenti in lista d'attesa vengono notificati quando si libera uno slot con un bottone "📌 Prenota questo slot".
- Notifica a cascata (intelligente): il bot avvisa un utente alla volta. Se non risponde entro un tempo X, passa al successivo.
- Nel DM è indicato il tempo massimo: "⏳ Hai X secondi prima che venga proposto al prossimo".
- Quando uno conferma, gli altri in lista ricevono un avviso che lo slot è stato preso e restano in lista per eventuali future disponibilità.

### Configurazione tempi cascata
- Variabile d'ambiente `WAITLIST_STEP_SECONDS` (default: 120) controlla quanti secondi attendere tra un utente e il successivo.
- Esempio (PowerShell):
	```powershell
	$env:WAITLIST_STEP_SECONDS=90
	powershell -ExecutionPolicy Bypass -File scripts/start_polling.ps1
	```

### Webhook via ngrok (opzionale)
- Imposta `NGROK_AUTHTOKEN` se necessario (account ngrok):
  - PowerShell: `$env:NGROK_AUTHTOKEN="<token>"`
- Avvia `scripts/start_webhook.ps1`. Il bot espone un endpoint su porta 8080 e crea automaticamente il tunnel ngrok.

### Test rapido
1. Avvia il bot e naviga fino a un giorno pieno: premi "🕰️ Entra in lista d'attesa".
2. Cancella una prenotazione esistente dal comando interno (se presente) o dal menu dedicato.
3. Verifica che arrivi il messaggio di notifica con il bottone per prenotare lo slot liberato.
4. Se il primo utente non risponde entro X secondi, controlla che il messaggio arrivi al successivo in lista.

## Come avviare la versione Full

In PowerShell (Windows), con la virtualenv del progetto già attiva e i requisiti installati:

```powershell
# dalla cartella del progetto
".\.venv\Scripts\python.exe" ".\prenotafacile-bot-progetto-n2\bot_full.py"
```

Note:
- La full usa il DB `prenotafacile_full.db` nella stessa cartella del file `bot_full.py`.
- Il token viene letto da `prenotafacile-bot-progetto-n2/token.txt` o dalla variabile d'ambiente `BOT_TOKEN`.

