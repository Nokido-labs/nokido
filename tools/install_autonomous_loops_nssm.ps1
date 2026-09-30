$svc = "NokidoAutonomousLoops"
$bat = "$env:USERPROFILE\Script python IA\Nokido\tools\nokido_autonomous_loops.bat"
$workDir = "$env:USERPROFILE\Script python IA\Nokido"
$logFile = "$env:USERPROFILE\Script python IA\Nokido\sandbox\autonomous_loops_nssm.log"

nssm stop $svc 2>$null | Out-Null
nssm remove $svc confirm 2>$null | Out-Null

nssm install $svc $bat
nssm set $svc AppDirectory $workDir
nssm set $svc AppStdout $logFile
nssm set $svc AppStderr $logFile
nssm set $svc Start SERVICE_AUTO_START
nssm set $svc DisplayName "Nokido Autonomous Loops (free local LLMs)"
nssm set $svc Description "Boucle évolutive auto : 6 patterns recurrent (health/git/rag/effectiveness/forge_missing/consolidate). LLMs locaux only, zero cloud cost."
nssm set $svc AppRestartDelay 10000
nssm set $svc AppExit Default Restart

nssm start $svc
Start-Sleep -Seconds 5
Write-Host "Status:" (nssm status $svc)
