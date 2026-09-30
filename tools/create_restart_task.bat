@echo off
:: create_restart_task.bat — Crée une tâche planifiée pour restart Hub sans UAC
:: Lancer UNE SEULE FOIS en tant qu'Administrateur

SET TASK_NAME=NokidoHubRestart
SET TRIGGER_FILE=%USERPROFILE%\Script python IA\Nokido\sandbox\hub_restart.trigger

:: Supprimer si existe déjà
schtasks /delete /tn "%TASK_NAME%" /f 2>nul

:: Créer la tâche — déclenché sur création du fichier trigger
:: La tâche tourne en SYSTEM (droits admin implicites)
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "nssm restart NokidoHub" ^
  /sc ONEVENT ^
  /rl HIGHEST ^
  /ru SYSTEM ^
  /ec Application ^
  /mo "*[System[Provider[@Name='Microsoft-Windows-Security-Auditing']]]" ^
  /f

echo [FALLBACK] Utilisation d'un watcher fichier plus simple...

:: Approche plus robuste : script PowerShell watcher
SET WATCHER_SCRIPT=%USERPROFILE%\Script python IA\Nokido\tools\hub_restart_watcher.ps1

echo $trigger = "%USERPROFILE%\Script python IA\Nokido\sandbox\hub_restart.trigger" > "%WATCHER_SCRIPT%"
echo while ($true) { >> "%WATCHER_SCRIPT%"
echo     if (Test-Path $trigger) { >> "%WATCHER_SCRIPT%"
echo         Remove-Item $trigger -Force >> "%WATCHER_SCRIPT%"
echo         nssm restart NokidoHub >> "%WATCHER_SCRIPT%"
echo         Write-Host "[HubWatcher] Restart effectué $(Get-Date)" >> "%WATCHER_SCRIPT%"
echo     } >> "%WATCHER_SCRIPT%"
echo     Start-Sleep -Seconds 2 >> "%WATCHER_SCRIPT%"
echo } >> "%WATCHER_SCRIPT%"

:: Créer la tâche planifiée qui lance le watcher au démarrage
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "powershell -WindowStyle Hidden -File \"%WATCHER_SCRIPT%\"" ^
  /sc ONLOGON ^
  /rl HIGHEST ^
  /ru "%USERNAME%" ^
  /f

echo.
echo [OK] Tâche '%TASK_NAME%' créée.
echo Pour déclencher un restart : créer le fichier sandbox\hub_restart.trigger
echo Le watcher le détecte en moins de 2s et fait nssm restart NokidoHub.
echo.
echo Lancer le watcher maintenant ?
schtasks /run /tn "%TASK_NAME%"
pause
