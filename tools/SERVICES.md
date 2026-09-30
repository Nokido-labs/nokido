# Nokido — Inventaire NSSM Services

> Auto-généré 2026-05-02 via `nssm get <svc> {Application,AppParameters,AppDirectory}`.
> Pour mettre à jour : voir `tools/regen_services_md.ps1` (à créer).

## Vue d'ensemble — 17 services

| Service | Status | Type | App | Port |
|---|---|---|---|---|
| **NokidoMCP** | Auto | python | `tools/nokido_hub.py` | 8766 |
| **NokidoWebHub** | Auto | python | `tools/nokido_web_hub.py` | 7400 |
| **NokidoDenoHubMCP** | Auto | bat → deno | `tools/nokido_deno_hub_mcp.bat` | 8769 |
| **NokidoDenoProxy** | Auto | bat → deno | `tools/nokido_deno_proxy.bat` | 8000 |
| **NokidoDenoWebHub** | Auto | bat → deno | `tools/nokido_deno_webhub.bat` | 7401 |
| **NokidoOpenAIProxy** | Auto | python | `tools/forge_openai_proxy.py` | 7777 |
| **NokidoLlamaNative** | **Manual** ⏸ | bat → llama-server | `tools/nokido_llamacpp_native.bat` | 8091 |
| **NokidoLlamaRouter** | Auto | bat → llama-server | `tools/nokido_llamacpp_router.bat` | 8092 |
| **NokidoAutonomousLoops** | Auto | bat | `tools/nokido_autonomous_loops.bat` | — |
| **NokidoGeminiDaemon** | Auto | python (py314) | `tools/gemini_poll_daemon.py --mode active --interval 30` | — |
| **NokidoGraph** | Auto | python (py314) | `app/forge_graph_explorer.py` | — |
| **NokidoHebbian** | Auto | python (py314) | `app/forge_hebbian_linker.py --daemon` | — |
| **NokidoHomeostasis** | Auto | python (3.12) | `app/forge_homeostasis_orchestrator.py --daemon` | — |
| **NokidoRSSWatcher** | Auto | python (py314) | `app/forge_rss_watcher.py --daemon` | — |
| **NokidoOfflineTrainer** | Auto | python (3.12) | `tools/forge_offline_trainer.py --daemon` | — |
| **NokidoMemoryConsolidator** | Auto | python (3.12) | `tools/forge_memory_consolidator.py --daemon` | — |
| **NokidoSelfPatcher** | **Pending install** | python (3.12) | `tools/forge_self_patcher.py --daemon` | — |

## Détail par service

### NokidoMCP — Hub MCP central (cerveau)

- **Application** : `~\miniforge3\python.exe`
- **AppParameters** : `tools\nokido_hub.py`
- **AppDirectory** : `~\Script python IA\Nokido`
- **DisplayName** : NokidoMCP
- **Port** : 8766 (Streamable HTTP MCP, bearer auth)
- **Pourquoi** : agent central. Si down = tout MCP down.
- **Logs** : `logs/mcp_audit.log`

### NokidoWebHub — Dashboard web

- **Application** : `~\miniforge3\python.exe`
- **AppParameters** : `tools\nokido_web_hub.py --host 127.0.0.1 --port 7400`
- **Port** : 7400 (HTTP UI)

### NokidoDenoHubMCP — Hub MCP variant Deno

- **bat** : `tools/nokido_deno_hub_mcp.bat`
- **Port** : 8769
- **Source ref** : `proxy_deno/hub_mcp/main.ts` ligne 4 — *"Phase B.2 - parallèle au Python :8766 — switch quand validé"*.
- **PAS un doublon** : migration progressive Python → Deno délibérée (phase B.2). Le hub Deno délègue l'exécution des tools au Python via subprocess `forge_dispatchers` / `forge_trajectory.dispatch_intent` — Python reste source de vérité. Objectif : isoler la couche transport HTTP/MCP en Deno (sandbox permissions natif). Voir `docs/SERVICES_REMEDIATION.md` #1.

### NokidoDenoProxy — Proxy Deno (système nerveux)

- **bat** : `tools/nokido_deno_proxy.bat`
- **Port** : 8000
- **Rôle** : proxy nervous system pour interconnexion services.

### NokidoDenoWebHub — WebHub variant Deno

- **bat** : `tools/nokido_deno_webhub.bat`
- **Port** : 7401
- **Source ref** : `proxy_deno/web_hub/main.ts` ligne 4 — *"Phase B.1 - parallèle au Python :7400 — switch quand validé"*.
- **PAS un doublon** : staging Deno phase B.1 délibéré. Endpoints portés `/health`, `/api/opsec/*`, `/api/anatomy/state`, `/anatomy`, `/api/events/*` — lecture state.json + SQLite read-only, mutations déléguées à Python. Voir `docs/SERVICES_REMEDIATION.md` #2.

### NokidoOpenAIProxy — Bridge OpenAI-compat pour clients tiers

