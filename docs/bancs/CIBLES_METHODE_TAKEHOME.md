# Cibles Nokido — méthode take-home et chantier bas niveau

Date : 2026-10-29. Périmètre : lecture seule du dépôt. Aucune mesure de latence, de RAM ou de débit n'a été
rejouée pour ce document ; les chiffres cités sont des mesures historiques, explicitement datées dans leur source.
Aucun accès à `%NOKIDO_DATA%\embeddings.db`, aucun service vivant, aucun `git add` ni `git commit` par l'agent.

## Méthode appliquée

Le banc générique reprend la méthode du take-home : juge déterministe gelé, référence mesurée et chaînée, candidat
exécuté dans une copie isolée, règle « exact ET strictement meilleur que le meilleur prouvé », promotion par l'owner,
jamais de commit par la boucle (`tools/forge_banc_amelioration.py:1-18`). Le pilote existant est `juge_ancrage_swarm`
(`config/bancs_amelioration.json:2-23`), avec un juge F1 hors du périmètre modifiable
(`tools/bancs/banc_juge_ancrage.py:1-10`).

Une cible n'est retenue que si son juge peut être **déterministe** : même entrée, même sortie, sans LLM, sans réseau,
sans base vivante. Une cible dont la sortie dépend d'un modèle ou d'un service est classée `ILLISIBLE`, jamais
« inutile ».

Précédent déjà en place : les bancs du census (`tests/nr/test_census_bancs_nr.py`), qui n'exécutent aucun modèle réel
mais jugent par des tests cachés hors ligne, une réponse exacte ou une égalité JSON. Leurs solutions de référence
prouvent que le juge est correct avant d'accuser un modèle (`tests/nr/test_census_bancs_nr.py:25`, `REFERENCES`) et
leur rapport est nommé dans la docstring (`tests/nr/test_census_bancs_nr.py:1-7`,
`sandbox/workspace/rapport_bancs_census_20261023.md`). C'est le même contrat « juge gelé, référence prouvée » que
celui repris ci-dessous, étendu aux fonctions internes de Nokido. Ce rapport n'est pas présent dans ce worktree à la
reprise : il est cité par référence, jamais rejoué.

## Tableau des cibles

