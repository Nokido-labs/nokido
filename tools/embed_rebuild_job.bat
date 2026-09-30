@echo off
REM ============================================================================
REM embed_rebuild_job.bat — rebuild des embeddings RAG restants puis arret auto.
REM Job GPU local (llama-server Vulkan) : DOIT tourner en contexte user user.
REM Declenche par la tache planifiee LaForge-EmbedRebuild (schtasks /run).
REM Etat sauvegarde en continu : forge_rebuild_local.py commit la DB par batch.
REM ============================================================================
del /q C:\tmp\embed_DONE.txt C:\tmp\embed_FAILED.txt 2>nul
echo === START %DATE% %TIME% === > C:\tmp\embed_rebuild.log
cd /d "%USERPROFILE%\Script python IA\Nokido"
"%USERPROFILE%\miniforge3\envs\laforge_py314t\python.exe" tools\forge_rebuild_local.py 4 >> C:\tmp\embed_rebuild.log 2>&1
set RC=%ERRORLEVEL%
echo === END %DATE% %TIME% rc=%RC% === >> C:\tmp\embed_rebuild.log
if "%RC%"=="0" (
    echo DONE %DATE% %TIME% > C:\tmp\embed_DONE.txt
) else (
    echo FAILED rc=%RC% %DATE% %TIME% > C:\tmp\embed_FAILED.txt
)
