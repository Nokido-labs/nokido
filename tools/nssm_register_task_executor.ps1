# Register forge_task_executor as NSSM service running as .\user
# Runs under user account so gemini_cli OAuth works
param([string]$Password = "")

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$Python = "$env:USERPROFILE\miniforge3\python.exe"
$Script = "$Root\tools\forge_task_executor.py"
$LogDir = "$Root\logs"
$SvcName = "NokidoTaskExecutor"

if (-not $Password) {
    $secpwd = Read-Host "Password for .\user" -AsSecureString
    $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secpwd))
}

# Stop + delete if exists
if (Get-Service $SvcName -ErrorAction SilentlyContinue) {
    Write-Host "Removing existing $SvcName..."
    nssm stop $SvcName confirm
    nssm remove $SvcName confirm
    Start-Sleep 2
}

Write-Host "Registering $SvcName..."
nssm install $SvcName $Python
nssm set $SvcName AppParameters $Script
nssm set $SvcName AppDirectory $Root
nssm set $SvcName DisplayName "Nokido Task Executor Daemon"
nssm set $SvcName Description "Poll tasks.db + dispatch via hub ask (gemini_cli user OAuth)"
nssm set $SvcName Start SERVICE_AUTO_START
nssm set $SvcName ObjectName ".\user" $Password
# Token lu depuis Nokido.env au runtime — ne pas hardcoder ici
# nssm set $SvcName AppEnvironmentExtra "FORGE_MCP_TOKEN=<token_from_Nokido.env>"
nssm set $SvcName AppStdout "$LogDir\task_executor_stdout.log"
nssm set $SvcName AppStderr "$LogDir\task_executor_stderr.log"
nssm set $SvcName AppRotateFiles 1
nssm set $SvcName AppRotateOnline 1
nssm set $SvcName AppRotateBytes 5242880

Write-Host "Starting $SvcName..."
nssm start $SvcName
Start-Sleep 3
$svc = Get-Service $SvcName -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host "Status: $($svc.Status)"
} else {
    Write-Host "Service not found after start"
}
