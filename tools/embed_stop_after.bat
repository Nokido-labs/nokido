@echo off
REM ============================================================================
REM embed_stop_after.bat — attend ~45 min, stoppe LaForge-EmbedRebuild, eteint.
REM Declenche par la tache planifiee LaForge-EmbedStop (schtasks /run).
REM Le rebuild commit la DB par batch -> arret = reprise propre au checkpoint.
REM ============================================================================
ping -n 2701 127.0.0.1 > nul
schtasks /end /tn LaForge-EmbedRebuild
echo STOPPED %DATE% %TIME% > C:\tmp\embed_STOPPED.txt
shutdown /s /t 60 /c "Nokido - session embedding ~1h terminee - arret auto"
