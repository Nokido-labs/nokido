# Roadmap — plan cognitif partagé pour les clients LLM/agents

**Arrêtée par l'owner le 2026-09-12, pour exécution à partir du 2026-09-13.**
Succède à la roadmap longue du 2026-09-05 comme direction courante. Ce fichier est
la source ; le blackboard `architecture_rules / category=roadmap` n'en porte que
les pointeurs (le mainteneur SSoT coupe un fait au premier `.` ou `;`).

## Mission

Faire évoluer Nokido vers un **plan cognitif partagé** pour ses clients LLM/agents,
en réutilisant d'abord les organes déjà présents.

> Ne créer aucun nouveau routeur, bus, gouverneur, système de mémoire ou protocole
> tant qu'un porteur existant n'a pas été identifié **et mesuré**.

## Architecture cible

```text
Claude / AGY / Codex / autres agents
        │
        ├── ACP          (client  ↔ agent)
        ├── A2A          (agent   ↔ agent)
        ├── MCP          (agent   ↔ outils / données)
        └── hooks / streams natifs
                    │
                    ▼
              NOKIDO CONTROL
          identity / capability
          provenance / lease
          execution / policy
                    │
                    ▼
             TRANSIENT GRAPH
          ┌─────────┼─────────┐
          ▼         ▼         ▼
       INTENT    COGNITION   MEMORY
       ROUTER     ROUTING    / STATE
          └────┬────┘
               ▼
        SNN / SPIKE PERCEPTION
        novelty / salience / context_need / urgency
               │
               ▼
        NOKIDO POLICY / METABOLISM
        ┌──────┼──────────┐
        ▼      ▼          ▼
      REUSE  RETRIEVE   EXECUTE ──→ Claude / AGY / Codex
                                          │
                                          ▼
                                        PROOF ──→ TRANSIENT
```

Responsabilités à ne **jamais** inverser :

| acteur | rôle |
|---|---|
| Nokido | perception · mémoire transient · orchestration · régulation · **preuve** |
| LLM | raisonnement · généralisation · synthèse |
| SNN | perception temporelle · salience · nouveauté · prédiction |
| ACP | client ↔ agent |
| A2A | agent ↔ agent |
| MCP | agent ↔ outils / données |

## Ordre de travail

```text
B1 → ACP/A2A runtime autopsy → C0.1 cartographie runtime
   → C0.2 firewall Claude réellement effectif → C0.3 transient
   → C0.4 governor déterministe → C0.5 SNN challenger
   → C0.6 baseline scientifique → C0.7 swarm
   → C0.8 neuromorphique hardware → C0.9 attestation
```

**Arrêt obligatoire à chaque point de contrôle.** Ne pas empiler de nouveaux
chantiers avant validation du précédent.

---

## B1 — AGY CLI ≠ AGY M2M — ✅ FAIT le 2026-09-12 (`cfd420fdb`)

Objectif : permettre la coexistence d'AGY CLI et d'AGY autonome M2M.

- **B1.1 recon** — fait. `forge_lock_manager` était importé par **zéro** module ;
  son `DEFAULT_DB` écrivait dans la base **gelée de 24,7 Go** ; son `lock()` était
  un `asyncio.Lock` **in-process**, donc exclusion nulle entre le hub et un service
  séparé.
- **B1.2 contrat** — la décision porte sur une **ressource réellement exclusive** :
  le **workdir résolu** que agy écrit (`--add-dir` + `--dangerously-skip-permissions`).
  Les deux surfaces lisent la même `LAFORGE_AGY_WORKDIR` avec des défauts
  différents (`C:\tmp` côté CLI, racine du dépôt côté M2M) : variable absente ⇒
  deux ressources ⇒ **parallèle** ; variable posée ⇒ une ⇒ **sérialisé**.
  `psutil` illisible ⇒ `UNKNOWN`, et un `UNKNOWN` **garde** le verrou.
- **B1.3 NR** — `tests/nr/test_agy_lock_ressource_reelle_nr.py`, rouge d'abord
  (14 échecs), inscrit dans `PURE_TESTS` **et** `forge_mutation_ratchet.SURFACES`.

