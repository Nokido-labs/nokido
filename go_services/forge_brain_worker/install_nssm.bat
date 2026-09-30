@echo off
:: Run as Administrator
set SVC=NokidoBrainWorkerRust
set DIR=%~dp0
set EXE=%DIR%target\release\forge_brain_worker.exe
set LAFORGE_ROOT=%USERPROFILE%\Script python IA\Nokido

nssm install %SVC% "%EXE%"
nssm set %SVC% AppDirectory "%DIR%"
nssm set %SVC% AppEnvironmentExtra LAFORGE_ROOT=%LAFORGE_ROOT% RUST_LOG=info
nssm set %SVC% Description "Nokido brain_worker Rust — ZMQ REP :5557 BGE-M3 ONNX DirectML"
nssm set %SVC% Start SERVICE_AUTO_START
nssm set %SVC% AppStdout "%DIR%logs\stdout.log"
nssm set %SVC% AppStderr "%DIR%logs\stderr.log"
nssm set %SVC% AppRotateFiles 1
nssm set %SVC% AppRotateBytes 10485760

mkdir "%DIR%logs" 2>nul
nssm start %SVC%
echo [NokidoBrainWorkerRust] installed on :5557
