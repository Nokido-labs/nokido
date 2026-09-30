---
name: laforge-models
description: Choisir / switcher un modèle Nokido (local ou cloud OAuth) au-delà des modèles natifs du CLI. Déclencher quand l'utilisateur veut "changer de modèle", "utiliser un autre modèle", "liste les modèles", "tourne en local", "utilise Claude Max / Gemini / Groq", "switch model", ou router une tâche vers un modèle Nokido précis. Le picker natif du CLI ne liste que ses modèles intégrés ; ce skill expose les modèles Nokido (locaux + cloud OAuth) via le hub MCP et préserve les quotas.
---

# Nokido — choix / switch de modèle (via le hub MCP)

Le picker natif du CLI (`/model`) ne liste que ses modèles intégrés (verrouillés).
Les modèles Nokido — **locaux** + **cloud OAuth** — sont accessibles via le hub MCP
`laforge-sovereign-hub`. Ce skill = la surface de "choix de modèle" pour Nokido.

## Lister les modèles disponibles

Appelle le tool MCP `hub` avec `action=list_providers` (ou `route_task`).
Affiche à l'utilisateur la liste : nom du provider, ring, disponibilité.

## Utiliser / switcher vers un modèle

Pour exécuter une tâche sur un modèle Nokido : tool MCP `ask(provider="<nom>", message="<tâche>")`.

| Provider | Quoi | Quand l'utiliser |
|---|---|---|
| `ollama` | local (qwen2.5-coder, deepseek) | micro-tâches — **préserve le quota natif du CLI** |
| `claude_cli` | Claude OAuth **Max/Ultra** (PAS l'API payante) | raisonnement / code lourd |
| `gemini_cli` | Gemini OAuth | alternatif lourd, quota frais |
| `groq` / `cerebras` | cloud rapide free-tier | itération rapide |
| `auto` | **switchboard Nokido** : déporte la micro-tâche en local, garde le cloud pour le lourd | **défaut recommandé** |

## Règle quota (déport)

Tout ce qui est déportable — relecture, docstring, typecheck, recherche, reformulation —
→ `ask(provider="ollama"|"auto")`. Garde le modèle natif (Haiku/Sonnet) pour l'interactif
court. Ne brûle pas le quota cloud sur du déportable.

> Note : ceci ne change PAS le modèle natif du CLI (impossible sans BYOK endpoint) — ça
> DÉLÈGUE le travail à un modèle Nokido via `ask`, en gardant le CLI comme orchestrateur.
