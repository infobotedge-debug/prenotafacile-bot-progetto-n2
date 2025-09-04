param(
    [switch]$Hard
)
$ErrorActionPreference = 'Stop'

$scriptsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $scriptsDir

function Stop-ByPidFile {
    if (Test-Path 'bot.pid') {
        try {
            $pid = (Get-Content -Raw 'bot.pid').Trim()
            if ($pid) {
                Write-Host ("Arresto processo PID: {0}" -f $pid)
                Stop-Process -Id ([int]$pid) -Force -ErrorAction SilentlyContinue
            }
        } catch {}
        Remove-Item 'bot.pid' -ErrorAction SilentlyContinue
    } else {
        Write-Host 'Nessun bot.pid trovato'
    }
}

function Stop-HardFallback {
    try {
        $procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'bot_completo\.py' }
        foreach ($p in $procs) {
            try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ("Terminato PID {0}" -f $p.ProcessId) } catch {}
        }
    } catch {}
}

Stop-ByPidFile
if ($Hard) { Stop-HardFallback }
Write-Host 'Stop completato.'
