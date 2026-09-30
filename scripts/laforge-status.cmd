@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PYTHON="
if exist "%USERPROFILE%\miniforge3\python.exe" (
    "%USERPROFILE%\miniforge3\python.exe" -c "import fastapi" >nul 2>&1
    if !errorlevel!==0 set "PYTHON=%USERPROFILE%\miniforge3\python.exe"
)
if "!PYTHON!"=="" if exist "%USERPROFILE%\anaconda3\python.exe" (
    "%USERPROFILE%\anaconda3\python.exe" -c "import fastapi" >nul 2>&1
    if !errorlevel!==0 set "PYTHON=%USERPROFILE%\anaconda3\python.exe"
)
if "!PYTHON!"=="" if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "import fastapi" >nul 2>&1
    if !errorlevel!==0 set "PYTHON=%~dp0.venv\Scripts\python.exe"
)
if "!PYTHON!"=="" (
    where python >nul 2>&1
    if !errorlevel!==0 (
        python -c "import fastapi" >nul 2>&1
        if !errorlevel!==0 set "PYTHON=python"
    )
)
if "!PYTHON!"=="" (
    where py >nul 2>&1
    if !errorlevel!==0 (
        py -3 -c "import fastapi" >nul 2>&1
        if !errorlevel!==0 set "PYTHON=py -3"
    )
)
if "!PYTHON!"=="" (
    echo [ERREUR] Aucun Python avec fastapi trouve. Vois laforge-start.cmd.
    pause
    exit /b 1
)

%PYTHON% tools\nokido.py status
echo.
pause
endlocal
