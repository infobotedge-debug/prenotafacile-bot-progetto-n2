param(
    [string]$BotToken = $env:BOT_TOKEN
)
$ErrorActionPreference = 'Stop'

$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $repoDir

if (-not $BotToken) {
    $tokenPath = Resolve-Path -LiteralPath '..\token.txt' -ErrorAction SilentlyContinue
    if ($tokenPath) { $BotToken = (Get-Content -Raw -Path $tokenPath).Trim() }
}
if (-not $BotToken) { Write-Error 'Imposta $env:BOT_TOKEN o crea ..\token.txt'; exit 1 }
$env:BOT_TOKEN = $BotToken
$env:FORCE_WEBHOOK = '0'

$venvPy = Resolve-Path -LiteralPath '..\.venv\Scripts\python.exe' -ErrorAction SilentlyContinue
$py = if ($venvPy) { $venvPy } else { 'python' }

$outLog = 'bot_run.log'
$errLog = 'bot_err.log'
if (Test-Path $outLog) { Remove-Item $outLog -Force }
if (Test-Path $errLog) { Remove-Item $errLog -Force }

$bot = Start-Process -FilePath $py -ArgumentList '-u','bot_completo.py' -NoNewWindow -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
"$($bot.Id)" | Set-Content -NoNewline 'bot.pid'
Write-Host ("Avviato in polling. PID: {0}" -f $bot.Id)
