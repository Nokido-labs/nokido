@echo off
cd /d "%~dp0"
echo [forge-dispatcher] building...
REM DEUX DRAPEAUX MESURES le 2026-09-18, sans lesquels ce script echoue sous
REM tout compte qui n'est pas proprietaire du depot :
REM  - buildvcs=false : le tamponnage VCS de Go appelle git, qui rend
REM    "dubious ownership" (exit 128). Meme piege que partout ailleurs ici,
REM    atteint par une autre porte.
REM  - GOCACHE : les comptes de service ont HOME=C:\Users\Default, donc
REM    %LocalAppData% n'est pas defini et Go refuse de construire.
if "%GOCACHE%"=="" set "GOCACHE=%~dp0..\..\sandbox\gocache"
go build -buildvcs=false -o forge_dispatcher.exe .
if %errorlevel% neq 0 (
    echo BUILD FAILED
    exit /b 1
)
echo BUILD OK — forge_dispatcher.exe ready
