@echo off
:: install_hub_service.bat — Installe Nokido Hub comme service Windows via NSSM
:: Prérequis : NSSM installé (choco install nssm)
:: Lancer en tant qu'Administrateur

SET SERVICE_NAME=NokidoHub
SET PYTHON=%USERPROFILE%\miniforge3\python.exe
SET SCRIPT=%USERPROFILE%\Script python IA\Nokido\tools\nokido_hub.py
SET WORKDIR=%USERPROFILE%\Script python IA\Nokido
SET LOGDIR=%USERPROFILE%\Script python IA\Nokido\sandbox

echo [1/5] Arret du service existant (si present)...
nssm stop %SERVICE_NAME% 2>nul
nssm remove %SERVICE_NAME% confirm 2>nul

echo [2/5] Installation du service...
:: IMPORTANT : NSSM sépare command et arguments — pas de guillemets dans AppParameters
nssm install %SERVICE_NAME% "%PYTHON%"
nssm set %SERVICE_NAME% AppParameters "\"%SCRIPT%\""
nssm set %SERVICE_NAME% AppDirectory "%WORKDIR%"
nssm set %SERVICE_NAME% AppStdout "%LOGDIR%\hub_stdout.log"
nssm set %SERVICE_NAME% AppStderr "%LOGDIR%\hub_stderr.log"
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateBytes 10485760
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% DisplayName "Nokido Hub MCP v17"
nssm set %SERVICE_NAME% Description "Serveur MCP autonome Nokido — Hub central multi-agents"

echo [3/5] Demarrage du service...
nssm start %SERVICE_NAME%

echo [4/5] Verification...
timeout /t 4 >nul
nssm status %SERVICE_NAME%

echo [5/5] Test healthcheck...
powershell -Command "try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8766/health' -UseBasicParsing).Content } catch { 'Hub non accessible: ' + $_.Exception.Message }"

echo.
echo [OK] Nokido Hub installe.
echo Logs stdout : %LOGDIR%\hub_stdout.log
echo Logs stderr : %LOGDIR%\hub_stderr.log
echo Logs live   : %LOGDIR%\hub_live.log
echo Pour arreter    : nssm stop NokidoHub
echo Pour desinstaller : nssm remove NokidoHub confirm
pause
