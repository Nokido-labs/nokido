$svc = "NokidoDenoHubMCP"
$bat = "$env:USERPROFILE\Script python IA\Nokido\tools\nokido_deno_hub_mcp.bat"
$workDir = "$env:USERPROFILE\Script python IA\Nokido"
$logFile = "$env:USERPROFILE\Script python IA\Nokido\sandbox\deno_hub_mcp.log"

nssm stop $svc 2>$null | Out-Null
nssm remove $svc confirm 2>$null | Out-Null

nssm install $svc $bat
if ($LASTEXITCODE -ne 0) { Write-Host "[ERR] install failed"; exit 1 }

nssm set $svc AppDirectory $workDir
nssm set $svc AppStdout $logFile
nssm set $svc AppStderr $logFile
nssm set $svc Start SERVICE_AUTO_START
nssm set $svc DisplayName "Nokido Deno Hub MCP :8769"
nssm set $svc Description "Deno port Hub MCP (Phase B.2) parallel Python :8766. Bearer auth + tools/call delegate."

nssm start $svc
Start-Sleep -Seconds 4
Write-Host "Service status : $(nssm status $svc)"
