@echo off
:: Run as Administrator
set SVC=NokidoGoDispatcher
set DIR=%~dp0
set EXE=%DIR%forge_dispatcher.exe

nssm install %SVC% "%EXE%"
nssm set %SVC% AppDirectory "%DIR%"
nssm set %SVC% Description "Nokido Go concurrent silo dispatcher — goroutines, no GIL, :8779"
nssm set %SVC% Start SERVICE_AUTO_START
nssm set %SVC% AppStdout "%DIR%logs\stdout.log"
nssm set %SVC% AppStderr "%DIR%logs\stderr.log"
nssm set %SVC% AppRotateFiles 1
nssm set %SVC% AppRotateBytes 10485760

mkdir "%DIR%logs" 2>nul
nssm start %SVC%
echo [NokidoGoDispatcher] installed and started on :8779
