$svc = "NokidoDenoProxy"
$bat = "$env:USERPROFILE\Script python IA\Nokido\tools\nokido_deno_proxy.bat"
$workDir = "$env:USERPROFILE\Script python IA\Nokido"
$logFile = "$env:USERPROFILE\Script python IA\Nokido\sandbox\deno_proxy.log"

nssm stop $svc 2>$null | Out-Null
nssm remove $svc confirm 2>$null | Out-Null

nssm install $svc $bat
nssm set $svc AppDirectory $workDir
nssm set $svc AppStdout $logFile
nssm set $svc AppStderr $logFile
nssm set $svc Start SERVICE_AUTO_START
nssm set $svc DisplayName "Nokido Deno Proxy nervous system :8000"
nssm set $svc Description "Phase A nervous system event-bus + persistence layer"
nssm set $svc AppRestartDelay 5000
nssm set $svc AppExit Default Restart

nssm start $svc
Start-Sleep -Seconds 5
Write-Host "Status:" (nssm status $svc)
