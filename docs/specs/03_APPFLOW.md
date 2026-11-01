# 03_APPFLOW.md — Machines d'état réelles de Nokido

> Ce document est généré en lisant le code source. **Chaque état et chaque transition cite sa source `fichier:ligne`.** Les faits non lus dans le code sont écrits « NON TROUVE dans le code » plutôt que supposés.

## (a) Admission d'un job — `app/forge_job_runner.py` + `app/forge_lane_admission.py`

### Machine : détermination de lane
**Fichier source :** `app/forge_job_runner.py:88-112` (`admettre_lancement`)

```text
ÉTAT initial: script + online + lane fournis
  → si lane vide: déduire lane = "auto:<basename(script)>" 
      source: forge_job_runner.py:89-93
      si online: lane += "@online"  (différencier @online / non-online, même fichier)
      source: forge_job_runner.py:91-93
ÉTAT: lane déterminée
```

### Machine : admission ressources + lane occupée
**Fichier source :** `app/forge_job_runner.py:93-112` ; `app/forge_lane_admission.py:397-450` (`check_ressources`)

```text
ÉTAT: lane déterminée
  → appel _la.check_ressources(heavy=True) (forge_job_runner.py:97)
      forge_lane_admission.py:397-450
        - si heavy False: ok True (forge_lane_admission.py:408-409)
        - health = _get_system_health() (forge_lane_admission.py:410)
          _get_system_health(): préfère sampler (forge_resource_manager) si frais (age <= CPU_SAMPLER_MAX_AGE_S=10s), sinon inspecteur, sinon psutil (fenêtre FENETRE_CPU_S=0.6s), sinon sentinelle degraded (100/100) (forge_lane_admission.py:100-158)
        - si degraded: journaliser_refus + return {ok False, reason "MESURE INDISPONIBLE...", alt ALT_CLOUD, source} (forge_lane_admission.py:411-418)
        - _ram_saturee(health): (ram_pct > MAX_RAM_PCT OU ram_dispo_gb < RESERVE_GB). MAX_RAM_PCT=85.0, RESERVE_GB=4.0 (forge_lane_admission.py:46-50, 301-307)
          si saturé OU _ram_decision(health)["ok"] False:
            - _try_reserve() (demande forge_resource_manager.request_resources, jamais de kill) (forge_lane_admission.py:276-298)
            - re-mesurer health + dec = _ram_decision(health) (_ram_decision compare live + snapshot sampler via arbitrer_ram à 2 observateurs) (forge_lane_admission.py:370-374, 342-368)
            - si toujours saturé: journaliser_refus + return {ok False, motif, alt ALT_CLOUD, reserve, freed_gb, source, age_s, retry_after RAM_RETRY_APRES_S=15, ram_desaccord} (forge_lane_admission.py:419-441)
        - si cpu_pct > MAX_CPU_PCT (90.0): journaliser_refus + return {ok False, motif CPU, alt ALT_CLOUD, source} (forge_lane_admission.py:442-448)
        - sinon return {ok True, ram_pct, cpu_pct} (forge_lane_admission.py:449)
  → si res.get("ok") False: admettre_lancement retourne {ok False, admit False, lane, reason, reserve, freed_gb, alt_cloud, react} (forge_job_runner.py:98-106)
      react indique : ne pas relancer en appel direct, mesurer/libérer/attendre ou router cloud (forge_job_runner.py:103-106)

ÉTAT: ressources OK
  → occupe = _la.current(lane) (forge_job_runner.py:107)
      current(): lit SQLite lanes DB (PRAGMA WAL), si expiré supprime et retourne None; si bail jeune (<60s) accepté sur parole, sinon si _holder_termine(holder) vrai et >60s depuis acquisition → supprime bail (forge_lane_admission.py:209-235)
        _holder_termine(): si holder commence par "job_" → lit forge_job_runner.read_job(holder, tail=0); retourne True si status in ("done","killed","dead") (forge_lane_admission.py:177-207)
  → si occupe: admettre_lancement retourne {ok False, admit False, lane, busy_by, reason "lane '...' occupée (1 job lourd/lane)", alt_cloud, react} (forge_job_runner.py:108-112)
  → sinon: {ok True, lane} (forge_job_runner.py:112)
```

