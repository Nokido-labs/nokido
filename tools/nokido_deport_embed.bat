@echo off
REM nokido_deport_embed.bat — lanceur de la vectorisation DEPORTEE (tache planifiee).
REM
REM Pourquoi un .bat plutot qu'une ligne schtasks /TR : le chemin du depot contient
REM une ESPACE ("Script python IA") et la commande imbrique deja des guillemets.
REM Passer tout ca a schtasks depuis PowerShell casse le quoting une fois sur deux
REM (mesure 2026-07-31). Ici schtasks ne voit qu'un seul chemin, sans argument.
REM
REM Le job est idempotent : il ne prend que les chunks embedding IS NULL, s'arrete
REM proprement sur quota (429) et elit le premier provider cloud qui repond.
REM Les cles viennent du COFFRE MACHINE (DPAPI machine), pas du .env.
REM
REM Installation (console ADMIN) :
REM   schtasks /Create /TN "Nokido-DeportEmbed" /SC HOURLY /RU user /RL HIGHEST /F /TR "%NOKIDO_ROOT%\tools\nokido_deport_embed.bat"
REM Verification :
REM   schtasks /Query /TN "Nokido-DeportEmbed" /V /FO LIST
REM Desinstallation :
REM   schtasks /Delete /TN "Nokido-DeportEmbed" /F

setlocal
set "PY=%USERPROFILE%\miniforge3\python.exe"
set "SCRIPT=%~dp0forge_reindex_deport.py"
set "MAX=%1"
if "%MAX%"=="" set "MAX=8000"

if not exist "%PY%" (
    echo [deport] ERREUR: interpreteur introuvable: %PY%
    exit /b 1
)
if not exist "%SCRIPT%" (
    echo [deport] ERREUR: script introuvable: %SCRIPT%
    exit /b 1
)

echo [deport] %DATE% %TIME% - lot de %MAX% chunks
"%PY%" "%SCRIPT%" --embed-only --max %MAX%
exit /b %ERRORLEVEL%
