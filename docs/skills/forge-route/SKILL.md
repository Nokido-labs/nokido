---
name: laforge-route
description: Activer / désactiver le routage des CLI agentiques (Claude Code, Gemini, Cline) vers les modèles Nokido (ex-LaForge) (ingress local/OAuth) ou revenir aux modèles natifs. Déclencher quand l'utilisateur veut "route via LaForge", "passe en local / LaForge", "reviens en natif", "active/désactive le routage CLI", "lf-route on/off", "utilise LaForge pour tous les CLI", "économise mon quota / déporte". Bascule un flag partagé lu par les wrappers au prochain lancement.
---

# LaForge — toggle routage CLI (lf-route)

Bascule si les CLI wrappés (`claude-lf` / `gemini-lf` / `cline-lf`) routent leurs appels LLM
vers les **ingress LaForge** (`:7776`/`:7778`/`:7777` → switchboard local/OAuth, **quota
préservé**) ou vers leurs **modèles natifs**.

## Basculer (sans `!`)

Appelle le hub `run` action=`trusted_script`, path=`tools/forge_cli_route.py` :

| `script_args` | Effet |
|---|---|
| `"on"` | routage LaForge **ON** pour tous les CLI |
| `"on claude"` | ON pour un seul (claude/gemini/cline/copilot) |
| `"off"` | **OFF** → CLI natifs |
| `"status"` | état courant + `hub_up` + mapping ingress |

## Comportement

- Flag = `sandbox/cli_route.json` (source unique), lu par chaque wrapper **au prochain
  lancement** (`claude-lf`…). Ne reroute PAS une session déjà lancée (base_url figé au démarrage).
- **Fallback** : routage ON mais hub `:8766` down → le wrapper retombe en **NATIF** auto (0 casse).
- **copilot** : BYOK via env (`COPILOT_PROVIDER_BASE_URL=:7777/v1` + MODEL_ID claude-sonnet-4.5 +
  WIRE_MODEL + WIRE_API completions), posé par `copilot-lf` quand ON → **0 quota GitHub** (cf `copilot help providers`).

## Pré-requis

Wrappers actifs : `$PROFILE` dot-source `tools/laforge_cli_aliases.ps1`.