| Cible | Périmètre (fichier:fonction) | Juge existant ou à écrire (fichier:ligne) | Métrique et sens | Corpus/fixture | Effort S/M/L | Candidat bas niveau (oui/non + raison) | Preuve | État |
|---|---|---|---|---|---|---|---|---|
| `juge_ancrage_swarm` (pilote) | `tools/forge_cli_swarm.py` : `_chiffres`, `_extraire`, `_juger_ancrage` | Existant : `tools/bancs/banc_juge_ancrage.py:39-50` | F1 des chiffres sans source, max | `tools/bancs/corpus_juge_ancrage.jsonl`, étiqueté à la main | S | non — parsing de texte et regex, pas de boucle chaude CPU pure | `config/bancs_amelioration.json:2-23`, `tools/bancs/banc_juge_ancrage.py:1-10` | PROUVÉ |
| Graphe d'imports `scan_forge_modules` | `app/forge_panorama_builder.py:145-179`, extraction `:107-142` | À écrire : `tools/bancs/banc_panorama_imports.py` (graphe doré figé depuis HEAD) | F1 du graphe par module, max ; temps de scan, min | `sandbox/bancs/panorama_imports_golden.json` à figer + 50 modules étiquetés à la main | M | non — `ast.parse` + I/O disque, et cache disque déjà en place (`:44-53`) ; un natif devrait reproduire la sémantique Python | code `:126-142` ; mesure historique 18/10 dans `tests/nr/test_panorama_cache_disque_nr.py:1-7` | À MESURER |
| Rédaction DLP `redact_text` | `app/forge_semantic_firewall.py:360-386`, motifs `:169-223`, bornes `:226-229` | À écrire : `tools/bancs/banc_redaction_dlp.py` | F1 des spans détectés + égalité exacte texte et mapping, max | `tests/test_semantic_firewall.py:24-60` + 120 cas adversariaux à étiqueter | M | non — `re` est déjà en C, coût borné par `_MAX_REDACT_LEN` et `_MAX_REDACTIONS`, pas boucle chaude | code `:360-386`, tests `:24-60` | À MESURER |
| Découpage Markdown `MarkdownChunker.chunk` | `app/forge_rag_store.py:191-281`, boucle `:208-267` | À écrire : `tools/bancs/banc_chunker_markdown.py` (propriétés) | Taux de conformité des invariants, max ; conservation des caractères, min | 20 documents `docs/**/*.md` + fixtures de headers et d'overlap | S | non — boucle Python pure mais volume faible, aucun profil de boucle chaude ne le désigne | code `:191-281` ; aucun test direct du chunker repéré | À MESURER |
| Complexité et sélection de modèle | `app/forge_cognitive_router.py:76-89` et `:100-118` | À écrire : `tools/bancs/banc_complexite_router.py` | Macro-F1 des trois classes, max | 100 prompts étiquetés simple, technical, strategic | M | non — deux regex et un dictionnaire, coût négligeable | code `:76-118`, tests `tests/nr/test_bunker_grade_nr.py:77-101` | À MESURER |
| Routage d'intention `IntentRouter.route` | `app/forge_agents.py:954-1006`, confiance `:1008-1025` | À écrire : `tools/bancs/banc_intent_router.py` | Top-1 accuracy et MRR, max | 150 demandes étiquetées par rôle attendu | M | non — balayage de mots-clés dans un dictionnaire, pas CPU-bound | code `:954-1006`, tests de fumée `tests/nr/test_core_coverage_nr.py:188-234` | À MESURER |
| Routeur DT `route_with_dt` | `app/forge_llm_router_dt.py:712-755`, modèle et base `:622-625`, entraînement `:641-654` | À écrire : `tools/bancs/banc_routeur_dt.py`, avec modèle gelé et base `provider_scores` remplacée par fixture | Accuracy contre oracle étiqueté, max | 100 prompts + modèle de test figé ; jamais `%NOKIDO_DATA%\embeddings.db` | L | non — inférence de modèle et I/O SQLite, pas boucle pure | code `:622-625`, `:641-654`, `:712-755` | ILLISIBLE |
| Compression `SymbioticBridge.compress_context` | `app/forge_symbiotic_bridge.py:16-24`, appel `:40-46`, compression `:48-61` | Aucun juge déterministe de fidélité ; un stub ne mesurerait que le fallback | Ratio de compression et conservation des tokens critiques, mais dépend du modèle | Aucun corpus déterministe ; Ollama local requis | L | non — réseau HTTP et sortie de modèle | code `:16-61` | ILLISIBLE |
| Audit d'index `forge_db_index_advisor.auditer` | `tools/forge_db_index_advisor.py:589`, plan `:525`, portée `:10-13` | À écrire : `tools/bancs/banc_index_advisor.py` | Précision et rappel des constats sur plans connus, max | Base SQLite synthétique de 6 tables + 20 requêtes à plan attendu | M | non — `sqlite3` et I/O, pas boucle pure | code `:10-13`, `:525`, `:589` | À MESURER |
| Budget de contexte résident | `tools/forge_context_budget.py:77-81`, CLI `:22-25`, postes `:84-110` | Existant : `--check` et `--json` du même module | Octets par poste, min ; verdict 0 ou 1 | Dépôt courant + fixtures de tests | S | non — lecture de fichiers et comptage d'octets | budgets `:77-81`, tests `tests/nr/test_budget_contexte_nr.py:337-365` | PROUVÉ |
| Routeur d'embeddings `_brain_worker_call` | `app/forge_embed_router.py:46-83`, provider HTTP `:95` | Aucun juge déterministe ; ZMQ `:5557` et HTTP requis | Débit et latence seulement en live, non rejouable hors services | Aucun corpus déterministe | L | non — I/O réseau et ZMQ | code `:46-83`, `:95` | ILLISIBLE |

## Trois cibles recommandées en premier

