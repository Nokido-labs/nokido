$svc = "NokidoWebHub"
$pyOld = (nssm get $svc Application)
Write-Host "[BEFORE] Application: $pyOld"
Write-Host "[BEFORE] AppParameters: $(nssm get $svc AppParameters)"

# Switch to py314
$py314 = "$env:USERPROFILE\miniforge3\envs\laforge_py314\python.exe"
nssm set $svc Application $py314

# Force PYTHONNOUSERSITE=1 to avoid user-site pollution shadow
$envBlock = "PYTHONNOUSERSITE=1`0PYTHONIOENCODING=utf-8`0PYTHONUTF8=1"
nssm set $svc AppEnvironmentExtra $envBlock

Write-Host ""
Write-Host "[AFTER] Application: $(nssm get $svc Application)"
Write-Host "[AFTER] AppEnvironmentExtra:"
nssm get $svc AppEnvironmentExtra

Write-Host ""
Write-Host "Restarting service..."
nssm restart $svc

Start-Sleep -Seconds 5
Write-Host "Status: $(nssm status $svc)"
