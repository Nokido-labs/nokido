# forge_gemini_keeper — warm Gemini CLI + endpoint rapide streamé (design, panel 2026-06-09)

## Problème
`provider="gemini_cli"` (Gemini CLI OAuth, modèles gemini-3.1-pro/gemma-4, **quota frais**) est le bon
chemin Gemini souverain — MAIS chaque invocation **cold-start** (Node + OAuth + chargement modèle ≈ 120s)
dépasse le cap 120s du tool hub `ask` → **inutilisable inline** dans les panels multi-LLM. Le CLI est
rapide **une fois warm** ; le cold-start est la taxe. (`provider="gemini"` API = 429 quota épuisé, à éviter.)

## Solution
`forge_gemini_keeper` : daemon supervisé qui tient le CLI **WARM** (cold-start payé 1× au boot) +
expose un endpoint local rapide/streamé `:7901`. Le provider `gemini_cli` du hub route vers `:7901`
(warm/rapide/SSE) au lieu de cold-spawner par appel.

## Stratégie (panel groq-70b / cerebras-120b / mistral-large — convergence)
- **Mécanisme = ACP** (`gemini --experimental-acp`, JSON-RPC stdio) si dispo, **REPL fallback** sinon.
  - **ACP gagne** : frontières de réponse **claires** (JSON-RPC délimité — le REPL exige des heuristiques
    de fin-de-réponse fragiles = "the crux", risque deadlock/corruption), **stream natif** (`session/update`),
    **OAuth tenu** dans la session. REPL = dégradé, dernier recours.
  - **Risque #1 (unanime)** : `--experimental-acp` est *expérimental* → peut changer/disparaître.
    Mitigation = **version-detect** (`gemini --help`/`--version`) + **fallback REPL** + wrapper isolant.

## Architecture
```
supervisor (services.toml, heartbeat/respawn)
  └─ forge_gemini_keeper (PY)
       ├─ subprocess `gemini --experimental-acp`  (ACP)  | OU `gemini` interactif (REPL)
       │     initialize + session/new  1×  (WARM)  → session/prompt par appel → session/update = stream
       ├─ endpoint :7901  POST /ask {prompt} (one-shot)  ·  GET /stream (SSE)  ·  GET /health
       ├─ SERIEL (1 session = lock FIFO ; pool N=2 si parallèle voulu)
       ├─ OAuth-watch : refresh AVANT expiry ; sur 401 -> re-init ; sinon notify ré-auth manuelle
       ├─ warm-ping périodique (~30-60s) anti-timeout Google
       └─ heartbeat sandbox/gemini_keeper.heartbeat + single-instance guard + respawn-on-death

hub provider "gemini_cli" -> si keeper :7901 up -> route there (warm) ; sinon cold-spawn (fallback)
```

## Modes de défaillance + mitigations (panel)
| Mode | Mitigation |
|---|---|
| CLI crash / segfault | supervisor respawn + watchdog ; daemon détecte PID mort -> relance |
| OAuth expiré | watch `expires_at`, pré-refresh ; sur 401 -> re-init ; échec -> notify ré-auth |
| Session gelée (timeout Google/réseau) | timeout strict (10s) -> respawn subprocess |
| Backpressure / saturation | file FIFO bornée (max 10) -> 429 si dépassé |
| ACP absent/instable | version-detect -> fallback REPL |

## PoC (preuve "warm → fast")
- `forge_gemini_keeper.py` : détecte ACP, tient le subprocess warm (init 1×), `/ask` → SSE.
- Test live : 1er appel ≈ cold (~120s, le warm du boot), 2e appel **< 2s** (même session). 100% local/souverain.
- Selftest **structurel** (le binaire gemini n'est pas joignable depuis le sandbox hub) : valide le framing
  JSON-RPC (`_build_prompt_rpc`) + l'assemblage des chunks (`_assemble_updates`) + la détection de mode —
  fonctions PURES, sans subprocess. La preuve warm→fast live tourne dans le runtime hub (où gemini existe).

## Phasage
- **P1 (PoC)** : keeper ACP+REPL + `/ask`+`/health` + selftest structurel. Manuel : `--ask` one-shot.
- **P2** : SSE `/stream` + warm-ping + OAuth-watch + single-instance/heartbeat + service services.toml.
- **P3** : route hub `gemini_cli` -> :7901 (si up) ; pool N=2 ; métriques (latence cold vs warm).

## ⚠ Finding empirique 2026-06-09 — gemini.cmd = SYSTEM-only-exécutable
Le BIN `C:\WINDOWS\system32\config\systemprofile\...\gemini.cmd` est exécutable **UNIQUEMENT par le process
hub SYSTEM** (son provider `gemini_cli` in-process, cf forge_agent_proxy). **TOUS mes contextes échouent
`WinError 5 Accès refusé`** : `run action=python/shell` (sandbox), `trusted_script` (LaForgeTrusted),
`run_job` (détaché), sandbox=windows — `bin_exists=true` mais exécution refusée.
→ **Le keeper DOIT être un SERVICE supervisé** (LaForge-Master spawn en SYSTEM) pour exécuter gemini.
L'ACP-gate (`--experimental-acp` supporté ?) ne peut être tranché QUE là. Une fois wiré, le keeper
**s'auto-probe au boot** : son heartbeat `mode` = `acp` (→ warm OK, le gain) ou `repl` (→ cold one-shot =
status-quo, PAS de warm-gain → pivot nécessaire). **NEXT = wirer `NokidoGeminiKeeper` (services.toml) +
lire `sandbox/gemini_keeper.heartbeat` champ `mode`.** C'est le seul moyen de savoir si le warm est viable.

## Souveraineté / éco
Tout local (le CLI parle à Google via SA propre session OAuth ; le keeper ne fait que tenir+relayer).
Réutilise : pattern keeper (`forge_llama_keeper`/`docker_keeper`) · SSE (`forge_swarm_bus`) · ACP
(`forge_acp_adapter`, ici côté CLIENT vers Gemini = dual) · `gemini_poll_daemon` (déjà un loop Gemini CLI).
