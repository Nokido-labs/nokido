# kill-gemini.ps1 - Trouve et tue les daemons Gemini Nokido
# Usage : .\kill-gemini.ps1
#
# Auteur : Claude (audit securite 2026-04-25)

Write-Host "=== Recherche des daemons Gemini ===" -ForegroundColor Cyan

$processes = Get-CimInstance Win32_Process | Where-Object { 
    $_.CommandLine -and (
        $_.CommandLine -match "gemini_poll_daemon" -or
        $_.CommandLine -match "gemini.*daemon" -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -match "gemini_with_inbox") -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -match "forge_agent_proxy")
    )
}

if (-not $processes) {
    Write-Host "Aucun daemon Gemini trouve. Rien a tuer." -ForegroundColor Green
    exit 0
}

Write-Host "`nProcessus trouves :" -ForegroundColor Yellow
$processes | ForEach-Object {
    $cmd = if ($_.CommandLine.Length -gt 120) { $_.CommandLine.Substring(0, 120) + "..." } else { $_.CommandLine }
    Write-Host "  PID=$($_.ProcessId)  Name=$($_.Name)  Cmd=$cmd"
}

Write-Host "`nConfirmation : tuer tous ces processus ? (O/N)" -ForegroundColor Yellow -NoNewline
$confirm = Read-Host " "

if ($confirm -ne "O" -and $confirm -ne "o" -and $confirm -ne "Y" -and $confirm -ne "y") {
    Write-Host "Annule par l'utilisateur." -ForegroundColor Red
    exit 0
}

Write-Host "`n=== Killing processes ===" -ForegroundColor Cyan
$killed = 0
foreach ($p in $processes) {
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        Write-Host "  KILLED PID $($p.ProcessId)" -ForegroundColor Green
        $killed++
    } catch {
        Write-Host "  FAILED PID $($p.ProcessId) : $_" -ForegroundColor Red
    }
}

Write-Host "`n=== Done : $killed processus tues ===" -ForegroundColor Cyan

# Verif finale
Start-Sleep -Seconds 2
$remaining = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine -match "gemini_poll_daemon"
}
if ($remaining) {
    Write-Host "`nATTENTION : il reste des daemons :" -ForegroundColor Red
    $remaining | ForEach-Object { Write-Host "  PID $($_.ProcessId)" }
} else {
    Write-Host "`nVerification : aucun daemon Gemini residual." -ForegroundColor Green
}
