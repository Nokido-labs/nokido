@echo off
REM tools/nokido_llamacpp_router.bat
REM Wrapper NSSM pour llama-server en MODE ROUTER (multi-modeles).
REM L UI affiche un selecteur Loaded/Available, charge a la demande, LRU unload.
REM
REM ATTENTION : llama-server affiche "router mode is experimental, not
REM recommended in untrusted environments". L isolation Job Object +
REM --api-key obligatoire reduit la surface, mais ne lance ce service
REM QUE sur loopback 127.0.0.1 et derriere une auth applicative.
REM
REM PRE-REQUIS : creer data\llm_models\ avec symlinks GGUF (mklink, admin).
REM   mklink "data\llm_models\qwen2.5-coder-7b-q4_K_M.gguf"  "%USERPROFILE%\.ollama\models\blobs\sha256-60e05f..."
REM   mklink "data\llm_models\qwen2.5-coder-1.5b-q4_K_M.gguf" "%USERPROFILE%\.ollama\models\blobs\sha256-29d8c9..."
REM   mklink "data\llm_models\deepseek-coder-6.7b-q4_0.gguf" "%USERPROFILE%\.ollama\models\blobs\sha256-..."
REM   mklink "data\llm_models\qwen3-8b-q4_K_M.gguf"          "%USERPROFILE%\.ollama\models\blobs\sha256-..."
REM
REM ISOLATION (2026-05-26) :
REM   - Spawn via tools/forge_llama_worker_isolated.py (Job Object Win32).
REM     Process memory cap (default 24 GB en router mode car --models-max 2
REM     peut charger 2 GGUF simultanes), KILL_ON_JOB_CLOSE, heartbeat.
REM   - --api-key FORGE_LLAMA_KEY obligatoire.
REM   - --webui-mcp-proxy retire (CORS hub :8766 sans CSRF token = surface attaque).

if "%FORGE_LLAMA_KEY%"=="" (
  echo [FATAL] FORGE_LLAMA_KEY env var not set. Refuse to start un-authenticated llama-server router.
  echo         Example : set "FORGE_LLAMA_KEY=$(openssl rand -hex 32)"
  exit /b 2
)

set "LAFORGE_PY=%USERPROFILE%\miniforge3\python.exe"
set "WRAPPER=%USERPROFILE%\Script python IA\Nokido\tools\forge_llama_worker_isolated.py"
set "LLAMA=%USERPROFILE%\llama-vulkan\llama-server.exe"
set "MODELS_DIR=%USERPROFILE%\Script python IA\Nokido\data\llm_models"
set "WEBUI_CFG=%USERPROFILE%\Script python IA\Nokido\data\llamacpp_webui_config.json"
set "HOST=127.0.0.1"
set "PORT=8092"
set "MEM_GB=24"

"%LAFORGE_PY%" "%WRAPPER%" --mem-gb %MEM_GB% --llama-exe "%LLAMA%" --require-api-key -- ^
  --models-dir "%MODELS_DIR%" ^
  --models-max 2 ^
  --models-autoload ^
  --host %HOST% --port %PORT% ^
  --api-key %FORGE_LLAMA_KEY% ^
  -ngl 99 ^
  -c 32768 ^
  -ctk q8_0 -ctv q8_0 ^
  -fa auto ^
  --cache-prompt ^
  --cache-reuse 256 ^
  --context-shift ^
  --mlock ^
  --metrics ^
  --slots ^
  --jinja ^
  --reasoning auto ^
  --prio 1 ^
  --threads -1 ^
  -np -1 ^
  --webui-config-file "%WEBUI_CFG%"