**Écart restant à instruire** : les noms de contrat demandés
(`AGY_INTERACTIVE_OAUTH`, `AGY_M2M_EXECUTION`) ne sont **pas** matérialisés comme
tels — la clé porte le workdir. Le volet `AGY_INTERACTIVE_OAUTH` (magasin OAuth
partagé) a été **délibérément laissé sans verrou** : aucune corruption mesurée,
et un garde branché sur un signal que personne n'émet ne garde rien. À trancher.

## P1 — Autopsie runtime ACP / A2A — ✅ FAIT le 2026-09-12

**Ordre tenu : rien construit, mesure seule.** Instrument
`sandbox/autopsie_p1_grille.py`, artefact `sandbox/autopsie_p1_grille.json`
(66 s, dénominateur : 4 562 sources lues sur `app` · `tools` · `tests`,
1 illisible nommée).

Première passe du 12/09, côté serveur ACP (`autopsie_runtime_acp_2026-09-12`) :
flux stdio nominal vert, admission WS fail-closed, **deux défauts** — un
dépassement de délai rendu `cancelled`, et une annulation qui ne borne pas le tour.

Seconde passe : la grille à neuf colonnes, pour les cinq modules.

> **Question décisive — TRANCHÉE : non, vers aucun.**

Aucune des sept clés du plan de contrôle n'est émise par aucun des quatre modules
mesurables — ni `execution_id`, ni `parent_execution_id`, ni `provenance`, ni
`capability`, ni `routing`, ni `usage`, ni `proof`. Les clés émises sont celles
des **specs seules** : 14 côté ACP (`sessionId`, `agentCapabilities`,
`protocolVersion`), 29 côté A2A (`preferredTransport`, `securitySchemes`, `skills`).

**Le plan de contrôle n'est pas manquant : il est complet et ignoré.**
`token_usage` porte 26 colonnes dont `execution_id`, `transport`,
`writer_component`, `measurement_source` ; ses 5 000 dernières lignes
(`max_rowid` 10 491) donnent `provenance` = `None` 2406 · `CLAUDE` 2524 ·
`UNKNOWN` 70, et **zéro ligne ACP ou A2A**.

**Point de rupture exact, et ASYMÉTRIQUE :**

| frontière | porteur d'extension | travail réel |
|---|---|---|
| A2A | `nokido:agent` · `nokido:cardHash` · `nokido:operational` — **en usage réel** | ajouter un champ sur un porteur vivant |
| ACP | **aucun** champ hors spec | créer d'abord le porteur |

Côté câblage : les trois modules ACP n'ont **ni appelant, ni importeur, ni
mention** dans le reste du code. Verdict de **deux observateurs concordants**
(AST statique + recon textuelle), avec **contrôle positif** — mêmes fichiers,
mêmes globs, 12 hits sur `subprocess` — donc le zéro est une absence prouvée et
non une non-lecture. Cela **corrige** la mesure antérieure qui annonçait deux
importeurs : c'était un artefact de son `findstr`.

### ⚠️ Recadrage owner du 2026-09-12 — ce constat n'est PAS un motif de rejet

```text
ACP inutilisé par Nokido   ≠   ACP inutile
```

L'absence d'appelant interne est **attendue** pour une frontière d'**exposition
vers l'extérieur**. Le but n'est pas de fabriquer un appelant Nokido pour
déclarer ACP « vivant » — ce serait un vert sans preuve.

**Hypothèse architecturale à mesurer, et elle reste ouverte :**

> Nokido peut-il devenir un **agent autonome consommable depuis Zed via ACP**,
> tout en restant le plan cognitif et le système d'autorité, le LLM de
> Zed/Claude/Codex n'étant qu'un **client cognitif** ?

Deux directions à mesurer séparément — la seconde est la plus intéressante :

```text
Nokido → forge_acp_server → ACP → agent externe → résultat → Nokido
Zed    → ACP → Nokido                                    (exposition)
```

Ne pas confondre les couches : ACP est la frontière **client/éditeur ↔ agent
autonome**, pas un protocole pour brancher un LLM. Zed a déjà ses fournisseurs
de LLM ; la question est `Zed → agent ACP Nokido`.

**À vérifier contre la spécification réelle**, sans supposer que l'implémentation
interne correspond à la version qu'utilise Zed aujourd'hui : `initialize`,
`session/new`, `session/prompt`, flux d'outils et de permissions, flux
résultat/événement. Nommer *ACP supporté par Nokido* vs *ACP attendu par Zed*,
et le point de rupture s'il existe.

