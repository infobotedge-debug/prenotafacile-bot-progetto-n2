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

### Test rapido
1. Avvia il bot e naviga fino a un giorno pieno: premi "🕰️ Entra in lista d'attesa".
2. Cancella una prenotazione esistente dal comando interno (se presente) o dal menu dedicato.
3. Verifica che arrivi il messaggio di notifica con il bottone per prenotare lo slot liberato.
4. Se il primo utente non risponde entro X secondi, controlla che il messaggio arrivi al successivo in lista.

