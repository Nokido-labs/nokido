---
name: forge-memory-ssot
description: "À utiliser avant de répondre « où en est X », d'affirmer qu'une chose existe ou non, de rouvrir une enquête, ou pour consigner une décision ou une erreur, depuis toute surface. Donne où vit chaque mémoire (SSoT, RAG, tableau noir, mémoire de l'agent), l'ordre de consultation, comment écrire sans doublon ni perte, et les pièges payés."
---

# forge-memory-ssot — la mémoire de Nokido : où lire, où écrire

Créée le 15/10 : Gemini web (« forge-memory-ssot ») et AGY (« forge-rag ») ont relevé
que le cycle mémoire n'avait pas de skill ; ses morceaux étaient dans forge-capability,
forge-tdd et forge-systematic-debugging, qu'un agent ne charge pas pour lire une mémoire.
Symboles relus dans le code le 15/10.

## Quatre mémoires, quatre usages

| mémoire | porte | lire | écrire |
|---|---|---|---|
| **SSoT** | l'état STRUCTURÉ d'un domaine (roadmap, rules, memory, providers, system_state) | `forge_ssot.point('point <domaine>')`, `consult_ssot(domaine, question)`, `list_domains()` | personne à la main : le mainteneur (tâche LaForge-SSoTMaintainer toutes les 5 min + hook POST_COMMIT) mine le tableau noir |
| **Tableau noir** | faits partagés entre agents, verrous d'édition | `blackboard_read_zone zone_name=…` | `blackboard_propose_fact` (clé explicite = idempotent) |
| **RAG** | historique, leçons, docs ingérées, ancres | outil `rag action=search topic=…`, `rag_fts` (BM25), `RAGEngine.search` | `anchor_solution`, `anchor_error` ; ingestion par forge-veille-* |
| **Mémoire de l'agent** | préférences et leçons d'UNE surface (Claude Code : MEMORY.md et ses fiches) | suivre les `[[liens]]` des fiches du domaine | propre à la surface ; ne remplace ni le SSoT ni le RAG |

L'outil MCP `memory` (actions context, rules, adr, instructions, providers, tasks,
search, status) donne un accès condensé à ces sources. **⚠️ 15/10 : `search`, `context`
et `providers` sont EN PANNE** (constaté par Codex, reproduit) : ils lisent des colonnes
qui n'existent plus (`rag_chunks.content` au lieu de `text`, `provider_scores.provider_id`).
Correctif préparé, en attente de la dérogation owner (fichier critique). D'ici là :
`rag action=search` pour chercher.

**Deux index lexicaux, pas un.** `rag_chunks_fts` est tenu par des triggers sur
`rag_chunks` (depuis le 01/09) et c'est lui que lit la recherche du moteur
(`RAGEngine._scores_lexicaux`). `rag_fts` est une autre table, alimentée à la main
(`anchor_*`), lue par une quarantaine de modules (`introspect`, `hook_recon_first`, le
preflight des leçons, le connecteur des pairs). Un contenu présent dans l'un peut
manquer dans l'autre : vérifier dans celui que lit son lecteur.

**Tableau noir.** Zones : mission, architecture_rules, discovered_facts, active_bugs,
scratch, tree_locks. Droits : mission et architecture_rules au ring 1 ou moins ;
discovered_facts et active_bugs au ring 2 ou moins. La roadmap = faits
`category=roadmap` de architecture_rules, préfixés `CURRENT:`, `NEXT:`, `BLOCKER:`,
`P0:`/`P1:`/`P2:` ; sans ce format, le SSoT sort vide ou tronqué.

## Lire, dans cet ordre

1. `introspect question=…` : symboles réels, enquêtes antérieures, et ce qu'il n'a PAS
   pu consulter. Il peut expirer (15/10 : deux appels coupés à 120 s) : passer alors au 2.
2. `tools/forge_retrieval_sweep.py <terme>` : 8 surfaces, dont les outils par leur NOM.
3. `tools/forge_symptom_index.py --ask <symptôme>` : sessions passées et leurs aveux.
4. Les fiches mémoire du domaine, en suivant les liens.

- « Point sur X » : lire le SSoT, ne jamais le re-dériver de sa mémoire de session.
- Une source muette ne prouve rien : `UNKNOWN` n'est pas `NO`. Dire ce qu'on n'a pas lu.
- Le RAG donne le contexte, pas la cause : la mesure présente l'emporte.

## Écrire

```python
from forge_self_correction import anchor_solution, anchor_error, session_summary, read_lessons
anchor_solution(problem=..., solution=..., example=..., domain="rag")
anchor_error(error_msg=..., context=..., solution=..., domain="systeme")
```

- `anchor_*` : `rag_chunks` (id déterministe), `rag_fts` (cherchable aussitôt) et
  `logs/lessons_learned.md`. Après une décision d'architecture ou une fausse piste.
- `read_lessons(last_n_chars)` en début de session, `session_summary(commits, tests,
  notes)` après un bloc de commits. Côté Claude Code, les hooks SessionStart et Stop le
  font déjà : ne pas doubler. Une surface sans hook les appelle elle-même.
- `preflight_check(action, context, limit)` (ou `_verbose`) : interroger les leçons
  avant une action risquée.
- Tableau noir : un fait = une clé stable + un `pointer_ref` vers la preuve.

## Règles qui protègent la base

- Jamais `SQL LIKE` pour chercher dans le RAG : `rag_fts` ou `RAGEngine.search`.
- Jamais `INSERT INTO rag_chunks` sans `id` explicite.
- `active` dans un WHERE sur `rag_chunks` = scan de 45 Go : écrire `+active`.
- Rien n'est supprimé : marquer `[PERIME]` / `[RESOLU]` (`superseded_by`, `active`,
  `retraction_status`) avec un pointeur vers ce qui remplace.
- Jamais d'écriture directe dans `embeddings.db` depuis un processus client (verrous).
  Écrire par `anchor_*`, par le tableau noir, ou par un `run_job` côté hub qui passe
  par `forge_db_path.write_retry` (la voie de forge-veille-rapide) ; jamais par un
  `sqlite3.connect()` nu, qui garde un verrou implicite et fait perdre les écritures
  des voisins.

## Pièges payés

- **13/10** : un TTL de 14 jours sur le tableau noir effaçait architecture_rules —
  81 faits de roadmap restaurés, correctif `1d2232cbc`.
- **13/10** : le corpus des conversations était figé depuis le 22/08 (indexeur muet) :
  le RAG ne voyait pas les sessions récentes. Son silence ne valait pas absence.
- **14/10** : le connecteur de ChatGPT cherchait des modules de code dans le RAG et
  recevait `[]` — son périmètre n'indexe pas ce code. Pas une preuve d'absence.
- Une purge efface `watch_jobs` et `agent_chain_nodes` : ligne absente ≠ jamais exécuté.
