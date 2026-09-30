<!-- Roadmap VIVANTE — curée depuis blackboard:architecture_rules + livrables de session.
     ⚠️ NE PAS régénérer par LLM. Le 2026-08-20, une passe `forge_roadmap_synth`
     a écrasé ce fichier par une sortie groq TRONQUÉE en plein milieu d'une phrase
     (« [… réponse tronquée 4000/4682 chars ] »), remplaçant des entrées précises et
     vérifiables par du remplissage générique. Une SSoT ne se reconstruit pas à partir
     d'un modèle qui n'a pas lu le vivant : elle se CURE, entrée par entrée, sur preuve. -->

# ROADMAP Nokido — l'organisme souverain

> Cap : un OS d'agents local-first qui **se gouverne, s'apprend, se régule et se soigne**.
> Marqueurs : ✅ fait · 🔄 en cours · ⬜ à faire.
> **Statut hérité du 2026-06-13**, sauf les lignes datées `(vérifié JJ/MM)` — celles-là
> seules ont été re-mesurées. Un ✅ non daté atteste d'une livraison passée, pas d'une
> vérification récente : ne pas le lire comme une garantie d'aujourd'hui.

## P0 — Socle vivant (gouvernance + boucles fermées)

- ✅ **Gate d'orchestration** — `forge_orchestration_gate.classify` : 3 voies (native/local/deport/cloud), plancher qualité d'abord.
- ✅ **Routeur de planification composé** — `plan_route` compose `intent_router` LIVE + classify (anti-dup, pas de routeur parallèle).
- ✅ **Apprentissage actif du routage** (Friston FEP) — `learn_adjust` re-rank par prior appris (`forge_active_inference`) ; `record_route_outcome` ferme la boucle.
- ✅ **Boucle endocrine→gate CLOSE** — afferent (`record_route_outcome`→dopamine/cortisol) + efferent (cortisol module `learn_adjust` : escalade sous stress, bloque cloud sous quota).
- ✅ **Gouvernance parallèle** — `forge_hub_gate` fail-closed dans `_tool_call` ; ring/firewall = post-filtre, jamais dans le scoring.
- ⬜ **active_inference Phase 2** — M (pas S) : d'abord `plan_route` DANS le routeur live, PUIS l'exécuteur appelle `record_route_outcome`. Le vrai chantier autonomie.
- ✅ **videur Phase 2** — `_resolve_ring` passe par `forge_videur.resolve_identity` (câblé e6ed01e9) → s'active au reboot.

## P1 — Organes-agents (l'organisme se structure)

- ✅ **Couche KEEPER** — 17 keepers (roadmap/memory/rules/canon/skills/workflow/agents/...), artefacts internalisés (RAG) + centralisés + consultés via index FTS5.
- ✅ **Équipe contrôle de flux** — 7 OrganAgents : videur(accès)/convoyeur(auth)/chef_de_gare(files)/voiturier(park)/coursier(prioritaire)/facteur(postal)/aiguilleur(ATC).
- ✅ **Census organe×agent** — 12 familles classées (réflexe/acteur/agent + statut + câblage). 10 live · 1 dormant · 1 gap.
- ✅ **Carte nerveuse** — `forge_nervous_map` : 175 composants découverts LIVE, pluggés cortex/SN, détection drift (nerf qui lâche).
- ✅ **Sentinelle anti-embolie** — `forge_organ_pulse` : 12 checks périodiques (wedge/lag/signaux non consommés/RAM/db_locks/wal/jobs/embed/cortisol/nerve_plug), supervisée.
- ✅ **Coagulation** — `forge_coagulation` : consomme `forge_critical_events` (1120 drainés), triage escalade/heal-borné/ack. Boucle immunitaire CLOSE (voit→soigne).
- 🔄 **Forge Orchestrator / ForgeSwarm** — orchestration déportée local (forge_workflow souverain), best-of-N.
- ⬜ **Régénération (gap)** — boucle close : `memory_keeper`(gaps/lessons) → `evolutionary_engine`/`forge_tool_forger` → `forge_quality_gate` → intégration.
- ✅ **gate_flux intercepteur** — `forge_flow_control.route_flow` advisory dans `_tool_call` (mappe chaque appel à son agent de flux, fail-open) → s'active au reboot.

## P1bis — Gardes anti-régression (vérifié 20/08)

