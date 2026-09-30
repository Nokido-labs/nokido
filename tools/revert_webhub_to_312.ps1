$svc = "NokidoWebHub"
$py312 = "$env:USERPROFILE\miniforge3\python.exe"
nssm set $svc Application $py312
# Clear AppEnvironmentExtra to default
nssm set $svc AppEnvironmentExtra
nssm restart $svc
Start-Sleep -Seconds 4
Write-Host "Application: $(nssm get $svc Application)"
Write-Host "Status: $(nssm status $svc)"
