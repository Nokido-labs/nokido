#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Bascule NokidoMCP de LocalSystem vers le compte utilisateur user.
    Permet a Gemini CLI / Claude CLI / autres outils OAuth de voir le bon profil.

.NOTES
    Rollback : nssm set NokidoMCP ObjectName LocalSystem ; nssm restart NokidoMCP

.PARAMETER UserName
    Nom du compte cible (defaut: user)

.PARAMETER SkipGeminiTest
    Skip le test gemini_cli a la fin
#>
param(
    [string]$UserName = "user",
    [switch]$SkipGeminiTest
)

$ErrorActionPreference = "Stop"

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin) {
    Write-Host "ERREUR : execute en administrateur." -ForegroundColor Red
    exit 1
}

$LF_ROOT = "$env:USERPROFILE\Script python IA\Nokido"
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupDir = "$LF_ROOT\sandbox\backups\nssm-switch-$ts"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

Write-Host "[1/7] Sauvegarde NSSM dump dans $BackupDir" -ForegroundColor Cyan
nssm dump NokidoMCP > "$BackupDir\nssm_dump.txt"
$currentObject = (nssm get NokidoMCP ObjectName).Trim()
Write-Host "      ObjectName actuel : $currentObject"

Write-Host "`n[2/7] Verification OAuth Gemini" -ForegroundColor Cyan
$geminiOAuth = "C:\Users\$UserName\.gemini\oauth_creds.json"
if (-not (Test-Path $geminiOAuth)) {
    Write-Host "      AVERTISSEMENT : $geminiOAuth absent" -ForegroundColor Yellow
    Write-Host "      Lance 'gemini' dans un terminal user et fais le login OAuth, puis relance ce script."
    $continue = Read-Host "      Continuer quand meme ? (o/N)"
    if ($continue -ne "o") {
        exit 0
    }
} else {
    $age = (Get-Date) - (Get-Item $geminiOAuth).LastWriteTime
    Write-Host "      oauth_creds.json present, age $($age.TotalHours.ToString('F1'))h" -ForegroundColor Green
}

Write-Host "`n[3/7] Mot de passe pour $UserName" -ForegroundColor Cyan
$securePass = Read-Host -AsSecureString "Mot de passe Windows de $UserName"
$BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePass)
$plainPass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)

Write-Host "`n[4/7] Grant SeServiceLogonRight a $UserName" -ForegroundColor Cyan
$tmpInf = "$env:TEMP\nssm_grant_$ts.inf"
$tmpDb  = "$env:TEMP\nssm_grant_$ts.sdb"

secedit /export /cfg "$tmpInf" /quiet | Out-Null

$sid = (New-Object System.Security.Principal.NTAccount($UserName)).Translate(
    [System.Security.Principal.SecurityIdentifier]).Value

$cfg = Get-Content $tmpInf -Raw
if ($cfg -match "SeServiceLogonRight\s*=\s*([^\r\n]*)") {
    $existing = $Matches[1]
    if ($existing -notmatch [regex]::Escape($sid)) {
        $newLine = "SeServiceLogonRight = $existing,*$sid"
        $cfg = $cfg -replace "SeServiceLogonRight\s*=\s*[^\r\n]*", $newLine
    } else {
        Write-Host "      $UserName a deja SeServiceLogonRight" -ForegroundColor Green
    }
} else {
    $cfg = $cfg -replace "(\[Privilege Rights\]\s*\r?\n)", "`$1SeServiceLogonRight = *$sid`r`n"
}
$cfg | Set-Content $tmpInf -Encoding Unicode
secedit /configure /db "$tmpDb" /cfg "$tmpInf" /areas USER_RIGHTS /quiet | Out-Null
Remove-Item $tmpInf, $tmpDb -Force -ErrorAction SilentlyContinue
Write-Host "      OK" -ForegroundColor Green

Write-Host "`n[5/7] Bascule NSSM ObjectName -> .\$UserName" -ForegroundColor Cyan
nssm set NokidoMCP ObjectName ".\$UserName" $plainPass | Out-Null
$plainPass = $null
[System.GC]::Collect()
$newObject = (nssm get NokidoMCP ObjectName).Trim()
Write-Host "      ObjectName apres : $newObject"

Write-Host "`n[6/7] Restart service + attente /health" -ForegroundColor Cyan
nssm restart NokidoMCP | Out-Null
Start-Sleep -Seconds 3

$hubOk = $false
for ($i = 0; $i -lt 12; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8766/health" -TimeoutSec 2 -UseBasicParsing
        if ($resp.StatusCode -eq 200) {
            Write-Host "      Hub UP : $($resp.Content)" -ForegroundColor Green
            $hubOk = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $hubOk) {
    Write-Host "      Hub PAS UP apres 12s. Check logs/mcp_service_err.log" -ForegroundColor Red
    exit 1
}

$svc = Get-CimInstance Win32_Service -Filter "Name='NokidoMCP'"
Write-Host "      Service tourne sous : $($svc.StartName)" -ForegroundColor Green

if (-not $SkipGeminiTest) {
    Write-Host "`n[7/7] Test gemini_cli depuis le hub" -ForegroundColor Cyan
    $body = @{
        jsonrpc = "2.0"; id = 99; method = "tools/call"
        params = @{
            name = "ask"
            arguments = @{
                provider = "gemini_cli"
                message = "reply with single word: pong"
                max_tokens = 10
            }
        }
    } | ConvertTo-Json -Depth 5
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8766/mcp" `
            -Method POST -Body $body `
            -ContentType "application/json" `
            -Headers @{"Accept"="application/json, text/event-stream"} `
            -TimeoutSec 30 -UseBasicParsing
        $snippet = $resp.Content.Substring(0, [Math]::Min(500, $resp.Content.Length))
        Write-Host "      Reponse : $snippet" -ForegroundColor Green
    } catch {
        Write-Host "      Test KO : $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "`n[7/7] Test gemini_cli SKIP (parametre)" -ForegroundColor DarkGray
}

Write-Host "`nTERMINE. Backup : $BackupDir\nssm_dump.txt" -ForegroundColor Cyan
Write-Host "Rollback : nssm set NokidoMCP ObjectName LocalSystem ; nssm restart NokidoMCP"
