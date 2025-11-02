# 🚀 Sistema Auto-Commit e Backup

## 📋 File Creati

1. **auto_commit.py** - Script per commit automatico su GitHub
2. **auto_backup.py** - Script per backup locale del database
3. **github_auto_commit.ps1** - Script PowerShell da eseguire alla chiusura di VS Code

## 🔧 Configurazione Iniziale

### 1️⃣ Crea Token GitHub

1. Vai su: https://github.com/settings/tokens
2. Click su "Generate new token (classic)"
3. Dai un nome descrittivo (es: "PrenotaFacile Auto-Commit")
4. Seleziona i permessi:
   - ✅ `repo` (Full control of private repositories)
5. Click su "Generate token"
6. **COPIA IL TOKEN** (non lo vedrai più!)

### 2️⃣ Configura Variabile d'Ambiente

**Windows PowerShell (Amministratore):**
```powershell
[System.Environment]::SetEnvironmentVariable('GITHUB_TOKEN', 'il_tuo_token_qui', 'User')
```

**Verifica che sia impostato:**
```powershell
$env:GITHUB_TOKEN
```

### 3️⃣ Configura Git con il Token

Nel terminale della cartella del progetto:
```bash
git remote set-url origin https://GITHUB_TOKEN@github.com/infobotedge-debug/prenotafacile-bot-progetto-n2.git
```

Oppure modifica manualmente `.git/config`:
```ini
[remote "origin"]
    url = https://GITHUB_TOKEN@github.com/infobotedge-debug/prenotafacile-bot-progetto-n2.git
```

Sostituisci `GITHUB_TOKEN` con il tuo token reale.

## 🎯 Utilizzo

### Manuale (alla chiusura di VS Code)

Esegui lo script PowerShell:
```powershell
.\github_auto_commit.ps1
```

Questo farà:
1. ✅ Backup locale dei database in `backups/`
2. ✅ Commit e push su GitHub
3. ✅ Log delle operazioni

### Automatico (integrato nel bot)

Il bot esegue automaticamente ogni giorno alle **23:00**:
- 📦 Backup del database
- 📤 Commit su GitHub
- 📱 Notifica Telegram all'admin (ID: 1235501437)

## 📊 Log

I log vengono salvati in:
- `auto_commit.log` - Log dei commit GitHub
- `auto_backup.log` - Log dei backup locali

## 🗂️ Struttura Backup

```
backups/
├── prenotafacile_backup_20251102_230000.db
├── prenotafacile_full_backup_20251102_230000.db
├── prenotafacile_backup_20251103_230000.db
└── ...
```

## ✅ Test Primo Commit

Per testare il sistema:

1. **Test backup:**
   ```bash
   python auto_backup.py
   ```
   Verifica che i file siano in `backups/`

2. **Test commit:**
   ```bash
   python auto_commit.py
   ```
   Controlla su GitHub che il commit sia arrivato

3. **Test completo:**
   ```powershell
   .\github_auto_commit.ps1
   ```

## 🔒 Sicurezza

- ⚠️ **NON committare mai il token nel codice**
- ✅ Il token è in variabile d'ambiente
- ✅ `.gitignore` esclude file sensibili
- ✅ I database sono esclusi da git

## 🆘 Troubleshooting

### Errore: "authentication failed"
- Verifica che il token sia corretto
- Verifica che il token abbia permessi `repo`
- Rigenera il token se necessario

### Errore: "remote not found"
- Verifica l'URL del repository in `.git/config`
- Assicurati di avere accesso al repository

### Backup non creati
- Verifica che i file database esistano
- Controlla i permessi della cartella `backups/`

## 📱 Notifiche Admin

L'admin riceverà un messaggio Telegram ogni giorno alle 23:00:

```
📊 Backup e Commit Automatico Completato

📁 Backup creati:
  • prenotafacile_backup_20251102_230000.db
  • prenotafacile_full_backup_20251102_230000.db

✅ Salvato anche su GitHub
```
