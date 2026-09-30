# restart_hub.ps1 - Reload du Hub via LaForge-Master (SOUVERAIN, Golden Rule #10).
#
# Le hub :8766 est spawné + POSSÉDÉ par le superviseur LaForge-Master. Faire
# `nssm stop/start NokidoMCP` DIRECT = crash-loop / conflit port 8766 (INTERDIT, Règle #10 ;
# NokidoMCP est d'ailleurs skip-NSSM = géré par le superviseur). On restart le MASTER ->
# il respawn proprement le hub + ses enfants (proxy, etc.) avec le nouveau code (ex: le
# forge_rbac qui lit le coffre DPAPI). Admin self-elevating.

$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal $current
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$PSCommandPath`""
    )
    exit
}

$NSSM = "C:\ProgramData\chocolatey\bin\nssm.exe"

Write-Host "[1/2] Restart LaForge-Master (respawn hub + flotte, charge le nouveau code)..." -ForegroundColor Cyan
cmd /c "`"$NSSM`" restart LaForge-Master"
Start-Sleep -Seconds 10

Write-Host "[2/2] Verify hub :8766 (warmup rag jusqu'a 60s)..." -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", 8766); $c.Close(); $ok = $true; break
    } catch { Start-Sleep -Seconds 2 }
}
if ($ok) {
    Write-Host "OK: hub :8766 UP (nouveau forge_rbac/DPAPI charge)" -ForegroundColor Green
} else {
    Write-Host "WARN: hub :8766 pas up apres 60s - verifier logs/supervisor" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Press Enter to close..."
[void][System.Console]::ReadLine()
