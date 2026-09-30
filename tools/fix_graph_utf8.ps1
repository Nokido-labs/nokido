$svc = "NokidoGraph"
# Use newline as separator (NSSM accepts both NUL and LF)
$envBlock = "PYTHONIOENCODING=utf-8`r`nPYTHONUTF8=1`r`nPYTHONNOUSERSITE=1"
nssm set $svc AppEnvironmentExtra $envBlock
# Restart properly
nssm stop $svc
Start-Sleep -Seconds 2
nssm start $svc
Start-Sleep -Seconds 12
$status = nssm status $svc
Write-Host "Status:" $status
Write-Host "Env:"
nssm get $svc AppEnvironmentExtra
