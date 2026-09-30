@echo off
REM ============================================================
REM Nokido - Start (double-click)
REM
REM Strategie Python : prefere conda (miniforge/anaconda) si present
REM dans PATH, sinon py -3, sinon python.
REM Si le Python trouve n a pas fastapi, on bascule sur le suivant.
REM ============================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"

set "PYTHON="

REM 1. miniforge3 user typique
if exist "%USERPROFILE%\miniforge3\python.exe" (
    "%USERPROFILE%\miniforge3\python.exe" -c "import fastapi" >nul 2>&1
    if !errorlevel!==0 (
        set "PYTHON=%USERPROFILE%\miniforge3\python.exe"
        goto :found
    )
)

REM 2. anaconda3 user typique
if exist "%USERPROFILE%\anaconda3\python.exe" (
    "%USERPROFILE%\anaconda3\python.exe" -c "import fastapi" >nul 2>&1
    if !errorlevel!==0 (
        set "PYTHON=%USERPROFILE%\anaconda3\python.exe"
        goto :found
    )
)

REM 3. venv local .venv/
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "import fastapi" >nul 2>&1
    if !errorlevel!==0 (
        set "PYTHON=%~dp0.venv\Scripts\python.exe"
        goto :found
    )
)

REM 4. python dans PATH
where python >nul 2>&1
if !errorlevel!==0 (
    python -c "import fastapi" >nul 2>&1
    if !errorlevel!==0 (
        set "PYTHON=python"
        goto :found
    )
)

REM 5. py -3 launcher
where py >nul 2>&1
if !errorlevel!==0 (
    py -3 -c "import fastapi" >nul 2>&1
    if !errorlevel!==0 (
        set "PYTHON=py -3"
        goto :found
    )
)

echo [ERREUR] Aucun Python avec fastapi installe trouve.
echo.
echo Verifie que l environnement Nokido est configure :
echo   pip install fastapi uvicorn httpx websockets pyjwt psutil textual-serve
echo.
echo Ou active d abord conda dans ce terminal :
echo   conda activate base
echo   python tools\nokido.py up
echo.
pause
exit /b 1

:found
echo ============================================================
echo Nokido - Demarrage de la stack
echo Python: %PYTHON%
echo ============================================================
echo.

REM Diagnostic
%PYTHON% tools\nokido.py doctor
if !errorlevel! neq 0 (
    echo.
    echo [ERREUR] Le diagnostic a detecte un probleme critique.
    echo Corrige les KO ci-dessus puis relance.
    pause
    exit /b 1
)

echo.
echo [*] Demarrage des modules...
%PYTHON% tools\nokido.py up
if !errorlevel! neq 0 (
    echo [ERREUR] Echec du demarrage.
    echo Logs: sandbox\logs\
    pause
    exit /b 1
)

REM Petite pause pour laisser le temps au hub de demarrer
REM ( < NUL redirige stdin proprement pour timeout )
timeout /t 2 /nobreak >nul < NUL

echo.
echo [*] Ouverture du navigateur...
%PYTHON% tools\nokido.py open

echo.
echo ============================================================
echo Hub demarre : http://localhost:7400/
echo Panel       : http://localhost:7400/launcher
echo.
echo Pour arreter : double-clic sur laforge-stop.cmd
echo ============================================================
echo.
pause
endlocal
