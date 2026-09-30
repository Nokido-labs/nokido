@echo off
REM Nokido Deno Proxy nervous system :8000 — NSSM wrapper
cd /d "%USERPROFILE%\Script python IA\Nokido\proxy_deno"
set LAFORGE_PERSIST_DIR=%USERPROFILE%\Script python IA\Nokido\nokido_persist
"%USERPROFILE%\.deno\bin\deno.exe" run --allow-net --allow-read --allow-write --allow-env --allow-run --no-check main.ts
