@echo off
nssm install LaForge-Master "deno" run -A proxy_deno/core/supervisor.ts
nssm set LaForge-Master AppDirectory "%NOKIDO_ROOT%"
nssm start LaForge-Master
