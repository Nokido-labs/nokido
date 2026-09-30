$svc = "NokidoGraph"
# NSSM AppEnvironmentExtra : NUL-separated KEY=VAL, multi via array
$envArr = @("PYTHONNOUSERSITE=1", "PYTHONIOENCODING=utf-8", "PYTHONUTF8=1")
$envBlock = ($envArr -join [char]0)
nssm set $svc AppEnvironmentExtra $envBlock
nssm restart $svc
Start-Sleep -Seconds 15
$status = nssm status $svc
Write-Host "Status:" $status
Write-Host "Env:"
nssm get $svc AppEnvironmentExtra