**Table transitions (a) :**
| transition | condition | source fichier:ligne |
|---|---|---|
| lane vide → auto:<basename> | lane=="" | forge_job_runner.py:88-93 |
| online + même basename → lane différente | online True ajoute "@online" | forge_job_runner.py:91-93 |
| check_ressources(heavy=True) → refus si degraded | health.degraded True | forge_lane_admission.py:411-418 |
| check_ressources → refus si RAM saturée ou indisponible | _ram_saturee OU _ram_decision() refuse (après tentative _try_reserve) | forge_lane_admission.py:419-441 |
| check_ressources → refus si CPU > MAX_CPU_PCT | cpu_pct > 90.0 | forge_lane_admission.py:442-448 |
| current(lane) voit bail expiré → libéré | row[2] <= now | forge_lane_admission.py:217-219 |
| current(lane) voit detenteur terminé et >60s → libéré | age>60 et _holder_termine True | forge_lane_admission.py:222-228 |
| lane occupée → refus admission | occupe truthy | forge_job_runner.py:108-112 |

## (b) Cycle de la soif — `tools/forge_epistemic_daemon.py`

### Boucle principale `run_once`
**Source :** `tools/forge_epistemic_daemon.py:915-976+` (début)

```text
ÉTAT: init
  → conn.executescript(_SCHEMA) ; seen = set(query_hash depuis epistemic_seen) (forge_epistemic_daemon.py:916-917)
  → rows = DISTINCT query_text depuis query_log WHERE length>8 ORDER BY timestamp DESC LIMIT 200 (forge_epistemic_daemon.py:918-922)
  → _split = _interoceptive_split() (soif + soin) (forge_epistemic_daemon.py:930)
    _interoceptive_split lit sandbox/health_diagnostic.json, calcule persistance dans sandbox/self_care_state.json; promeut soin->soif si chronique >=3 cycles ou marqueur KNOW_MARKERS (forge_epistemic_daemon.py:290-352)
  → _intention = _intentional_split() depuis docs/roadmap_state.json (forge_epistemic_daemon.py:931)
  → rows += [(q,) for q in _split["soif"]] (forge_epistemic_daemon.py:932)
  → pour chaque item soin: _propose_care(item) (forge_epistemic_daemon.py:933-934)
    _propose_care: si sev high/critical et NOUVELLE (transition) → _tir_algedonique_autorise (plafond N tirs/6h) ; si autorisé → forge_critical_events.persist + _noter_emission ; toujours propose au blackboard discovered_facts category="self_care" key=f"self_care_{sig}" ring=2 (forge_epistemic_daemon.py:355-434)
  → effecteur_enquete(_split["soin"]) (forge_epistemic_daemon.py:936-942)
    effecteur_enquete: charge état (sinon ETAT_ILLISIBLE), clôture si absent 2 cycles du capteur, met à jour rapports, trouve candidat (chronique>=3, pas en cours, hors recul, hors quarantaine), si armé et budget OK dépose enquête via _deposer_enquete (agent ANTIGRAVITY) avec description_enquete (lecture seule) ; sinon états BUDGET/DESARME/BLOQUE_PAR_DEPENDANCE (forge_epistemic_daemon.py:791-882)
```

### Décision d'examen exteroceptif
**Source :** `tools/forge_epistemic_daemon.py:943-976`

