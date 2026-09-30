@echo off
setlocal
REM Nokido — boot searxng natif WSL + portproxy loopback.
REM Lance dockerd + searxng dans la VM Debian, puis (re)cable le portproxy
REM 127.0.0.1 -> IP_WSL pour 8080 (searxng) et 2375 (dockerd). L'IP WSL change
REM a chaque demarrage de la VM : ce script la re-resout et re-pointe le
REM portproxy. Doit tourner ELEVE (netsh portproxy = admin) — tache planifiee
REM Nokido-WSLSearxng au logon, /RL HIGHEST.

wsl -d Debian -u root service docker start
wsl -d Debian docker start searxng-laforge

set WSLIP=
for /f "usebackq tokens=1" %%i in (`wsl -d Debian hostname -I`) do set WSLIP=%%i
if "%WSLIP%"=="" (
  echo [searxng-boot] IP WSL introuvable — VM down ? abandon.
  exit /b 1
)

netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=8080 >nul 2>&1
netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=2375 >nul 2>&1
netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=8080 connectaddress=%WSLIP% connectport=8080
netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=2375 connectaddress=%WSLIP% connectport=2375
echo [searxng-boot] dockerd+searxng up, portproxy 8080/2375 -^> %WSLIP%
endlocal