**Premier E2E** : le chemin le moins artificiel, `Zed → ACP → Nokido → capacité
déterministe réelle → résultat → ACP → Zed`. Pas besoin d'un LLM au premier test :
il démontre le **transport et l'intégration**, pas la qualité cognitive.

**Invariant** : le serveur ACP ne décide ni des skills ni des politiques — il
délègue au plan cognitif. Et `CLAUDE.md` n'est qu'une projection pour Claude
Code ; ACP est une **autre projection**, pour Zed. Ne pas y recopier la
constitution.

**Provenance obligatoire**, en propageant un identifiant existant plutôt qu'en
en inventant un au milieu de la chaîne :

```text
session ACP → execution_id → provenance = ZED / ACP → capability → skill → résultat → proof
```

**Critère de décision — la phase ne se clôt pas sur `OUVERT`** :

| verdict | condition |
|---|---|
| `LIVRÉ` | Nokido consommable comme agent ACP réel **et** chemin Zed utilisable **et** execution/provenance conservés |
| `REJETÉ` | compatibilité impossible · implémentation trop incomplète · dépendance externe inaccessible · bénéfice < coût — **motif précis exigé** |

« Aucun appelant interne » ne constitue **pas** un motif de rejet.

**Priorité** : `P1 = opportunité d'interopérabilité`, menée **sans interrompre**
le reste du plan cognitif. Si une vérification bloque : `PARK ACP` → item
indépendant suivant → revenir ensuite. Le sujet n'est jamais supprimé.

**Convergence visée entre les quatre frontières** — elles ne sont pas
concurrentes : `M2M` interne · `A2A` agent↔agent · `ACP` éditeur↔agent ·
`MCP` agent↔outils. Point commun à faire converger :
`execution_id · provenance · capability · result · proof`. Si Nokido porte déjà
ce contrat, ACP n'est qu'une frontière de plus.

## C0.1 — Effectivité des organes existants

Tracer `forge_intent_parser` · `forge_intention_gate` · `forge_intention_journal` ·
`forge_cognitive_router` · `forge_snn_router` · `forge_spike_router` ·
`forge_routing_decision` · `forge_llm_router` · `forge_swarm_router` ·
`forge_task_router` · `forge_metabolism` · `forge_token_monitor`.

Pour chacun : `CALLED_RUNTIME` · `INPUT` · `OUTPUT` · `DECISION` · `CONSUMER`.
**Un import ne compte pas.** Produire un chemin runtime réel :
`entrée client → intent → routing → éventuel SNN → contexte → exécution → résultat → preuve`.

## C0.2 — Hooks Claude réellement effectifs

Ne pas modifier l'algorithme de `reduire()` avant d'avoir mesuré l'événement réel.
`hook_context_firewall` a un banc à **681 796 → 7 550 tokens (98,9 %)** et un effet
production mesuré à **0 archive / 0 réduction**.

Hypothèse à mesurer sur le payload réel : `traiter()` lit `tool_output` alors que
PostToolUse fournit **`tool_response`**.

Séquence obligatoire :
`payload réel → noms de clés seulement → Bash réel → MCP réel → type/structure →
correctif d'adaptateur → NR sur le payload mesuré → test négatif → E2E`.

⛔ Jamais `str(tool_response)` comme adaptation générique.
Test négatif obligatoire : forme non réductible ⇒ `NO_REDUCTION`, sortie originale
préservée. Mesurer séparément `raw_tool_response_tokens` ·
`visible_tool_response_tokens` · `input_tokens` · `cache_read_tokens` — le ratio de
réduction du tool **n'est pas** automatiquement un gain de tokens LLM.

## C0.3 — Transient cognitif

Seulement après preuve du câblage existant. **Ne pas créer une seconde mémoire
générale.** Événements structurés seulement :

```text
INTENT · CONTEXT_REQUEST · CONTEXT_PROVIDED · OBSERVATION · TOOL_REQUEST
TOOL_RESULT · DECISION · DELEGATION · EXECUTION · ERROR · PROOF · COMPLETION
```

Chaque événement peut porter : `event_id` · `execution_id` · `parent_execution_id` ·
`provenance` · `execution_mode` · `transport` · `correlation_id` · `source` ·
`measured_at` · `validity` · `sensitivity`.

