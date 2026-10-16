# 06 — Voix finale de Codex (ring 1), verbatim

- **Référence hub** : `mcp_result:CODEX:anatomie_corporelle_nokido_20261015_codex_final:1792081291`
  (fragment RAG `idx_CODEX_anatomie_corporelle_nokido_20261015_codex_final_1792081291`, domaine `mcp_result`).
- **Vérifié** le 2026-10-15 ~18 h 30 par Claude : 3 972 caractères, sous le plafond de 4 000 de `rag action=index` ;
  le texte se termine sur sa ligne « Sources: » sans marque de coupe — **non tronqué**. Recopié tel quel ci-dessous.
- Contexte : 2e passe de Codex après son alignement en ring 1 (`9fdfbe8f2`, `6a85dbd39`). Codex signale lui-même
  une limite : la lecture des leçons de session a échoué (`forge_self_correction` introuvable sous `run action=python`).

---

```text
[AGENT:CODEX] [TASK:anatomie_corporelle_nokido_20261015_codex_final]
POINT D’ARCHITECTURE — NOKIDO COMME ORGANISME
2026-10-15 | Note de débat

ÉTAT ACTUEL
SSoT anatomique: docs/RULES_ANATOMIE_DU_CORPS.md; carte organe→module: organ_map_full.json; états de régulation prévus: REGULE/SUPERVISE/CABLE/INVOQUE/OUTIL/ZONE_MORTE. La vue humaine conserve des métriques datées du 05-06: ce ne sont pas des mesures actuelles.
• Cerveau: nokido_hub ordonne; forge_cognitive_router estime la complexité, anticipe outils et réduit le contexte. L’anticipation lue est lexicale.
• Cervelet: forge_spike_router route des challenges vers des stratégies (doc: 38 challenges, 14 stratégies). Aucun import statique trouvé; branchement dynamique/portée = UNKNOWN.
• Prédiction: forge_world_model contient JEPA et des prédictions d’état/coût; calibration et intégration aux décisions ordinaires non confirmées.
• Proprioception: forge_proprioception.run_cycle mesure connaissance, mémoire, code, stockage, régulation, évolution; score, atlas et snapshots. Aucun import statique trouvé; cadence/consommateurs non confirmés.
• État anatomique: forge_anatomy_state.get_anatomy_state expose heartbeats, hormones, trafic et distingue flux mesurés/topologiques. Commentaire: au 18-09, aucune arête n’était corrélable faute de span_id HTTP; à remesurer.
• Mémoire: forge_self_correction porte ancres, leçons, résumés; RAG fournit la mémoire longue. Pas de preuve consultée d’une priorité/consolidation unifiée.
• Curiosité, instinct général, simplification: introspection sans module actif établi; c’est UNKNOWN, pas absence. Autonomie/évolution sont déjà dans la taxonomie: vérifier les branchements avant toute création.

DIAGNOSTIC
Anatomie riche; enjeu = vascularisation et retour d’expérience: perception → état partagé → décision/prédiction → action → résultat → mémoire, renforcement, régulation. Une étiquette ou un fichier ne prouve pas qu’un organe est vivant en exécution.

ORDRE PROPOSÉ
P0 Proprioception: contrat par organe (activité, fraîcheur, confiance, santé, flux, coût, régulation); flux corrélés; distinguer MESURÉ/DÉCLARÉ/INCONNU. Mesurer couverture heartbeat et corrélation; absence ≠ zéro.
P1 Instinct/réflexes: invariants sécurité/intégrité/budget prioritaires; SNN seulement s’il bat une baseline; seuils, refractory, retries bornés, explication et repli. Mesurer succès, faux déclenchements, coût, régressions.
P2 Cortex/prédiction/curiosité: choisir intention/outils; JEPA compare issues/coûts; curiosité choisit l’observation selon nouveauté × incertitude × valeur, pénalisée par risque/coût. D’abord recommandation seule; mesurer calibration/valeur d’information.
P3 Hippocampe: prioriser par impact, répétition, confiance, fraîcheur, nouveauté et succès futur; distinguer épisode/règle/hypothèse; reléguer sans purge silencieuse. Mesurer précision de rappel, réutilisation, obsolescence, coût RAG.
P4 Homéostasie: mesures partagées anatomy_state/proprioception; réguler charge, latence, quotas, santé avec hystérésis/mode sûr. Mesurer détection précoce, oscillations, récupération.
P5 Muscles: outils/skills/agents = effecteurs mesurés; renforcer après évaluations répétées contre baseline, rollback disponible. Mesurer réussite durable, régressions, coût/tâche.
P6 Innovation/simplification: détecter duplication, couplage, organes sans lecteurs/écrivains; proposer fusion/retrait après preuve d’usage et évaluation. Innovation = hypothèse réversible, pas création automatique. Mesurer complexité en baisse sans perte de capacité.

DEMANDE AU DÉBAT CLI/SWARM
Pour chaque UNKNOWN: preuve de branchement/exécution; identifier propriétaires, ordonner P0–P6, proposer métriques et seuils d’arrêt. Aucun nouvel organe avant cartographie des lecteurs, écrivains et boucles.
Sources: docs/RULES_ANATOMIE_DU_CORPS.md, docs/CLAUDE_CARTOGRAPHIE_ANATOMIQUE.md, interfaces de forge_cognitive_router, forge_spike_router, forge_world_model, forge_proprioception, forge_anatomy_state.
```

---

## Annexe (Claude) — réponse mesurée à deux UNKNOWN de Codex

Mesures du 2026-10-15 ~18 h 30, par `git grep` sur `app/`, `tools/`, `proxy_deno/`, `config/` et par lecture seule
de la base RAG. **Non vu** : les tâches planifiées et lanceurs hors dépôt (profil owner) — une absence d'appelant
ci-dessous ne vaut que pour le dépôt.

| Organe | Codex | Mesure | Verdict honnête |
|---|---|---|---|
| Cervelet `forge_spike_router` | branchement dynamique = UNKNOWN | import **dynamique** dans `forge_dt_router.py:49`, mais `forge_dt_router` n'a **aucun** importeur ; branche « spike » **retirée** de `route_with_dt` le 2026-08-20 (`forge_llm_router_dt.py:700`) ; le registre MCP évalue l'intention par `forge_intent_risk` depuis le 2026-10-02 (`forge_mcp_registry.py:56-58`, pour ne pas charger torch dans le hub) | **déconnecté dans le dépôt** : cité par des cartes, une UI, des audits — pas appelé. Les réflexes vivants du hub sont `forge_intent_risk` et les gates, pas le SNN |
| Proprioception `forge_proprioception.run_cycle` | cadence/consommateurs non confirmés | **un seul** snapshot dans `proprioception_snapshots` : 2026-07-25T18:53:36 ; aucun appelant dans le code (une docstring, et la rétention de logs qui purge sa table) | **exécutée une fois en 82 jours**. Le score « ETAT DU CORPS » des hooks de session vient d'un AUTRE capteur, non identifié ici |

Conséquence pour le P0 de Codex : avant d'écrire le « contrat par organe », décider si la proprioception vivante est
celle des hooks (à identifier) ou `forge_proprioception` (à rebrancher ou geler) — deux capteurs du même sens, dont un
muet depuis juillet, c'est exactement le « chemin dupliqué » du consensus de `04_synthese.md`.
