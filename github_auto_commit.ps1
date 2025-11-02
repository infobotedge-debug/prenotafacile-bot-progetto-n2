# Script PowerShell per auto-commit e backup
# Eseguire ogni volta che si chiude il progetto

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "🧠 Avvio salvataggio automatico su GitHub" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Esegui backup locale
Write-Host "📦 Creazione backup locale..." -ForegroundColor Green
python auto_backup.py

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Backup locale completato" -ForegroundColor Green
} else {
    Write-Host "❌ Errore durante il backup" -ForegroundColor Red
}

Write-Host ""

# Esegui commit su GitHub
Write-Host "📤 Commit su GitHub..." -ForegroundColor Green
python auto_commit.py

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Commit su GitHub completato" -ForegroundColor Green
} else {
    Write-Host "❌ Errore durante il commit" -ForegroundColor Red
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "✅ Salvataggio completato!" -ForegroundColor Green
Write-Host "Puoi chiudere Visual Studio Code." -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

pause