- **Application** : `~\miniforge3\python.exe`
- **AppParameters** : `tools\forge_openai_proxy.py`
- **AppDirectory** : `~\Script python IA\Nokido`
- **DisplayName** : Nokido OpenAI-compat Proxy :7777
- **Port** : 7777 (127.0.0.1, OpenAI-compat `/v1/models` + `/v1/chat/completions`)
- **Rôle** : wrap le `ask` tool MCP du Hub :8766 pour exposer Nokido comme provider OpenAI-compatible (LobeHub, Cline, autres clients).
- **Logs** : `logs/openai_proxy.{stdout,stderr}.log` (rotate 10 MB).
- **Installer** : `tools/install_openai_proxy_nssm.ps1`.

### NokidoLlamaNative — Inférence locale dédiée

- **bat** : `tools/nokido_llamacpp_native.bat` → `llama-server.exe` Vulkan
- **Modèle** : `qwen2.5-coder:7b-instruct-q4_K_M` (4.7 GB) + draft `qwen2.5-coder:1.5b-Q4_K_M` (986 MB)
- **Port** : 8091 (OpenAI-compat)
- **VRAM/RAM** : ~6.5 GB chargé (model + draft + KV cache q8_0)
- **Status courant** : **Manual** (désactivé 2026-05-02 pour libérer RAM)
- **Réactiver** : `Set-Service NokidoLlamaNative -StartupType Automatic; Start-Service NokidoLlamaNative`

### NokidoLlamaRouter — Router inférence

- **bat** : `tools/nokido_llamacpp_router.bat`
- **Port** : **8092** (OpenAI-compat, multi-modèles autoload, max 2 — `--models-max 2 --models-autoload`)
- **Rôle** : llama-server multi-modèles. Coexiste avec NokidoLlamaNative sur :8091.

### NokidoAutonomousLoops — Boucles évolutives

- **bat** : `tools/nokido_autonomous_loops.bat`
- **Rôle** : Boucle évolutive 7 patterns circadiens (cf. CLAUDE.md commit d418189).
- **Output** : `autonomous_loop_state` table + `autonomous_loop_audit`.

### NokidoGeminiDaemon — Polling daemon Gemini

- **Application** : `~\miniforge3\envs\laforge_py314\python.exe`
- **AppParameters** : `tools\gemini_poll_daemon.py --mode active --interval 30`
- **Rôle** : pull inbox Gemini CLI toutes les 30s, ingest event bus.

### NokidoGraph — Graph explorer

- **Application** : `python (py314)`
- **AppParameters** : `app\forge_graph_explorer.py`

### NokidoHebbian — Hebbian linker

- **Application** : `python (py314)`
- **AppParameters** : `app\forge_hebbian_linker.py --daemon`
- **Rôle** : reinforce skill associations via Hebbian rule (Nokido cognitive loop).

### NokidoHomeostasis — Homeostasis orchestrator

- **Application** : `~/miniforge3/python.exe` (3.12 main, **PAS** py314)
- **AppParameters** : `app/forge_homeostasis_orchestrator.py --daemon`
- **Rôle** : équilibre ressources / mood système (cf. forge_system_mood).
- **Note** : utilise miniforge3 base (3.12), pas l'env py314 comme les autres. Incohérence à clarifier.

### NokidoRSSWatcher — RSS watcher

- **Application** : `python (py314)`
- **AppParameters** : `app\forge_rss_watcher.py --daemon`
- **Rôle** : ingest flux RSS techniques → biblio_raw → RAG.

### NokidoOfflineTrainer — Batch AMI trainer (Hassabis offline replay)

- **Application** : `~\miniforge3\python.exe`
- **AppParameters** : `tools\forge_offline_trainer.py --daemon`
- **AppDirectory** : `~\Script python IA\Nokido`
- **Rôle** : batch SGD toutes les 6h sur `RAG/execution_traces.db` (13k+ transitions). Entraîne 6 modèles : value_net, policy_net, cost_net, world_model NMLP, JEPA, H-JEPA. Guard MIN_NEW_TRACES=50.
- **Heartbeat** : `sandbox/offline_trainer.heartbeat`
- **Logs** : `logs/offline_trainer.{stdout,stderr}.log` (rotate 10 MB)
- **Installer** : `tools/install_offline_trainer_nssm.ps1` **[NEEDS ADMIN]**
- **Rollback** : `nssm stop NokidoOfflineTrainer; nssm remove NokidoOfflineTrainer confirm`
- **One-shot** : `LAFORGE_PYTHON tools/forge_offline_trainer.py --once --min-traces 1`

### NokidoMemoryConsolidator — Hippocampus→cortex (Hassabis sleep)

