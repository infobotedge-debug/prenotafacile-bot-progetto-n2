param(
    [string]$BotToken = $env:BOT_TOKEN
)
$ErrorActionPreference = 'Stop'

$scriptsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $scriptsDir
$rootDir = (Resolve-Path -LiteralPath '..').Path

# Tenta di usare py launcher con 3.12/3.11 per compatibilità con le dipendenze
$pyExe = 'python'
$pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @('3.12','3.11')) {
        try { & py -$v -c "import sys" 2>$null; $pyExe = 'py'; $pyArgs = @("-$v"); break } catch {}
    }
}

if (-not $BotToken) {
    $tokenPath = Resolve-Path -LiteralPath '..\token.txt' -ErrorAction SilentlyContinue
    if ($tokenPath) { $BotToken = (Get-Content -Raw -Path $tokenPath).Trim() }
}
if (-not $BotToken) { Write-Error 'Imposta $env:BOT_TOKEN o crea ..\token.txt'; exit 1 }
$env:BOT_TOKEN = $BotToken
$env:FORCE_WEBHOOK = '0'

# Assicura un virtualenv locale con le dipendenze giuste
$venvPath = Resolve-Path -LiteralPath '..\.venv' -ErrorAction SilentlyContinue
if (-not $venvPath) {
    Write-Host 'Creo virtualenv locale (.venv)...'
    & $pyExe @pyArgs -m venv ..\.venv
}
$venvPy = Resolve-Path -LiteralPath '..\.venv\Scripts\python.exe' -ErrorAction SilentlyContinue
if (-not $venvPy) { Write-Error 'Virtualenv non trovato/creato. Verifica Python installato.'; exit 1 }

# Installa/aggiorna dipendenze
Write-Host 'Aggiorno pip e installo requirements...'
& $venvPy -m pip install --upgrade pip setuptools wheel | Out-Null
& $venvPy -m pip install -r (Join-Path $rootDir 'requirements.txt') | Out-Null

$py = $venvPy

# Chiude un eventuale processo precedente
if (Test-Path 'bot.pid') {
    try { $old = Get-Content -Raw 'bot.pid'; if ($old) { Stop-Process -Id ([int]$old) -Force -ErrorAction SilentlyContinue } } catch {}
    Remove-Item 'bot.pid' -ErrorAction SilentlyContinue
}

$outLog = Join-Path $scriptsDir 'bot_run.log'
$errLog = Join-Path $scriptsDir 'bot_err.log'
if (Test-Path $outLog) { Remove-Item $outLog -Force }
if (Test-Path $errLog) { Remove-Item $errLog -Force }

$bot = Start-Process -FilePath $py -ArgumentList @('-u', 'bot_completo.py') -WorkingDirectory $rootDir -NoNewWindow -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
"$($bot.Id)" | Set-Content -NoNewline 'bot.pid'
Write-Host ("Avviato in polling. PID: {0}" -f $bot.Id)
