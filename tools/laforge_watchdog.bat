@echo off
REM Nokido Service Watchdog — NSSM wrapper
REM Surveille les 7 services HTTP et redémarre si DOWN 2x consécutif

cd /d "%NOKIDO_ROOT%"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PYTHONNOUSERSITE=1
set LAFORGE_WATCHDOG_INTERVAL=30
set LAFORGE_WATCHDOG_FAIL_THRESHOLD=2
"%USERPROFILE%\miniforge3\python.exe" app\forge_service_watchdog.py --interval 30
