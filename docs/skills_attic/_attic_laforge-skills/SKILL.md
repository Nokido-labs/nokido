---
name: laforge-skills
description: "Catalogue et passerelle vers les skills de l'écosystème Nokido, exposées via le hub HTTP:8766. Déclenchement par intention : utiliser dès que la demande utilisateur évoque une capacité Nokido (recon, exploit, RAG, RBAC, NPU, netcfg, CTF, membrane souveraine, firewall sémantique, rôles PLANNER/ EXECUTOR/REVIEWER/ROUTER/SUMMARIZER/SENTINEL/MONITOR, task queue, mailbox, rescue, trust score), demande \"quelle skill pour…\", \"qu'est-ce que Nokido sait faire\", \"lance une skill\", \"installe une skill\", ou cite un slug ClawHub. Le skill délègue search / install / run / list / info / remove / status à `@skill` côté Nokido sans dupliquer la logique."
---

# laforge-skills — Passerelle skills via le Hub Nokido

## Rôle

Ce skill est une **interface fine** côté Claude Code vers le sous-système
skills de Nokido. Il NE contient AUCUNE logique métier : tout est délégué
au hub `tools/nokido_hub.py` (port 8766) et au handler `@skill` côté
Nokido (`app/forge_handler_skill.py`, `app/forge_clawhub_bridge.py`,
`app/forge_clawhub_autoinstall.py`, `app/forge_skill_rag_bridge.py`).

Objectif : permettre à Claude de **découvrir** les capacités Nokido à la
demande, de proposer la bonne skill selon l'intention, et de l'invoquer
sans dupliquer le catalogue dans le contexte.

## Quand se déclencher (intent triggers)

Activer ce skill dès qu'une de ces situations se présente :

- L'utilisateur demande **ce que Nokido sait faire** ("liste les skills",
  "quelles capacités", "qu'est-ce qui est dispo", "carte des organes").
- L'utilisateur cherche **une skill par domaine** ("une skill pour le
  recon réseau", "trouve-moi un solver CTF", "skill RAG", "skill NPU
  embedder", "outil pour netcfg").
- L'utilisateur **nomme un slug ClawHub** ou un module `forge_*.py` et
  veut l'exécuter ou l'inspecter.
- L'utilisateur veut **installer / désinstaller / mettre à jour** une
  skill du marketplace ClawHub.
- L'utilisateur demande l'**état** du bridge skills, la liste des skills
  installées, ou le résultat d'un Guardian review.
- L'utilisateur évoque un **rôle Nokido** (PLANNER / EXECUTOR / REVIEWER
  / ROUTER / SUMMARIZER / SENTINEL / MONITOR) et veut le router vers une
  skill spécifique.

NE PAS déclencher pour les tâches purement code (édition de fichiers
Nokido, refactor, etc.) — utiliser le skill `nokido` ou `laforge-ops`
à la place.

## Toolset minimal

Outils de base suffisants — pas de dépendance exotique :

- `Bash` ou `PowerShell` pour `curl` HTTP vers le hub.
- `WebFetch` pour requêtes GET enrichies sur le hub.
- `Read` pour inspecter un module skill installé localement.

Le hub fait tout le reste (review Guardian, sandbox d'exécution, RAG
bridge, persistence). Ne JAMAIS réimplémenter ces fonctions ici.

## Endpoints du hub utilisés

Hub : `http://127.0.0.1:8766`

| Endpoint               | Méthode | Usage                                       |
| ---------------------- | ------- | ------------------------------------------- |
| `/health`              | GET     | Vérifier que le hub est UP avant tout.      |
| `/mcp`                 | POST    | JSON-RPC vers les 13 tools MCP (skill_*).   |
| `/api/mcp/servers`     | GET     | Liste serveurs MCP + skills enregistrées.   |
| `/api/mcp/toggle`      | POST    | Activer / désactiver une skill.             |
| `/api/mcp/flags`       | POST    | Modifier flags d'une skill.                 |

