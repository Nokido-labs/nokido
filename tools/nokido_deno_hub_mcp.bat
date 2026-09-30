@echo off
REM Nokido Deno Hub MCP launcher - NSSM wrapper
REM Lance proxy_deno/hub_mcp/main.ts sur :8769 (parallel Python :8766)

cd /d "%USERPROFILE%\Script python IA\Nokido\proxy_deno"
set LAFORGE_DENO_HUB_PORT=8769
set LAFORGE_PERSIST_DIR=%USERPROFILE%\Script python IA\Nokido\nokido_persist
"%USERPROFILE%\.deno\bin\deno.exe" run --allow-net --allow-read --allow-env --no-check hub_mcp/main.ts
