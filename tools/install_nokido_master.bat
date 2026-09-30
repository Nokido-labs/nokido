@echo off
REM install_nokido_master.bat
REM Installe LaForge-Master (superviseur Deno) et desactive les 17 services NSSM individuels.
REM REQUIS : droits administrateur
REM Usage  : ! tools\install_nokido_master.bat  (depuis terminal admin)

setlocal

set "ROOT=%USERPROFILE%\Script python IA\Nokido"
set "DENO=%USERPROFILE%\.deno\bin\deno.exe"
set "SUPERVISOR=%ROOT%\proxy_deno\core\supervisor.ts"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║  LaForge-Master install                      ║
echo ╚══════════════════════════════════════════════╝
echo.

REM ── 1. Verifier droits admin ──────────────────────────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Relancer en tant qu administrateur.
    pause & exit /b 1
)

REM ── 2. Installer / mettre a jour LaForge-Master ──────────────────────────
echo [1/4] Installation service LaForge-Master...
nssm install LaForge-Master "%DENO%" 2>nul
nssm set LaForge-Master AppParameters run --allow-net --allow-read --allow-write --allow-env --allow-run --allow-sys -A "%SUPERVISOR%"
nssm set LaForge-Master AppDirectory "%ROOT%"
nssm set LaForge-Master AppEnvironmentExtra PYTHONIOENCODING=utf-8
nssm set LaForge-Master DisplayName "Nokido Master Supervisor"
nssm set LaForge-Master Description "Superviseur Deno unique — remplace 17 services NSSM individuels"
nssm set LaForge-Master Start SERVICE_AUTO_START
nssm set LaForge-Master AppStdout "%ROOT%\logs\supervisor\laforge-master.log"
nssm set LaForge-Master AppStderr "%ROOT%\logs\supervisor\laforge-master-err.log"
nssm set LaForge-Master AppStdoutCreationDisposition 4
nssm set LaForge-Master AppStderrCreationDisposition 4
nssm set LaForge-Master AppRotateFiles 1
nssm set LaForge-Master AppRotateBytes 5242880
echo    OK

REM ── 3. Desactiver les 17 services individuels (garder installes pour rollback) ──
echo [2/4] Desactivation services individuels...
for %%S in (
    NokidoAutonomousLoops
    NokidoDenoHubMCP
    NokidoDenoProxy
    NokidoDenoWebHub
    NokidoGeminiDaemon
    NokidoGraph
    NokidoHebbian
    NokidoHomeostasis
    NokidoLlamaNative
    NokidoLlamaRouter
    NokidoMCP
    NokidoNetcfgMCP
    NokidoOllama
    NokidoOpenAIProxy
    NokidoRSSWatcher
    NokidoWebHub
    NokidoCapture
) do (
    nssm stop %%S 2>nul
    nssm set %%S Start SERVICE_DISABLED 2>nul
    echo    disabled: %%S
)
echo    OK

REM ── 4. Creer dossier logs si absent ──────────────────────────────────────
echo [3/4] Preparation dossiers logs...
if not exist "%ROOT%\logs\supervisor" mkdir "%ROOT%\logs\supervisor"
echo    OK

REM ── 5. Demarrer LaForge-Master ───────────────────────────────────────────
echo [4/4] Demarrage LaForge-Master...
nssm start LaForge-Master
timeout /t 3 /nobreak >nul
nssm status LaForge-Master
echo.
echo Control API : http://127.0.0.1:8765/supervisor/status
echo Logs        : %ROOT%\logs\supervisor\
echo.
echo ✓ Installation terminee. Verifier le statut dans 30s.
pause