- ✅ **Cliquet de couverture NR** — aucun module neuf sans test d'EFFET. A mordu sur 4 outils du lot du 20/08 ; refermé.
- ✅ **Garde de capacités** — `forge_capability_audit` : le README déclare, le code décide. 8 contrôles, 3 verdicts (ALIGNE / DIVERGE / INDETERMINE — un contrôle qui ne mesure rien ne prouve rien). Première passe : 7 divergences sur 8, toutes corrigées. Câblé BLOQUANT dans `ci_local`.
- ✅ **Registre de vitalité des gardes** — 13 gardes avec verdict RÉEL daté ; un garde qui cesse de se prononcer sur un domaine critique bloque la livraison au bout de 14 jours.
- 🔄 **`archi-lint`** — `semgrep.EXE` **démarre de nouveau** : `--version` rend `1.164.0` (vérifié 30/08). L'erreur « Failed to create system store X509 authenticator » du 19/08 ne se reproduit plus. Reste à mesurer, et c'est une autre question : que le gate `archi-lint` rende un VERDICT et pas seulement que son binaire réponde — un exécutable qui démarre ne prouve pas un contrôle qui mesure.
- ⬜ **Contrôles de capacité restants** — le garde v1 ne couvre que le mécaniquement vérifiable. Non encore mesurés : LNN « runs on the local NPU » (le module est `ncps`/PyTorch), MCTS « inspired by DeepMind » (profondeur 1, sans backprop — le code le reconnaît), « every prompt routed via le firewall », « every change passes governed_edit », sandbox « network-isolated » universel, scores BFCL sans date de mesure consignée (HumanEval est désormais daté : **2026-08-21**, runner au commit `1486b362`, et le README porte la réserve — vérifié 30/08).
- ✅ **`/api/graph/proprioception` recâblé** (vérifié 30/08) — `?file=<chemin>` rend bien le voisinage AST : `imports_from`, `imported_by`, `calls_top`, `center`, `depth`, `stats`. Sans paramètre et avec `?source=graph`, la route rend le résumé du graphe de connaissances. Le README ne sur-promet donc plus sur ce point.

## P2 — Cognition distribuée & régulation fine

- ⬜ **Sens multimodaux (dormant)** — fusion ui_oracle/video/android/crawl sous UN contrat OrganAgent.
- ✅ **cortisol→resource throttle** — `forge_resource_manager.should_throttle` lit le cortisol (>=0.85 → throttle, prouvé) → s'active au reboot.
- ⬜ **coagulation `--armed`** — `forge_remediation` AGIT (heals bornés actifs) sur autorisation, pas juste dry-run.
- ⬜ **Gouvernance épistémique RAG** — trust-ring sur les DONNÉES ingérées + 3 cercles de savoir (enveloppe + gate min-trust à la récup).
- ⬜ **RAG 1024D / world model 4096D** — unification cognition, tiering, decay temporel différencié.
- ⬜ **Multi-machine** — Tailscale, P2P silo, pool LLM distant (LM Link).

## P2bis — Modèle central de l'état d'une mémoire (ouvert 20/08, décision owner)

> Le verrou n'est plus le stockage. Il a été traité : ingestion, indexation, compaction,
> RAM, contention SQLite, observabilité, faux-verts. Ce qui manque est **la décision**.

Chaque correctif de mémoire ajoute aujourd'hui une **heuristique indépendante** au lieu
de renseigner un modèle commun. Le bug trouvé le 20/08 en est la démonstration : le
compacteur traduisait « je ne sais pas quand ceci a été appris » en « c'est assez vieux
pour partir au froid ». Le système ne distingue pas encore **inconnu**, **ancien**,
**peu fiable** et **sans importance** — quatre choses différentes qu'une seule date
prétend trancher.

