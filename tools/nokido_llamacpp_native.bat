@echo off
REM tools/nokido_llamacpp_native.bat
REM Wrapper NSSM pour llama-server natif Vulkan (build b8772-bafae2765).
REM Hardware cible : AMD Radeon 780M (Vulkan, 20.3 GB UMA, 19.3 GB libre).
REM Modele target : qwen2.5-coder:7b-instruct-q4_K_M (4.7 GB blob Ollama).
REM Modele draft  : qwen2.5-coder:1.5b-Q4_K_M (986 MB) pour speculative decoding.
REM   architecture identique (qwen2 family) = compat 100%, gain 1.5-2x sur code.
REM
REM ISOLATION (2026-05-26) :
REM   - Spawn via tools/forge_llama_worker_isolated.py (Job Object Win32) :
REM       * Process memory cap (default 16 GB).
REM       * KILL_ON_JOB_CLOSE : si le wrapper meurt, llama-server meurt avec.
REM       * Heartbeat sandbox/llama_worker_isolated.heartbeat pour supervisor.
REM       * Pause flag sandbox/llama_rebuild_pause (NtSuspend).
REM   - Auth : --api-key FORGE_LLAMA_KEY obligatoire (sinon arret immediat).
REM   - --webui-mcp-proxy retire : ouvrait CORS vers hub :8766 sans CSRF token.
REM
REM Service NSSM :
REM   nssm install NokidoLlamaNative <full_path_to_this_bat>
REM   nssm set NokidoLlamaNative AppDirectory <project_root>
REM   nssm set NokidoLlamaNative AppThrottle 5000
REM   nssm set NokidoLlamaNative AppEnvironmentExtra FORGE_LLAMA_KEY=<token>
REM
REM Optimisations actives (cf. llama-server --help) :
REM   -ngl 99               full GPU offload (large marge VRAM)
REM   -c 8192               ctx 8K (32K saturait 20GB UMA -> decode lent)
REM   -np 2                 2 slots au lieu de auto(4) -> KV cache /2
REM   -ctk q8_0 -ctv q8_0   KV cache quantise 8-bit (economie ~50% cache VRAM)
REM   -fa auto              Flash Attention auto-detect
REM   --cache-prompt        prompt caching (multi-tour)
REM   --cache-reuse 256     reutilise cache meme avec prefix qui change un peu
REM   --context-shift       shift au lieu de truncate quand ctx plein
REM   --mlock               lock RAM (anti-swap Windows + UMA)
REM   --metrics             expose /metrics Prometheus (monitoring)
REM   --props               permet POST /props pour tweak runtime
REM   --slots               expose /slots monitoring
REM   --jinja               template chat (qwen native)
REM   --reasoning auto      detecte si modele a thinking (qwen3 etc.)
REM   -a qwen,laforge-coder aliases pour clients OpenAI-compat
REM   --prio 1              priorite medium (pas realtime, evite hang systeme)
REM   --threads -1          auto-detect threads CPU
REM   -np -1                slots auto
REM   -md <draft.gguf>                 vraie speculative decoding avec draft model
REM   -ngld 99                         draft full GPU
REM   -cd 32768                        ctx draft = ctx target
REM   --draft-max 16                   tokens draft par iteration
REM   --draft-min 4                    minimum draft (tradeoff acceptance/throughput)
REM   --draft-p-min 0.65               proba minimum acceptation draft (vs default 0.75)
REM   --override-kv general.name=str:..  fixe le nom du modele dans l UI

if "%FORGE_LLAMA_KEY%"=="" (
  echo [FATAL] FORGE_LLAMA_KEY env var not set. Refuse to start un-authenticated llama-server.
  echo         Example : set "FORGE_LLAMA_KEY=$(openssl rand -hex 32)"
  exit /b 2
)

set "LAFORGE_PY=%USERPROFILE%\miniforge3\python.exe"
set "WRAPPER=%USERPROFILE%\Script python IA\Nokido\tools\forge_llama_worker_isolated.py"
set "LLAMA=%USERPROFILE%\llama-vulkan\llama-server.exe"
set "MODEL=D:\ollama\models\blobs\sha256-60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463"
set "DRAFT=D:\ollama\models\blobs\sha256-29d8c98fa6b098e200069bfb88b9508dc3e85586d20cba59f8dda9a808165104"
set "HOST=127.0.0.1"
set "PORT=8091"
set "MEM_GB=16"

"%LAFORGE_PY%" "%WRAPPER%" --mem-gb %MEM_GB% --llama-exe "%LLAMA%" --require-api-key -- ^
  -m "%MODEL%" ^
  -md "%DRAFT%" ^
  --host %HOST% --port %PORT% ^
  --api-key %FORGE_LLAMA_KEY% ^
  -ngl 99 ^
  -ngld 99 ^
  -c 8192 ^
  -cd 8192 ^
  -np 2 ^
  -b 2048 -ub 512 ^
  -ctk q8_0 -ctv q8_0 ^
  -fa auto ^
  --cache-prompt ^
  --cache-reuse 256 ^
  --context-shift ^
  --mlock ^
  --metrics ^
  --props ^
  --slots ^
  --jinja ^
  --reasoning auto ^
  -a "qwen,qwen2.5-coder,laforge-coder" ^
  --prio 1 ^
  --threads -1 ^
  --draft-max 16 ^
  --draft-min 4 ^
  --draft-p-min 0.65 ^
  --webui-config-file "%USERPROFILE%\Script python IA\Nokido\data\llamacpp_webui_config.json" ^
  --path "%USERPROFILE%\Script python IA\Nokido\data\llamacpp_webui_fr" ^
  --override-kv general.name=str:Qwen2.5-Coder-7B-Instruct-Q4_K_M
