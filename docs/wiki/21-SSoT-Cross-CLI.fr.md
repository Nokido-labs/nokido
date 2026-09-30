---
type: guide
title: 21 — SSoT Cross-CLI
status: draft
resource: repo://docs/wiki/21-SSoT-Cross-CLI.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 21 — SSoT Cross-CLI

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](21-SSoT-Cross-CLI.md) · **Français**

> Statut : LIVE (alpha). Moteur générique, 5 domaines, triggers auto.

La couche **SSoT (Single Source of Truth)** fait que « point sur X » rend la **même
réponse structurée** dans chaque CLI (Claude Code, Gemini, local), au lieu que chaque
agent re-dérive depuis sa mémoire de session volatile.

## Problème

Taper « point sur la roadmap » dans des CLI différents rendait des réponses
**différentes** : chaque agent reconstruisait depuis un sous-ensemble de sources
éparpillées. Pas d'artefact canonique.

**Fix** : forcer la lecture d'un **SSoT structuré** + contraindre la sortie à un
**schéma** → la « personnalité » du moteur d'inférence est écrasée → réponse uniforme.

## Architecture (3 couches)

| Couche | Module | Rôle |
|---|---|---|
| **Moteur** | `app/forge_ssot.py` | `consult_ssot(domain)` (structuré déterministe 0-LLM, sinon fallback markdown keeper + schéma) · `enforce_schema` · `answer_uniform` · `point(query)`/`detect_domain` · registre `DOMAINS` |
| **Maintainer** | `app/forge_ssot_maintainer.py` | `build_doc` par domaine (déterministe) → écrit `docs/<domain>_state.json` en contexte TRUSTED · `refresh_all` |
| **Routing** | `forge_knowledge_concierge.plan` (Kind.KEEPER → source `ssot`) + `forge_mcp_registry.handle_route_task` STEP 0 | « point sur X » court-circuite vers le SSoT |

### Domaines (5)

| Domaine | Source | Fichier |
|---|---|---|
| `roadmap` | synth + state capté | `docs/roadmap_state.json` |
| `rules` | blackboard `architecture_rules` | `docs/rules_state.json` |
| `memory` | `logs/lessons_learned.md` | `docs/memory_state.json` |
| `providers` | `forge_endpoint_registry.build_inventory` | `docs/providers_state.json` |
| `system_state` | `_capture_state` (ports/services live) | `docs/system_state.json` |

### Triggers (fraîcheur auto)

- **POST_COMMIT** (`.githooks/post-commit`) : `refresh_all` en background à chaque commit.
- **schtask `LaForge-SSoTMaintainer`** (`tools/schtasks/`) : refresh toutes les 5 min.

### Ajouter un domaine

1. `forge_ssot.DOMAINS` += entrée (`file`/`keeper`/`schema`) + un `*_SCHEMA` + synonymes.
2. `forge_ssot_maintainer` : un `_<domain>_build_doc()` + entrée `MAINTAINERS`.

## Usage

```
route_task task_type=chat payload={"prompt": "point sur les règles"}
-> {"status": "ssot", "domain": "rules", "kind": "structured", "answer": {...}}
```

Côté code : `forge_ssot.point(query)` ou lecture directe de `docs/<domain>_state.json`.

---

## Annexe — Anti-pattern « wedge » (corrigé)

Bug systémique trouvé par audit souverain : un handler async qui wrappe une **coroutine
déjà async** dans `run_in_executor(None, lambda: asyncio.run(coro))`.

```python
# AVANT (gèle tout le hub : nouvelle event-loop/appel + ThreadPool défaut épuisé + pas de timeout)
res = await get_event_loop().run_in_executor(None, lambda: asyncio.run(route(...)))
# APRÈS (route() est déjà une coroutine bornée -> await direct + timeout externe < cap hub)
res = await asyncio.wait_for(route(...), timeout=100)
```

**Règle** : coroutine async → `await` direct (jamais `asyncio.run`-in-thread). Travail
SYNC lourd → executor **dédié borné** (pas `None`) + `get_running_loop()`.

---

## Annexe — Provider GLM-5.2 (Zhipu z.ai)

`forge_agent_proxy.ZaiGLM52` (OpenAI-compat, base `https://api.z.ai/api/paas/v4`).
Clé = vault `ZAI_API_KEY`. Auto-fédéré au registre (`api:zai_glm5_2`).

- `glm-5.2` (flagship) = **payant**.
- **Free tier** = modèles Flash, ex `glm-4.5-flash` (≤ 8k/requête). Modèle « thinking »
  → passer `"thinking": {"type": "disabled"}` sinon tout le budget part en reasoning.
- Endpoint **Anthropic** natif (`/api/anthropic`, model `glm-5.2[1m]`) pour Claude Code CLI direct.
