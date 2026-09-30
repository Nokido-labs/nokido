$svc = "NokidoDenoWebHub"
$bat = "$env:USERPROFILE\Script python IA\Nokido\tools\nokido_deno_webhub.bat"
$workDir = "$env:USERPROFILE\Script python IA\Nokido"
$logFile = "$env:USERPROFILE\Script python IA\Nokido\sandbox\deno_webhub.log"

# Cleanup if exists
nssm stop $svc 2>$null | Out-Null
nssm remove $svc confirm 2>$null | Out-Null

# Install
nssm install $svc $bat
if ($LASTEXITCODE -ne 0) { Write-Host "[ERR] install failed"; exit 1 }

# Configure
nssm set $svc AppDirectory $workDir
nssm set $svc AppStdout $logFile
nssm set $svc AppStderr $logFile
nssm set $svc Start SERVICE_AUTO_START
nssm set $svc DisplayName "Nokido Deno WebHub :7401"
nssm set $svc Description "Deno port webhub PUBLIC layer (Phase B.1) parallel to Python :7400"

# Start
nssm start $svc

Start-Sleep -Seconds 4
$status = (nssm status $svc)
Write-Host "Service status : $status"
