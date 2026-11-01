# Point roadmaps et stratégie de résolution collaborative — 24/10/2026

## 1. Point mesuré

- Arbre `forge_roadmap_keeper` (SSoT `docs/roadmap_state.json`, rafraîchi à 13 h 49) : **109 / 195 items clos = 55,9 %**. Objectif owner : **65 % (127)**, il manque **18 clôtures**. Restent 62 PARTIEL et 15 OUVERT.
- Les chantiers ouverts le 24/10 ne sont **pas** dans l'arbre : ils vivent au tableau noir. Défaut d'organisation n° 1.
- Les 7 veilles du 24/10 n'ont rien appris de valide : SearXNG était muet, avec 0 résultat de recherche et un contenu probablement fabriqué, aujourd'hui en quarantaine. Ce qui a vraiment appris quelque chose : la doc officielle déjà au RAG, les 3 avis externes convergents (swarm fort, Gemini, ChatGPT) et les mesures directes.

## 2. Roadmaps réorganisées en 5 fronts, par causalité

La mesure d'abord, car toute décision en dépend. Puis l'identité, la régulation, l'économie, et enfin le stock.

| Front | Fait le 24/10 (intégré) | Reste |
|---|---|---|
| **F1 Fiabilité de la mesure** (fondation) | Primitive `Mesure` + phase A2 (b45d94c1f, 07219a2e7) ; juge phases 1-2 et mutants (1bcbb5416, 25f2c1d6e) ; caractères invisibles (836ebb619) ; `contexte_execution` (76de6c132) ; essaim par force (4badf6557) ; OTLP sans collecteur (3fcb3c1c9, c0e892b36) ; garde mémoire à deux observateurs (50cc6ec7c) | **Régression `desc=` : 19 NR rouges (en cours)** ; phase B (migrer census, catalogue, juge et essaim vers `Mesure`) ; défauts du banc (bascule, texte d'erreur, `tools` transmis) ; supersession du RAG (dette de 60 jours) |
| **F2 Identités et gouvernance des surfaces** | MCP 2026-07-28 lots 1 à 5 (vérifiés en réel 5/5) ; agent = identité prouvée ; transport signalé et registre ; AGY en MCP seul, écriture native refusée (prouvé) ; installeur `--home` et VIBE_HOME ; dépôt long sécurisé des pairs | Passeport d'appel à 3 axes (appelant, routage, endpoint servi) ; Codex, Copilot et Cline (leviers UNKNOWN) ; scanner de secrets central pour les pairs (inachevé, GLM) ; actifs à la prochaine relance |
| **F3 Régulation du corps** | llama-server non justifiés (liste blanche des lanceurs Nokido) ; Docker arrêté sur signal de fin et vérifié en réel ; coupe-circuit OpenCode ; éviction mesurée (les seuils fonctionnent) | Étaler les veilles (7 en parallèle ont saturé la RAM) ; SearXNG (moteurs bloqués depuis le 15/10) |
| **F4 Économie et modèles** | Matrice de toutes les voies : seul Groq est joignable (gpt-oss-120b 4/4) ; Mammouth sans budget ; Ollama Cloud sans clé | Voie API Claude frugale (**bloquée : SDK absent, installation à refaire ; clé illisible depuis le bac à sable**) ; Batch et advisor (phases 2 et 3) ; étude Managed Agents (relancée) |
| **F5 Stock de l'arbre (195 items)** | — | **18 clôtures** pour atteindre 65 % : viser les PARTIEL dont le RED est déjà écrit (coagulation, méthode par couches, parité des CLI, registre des demandes owner…) |

## 3. Stratégie : un gestionnaire de projets et des exécutants, sur le modèle de llm-council

Le dépôt `karpathy/llm-council` est déjà au RAG. Il procède en 3 étapes : (1) plusieurs modèles répondent séparément ; (2) chacun classe les réponses des autres, **anonymisées** ; (3) un président synthétise. Nokido a déjà les briques : `forge_council_bias_bench` (proposition, classement, `parse_classement`), `app/collab_modes/mode_chef` (un chef qui distribue et synthétise), `_arbitration` (consensus, méta-évaluation), `forge_roadmap_keeper` et la chronologie causale, `forge_task_executor` (exécuteurs, juge, coupe-circuit) et le census (force mesurée). **On câble l'existant, sans nouveau système.**

**Rôles**
- **Gestionnaire de projets** : un ORGANE de Nokido, pas une session. `forge_roadmap_keeper` tient l'état (arbre unique où les chantiers du tableau noir sont versés) ; la chronologie ordonne par causalité ; `mode_chef` distribue. Il impose des limites de travail en cours : 1 tâche active par exécuteur, et un plafond global lié à la RAM, plus jamais 7 veilles d'un coup.
- **Président** : Claude CLI, pour synthétiser, relire et intégrer. Les décisions reviennent à l'owner, par questions à choix multiples.
- **Exécutants** : choisis par force MESURÉE (census et matrice) et par palier S/M/L ; les familles en panne sont mises au repos par le coupe-circuit.

**Cycle par item** (les petits S sautent les étapes 1 et 2)
1. **Propositions séparées** (items M et L) : 2 ou 3 exécutants de familles différentes proposent un plan, sans se voir. Coût bas grâce aux membres gratuits forts (Groq gpt-oss-120b, glm flash, mistral), avec Claude headless pour les L.
2. **Revue croisée anonyme** : chacun classe les plans anonymisés (mécanisme de `forge_council_bias_bench`), ce qui neutralise la préférence pour soi.
3. **Synthèse du président**, qui produit une tâche avec `[LIVRABLE_CONTRAT]`, des fichiers autorisés et un RED d'abord.
4. **Exécution**, puis **juge** (effet réel, mutants), puis **intégration** : garde de divergence, rejeu du RED si non observé, et balayage de TOUS les NR du module touché (leçon de la régression `desc=`).
5. Le **gestionnaire** met à jour l'arbre et le point SSoT ; une CI de référence n'est lancée que sur GO de l'owner.

## 3 bis. Pistes externes (Gemini web, 24/10) : à VÉRIFIER, pas encore des faits

Dépôts cités, en cours d'ingestion intégrale pour vérification (un 404 réfute la piste) : `jpicklyk/task-orchestrator`, `eyaltoledano/claude-task-master`, `madebyaris/agent-orchestration`. Cités sans vérification : `evermind-ai/raven`, `claude-codex-bridge`, `moai-adk`.

Mécanique à retenir si elle se confirme, et vérifiable chez nous : **les quality gates portés par le MOTEUR D'ÉTAT, pas par le prompt** (`task-orchestrator`). La transition d'un item de roadmap vers CLOS est REFUSÉE par le serveur tant qu'aucune preuve structurée n'est attachée au nœud : sha de commit relu, NR verts nommés, artefact `[LIVRABLE_CONTRAT]`. C'est le pendant, pour la roadmap, de ce que le juge fait pour les tâches. Nokido le permet : `forge_roadmap_keeper` + `forge_roadmap_verif_appliquer` + la primitive `Mesure`. Autre idée confirmée par notre propre mesure : **l'homéostasie matérielle comme garde de l'ordonnanceur**. Les orchestrateurs cités n'en ont pas, et chez nous, 7 veilles parallèles ont saturé la RAM le 24/10.

## 4. Première vague proposée

1. Finir F1 : la régression `desc=` et les défauts du banc (en cours).
2. Câbler le cycle du conseil : `mode_chef` + `forge_council_bias_bench` comme étapes 1 et 2, sur UN item pilote.
3. Verser les chantiers du 24/10 dans l'arbre (`forge_roadmap_keeper`).
4. Lancer la course aux 18 clôtures, en partant des PARTIEL dont le RED est déjà écrit.
5. Quality gate serveur sur la transition vers CLOS dans `forge_roadmap_keeper` : RED puis GREEN, si l'ingestion confirme le motif.
