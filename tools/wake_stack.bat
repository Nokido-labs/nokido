@echo off
REM ============================================================================
REM wake_stack.bat - reveil Nokido A LA DEMANDE (rien ne tourne au boot).
REM   1) monte le volume chiffre (forge_at_rest_veracrypt.py --mount) -> verifie V:
REM   2) demarre le superviseur LaForge-Master (amene le hub :8766 + enfants)
REM   3) [option /lm] demarre le pool LM Studio (:1234)
REM Lancer EN ADMIN (clic droit > Executer en tant qu'administrateur) :
REM   demarrer un service Manual exige l'elevation, VeraCrypt aussi pour attacher V:.
REM
REM 2026-07-10 : l'etape 1 faisait `VeraCrypt.exe /q background /a favorites`, mais
REM AUCUN fichier de favoris n'existe sur cette machine (ni AppData\Roaming, ni
REM ProgramData) -> montage NO-OP SILENCIEUX, puis le superviseur demarrait sur un
REM V: absent : jonction LaForge\RAG pendue -> gate 'switches' fail-closed ->
REM le hub bind :8766 mais TOUT appel renvoie GATE_DENIED. On passe donc par le
REM monteur souverain (conteneur C:\LaForge_data + keyfile au vault DPAPI, zero
REM passphrase) et on ECHOUE FORT si V: n'est pas la.
REM ============================================================================
setlocal
set PY="%USERPROFILE%\miniforge3\python.exe"
set VCMOUNT="%~dp0forge_at_rest_veracrypt.py"

echo.
echo [wake 1/3] Montage du volume chiffre (conteneur + keyfile vault)...
if not exist %PY% (
    echo   ERREUR: python miniforge introuvable: %PY%
    pause
    exit /b 1
)
%PY% %VCMOUNT% --mount
if errorlevel 1 (
    echo   ERREUR: montage echoue. Relancer wake_stack.bat EN ADMIN.
    pause
    exit /b 1
)
if not exist %NOKIDO_DATA%\embeddings.db (
    echo   ERREUR: V: monte mais embeddings.db ABSENT -^> mauvais volume. Abandon.
    echo   ^(ne PAS monter LaForge\rag_secure.hc : conteneur d'origine, RAG fige au 01/06^)
    pause
    exit /b 1
)
echo   -^> V: monte, embeddings.db present.

echo.
echo [wake 2/3] Demarrage superviseur LaForge-Master (hub :8766)...
net start LaForge-Master 2>nul || sc start LaForge-Master
echo   -> Hub: http://127.0.0.1:8766/health

if /I "%~1"=="/lm" (
    echo.
    echo [wake 3/3] Demarrage pool LM Studio :1234 ...
    where lms >nul 2>nul && (lms server start) || echo   'lms' introuvable au PATH - lancer LM Studio a la main
) else (
    echo.
    echo [wake 3/3] LM Studio NON demarre ^(ajouter /lm pour le pool local^).
)

echo.
echo [wake] Termine.
endlocal
pause
