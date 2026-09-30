@echo off
REM ============================================================================
REM wake_respawn.bat - relance Nokido apres wake-from-sleep Windows.
REM Declenche par scheduled task LaForge-WakeRespawn (EventID 107 Power-Troubleshooter).
REM Tourne en SYSTEM (S-1-5-18), HighestAvailable, sans UI.
REM ============================================================================
set LOGFILE=%USERPROFILE%\Script python IA\Nokido\logs\wake_respawn.log
echo === WAKE %DATE% %TIME% === >> "%LOGFILE%"

REM Step 1 : nettoyer les PID files orphelins
"%USERPROFILE%\miniforge3\python.exe" "%USERPROFILE%\Script python IA\Nokido\tools\forge_pid_gc.py" >> "%LOGFILE%" 2>&1

REM Step 2 : si LaForge-Master n'est pas running, le redemarrer
sc query LaForge-Master | findstr /C:"RUNNING" >nul
if %ERRORLEVEL% neq 0 (
    echo [wake] LaForge-Master NOT running - starting >> "%LOGFILE%"
    nssm start LaForge-Master >> "%LOGFILE%" 2>&1
) else (
    echo [wake] LaForge-Master already running - skip start >> "%LOGFILE%"
)

REM Step 3 : poser un flag pause sur embed_rebuild pendant 5min (laisse RAM se stabiliser)
echo wake-stabilization > "%USERPROFILE%\Script python IA\Nokido\sandbox\embed_rebuild_pause"

echo === END %DATE% %TIME% === >> "%LOGFILE%"