- **Application** : `~\miniforge3\python.exe`
- **AppParameters** : `tools\forge_memory_consolidator.py --daemon`
- **AppDirectory** : `~\Script python IA\Nokido`
- **Rôle** : toutes les 12h, sélectionne traces `success=1 AND cost_after < 0.3`, group par task_type, synthèse ollama, INSERT rag_chunks source=`experience/consolidated/<task_type>`. MIN_GROUP_SIZE=5.
- **Heartbeat** : `sandbox/memory_consolidator.heartbeat`
- **Logs** : `logs/memory_consolidator.{stdout,stderr}.log` (rotate 10 MB)
- **Installer** : `tools/install_memory_consolidator_nssm.ps1` **[NEEDS ADMIN]**
- **Rollback** : `nssm stop NokidoMemoryConsolidator; nssm remove NokidoMemoryConsolidator confirm`
- **One-shot** : `LAFORGE_PYTHON tools/forge_memory_consolidator.py --once`

### NokidoSelfPatcher — Autonomous self-patching loop

- **Application** : `~\miniforge3\python.exe`
- **AppParameters** : `tools\forge_self_patcher.py --daemon`
- **AppDirectory** : `~\Script python IA\Nokido`
- **Rôle** : Toutes les 1h, lit `sandbox/evolution_proposal_*.md`, applique règles déterministes (cp1252 Unicode, utf-8 stdout) + LLM patch (laforge-qwen) sur patterns inconnus, teste via pytest, commit+push si pass.
- **Heartbeat** : `sandbox/self_patcher.heartbeat`
- **Applied** : `sandbox/patch_applied/*.md` (proposals traitées)
- **Logs** : `logs/self_patcher.{stdout,stderr}.log` (rotate 10 MB)
- **Installer** : `tools/install_self_patcher_nssm.ps1` **[NEEDS ADMIN]**
- **Dry-run** : `LAFORGE_PYTHON tools/forge_self_patcher.py --once --dry-run`
- **Rollback** : `nssm stop NokidoSelfPatcher; nssm remove NokidoSelfPatcher confirm`

## Anomalies / TODO

1. ~~**NokidoDenoHubMCP (8769) vs NokidoMCP (8766)**~~ **RESOLU 2026-05-02** : DenoHub :8769 = phase B.2 migration délibérée, PAS un doublon. Voir entrée détaillée plus haut + `docs/SERVICES_REMEDIATION.md` #1.
2. ~~**NokidoDenoWebHub (7401) vs NokidoWebHub (7400)**~~ **RESOLU 2026-05-02** : DenoWebHub :7401 = phase B.1 staging délibéré, PAS un doublon. Voir entrée détaillée plus haut + `docs/SERVICES_REMEDIATION.md` #2.
3. **NokidoHomeostasis** utilise miniforge3 (3.12) alors que Graph/Hebbian/RSSWatcher/GeminiDaemon utilisent **`laforge_py314`** env. Sanity test py314 import OK 2026-05-02. Migration script prêt : `tools/migrate_homeostasis_py314.ps1` **[NEEDS ADMIN]**.
4. ~~**NokidoLlamaRouter port**~~ **RESOLU 2026-05-02** : port = **8092** (cf. tableau + section détail).
5. **Tous services en LocalSystem** = surprivilege. Migration script prêt : `tools/migrate_services_user.ps1` **[REQUIRES MANUAL PASSWORD INPUT]** — pilote sur NokidoRSSWatcher avant rollout global.

## Commandes utiles (admin)

```powershell
# Status global
Get-Service Name, Nokido* | Format-Table Name, Status, StartType

# Stop / Start individuel
Stop-Service NokidoLlamaNative -Force
Start-Service NokidoLlamaNative

# Désactiver auto-start (passer Manual)
Set-Service NokidoLlamaNative -StartupType Manual

# Reconfig NSSM (admin)
$NSSM = "C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"
& $NSSM set NokidoMCP AppStdout "~\Script python IA\Nokido\logs\mcp.stdout.log"
& $NSSM set NokidoMCP AppStderr "~\Script python IA\Nokido\logs\mcp.stderr.log"

# Migrer execution user LocalSystem → user
& $NSSM set NokidoMCP ObjectName "DESKTOP-XXXX\user" "<password>"
& $NSSM restart NokidoMCP
```

## Cross-ref forge_services_launcher.py

Le module `tools/forge_services_launcher.py` orchestre certains services en **mode standalone** (sans NSSM) :

- `start_brain_worker()` :5557 ZMQ ONNX NPU
- `start_lmstudio()` :1234 (skip si pas installé)
- `start_llamacpp_native()` :8080 (override port — conflit avec :8091 NSSM ?)
- `start_gemini_poll()` (daemon)
- `start_biblio_worker()`

**Possible double-démarrage** si le launcher est run en parallèle des NSSM. Le launcher devrait skip si NSSM service `Running`.

## Logs centralisés

Conseil : configurer NSSM AppStdout/AppStderr pour chaque service vers `LaForge/logs/<service>.log` :

```powershell
foreach ($s in @("NokidoMCP","NokidoWebHub",...)) {
    & $NSSM set $s AppStdout  "~\Script python IA\Nokido\logs\$s.stdout.log"
    & $NSSM set $s AppStderr  "~\Script python IA\Nokido\logs\$s.stderr.log"
    & $NSSM set $s AppRotateFiles 1
    & $NSSM set $s AppRotateBytes 10485760
}
```

→ rotation auto à 10 MB/fichier, debug centralisé.
