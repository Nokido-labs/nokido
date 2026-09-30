@echo off
:: install_woodpecker_agent.bat — Installe l'agent Woodpecker comme service Windows
:: Prérequis :
::   1. Télécharger woodpecker-agent.exe depuis :
::      https://github.com/woodpecker-ci/woodpecker/releases/latest
::      -> woodpecker-agent_windows_amd64.exe -> renommer en woodpecker-agent.exe
::   2. Placer woodpecker-agent.exe dans C:\tools\woodpecker\
::   3. Configurer tools\woodpecker.env (TOKEN + SERVER)
::   4. Lancer ce script en tant qu'Administrateur

SET SERVICE_NAME=WoodpeckerAgent
SET AGENT_DIR=C:\tools\woodpecker
SET AGENT_EXE=%AGENT_DIR%\woodpecker-agent.exe
SET ENV_FILE=%USERPROFILE%\Script python IA\Nokido\tools\woodpecker.env
SET LOGDIR=%USERPROFILE%\Script python IA\Nokido\sandbox
SET WORKDIR=%USERPROFILE%\Script python IA\Nokido

echo ============================================================
echo  Nokido — Installation Woodpecker Agent comme service NSSM
echo ============================================================

:: Vérifier que l'exe existe
if not exist "%AGENT_EXE%" (
    echo [ERREUR] woodpecker-agent.exe introuvable dans %AGENT_DIR%
    echo.
    echo Télécharge-le ici :
    echo https://github.com/woodpecker-ci/woodpecker/releases/latest
    echo Renomme en woodpecker-agent.exe et place dans %AGENT_DIR%
    pause
    exit /b 1
)

echo [1/5] Arret du service existant...
nssm stop %SERVICE_NAME% 2>nul
nssm remove %SERVICE_NAME% confirm 2>nul

echo [2/5] Création du répertoire agent...
if not exist "%AGENT_DIR%" mkdir "%AGENT_DIR%"

echo [3/5] Installation du service NSSM...
nssm install %SERVICE_NAME% "%AGENT_EXE%"
nssm set %SERVICE_NAME% AppParameters "agent"
nssm set %SERVICE_NAME% AppDirectory "%WORKDIR%"
nssm set %SERVICE_NAME% AppEnvironmentExtra "WOODPECKER_BACKEND=local" "WOODPECKER_LOG_LEVEL=info" "PYTHONUTF8=1" "PYTHONUNBUFFERED=1" "PATH=%USERPROFILE%\miniforge3;%USERPROFILE%\miniforge3\Scripts;C:\Program Files\Git\cmd;C:\Program Files\Git\mingw64\bin;%PATH%"
nssm set %SERVICE_NAME% AppStdout "%LOGDIR%\woodpecker_stdout.log"
nssm set %SERVICE_NAME% AppStderr "%LOGDIR%\woodpecker_stderr.log"
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateBytes 5242880
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% DisplayName "Nokido Woodpecker CI Agent"
nssm set %SERVICE_NAME% Description "Agent CI Woodpecker — Local Backend — Nokido v17"

echo [4/5] Configuration TOKEN depuis woodpecker.env...
:: Lire le token depuis woodpecker.env
for /f "tokens=2 delims==" %%a in ('findstr "WOODPECKER_TOKEN" "%ENV_FILE%"') do (
    nssm set %SERVICE_NAME% AppEnvironmentExtra "WOODPECKER_TOKEN=%%a"
)
for /f "tokens=2 delims==" %%a in ('findstr "WOODPECKER_SERVER" "%ENV_FILE%"') do (
    nssm set %SERVICE_NAME% AppEnvironmentExtra "WOODPECKER_SERVER=%%a"
)

echo [5/5] Démarrage du service...
nssm start %SERVICE_NAME%
timeout /t 3 >nul
nssm status %SERVICE_NAME%

echo.
echo ============================================================
echo  Woodpecker Agent installé !
echo  Logs : %LOGDIR%\woodpecker_stdout.log
echo  Pour arrêter  : nssm stop WoodpeckerAgent
echo  Pour redémarrer : nssm restart WoodpeckerAgent
echo ============================================================
pause
