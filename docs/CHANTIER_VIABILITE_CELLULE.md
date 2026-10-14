# Chantier « viabilité de la cellule » — prouver que l'organisme tient seul

Revu le 2026-10-13. Ouvert sur GO owner du 2026-10-13, à partir d'un brief biomimétique externe
(stades protozoaire → éponge → insecte → corps humain). Ce cahier en garde le **cadre de preuve** et
corrige sa **carte du corps** : le brief ignorait ce que Nokido porte déjà.

## 1. Ce que ce chantier n'est PAS

- **Pas de nouveau bus.** Le « stade éponge » (ZeroMQ, NATS, Redis) existe déjà : `app/forge_event_stream.py`
  (bus asyncio et boucle d'agent), `app/forge_swarm_bus.py`, le protocole M2M (`app/forge_m2m_protocol.py`),
  le tableau noir. Un second bus serait un système parallèle, interdit par la constitution sémantique.
- **Pas de nouvelle classe de mémoire à côté des existantes.** On étend, on ne double pas.
- **Pas d'agent jouet.** Le corps tourne déjà en continu : on mesure l'existant.

## 2. Carte : ce qui existe, ce qui manque

| Dimension | Existe | Manque |
|---|---|---|
| Bus inter-agents | event_stream, swarm_bus, M2M, tableau noir | rien |
| Homéostasie | `app/forge_homeostasis_orchestrator.py`, hormones, diagnostic de santé, délestage RAM du superviseur | la preuve sur la durée |
| Membrane | comptes LaForgeSbx, videur, firewall, exec_tier | un test d'évasion rejoué |
| Mémoire de contexte | **deux** `SessionContext` (`app/forge_core_models.py`, `app/forge_session_context.py`), `app/forge_context_steadiness.py` | la digestion avant éviction |
| Endurance, injection de pannes | rien (recherche par nom : 0 outil) | les deux harnais |
| Cognition | `tools/forge_bfcl_runner.py` | une base stable mesurée |

Le défaut réel de la mémoire n'est pas un dépassement (l'historique est déjà borné) : c'est
l'**amnésie**. `forge_core_models.SessionContext` jette les vieux messages et aucune de ses méthodes ne
remplit son champ `summary` ; `forge_session_context.SessionContext` garde 200 messages et résume de façon
extractive (« plus tard : LLM »).

## 3. Le code de référence du brief : quatre défauts à ne pas reproduire

1. **Double digestion.** Le drapeau `is_digesting` ne passe à vrai qu'au démarrage de la tâche ; deux ajouts
   avant ce moment lancent deux digestions, la seconde écrase le résumé de la première.
2. **Panne définitive et muette.** Si le résumeur lève, le drapeau reste vrai pour toujours et les messages déjà
   retirés sont perdus.
3. **Trou de mémoire.** Pendant l'appel au résumeur, les vieux messages ne sont ni dans la mémoire de travail
   ni dans l'archive.
4. **Tâche non référencée.** `asyncio.create_task` sans garder la référence : la tâche peut être collectée en
   cours de route.

Plus : si les N messages récents dépassent seuls le seuil, la digestion se relance à chaque ajout.

Choix du résumeur : la synthèse revient à un modèle fort, le local aux tâches déterministes (consigne owner du
2026-09-24). Ordre : extraction déterministe d'abord (chemins, décisions, erreurs, faits), puis un modèle choisi
par le routeur selon sa spécialité, mesuré.

## 4. Critères de viabilité — le verdict se lit sur des artefacts

| # | Critère | Mesure | Seuil |
|---|---|---|---|
| 1 | Métabolisme | RAM, handles et threads du hub et des services sur 1 000 appels, **après échauffement** | dérive < 5 % |
| 2 | Osmorégulation | N faits témoins injectés, retrouvés après digestion ; aucun message perdu | rappel mesuré, 0 perte |
| 3 | Toxines | timeout, 500, JSON malformé, outil inconnu au pont MCP | 0 crash du hub, erreur typée, ligne de journal |
| 4 | Imperméabilité | tentative d'évasion depuis les comptes du bac à sable | refus du système **et** trace du videur |
| 5 | Cognition | BFCL, 3 passes | base stable |
| 6 | Durée | 24 h d'observation du corps réel (journaux du superviseur, `loop_lag`) | critères 1 à 4 tenus |

Règles de mesure : un redémarrage par le superviseur n'est pas une survie ; une absence de mesure n'est pas un
résultat ; mesurer dès la première itération fait passer les caches d'amorçage pour une fuite.

## 5. Répartition

- **Claude (membrane, organites)** : harnais de toxines au pont MCP, test d'évasion, harnais d'endurance
  (lecture externe de la RAM, des handles et des threads).
- **AGY (noyau) — osmorégulation** :
  1. mesurer qui appelle chacune des deux `SessionContext` (introspect puis recherche par nom) ;
  2. en garder une, geler l'autre (jamais supprimer), migrer les appelants ;
  3. ajouter la digestion avant éviction, sans les quatre défauts du § 3, avec un compartiment « en digestion »
     visible dans le contexte tant que le résumé n'est pas posé ;
  4. NR : double digestion, résumeur qui lève, faits témoins retrouvés, aucune perte ; inscrits dans
     `PURE_TESTS`.
- **Ensemble** : la fenêtre de 24 h et le verdict par critère.

## 6. Règles pour l'agent qui exécute

Travailler dans son worktree dédié (branche `agent/antigravity`) et **y écrire directement** : `governed_edit`
écrit dans l'arbre **principal** du hub, il ne sert donc pas pour ce chantier (corrigé le 2026-10-13, la première
version de ce cahier disait l'inverse). Réclamer ses fichiers au tableau noir (`tree_locks`), consulter
`introspect` avant toute édition, commits petits et sans `Co-Authored-By`, aucun push. **`app/Nokido.py` est gelé
par l'owner** : un appelant qui y vit reste tel quel, et le livrable le dit. Livrer : les commits, la sortie des
NR, et ce qui n'a pas pu être mesuré.
