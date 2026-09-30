@echo off
REM Nokido Autonomous Loops daemon — NSSM wrapper
REM Lance forge_autonomous_loops.py --daemon (free LLMs locaux only)

cd /d "%USERPROFILE%\Script python IA\Nokido"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PYTHONNOUSERSITE=1
"%USERPROFILE%\miniforge3\envs\laforge_py314\python.exe" app\forge_autonomous_loops.py --daemon --tick 60