```text
ÉTAT: rows prêts
  → besoin = nb(qt) avec hash(_norm(qt)) non dans seen (forge_epistemic_daemon.py:946-947)
  → motif = _decision_examen(besoin) (forge_epistemic_daemon.py:947)
    _decision_examen: si demande manuelle < DEMANDE_TTL_S (6h) → "demande manuelle"; si besoin>=SEUIL_EXAMEN (10) → "seuil: ..."; si aucun dernier examen → "aucun examen enregistre"; si age >= EXAMEN_MAX_AGE_S (24h) → "echeance..." sinon None (forge_epistemic_daemon.py:537-562)
  → si motif None: return {examen:"EN_ATTENTE : besoin/SEUIL..."} (forge_epistemic_daemon.py:951-953)
  → prets, detail = _reveiller_piliers_sous_veto(motif) (forge_epistemic_daemon.py:954)
    _reveiller_piliers_sous_veto pose veto sommeil via forge_resource_manager.poser_veto_sommeil(SERVICE_SOIF="NokidoEpistemicSoif", ttl VETO_EXAMEN_S=900s) puis _reveiller_piliers (forge_epistemic_daemon.py:888-902)
    _reveiller_piliers déclare wanted pour piliers examen (embed.wanted, rerank.wanted) + Qdrant readyz, attend jusqu'à ATTENTE_PILIERS_S=180s (forge_epistemic_daemon.py:564-596)
  → si pas prets: return {examen:"DIFFERE_PAR_REGULATION..."} (forge_epistemic_daemon.py:955-956)
  → examen="FAIT", boucle sur rows non vus (forge_epistemic_daemon.py:958-976)
    pour chaque: h non seen; cov = ev.coverage_dense(qt); si !cov.ok → abstentions[dependance]++, continuer (ne marque PAS vu); sinon examinees++, INSERT OR REPLACE epistemic_seen, puis selon verdict/gap déclenche _propose_gap (forge_epistemic_daemon.py:969-976)
```

**Table transitions (b) :**
| transition | condition | source fichier:ligne |
|---|---|---|
| soin -> _propose_care (blackboard) | tout item soin | forge_epistemic_daemon.py:933-934 |
| soin high/critical + nouvelle transition -> canal algedonique | sev in {high,critical} et nouvelle et _tir_algedonique_autorise ok | forge_epistemic_daemon.py:375-411 |
| _tir_algedonique_autorise refuse (plafond ou illisible) | >=PLAFOND_TIRS dans FENETRE_TIRS_S ou registre illisible | forge_epistemic_daemon.py:163-192 |
| effecteur_enquete: candidat trouvé et armé et budget OK -> DEPOSEE | chronique>=3, pas en cours, hors recul, hors quarantaine, _effecteur_arme() True, temps depuis dernière >=24h | forge_epistemic_daemon.py:830-882 |
| effecteur_enquete -> DESARME | armé False | forge_epistemic_daemon.py:863-864 |
| effecteur_enquete -> BUDGET | budget fenêtré non écoulé | forge_epistemic_daemon.py:861-862 |
| examen déclenché si demande manuelle <6h OU besoin>=10 OU aucun examen OU age>=24h | _decision_examen | forge_epistemic_daemon.py:537-562 |
| examen DIFFERE si piliers pas prêts dans 180s | _reveiller_piliers_sous_veto | forge_epistemic_daemon.py:564-596, 888-902 |
| question non vue mais cov dépendance manquante -> abstention, PAS marqué vu | cov.ok False | forge_epistemic_daemon.py:969-972 |

## (c) Self-patcher — `tools/forge_self_patcher.py` + `app/forge_autonomous_loops.py` + `app/forge_mutation_judge.py`

### Cycle self-patcher `run_once`
**Source :** `tools/forge_self_patcher.py:653-783`

