@echo off
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
:: On utilise le python de Miniforge que ton script a identifié
"%USERPROFILE%\miniforge3\python.exe" "%~dp0nokido_mcp_server.py"