---
name: forge-models
description: Choisir / switcher un modèle Nokido (local ou cloud OAuth) au-delà des modèles natifs du CLI. Déclencher quand l'utilisateur veut "changer de modèle", "utiliser un autre modèle", "liste les modèles", "tourne en local", "utilise Claude Max / Gemini / Groq", "switch model", ou router une tâche vers un modèle Nokido précis. Le picker natif du CLI ne liste que ses modèles intégrés ; ce skill expose les modèles Nokido (locaux + cloud OAuth) via le hub MCP et préserve les quotas.
targets: [claude, gemini, copilot]
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


## [fusionné depuis laforge-quota]

> **[archivé 2026-08-11]** Frontmatter d'origine, neutralisé. Le dossier
> `forge-quota` a été supprimé, son contenu vit ici.
>
>     name: laforge-quota
description: Gestion quota Gemini CLI. Pools séparés Flash/Pro/Preview. Sélection auto modèle. Reporter quota réel au hub.
---

# Nokido Quota — Gestion Modèles Gemini

## Règle fondamentale au boot

```python
# TOUJOURS en premier à chaque session
import subprocess
subprocess.run(['python', 'tools/hub_call.py', 'quota_model', 'quality=medium', 'apply=true'],
    cwd=r'~\Script python IA\LaForge')
```

## Reporter le quota réel (après /model dans CLI)

```python
import subprocess
subprocess.run(['python', 'tools/hub_call.py', 'quota_report',
    'flash=100', 'flash_lite=23', 'pro=0', 'preview_pro=0'],
    cwd=r'~\Script python IA\LaForge')
```

## Niveaux de qualité

| Niveau | Modèle prioritaire | Quand |
|--------|-------------------|-------|
| ultra/high | gemini-3.1-pro-preview | Raisonnement complexe |
| medium | gemini-2.5-flash-lite | Usage général |
| low | gemini-2.5-flash-lite | Poll, routing léger |
| local | groq / llamacpp | Fallback hors quota Google |

## Si erreur 429

```python
subprocess.run(['python', 'tools/hub_call.py', 'quota_model', 'quality=low', 'apply=true'],
    cwd=r'~\Script python IA\LaForge')
```

## Pools quota (indépendants)

- Flash 2.5 + Flash-Lite = **même pool** (reset 12h)
- Pro 2.5 = pool séparé (reset 24h)
- Pro 3.1 preview = **pool totalement séparé** (reset 24h)
- 0% utilisé dans /model = vraiment disponible

