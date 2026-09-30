@echo off
REM Lance l'icone systray Nokido en arriere-plan (pythonw = pas de fenetre console).
REM A mettre en raccourci dans shell:startup pour un demarrage auto au login (pas de tache planifiee).
start "" "%USERPROFILE%\miniforge3\pythonw.exe" "%USERPROFILE%\Script python IA\Nokido\tools\nokido_tray.py"