- ⬜ **Métadonnées déclaratives par mémoire** — `memory_class`, `temporal_status`, `confidence`, `owner_authority`, `valid_until`, `supersedes`. Aujourd'hui la permanence se DÉDUIT du préfixe du nom de fichier (`feedback_`, `decision_`, `politique_`…) : c'est une heuristique fragile, qui rend `decision_temporaire_x` immortelle et laisse vieillir `invariant_x`.
- ⬜ **Sélection sous contrainte, pas troncature par âge** — le seuil est exprimé en **octets** alors que l'unité est la mémoire. 100 notes courtes essentielles ne valent pas 10 longues secondaires. La compaction doit arbitrer sur `importance × confiance × récence d'usage × redondance`, l'âge n'étant qu'un signal parmi d'autres.
- ⬜ **Fraîcheur ≠ importance ≠ confiance** — le plancher de 2 jours protège ce qui vient d'être appris, mais « appris hier et jamais confirmé » est souvent moins fiable que « appris il y a six mois et confirmé 18 fois ». Le compteur de confirmations n'existe pas.
- ⬜ **Décision unique** — rappel, archivage et oubli doivent découler du même modèle, pas de trois heuristiques séparées.

*Acquis qui restent valides : l'archive froide, le ledger append-only et le fichier-topic
garantissent déjà que **rien n'est perdu**. Le chantier porte sur ce qu'on CHARGE, jamais
sur ce qu'on détruit.*

## Permanence (au prochain reboot lanceur)

- ⬜ Services supervisés `NokidoOrganPulse` + `NokidoCoagulation` (déjà dans `services.toml`, run_job en attendant).
- ⬜ Relève des daemons optionnels stale (searxng=Docker coupé, trainer/patcher on-demand).
- ⬜ **Compaction de l'index mémoire** — `forge_memory_compactor` réparé le 20/08 (année non figée, plus récente des dates ISO, sans-date jamais archivé, convergence vers la cible, seuil aligné sur 17 Ko). L'écriture a EU LIEU au SessionStart du 30/08, sous le compte qui en a le droit : `20.1KB -> 19.3KB, 2 archivées`. Reste ouvert : la cible de 17 Ko n'est pas atteinte au plancher de 2 jours, et le compacteur le DIT au lieu de forcer (« l'index demande une revue éditoriale, pas davantage de compaction ») — c'est le chantier P2bis ci-dessus, pas un défaut de l'outil.

---
*L'alignement ÉMANE de Nokido (blackboard `architecture_rules` + RAG `domain=reference`). Discipline : grounder sur le canon avant d'affirmer ; déporter le long ; réutiliser avant de reconstruire.*


## Px - Cerveau et Autopoïèse : Epistemic Drive (La soif épistémique)
> Ajouté le 2026-09-06 suite à l'analyse de la boucle d'autorégulation de la connaissance. Ce chantier définit la prochaine frontière de l'organisme.

- 🔲 **Détecteur Épistémique** : Différencier les états (KNOWN, UNCERTAIN, UNKNOWN, BLIND_SPOT) pour identifier proactivement les "trous" dans la carte de connaissance, sans attendre de prompt utilisateur.
- 🔲 **Générateur de Questions et Score de Priorité** : pistemic_value = uncertainty * relevance * gain * actionability * novelty * contradiction / cost. Ne pas brûler des tokens pour des choses déjà connues à 97%.
- 🔲 **Swarm à Preuves concurrentes comme détecteur de contradiction** : Un statut CONTESTED (divergence entre agents) augmente l'epistemic drive et déclenche la recherche ciblée.
- 🔲 **Curiosité par surprise (Friston / Active Inference)** : Si une prévision diffère d'une observation (xpected ≠ observed), déclencher un EPISTEMIC_EVENT qui lance le Swarm pour enquêter, générer des hypothèses et falsifier.
- 🔲 **La boucle scientifique (Expérience empirique)** : Ne pas se contenter de chercher des documents. Générer une expérience, modifier un état, mesurer l'impact (ex: libération iGPU), et intégrer cette connaissance expérimentale.
- 🔲 **Homeostatic Epistemic Controller** : Réguler la curiosité. Le système n'enquête (dépense métabolique) que lorsqu'il a un surplus de ressources (CPU/RAM/I/O) ou pendant le sommeil paradoxal, en accumulant l'pistemic_debt le reste du temps.

## Px - Phase de Qualification & Stratégie Partenaires (Benchmarks)
> Ajouté le 2026-09-06. Nokido devient une plateforme d'évaluation mesurable pour convaincre des sponsors et asseoir sa crédibilité d'ingénierie.

- 🔲 **Création du protocole BENCHMARKS.md** : Définir la méthodologie de test de Nokido face aux standards de l'industrie (SWE-bench, BFCL).
- 🔲 **Mesure de l'Efficacité Organique** : Prouver par les chiffres (Tokens économisés, baisse de la latence, résilience aux pannes) la supériorité de l'architecture distribuée par rapport à un agent LLM classique.
- 🔲 **Infrastructure Partners** : Ouvrir officiellement le projet au sponsoring de compute (AWS, Cloudflare, NVIDIA, Modal, Together AI) en échange d'une vitrine technique dans nos benchmarks.