```text
ÉTAT: init
  → APPLIED_DIR créé si possible ; applied = fichiers dans APPLIED_DIR (*.md) (forge_self_patcher.py:654-658)
  → proposals = sorted(PROPOSALS_DIR.glob("evolution_proposal_*.md")), pending = non dans applied (forge_self_patcher.py:659-660)
  → pert = _pertinence() ; si OBSERVATION → dry_run=True, mode SIMULATION (forge_self_patcher.py:663-672)
  → pour chaque proposal pending:
      lit texte; rel = _extraire_rel (bloc JSON avec error_id+pointer_ref) (forge_self_patcher.py:681-686)
        si REL sans pointer_ref.file → NON consommee (forge_self_patcher.py:683-686)
      test_f2p = _test_du_rel(rel); si présent: vert? _rel_deja_vert() True → marque skipped "test du REL deja vert" et continue; None → NON consommee (forge_self_patcher.py:687-700)
      extrait patterns depuis lignes "- **..." (forge_self_patcher.py:702-717)
      si pas patterns et pas dry_run → marque skipped "no actionable patterns" (forge_self_patcher.py:707-717)
```

### Génération + soumission au juge
**Source :** `tools/forge_self_patcher.py:719-783` ; `app/forge_autonomous_loops.py:685-748` ; `app/forge_mutation_judge.py:899-948`

```text
ÉTAT: patterns disponibles
  → 1) Règles déterministes: pour patterns matchant DETERMINISTIC_RULES (_rule_cp1252, _rule_missing_utf8_stdout) si rel None → _batch_deterministic(rule_fn, rule_key, dry_run) (forge_self_patcher.py:723-734)
      _batch_deterministic: parcourt app/*.py + tools/*.py, skip si non safe, si dry_run log DRY-RUN, sinon _submit_to_judge(f"rule:{rule_name}", rel, new_text, rule_name) (forge_self_patcher.py:550-573)
  → 2) LLM fallback si unmatched et pas applied_files: rag_ctx = _rag_lookup; boucle jusqu'à PASSES_MAX si rel (sinon 1) avec raffinement si rejet raffiné (_REJETS_RAFFINABLES = ("MEURT","SURVIT_SANS_GAIN"); PASSES_MAX=2) (forge_self_patcher.py:737-759)
      _llm_generate_patch construit prompt avec patterns+rag_ctx+rel_ctx, _ask_cascade sur providers (défaut groq,ollama) avec hub_call ask; parse JSON (forge_self_patcher.py:259-401)
      _essayer_patch: vérifie safe_check et cible == pointer_ref.file si rel, taille < MAX_PATCH_LINES, search présent, crée candidate = src.replace(search,replace,1), appelle _submit_to_judge(f"proposal:{prop.stem}", target, candidate, desc, test_f2p) (forge_self_patcher.py:595-650)
  → _submit_to_judge: ajoute perimetre_mesure(rel) aux tests si non fourni; appelle forge_autonomous_loops.submit_candidate_to_judge(ref, rel, nouveau, tests) (forge_self_patcher.py:515-548)
      submit_candidate_to_judge: vérifie porte évolution (forge_mutation_judge.evolution_autorisee()) — si refus => enregistre HALTED et retourne {status:"HALTED", verdict:"HALTED", porte}; sinon archive candidat dans sandbox/evolution/candidates/{sha}.py; si pas tests utilise juge.perimetre_mesure(rel); appelle juge.juger_module_avec_gain(rel,nouveau,tests) (forge_autonomous_loops.py:685-748)
        juge.juger_module_avec_gain: baseline = mesurer(tests), baseline_ho = mesurer(held_out(tests)); r = juge.juger_module(rel,nouveau,tests); si !SURVIT => journalise et retourne; sinon candidat = mesurer(tests), g = juger_gain(baseline,candidat); si AMELIORE → jho = juger_held_out(baseline_ho, mesurer(ho)); si jho != DEGRADE → verdict AMELIORE (conserve), sinon restaure depuis git HEAD et verdict REJETE_HELD_OUT; si pas AMELIORE → restaure depuis git HEAD, verdict SURVIT_SANS_GAIN ou GAIN_INDECIDABLE selon cas (forge_mutation_judge.py:899-948)
          juge.juger_module: verrou (_prendre_verrou), mutable() (refuse si zone évaluateur ou périmètre immuable), patron_sain() depuis git HEAD, .bak via tracer_bak(), ast.parse, écrit fichier, _restaurer depuis git HEAD sur échec; juger_memoire() en premier (récidive); import réel via subprocess; exécute tests fournis (forge_mutation_judge.py:471-551)
            perimetre_immuable parcourt depuis RACINES avec BFS sur imports locaux (profondeur 4) → fichiers intouchables (forge_mutation_judge.py:85-135)
            zone_evaluateur_touchee interdit tests/, tools/ci_local.py, config/constitution.toml, sandbox/evolution/, conftest.py, pyproject.toml, pytest.ini, setup.cfg, tox.ini, tools/forge_merge_gate.py, tools/forge_heldout_gate.py, app/forge_mutation_judge.py, app/forge_autonomous_loops.py, app/forge_guarded_mutation_loop.py (forge_mutation_judge.py:146-162)
            evolution_autorisee: vérifie human_lock_state, frein evolution.halt (précédence), puis armement (LAFORGE_EVOLUTION_ARMED ou fichier evolution.armed avec portée l1/tout) — portées combinées prennent la plus restrictive (forge_mutation_judge.py:193-272)
            juger_gain: anti-Goodhart, exige non-régression par test, compare tests_ok/durée et métrique déclarée si présente; verdicts AMELIORE/NEUTRE/DEGRADE/INDECIDABLE (forge_mutation_judge.py:787-851)
            juger_held_out: teste sur jeu disjoint (24 NR déterministes) — si perte → REJETE_HELD_OUT (forge_mutation_judge.py:853-891)
  → si verdict dans VERDICTS_RETENUS ("SURVIT","AMELIORE") → applied_files append, stats["patches_applied"]++, anchor_solution appelé (forge_self_patcher.py:634-651)
  → sinon stats["patches_failed"]++ (forge_self_patcher.py:649)
  → si applied_files et pas dry_run → log "en attente de commit owner" (forge_self_patcher.py:763-765) ; _git_commit est DESARMÉ (forge_self_patcher.py:499-509)
  → marque proposal traité dans APPLIED_DIR (sauf dry_run) (forge_self_patcher.py:768-783)
```

