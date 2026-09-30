@echo off
REM Nokido Deno WebHub launcher — NSSM wrapper
REM Lance proxy_deno/web_hub/main.ts sur :7401

cd /d "%USERPROFILE%\Script python IA\Nokido\proxy_deno"
set LAFORGE_DENO_WEBHUB_PORT=7401
set LAFORGE_PERSIST_DIR=%USERPROFILE%\Script python IA\Nokido\nokido_persist
set LAFORGE_PYTHON=%USERPROFILE%\miniforge3\python.exe
"%USERPROFILE%\.deno\bin\deno.exe" run --allow-net --allow-read --allow-write --allow-env --allow-run --no-check web_hub/main.ts