1. **`scan_forge_modules`** — motif : c'est le seul poste dont le coût à froid est déjà mesuré et attribué
   (`tests/nr/test_panorama_cache_disque_nr.py:1-7` : 6,2 s sur 13,65 s d'introspect, 593 modules re-parsés), et sa
   sortie est un graphe déterministe, donc jugeable sans LLM ni base. Le cache disque (`app/forge_panorama_builder.py:44-53`)
   réduit déjà le coût récurrent : le premier gain à prouver n'est pas « plus vite » mais **le même graphe, plus vite**.
   Commencer par figer le graphe doré depuis HEAD, puis mesurer le temps de scan à froid sur une copie isolée.

2. **`redact_text`** — motif : fonction de sécurité, sortie déterministe, corpus de tests déjà présent
   (`tests/test_semantic_firewall.py:24-60`), et métrique F1 naturelle sur des spans. Le juge doit inclure des cas
   négatifs pour éviter qu'une règle plus agressive « gagne » en supprimant du texte bénin. Effort M, aucun service.

3. **`MarkdownChunker.chunk`** — motif : fonction pure, sans I/O, sans LLM, sans base, donc jugeable par propriétés
   (headers, overlap, taille maximale, conservation du contenu). Elle n'a pas de test direct repéré, ce qui rend le
   juge utile même avant optimisation. Le volume est faible : ce n'est pas un candidat natif, mais c'est une cible
   take-home propre.

Écartés du premier lot : `route_with_dt` (dépend d'un modèle et de la base), `SymbioticBridge` et
`forge_embed_router` (réseau et modèles), `forge_db_index_advisor` (juge à construire sur fixture, effort M).

## Chantier bas niveau

Recherche par les termes : `bas niveau`, `low-level`, `rust`, `wasm`. `docs/roadmap_state.json` et les 200 premières
lignes de `docs/ROADMAP.md` ne rendent aucune entrée de chantier exploitable sous ce vocabulaire : le chantier y est
`ILLISIBLE`, pas absent. Seules des mentions d'archive ressortent d'un balayage large, par exemple la revue de la cible
Spin/WASM (`docs/archive/audits/ARCH_REVIEW_2026-05-02_md_router_spin.md:57-191`).

L'ancrage réel est un item de roadmap hors de ces deux fichiers : `roadmap_p2_rust_wasm_cible_20261016`, statut
`PARTIEL`, priorité `P2`, texte « Poste résiduel de la question lente (5,8 s), profil du hub en charge de jour, puis
candidat suivant. » (`docs/specs/06_PLAN.md:118`, repris dans `docs/specs/04_PRD.md:207`). Il est explicitement
dépendant du traitement de la dette : `p0_owner_traiter_toute_la_dette_20261016` -> `roadmap_p2_rust_wasm_cible_20261016`,
raison « dette avant tout nouveau chantier (owner 16/10) » (`docs/roadmap_dependances.json:24`).

Verdict de ce recensement : **aucune cible du tableau ne réunit les trois conditions d'un vrai candidat bas niveau**
(boucle chaude, CPU-bound, sans I/O).

- `scan_forge_modules` est CPU-bound par `ast.parse`, mais lit les fichiers et bénéficie déjà d'un cache disque.
  Un portage natif devrait reproduire la sémantique de `ast`, pour un gain borné par le cache.
- `MarkdownChunker.chunk` est une boucle Python pure, mais son volume est celui de l'ingestion documentaire, pas
  d'un chemin chaud.
- `redact_text` s'appuie sur `re`, déjà implémenté en C ; le coût est borné et le risque de régression sémantique
  élevé.
- Les routeurs (`route_with_dt`, `IntentRouter`, `forge_cognitive_router`) sont soit des scans de dictionnaire,
  soit de l'inférence de modèle avec I/O.
- `SymbioticBridge` et `forge_embed_router` sont réseau.

Le juge `tools/forge_bench_takehome.py` n'est pas réutilisable tel quel : il mesure les cycles d'un simulateur et
protège les fichiers du défi par empreinte (`tools/forge_bench_takehome.py:1-16`, `:31-38`), pas le comportement
d'une fonction Nokido.

Recommandation : ne pas ouvrir de chantier natif sur la base de ce recensement. D'abord traiter la dette P0, puis
exécuter le profil du hub en charge de jour prévu par l'item P2 et vérifier qu'un poste résiduel de 5,8 s est
réellement CPU-bound. Si un candidat émerge, son acceptance doit être le juge déterministe de la cible (même sortie
exacte) plus un gain médian mesuré sur au moins cinq exécutions, référence chaînée et promotion owner.

## Limites

- Aucune nouvelle mesure de latence, de RAM ou de débit : les seuls chiffres cités sont historiques et datés dans
  leur source.
- `%NOKIDO_DATA%\embeddings.db` n'a pas été lu ; les cibles qui en dépendent sont `ILLISIBLE` pour une preuve sur l'état courant.
- Les services `:5557`, `:8099` et Ollama n'ont pas été sollicités.
- `ILLISIBLE` signifie « non mesurable dans ce périmètre », pas « inexistant » ni « inutile ».