**Table transitions (c) :**
| transition | condition | source fichier:ligne |
|---|---|---|
| proposal REL sans pointer_ref.file → NON consommee | rel et pointer_ref.file manquant | forge_self_patcher.py:683-686 |
| test REL déjà VERT → skip marqué | _rel_deja_vert True | forge_self_patcher.py:691-700 |
| test REL illisible → NON consommee | _rel_deja_vert None | forge_self_patcher.py:690-693 |
| evolution non autorisée → HALTED consigné | forge_mutation_judge.evolution_autorisee() False | forge_autonomous_loops.py:706-713 |
| fichier dans zone évaluateur ou périmètre immuable → REFUSE | forge_mutation_judge.mutable() False | forge_mutation_judge.py:291-302 |
| pas de patron sain depuis git HEAD → REFUSE | patron_sain() !ok | forge_mutation_judge.py:490-495 |
| récurrence détectée (juger_memoire) → MEURT restauré | mem.verdict=="RECIDIVE" | forge_mutation_judge.py:523-527 |
| import réel échoue → MEURT restauré depuis git HEAD | subprocess import returncode !=0 | forge_mutation_judge.py:529-536 |
| test échoue → MEURT restauré depuis git HEAD | pytest returncode !=0 | forge_mutation_judge.py:538-545 |
| SURVIT mais pas AMELIORE → restauré depuis git HEAD, verdict SURVIT_SANS_GAIN/NEUTRE | juger_gain pas AMELIORE | forge_mutation_judge.py:944-948 |
| AMELIORE mais held-out dégradé → restauré depuis git HEAD, verdict REJETE_HELD_OUT | juger_held_out DEGRADE | forge_mutation_judge.py:933-943 |
| AMELIORE et held-out TENU → conservé (AMELIORE) | verdict final AMELIORE | forge_mutation_judge.py:928-932 |
| MEURT/SURVIT_SANS_GAIN → raffiné (passe suivante) si rel et < PASSES_MAX | boucle raffinement | forge_self_patcher.py:740-759 |
| SURVIT/AMELIORE → en attente commit owner (_git_commit désarmé) | VERDICTS_RETENUS | forge_self_patcher.py:763-765, 499-509 |

