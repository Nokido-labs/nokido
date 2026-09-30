@echo off
REM Install gemini_poll_daemon comme service NSSM
REM Usage : run as Administrator
REM Cible : NokidoGeminiDaemon (auto-restart, persistance reboot)

setlocal

set SVC=NokidoGeminiDaemon
set ROOT=%USERPROFILE%\Script python IA\Nokido
set PY=%USERPROFILE%\miniforge3\python.exe
set SCRIPT=%ROOT%\tools\gemini_poll_daemon.py

REM Verifier si le service existe deja
nssm status %SVC% >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] Service %SVC% existe deja. Stop + remove avant reinstall.
    nssm stop %SVC%
    nssm remove %SVC% confirm
)

echo [INFO] Installation %SVC%...
nssm install %SVC% "%PY%"
nssm set %SVC% AppParameters "\"%SCRIPT%\" --mode active --interval 30"

REM Configuration NSSM
nssm set %SVC% AppDirectory "%ROOT%"
nssm set %SVC% AppEnvironmentExtra ^
    "PYTHONNOUSERSITE=1" ^
    "PYTHONIOENCODING=utf-8" ^
    "FORGE_HUB_URL=http://127.0.0.1:8766" ^
    "GEMINI_POLL_MODE=active" ^
    "GEMINI_POLL_INTERVAL_S=30"

REM Logs separes
nssm set %SVC% AppStdout "%ROOT%\sandbox\gemini_poll_daemon.log"
nssm set %SVC% AppStderr "%ROOT%\sandbox\gemini_poll_daemon.log"
nssm set %SVC% AppRotateFiles 1
nssm set %SVC% AppRotateBytes 10485760

REM Restart auto en cas de crash
nssm set %SVC% AppExit Default Restart
nssm set %SVC% AppRestartDelay 5000
nssm set %SVC% AppThrottle 30000

REM Demarrage automatique au boot
nssm set %SVC% Start SERVICE_AUTO_START

REM Description
nssm set %SVC% Description "Nokido Gemini polling daemon — autonomie inter-agents (cascade API > OAuth > Groq)"

echo [INFO] Configuration terminee. Demarrage du service...
nssm start %SVC%

echo.
echo [DONE] Service %SVC% installe et demarre.
echo Verifier : nssm status %SVC%
echo Logs    : %ROOT%\sandbox\gemini_poll_daemon.log
echo Stop    : nssm stop %SVC%
echo Remove  : nssm remove %SVC% confirm

endlocal