Ne pas stocker automatiquement les transcripts complets. Objectif : *LLM A découvre
X → Nokido conserve X → LLM B demande X → Nokido fournit X → travail non répété*.
Mesures : `tool_calls_saved` · `tokens_saved` · `context_saved` · `latency_saved` ·
`work_saved`.

## C0.4 — Context governor déterministe (avant le SNN)

Réutiliser les règles et organes existants. Décisions : `REUSE` · `RETRIEVE` ·
`EXECUTE` · `DEFER` · `VERIFY` · `WAKE_LLM`.

Connue + fraîche ⇒ `REUSE` · manquante ⇒ `RETRIEVE` · changement significatif ⇒
`WAKE_LLM` · aucune nouveauté ⇒ aucun LLM supplémentaire.
Mesurer l'effet réel **avant tout ML** : LLM turns · tool calls · input tokens ·
cache read · latency · quality.

## C0.5 — SNN challenger

Le SNN **n'est pas une autorité** et ne remplace pas le LLM. Entrées temporelles
compactes (`context_used_pct`, `cache_read`, `cache_miss`, `tool_count`,
`repeat_score`, `failure_rate`, `task_age`, `new_information`, `evidence_delta`,
`intent`, `uncertainty`). Sorties candidates : `novelty` · `salience` · `urgency` ·
`context_need` · `cognitive_pressure`.

Chaîne : `SNN → proposition` puis `Nokido policy → décision` puis `LLM → cognition`.

⛔ Le banc SNN précédent sur la détresse système **reste fermé** — aucune
réouverture sans nouvelle hypothèse, nouvelle tâche et nouveau protocole.

## C0.6 — Baseline scientifique

`A = LLM seul` · `B = LLM + Nokido déterministe` · `C = LLM + Nokido + SNN`.
Même tâche, même environnement, mêmes critères. Mesurer `input_tokens` ·
`cache_read_tokens` · `cache_write_tokens` · `output_tokens` · `reasoning_tokens` ·
`tool_calls` · `LLM_turns` · `latency` · `cost` · `work_avoided` · `quality` ·
`false_positive` · `false_negative`.

**Le SNN n'est retenu que si `C > B`** sur une métrique utile sans dégrader une
autre propriété critique. Si `B` fait aussi bien ou mieux : *SNN non retenu pour
cette tâche*.

## C0.7 — Swarm

Une fois le transient et le governor prouvés. Tous les acteurs convergent vers
`execution_id` · `parent_execution_id` · `provenance` · `capability` · `proof` ·
`transient`. Le swarm partage les **observations et résultats structurés**, jamais
les transcripts complets.

## C0.8 — Neuromorphisme

Seulement si C0.5/C0.6 montrent un gain. Mesurer `event_count` · `spike_count` ·
`firing_rate` · `sparsity` · `inference_latency` · `energy_estimate` ·
`LLM_WAKEUPS_AVOIDED` · `TOKENS_AVOIDED` · `CONTEXT_AVOIDED`.
Backend abstrait (CPU · NPU/accélérateur · neuromorphique) : **aucune dépendance à
un matériel unique**.

## C0.9 — Attestation

La preuve reste **séparée** de la cognition :
`execution → transient → decision → result → proof`.
Jamais `SNN prediction → authority`.

---

## Règles transverses

1. Aucun nouveau module tant qu'un porteur existant n'a pas été exhaustivement mesuré.
2. Un import ≠ un appel runtime.
3. Un hook configuré ≠ un effet réel.
4. Un test vert hors de `PURE_TESTS` / `SURFACES` ne garde rien.
5. Une fixture créée depuis une hypothèse sur le schéma ne prouve pas l'émetteur.
6. `UNKNOWN` n'est jamais `PASS`, `FAIL`, `0` ou `False`.
7. Une estimation tiktoken reste `ESTIMATED`, jamais `REPORTED`.
8. Les transcripts LLM complets ne doivent jamais devenir le transient par défaut.
9. Un SNN propose ; les policies Nokido décident.
10. Toute optimisation doit avoir une baseline avant/après.
11. Ne pas confondre : tokens du tool · tokens visibles au LLM · tokens de contexte ·
    `cache_read` · coût · travail évité.
12. Chaque phase se termine par `NR → E2E → CI → preuve`.
13. Arrêt obligatoire à chaque point de contrôle.
