@echo off
REM Wrapper pytest Nokido — force miniforge3 + isolation user-site
set PYTHONNOUSERSITE=1
"%USERPROFILE%\miniforge3\python.exe" -m pytest %*
