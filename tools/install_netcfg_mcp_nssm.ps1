# install_netcfg_mcp_nssm.ps1 - Convert startup .cmd into silent NSSM service
#
# Before: %APPDATA%\...\Startup\netcfg-agent-mcp.cmd opens visible cmd 30s post-login
# After : Windows service NokidoNetcfgMCP, 0 window, auto-start
#
# Run normal - script self-elevates via UAC.

$ErrorActionPreference = "Stop"

# Self-elevation
$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal $current
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[*] Not admin - relaunching via UAC..." -ForegroundColor Yellow
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$PSCommandPath`"")
    Start-Process powershell -Verb RunAs -ArgumentList $args
    exit
}

$svc        = "NokidoNetcfgMCP"
$exe        = "$env:USERPROFILE\Script python IA\netcfg-agent-mcp\dist\netcfg-agent-mcp.exe"
$workDir    = "$env:USERPROFILE\Script python IA\netcfg-agent-mcp"
$logDir     = "$env:USERPROFILE\Script python IA\netcfg-agent-mcp\logs"
$logOut     = Join-Path $logDir "mcp_http.stdout.log"
$logErr     = Join-Path $logDir "mcp_http.stderr.log"
$startupCmd = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\netcfg-agent-mcp.cmd"
$NSSM       = "C:\ProgramData\chocolatey\bin\nssm.exe"
$bakPath    = $null

if (-not (Test-Path $NSSM)) { throw "NSSM not found at $NSSM" }
if (-not (Test-Path $exe))  { throw "netcfg-agent-mcp.exe not found at $exe" }
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

Write-Host "[1/5] Stop + remove old instance ($svc)..." -ForegroundColor Cyan
$existing = Get-Service -Name $svc -ErrorAction SilentlyContinue
if ($existing) {
    cmd /c "`"$NSSM`" stop $svc" 2>&1 | Out-Null
    cmd /c "`"$NSSM`" remove $svc confirm" 2>&1 | Out-Null
    Write-Host "  Old instance removed."
} else {
    Write-Host "  No old instance."
}

Write-Host "[2/5] Install service $svc..." -ForegroundColor Cyan
& $NSSM install $svc $exe serve --transport http --host 127.0.0.1 --port 8767 --standalone
& $NSSM set $svc AppDirectory       $workDir
& $NSSM set $svc AppStdout          $logOut
& $NSSM set $svc AppStderr          $logErr
& $NSSM set $svc AppRotateFiles     1
& $NSSM set $svc AppRotateBytes     10485760
& $NSSM set $svc Start              SERVICE_AUTO_START
& $NSSM set $svc DisplayName        "Nokido netcfg-agent MCP :8767"
& $NSSM set $svc Description        "Silent HTTP transport netcfg-agent-mcp (replaces Startup .cmd)"
& $NSSM set $svc AppRestartDelay    5000
& $NSSM set $svc AppExit Default    Restart

Write-Host "[3/5] Kill orphan processes (cmd Startup + .exe children)..." -ForegroundColor Cyan
Get-Process -Name "netcfg-agent-mcp","cmd" -ErrorAction SilentlyContinue | Where-Object {
    ($_.Path -eq $exe) -or ($_.MainWindowTitle -match "netcfg-agent-mcp")
} | ForEach-Object {
    Write-Host ("  kill PID " + $_.Id + " (" + $_.ProcessName + ")")
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}

Write-Host "[4/5] Disable .cmd in Startup folder..." -ForegroundColor Cyan
if (Test-Path $startupCmd) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $bakPath = "$startupCmd.disabled-$stamp"
    Move-Item $startupCmd $bakPath -Force
    Write-Host ("  Moved -> " + $bakPath)
} else {
    Write-Host "  Already absent."
}

Write-Host "[5/5] Start service + check port 8767..." -ForegroundColor Cyan
& $NSSM start $svc
Start-Sleep -Seconds 6
$status = & $NSSM status $svc
Write-Host ("Status: " + $status)

$listen = Get-NetTCPConnection -LocalPort 8767 -State Listen -ErrorAction SilentlyContinue
if ($listen) {
    Write-Host ("OK: Port 8767 LISTEN by PID " + $listen.OwningProcess) -ForegroundColor Green
} else {
    Write-Host ("WARN: Port 8767 not in LISTEN. Check " + $logErr) -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Rollback commands:" -ForegroundColor DarkGray
Write-Host ("  nssm stop $svc; nssm remove $svc confirm") -ForegroundColor DarkGray
if ($bakPath) {
    Write-Host ("  Move-Item '$bakPath' '$startupCmd'") -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Press Enter to close..."
[void][System.Console]::ReadLine()