Le bridge handler `@skill` n'est pas exposé en HTTP direct — il passe
par `/mcp` JSON-RPC avec les tools `skill_search`, `skill_install`,
`skill_run`, `skill_list`, `skill_info`, `skill_remove`, `skill_status`
(noms exacts à vérifier via `tools/list` au premier appel — le hub est
la source de vérité, pas ce document).

## Workflow standard

### Étape 0 : Vérifier que le hub est vivant

```bash
curl -s -m 2 http://127.0.0.1:8766/health
```

Si le hub est down : informer l'utilisateur et proposer de le démarrer
via `python tools/nokido_hub.py` (cf. skill `laforge-ops`). NE PAS
tenter de fallback local — toute la logique skills est côté hub.

### Étape 1 : Découvrir les tools disponibles

Lister les tools MCP exposés par le hub pour récupérer les noms exacts
des fonctions skill_* :

```bash
curl -s -X POST http://127.0.0.1:8766/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Filtrer la réponse sur les tools dont le nom contient `skill`.

### Étape 2 : Mapper l'intention utilisateur vers un tool

| Intention utilisateur                          | Tool à appeler          |
| ---------------------------------------------- | ----------------------- |
| "qu'est-ce que Nokido sait faire / liste"     | `skill_list`            |
| "trouve une skill pour X"                      | `skill_search` (q=X)    |
| "détails sur la skill X"                       | `skill_info` (slug=X)   |
| "installe la skill X"                          | `skill_install`         |
| "lance / exécute la skill X avec ce contexte"  | `skill_run`             |
| "désinstalle X"                                | `skill_remove`          |
| "état du bridge skills"                        | `skill_status`          |

Si plusieurs résultats remontent, **présenter les 3-5 meilleurs** avec
un résumé (slug, description, ring de sécurité requis, dernière review
Guardian) et laisser l'utilisateur choisir. Ne pas exécuter sans
confirmation.

### Étape 3 : Invoquer le tool via JSON-RPC

```bash
curl -s -X POST http://127.0.0.1:8766/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"skill_search","arguments":{"query":"recon"}}}'
```

Pour `skill_run`, toujours :
1. Confirmer l'intention avec l'utilisateur (action non triviale).
2. Vérifier le ring de sécurité requis avec `skill_info`.
3. Passer le contexte minimal (pas de PII brute — le firewall sémantique
   du hub redirige déjà via `forge_semantic_firewall.pre_flight`, mais
   éviter d'envoyer des données sensibles sans nécessité).

### Étape 4 : Retour et persistance

Résumer le résultat à l'utilisateur. Si la skill a produit un artefact
(fichier, output technique), le persister via le hub
(`/api/ingest` ou `skill_run` retourne déjà un payload structuré).

## Anti-patterns (à NE PAS faire)

1. **Ne pas dupliquer le catalogue dans ce skill.** Le hub est la source
   de vérité. Toute liste codée en dur ici dérivera dans la semaine.
2. **Ne pas réimplémenter SkillGuardian / sandbox.** Tout passe par
   `forge_clawhub_bridge.review_and_install()`.
3. **Ne pas court-circuiter le firewall sémantique.** Si l'utilisateur
   demande à passer du contenu sensible à une skill cloud, le hub
   redirige automatiquement vers une skill locale ou bloque.
4. **Ne pas appeler directement les modules `app/forge_*.py` en Python**
   depuis Claude Code — utiliser HTTP:8766. La cohérence trust score /
   mailbox / task queue dépend du passage par le hub.
5. **Ne pas créer de skill côté Nokido depuis ce skill.** Pour publier
   une nouvelle skill, suivre le workflow ClawHub (skill marketplace),
   pas un fichier local.

## Liens utiles

- Hub : `tools/nokido_hub.py` (Starlette :8766)
- Bridge skills : `app/forge_clawhub_bridge.py`
- Auto-install : `app/forge_clawhub_autoinstall.py`
- Handler TUI `@skill` : `app/forge_handler_skill.py`
- Bridge RAG skills : `app/forge_skill_rag_bridge.py`
- Skill jumeau côté Claude pour le hub global : `nokido`
- Skill ops (démarrage / monitoring du hub) : `laforge-ops`