## (d) Bancs — `tools/forge_bfcl_runner.py` et `tools/forge_humaneval_runner.py`

> Section (d) réécrite par Claude le 26/10 à l'intégration : la version livrée n'avait lu que les 200 premières
> lignes des runners et concluait « CANARI_N NON TROUVÉ » à tort.

```text
ÉTAT: run(...) -- BFCL forge_bfcl_runner.py:634 ; HumanEval forge_humaneval_runner.py:636
  → pour chaque cas i : appel du fournisseur ; une erreur d'appel (« [ERR] ... ») compte dans `errors`
  → HumanEval seulement : 429 sur quota JOURNALIER (_quota_journalier, forge_humaneval_runner.py:206)
      -> quota_epuise retenu (forge_humaneval_runner.py:685-686) -> ARRÊT après le cas courant, tâches non
         jouées dites dans le résumé (forge_humaneval_runner.py:827-828, « arret_quota » :861)
  → CANARI : après CANARI_N = 3 cas (BFCL :631, HumanEval :633), si les 3 sont des erreurs d'appel
      -> passe ARRÊTÉE, ni JSON de mesure ni ancre RAG, retour {non_mesure: True, canari}
         (BFCL :758-762 ; HumanEval :831-834)
  → sinon : passe complète -> JSON de mesure + anchor_solution
ÉTAT final (point d'entrée) : sys.exit(2) si non_mesure, sinon 0 (BFCL :857 ; HumanEval :921)
```

**Table transitions (d) :**
| transition | condition | source fichier:ligne |
|---|---|---|
| canari -> passe arrêtée, non_mesure | i + 1 == CANARI_N et errors == CANARI_N et len(subset) > CANARI_N | forge_bfcl_runner.py:758 ; forge_humaneval_runner.py:831 |
| quota journalier -> arrêt anticipé (HumanEval) | 429 « per day / TPD / RPD / daily » | forge_humaneval_runner.py:206-211, 685-686, 827-828 |
| non_mesure -> rc 2 au point d'entrée | _s.get("non_mesure") | forge_bfcl_runner.py:857 ; forge_humaneval_runner.py:921 |

---

## Notes d'implémentation
- `forge_job_runner.admettre_lancement` est le point d'entrée unique pour admission (MCP/REST partagent) (forge_job_runner.py:70-112)
- Lane admission utilise base SQLite `LAFORGE_LANES_DB` avec WAL, TTL 7200s, libération automatique si holder terminé (forge_lane_admission.py:40, 163-175, 177-235)
- Epistemic daemon ne marque vu une question que si coverage_dense réussit (dépendance manquante → abstention, pas marqué vu) (forge_epistemic_daemon.py:969-972)
- Self-patcher soumet TOUJOURS au juge (thymus) via `forge_autonomous_loops.submit_candidate_to_judge` → `forge_mutation_judge.juger_module_avec_gain`; `_git_commit` est désarmé (forge_self_patcher.py:515-548, 499-509)
- Juge restaure TOUJOURS depuis `git HEAD` (patron sain), jamais depuis `.bak` (forge_mutation_judge.py:311-323, 512-519)
- Held-out disjoint requis pour conserver un gain (REJETE_HELD_OUT si dégradé) (forge_mutation_judge.py:853-891, 925-943)
