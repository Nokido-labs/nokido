@echo off
:: Nokido Tray — lance l'icône tray en arrière-plan
:: Mettre ce .bat dans shell:startup pour démarrage automatique
start "" /B %USERPROFILE%\miniforge3\pythonw.exe "%USERPROFILE%\Script python IA\Nokido\tools\nokido_tray.py"
