# État organique de Nokido — mesuré le 2026-09-07

> « Le gap n'est PAS l'absence d'organes mais l'absence de (a) leur AGENTIFICATION sous
> contrat et surtout (b) les BOUCLES DE RÉGULATION inter-organes. Comme en biologie :
> l'essentiel n'est pas un organe de plus, c'est le câblage endocrinien/nerveux qui fait
> COOPÉRER les organes. »
> — Directive user, `app/forge_organ_agents.py`

Ce document est un **relevé daté**, pas une déclaration. Source de vérité :
`forge_organ_agents.census() / gaps() / probe()` et `regulation_gaps()`. Le régénérer,
ne pas le recopier — une carte déclarative vieillit sans prévenir, et ce module l'a
payé (`cortisol_to_throttle` annoncé « à câbler » trois semaines après son câblage,
au point qu'une analyse externe a recommandé de refaire le travail dans la forme
précisément mesurée comme nuisible).

## Les trois tiers — la hiérarchie n'est pas un organigramme

Modèle validé par débat swarm (`architecture_rules:organ_tiers_validated`). **Le tier
dit ce qu'on a le droit de faire à un organe**, pas son importance :

| tier | contrat | conséquence |
|---|---|---|
| `REFLEX` | hot-path synchrone < 10 ms | **NE PAS agentifier** — y mettre un LLM le tue |
| `ACTOR` | event-driven déterministe, 0 LLM | daemon / keeper |
| `AGENT` | état + proactif + autonome | contrat OrganAgent |

## Les 12 familles — état MESURÉ

| famille | tier | statut |
|---|---|---|
| SNC / cerveau (`forge_orchestration_gate`, `nokido_hub`, `forge_cognitive_router`) | AGENT | LIVE |
| Mémoire / hippocampe (`forge_self_correction`, RAG, `forge_memory_keeper`) | AGENT | LIVE |
| Immunitaire (`forge_videur`, `forge_integrity`, `forge_semantic_firewall`, `forge_hub_gate`) | REFLEX | LIVE |
| Endocrinien (`forge_endocrine`, `forge_hormones`, `forge_motivation`) | ACTOR | LIVE |
| SN végétatif (`forge_autonomous_loops`, `forge_resource_manager`, keepers) | ACTOR | LIVE |
| Digestif (`forge_ingest_self`, `forge_rag_warmup`, `forge_post_commit`) | ACTOR | LIVE |
| Locomoteur (`forge_silo_engine`, `forge_orchestrator`, `forge_spawn_swarm`) | AGENT | LIVE |
| Circulatoire (`forge_message_frame`, `forge_events`, `nervous_system.ts`) | ACTOR | LIVE |
| Excréteur (`forge_secret_guard`, NoiseGuardian) | REFLEX | LIVE |
| Observabilité / proprioception (`forge_trace_viz`, `forge_meta_health`, `forge_loop_sentinel`) | ACTOR | LIVE |
| **Sens (multimodal)** (`forge_ui_oracle`, `forge_video_observe`, `forge_android`, `forge_crawl`) | AGENT | **DORMANT** |
| **Reproductif / régénération** (`evolutionary_engine`, `forge_tool_forger`, `forge_remediation`) | AGENT | **GAP** |

## Régulation — mesure, pas déclaration

```
probe(endocrine_to_gate)     present, 6 hits    app/forge_orchestration_gate.py
probe(cortisol_to_throttle)  present, 7 hits    app/forge_resource_manager.py
regulation_gaps()            1874 modules audités
                             0 organe en défaut · 0 mort silencieuse
                             0 zone morte · 0 outil au repos
```

⚠️ Le cortisol est un **modulateur de sensibilité, PAS un veto**. Rendu en veto il avait
refusé 471 spawns à RAM 60 % / CPU 6 %, puis 382 à RAM 37,8 % — le frein empêchait la
guérison au lieu de protéger. Ne jamais le « re-câbler » en veto : c'est la régression
déjà mesurée.

## Les deux boucles encore ouvertes

**`regeneration_loop` (P1)** — la seule boucle essentielle qui reste, et **c'est le Dev
Swarm** :

```
memory_keeper (gaps / lessons)
   -> evolutionary_engine / forge_tool_forger   propose modules & correctifs
   -> forge_quality_gate                        éprouve
   -> intégration
```

« Le système se répare/évolue depuis ses propres traces. » Sa **branche afférente** est
la qualité des traces : un graphe qui ment sur qui appelle qui, un registre de vitalité
qui déclare morts des gardes vivants, un gate qui rend vert sans avoir mesuré — la
boucle consommerait du faux et se réparerait de travers. C'est ce qui a été durci le
2026-09-07 (identité des nœuds, registre de vitalité, mesure d'approvisionnement).

**`immune_sentinel` (P1)** — agentifier `forge_inspector` / `forge_idle_watchdog` en
sentinelle proactive qui CHASSE les anomalies, au lieu d'un gate-on-request. Tier ACTOR.

**`sensory_fusion` (P2)** — unifier vision / écran / android / crawl sous un contrat
OrganAgent multimodal.

## Ce que la lecture par les commits ajoute — et ses limites

3 788 commits conventionnels (fenêtre de 4 000), scopes **auto-déclarés** :
`feat 41,3 % · fix 39,6 %` — 81 % du temps à construire et réparer.

Domaines par cohésion mesurée (674 commits, 29 couples acte × domaine) :

| domaine | commits | fichiers distincts | lecture |
|---|---|---|---|
| `veille` | 83 | 23 | le plus **cohérent** — `forge_watch_agent` en centre |
| `hub` | 19 | 12 | le plus **net** — `nokido_hub`, `forge_mcp_registry` |
| `sec` | 127 | ~120 | `forge_authz_shadow`, `forge_hub_token_rotation`, `forge_videur` |
| `qa` | 105 | ~115 | `ci_local`, `forge_feature_checklist`, `forge_release_gate` |
| `core` | 237 | ~150 | **pas un domaine** : un résidu sans centre |

🪤 **`tools/ci_local.py` domine SIX couples sur dix**, à travers des domaines sans
rapport. Ce n'est pas un organe, c'est un **carrefour** — à exclure de toute sélection
par domaine, sous peine de le désigner pour tout.

⚠️ Cette lecture est **statistique et déclarative** (les scopes sont écrits par leurs
auteurs). Elle complète la carte organique, elle ne la remplace pas : la carte dit les
tiers et les boucles, que des compteurs de commits ne peuvent pas voir.
