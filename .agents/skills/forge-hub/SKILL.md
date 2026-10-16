---
name: forge-hub
description: "À utiliser pour parler au hub Nokido (:8766) depuis n'importe quelle surface : un outil répond « action inconnue » ou une action manque au schéma en cache, notifier un pair, interroger un modèle par `ask`, connaître son identité et son ring, sonder le hub. Donne les actions du schéma, le recours `hub_call.py` et ses limites."
---

# forge-hub — parler au hub Nokido (:8766)

Hub MCP : `http://127.0.0.1:8766/mcp`. Toute action passe par lui : c'est là que les
gardes s'appliquent (videur, firewall, exec_tier) et que l'appel est journalisé.

## Actions de l'outil `hub` (schéma relu le 15/10)

| action | sert à |
|---|---|
| `whoami` | identité, ring, tâches non réclamées par agent (« personne ne draine ») |
| `poll` | messages en attente |
| `notify to=… message=…` | message inter-agents ; `to` = claude, gemini, cline, daemon ou hub ; message au format M2M `{intent, pointer_ref}` |
| `list_providers` | providers LLM du registre |
| `search_recent` | recherche récente |
| `get_mode`, `set_mode` | mode du hub |
| `quota_model quality=… apply=true` | choix de modèle selon la qualité (high, medium, low, ultra) |
| `quota_report flash=… flash_lite=… pro=… preview_pro=…` | déclarer le quota consommé — 4 pools Gemini seulement, voir `forge-quota` |
| `redemarrer_stack message=…` | relancer la pile par le dialogue owner, jamais `nssm` à la main |
| `demander_ordre ordre=…`, `ordre_bureau`, `confirmer_owner` | question à l'owner (élicitation), puis exécution ou dépôt pour le tray |
| `emit_telemetry` | lire son handler avant usage |

Le reste est porté par des outils MCP distincts : `ask`, `run`, `query`, `rag`, `read`,
`task`, `governed_edit`, `blackboard_*`, `introspect`, etc.

## « Action inconnue » ou action absente du schéma

1. **Schéma en cache.** La plupart des CLI chargent le schéma MCP au démarrage : une
   action ajoutée au hub depuis reste invisible. Relancer la session du CLI (ou son
   lanceur) recharge le schéma. Une action invisible n'est pas une action absente.
2. **Action servie mais hors de l'enum** (mesuré le 14/10 : `quota_status`) :
   `tools/hub_call.py quota_status`, avec les limites ci-dessous.

## `tools/hub_call.py` — un recours, avec trois limites

`LAFORGE_PYTHON tools/hub_call.py <action|outil> [clé=valeur …]` envoie un JSON-RPC
direct à `:8766/mcp`. Les noms `ask`, `query`, `rag`, `read`, `write`, `web_search`,
`biblio`, `research_agent`, `run`, `event`, `hub_status` partent comme outils ; tout
autre nom part comme `hub action=<nom>`.

1. **Il signe GEMINI** : le jeton lu est `FORGE_TOKEN_GEMINI`. Un autre agent qui
   l'utilise agit sous l'identité de Gemini et fausse l'attribution. Réservé aux
   surfaces Gemini / AGY ; les autres passent par leurs propres outils MCP.
2. **Jamais depuis l'outil `run` du hub** : `run` s'exécute DANS le hub, et un script
   qui rappelle `:8766` le fait attendre sur lui-même. Le lancer depuis le shell de la
   surface.
3. Côté Claude Code, sonder le hub = Bash + `curl` vers `:8766`, un seul segment.

```
LAFORGE_PYTHON tools/hub_call.py poll
LAFORGE_PYTHON tools/hub_call.py quota_status
LAFORGE_PYTHON tools/hub_call.py ask provider=groq message="ta question"
```

`LAFORGE_PYTHON` = `~/miniforge3/python.exe`, jamais `python` brut.

## Interroger un autre modèle

Outil MCP `ask`, avec `provider=` ou la forme `provider:model`. Les noms acceptés par
`ask` ne sont pas ceux du registre `list_providers` : un nom du registre peut être
inconnu de `ask` (piège payé : `gemini_flash`, 9 tours sur 9 en réponse vide).
`gemini_cli` = `agy.exe` sur l'abonnement owner : il rend un texte, pas un agent.

- choisir un modèle, tourner en local : `forge-models` ;
- budget, 429, pools : `forge-quota` ;
- débat entre modèles : `forge-m2m-debat-mesure` ;
- faire travailler AGY : `forge-m2m-agy`.

## État du système

`hub action=whoami` (services dégradés, tâches en souffrance) ou
`forge_ssot.point('point system_state')`. Pas d'instantané figé : celui qu'indiquait
cette skill datait d'avril.

## Quand le hub ne répond plus

Skill `forge-rescue`. Relance : `hub action=redemarrer_stack`. `LaForge-Master :8765`
est le propriétaire exclusif du hub ; un restart direct crée un conflit de port.
