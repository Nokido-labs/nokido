# Vérifications de Clôture — Lot 2 (19 octobre 2026)

- **Date de l'audit** : 19 octobre 2026
- **Auteur** : Agent Antigravity (`agt_antigravity`, Ring 1)
- **Zone Blackboard** : `architecture_rules`, catégorie `roadmap`
- **Mode d'audit** : Lecture seule, vérification sur pièces (git, logs, tests NR, blackboard)

---

## 1. `p2_bail_priorite_403_depuis_un_job_2026-10-14`

### Valeur entière lue (Tableau Noir)
```text
[PARTIEL 2026-10-18 : CODE DEJA CONFORME -- identite CI_REFERENCE (ring 2, sans write_paths) declaree le 16/10 et tools/forge_ci_reference.py demande le bail avec agent=IDENTITE ; garde NR 2c2ef7197. Jeton au coffre (lu par ce compte) : PRESENT. Reste = confirmer sur le JOURNAL du hub qu'un bail CI_REFERENCE est accorde (200, pas 403) a la prochaine CI de reference ; si jeton absent : semis owner puis relance du hub (jeton seme apres le boot = inconnu)] [PARTIEL 2026-10-18 : DECIDE owner -- identite dediee FORGE_TOKEN_CI_REFERENCE a bail court ; reste = RED/GREEN dans config/agent_identities.json + semis du jeton (geste owner)] [DECISION OWNER 2026-10-18 (choix multiple) : OUI identite CI dediee (FORGE_TOKEN_CI_REFERENCE, droit de bail court) ; RED puis GREEN ; jeton seme par l'owner au coffre] [OWNER 2026-10-18 : verif 90291b74a (lot 2) ; reste = Décision d'autorisation owner : accorder une identité d'organe propre à la CI (ex. FORGE_TOKEN_CI_REFERENCE) avec droit de bail court dans config/agent_identities.json pour autoriser la prise de bail depuis un job de CI (évite le 403 sous identité SERVICES).] [OUVERT 2026-10-18 : toujours a confirmer sur le JOURNAL du hub (au 14/10 : lecture de code seulement) ; aucun correctif trouve] P2 (lecture de code, a confirmer sur le journal du hub) : le bail de priorite (forge_resource_manager.demander_bail -> POST /api/resource/request) rend 403 depuis un run_job parce que le job n'a pas d'identite d'organe : LAFORGE_AGENT_NAME vide -> forge_hub_client.entetes_organe presente le jeton SERVICES (sans jeton : 401, pas 403). 403 = authentifie en SERVICES mais NON autorise a prendre un bail. Ce n'est pas une ACL du compte LaForgeSbxOffline. Remede = decision OWNER d'autorisation : identite d'organe propre a la CI (ex. FORGE_TOKEN_CI_REFERENCE) portant le droit de bail 'court', posee par le lanceur de la reference. D'ici la : DeportEmbed mis en pause a la main pendant la reference (GO owner 14/10).
```

### Examen des éléments du « reste = »
1. **Identité CI_REFERENCE déclarée au ring du bail (ring 2, sans write_paths)** : **FAIT**
   - *Preuve* : `config/agent_identities.json:434-446` (`ring: 2`, `write_paths: []`) et test de non-régression `tests/nr/test_ci_reference_identite_bail_nr.py:50-54` validé dans le commit `2c2ef7197`.
2. **Demande de bail sous `agent=IDENTITE` dans `forge_ci_reference.py`** : **FAIT**
   - *Preuve* : `tools/forge_ci_reference.py:91` (`IDENTITE = "CI_REFERENCE"`), appel `bail_priorite(..., agent=IDENTITE)` à la ligne 101, validé par `tests/nr/test_ci_reference_identite_bail_nr.py:57-72` (`2c2ef7197`).
3. **Jeton `FORGE_TOKEN_CI_REFERENCE` au coffre** : **FAIT**
   - *Preuve* : Présent au coffre du hub et résolu par `_exiger_identite` / `config/agent_identities.json:446`.
4. **Confirmer sur le JOURNAL du hub qu'un bail CI_REFERENCE est accordé (200, pas 403) à la prochaine CI de référence** : **RESTE**
   - *Preuve* : Les baux historisés dans `sandbox/baux_priorite/` (dont `bail_1792314198_f7d5af.json` du 18/10 11:03) précèdent le commit `2c2ef7197` (18/10 14:05). La prochaine CI de référence n'a pas encore été déclenchée (geste owner attendu selon `P1_audit_pair_efficience_A_G_20261019` : « 01 reference gelee : push + CI ref = geste owner »). Le constat HTTP 200 au journal du hub lors d'une CI de référence complète reste à faire.

### Verdict
**NON CLOSABLE** — En attente du passage de la prochaine CI de référence pour constater le code HTTP 200 sur pièce au journal du hub.

---

## 2. `roadmap_p2_priorite_hamilton_deux_boucles`

### Valeur entière lue (Tableau Noir)
```text
[PARTIEL 2026-10-18 : INSTRUIT -- un SEUL publieur dans EventStream (app/forge_hybrid_cortex.py:112) : l'EventStream n'est pas le chemin chaud ; le chemin chaud mesure est le ByteRouter (sonde deja cablee forge_byte_router.py:239, comptes par agent:outil). Reste = poser la couche reflexe Hamilton sur le ByteRouter (pas sur EventStream), flood sur ce canal, puis taus sur mesure ; decision d'architecture a soumettre a l'owner avant tout code] [PARTIEL 2026-10-18 : MESURE DE BASE (forge_hotpath_probe, fenetre 11 860 s de charge reelle, 5 executeurs actifs) : pool to_thread JAMAIS sature (file 0, occupes max 5/20, p95 1) ; EventStream : 0 evenement vu en 3,3 h (attente/dispatch/inter-arrivee vides) -> la sonde ou l'EventStream n'est pas sur le chemin chaud (signal sans emetteur a instruire AVANT tout flood, un flood sur un canal muet ne mesure rien) ; plus bavard = TRAY get_mode + hub 1153 appels chacun (~6/min). Reste = instruire qui publie dans EventStream (git grep des publish), puis flood sur le canal REEL, puis taus sur mesure] [PARTIEL 2026-10-18 : DECIDE owner -- GO, mesure d'abord (fenetre de base forge_hotpath_probe --allumer) ; reste = la mesure puis le rapport] [DECISION OWNER 2026-10-18 (choix multiple) : GO MESURE D'ABORD : instrumenter la latence du hot-path event_stream/byte_router (base puis flood reel) ; l'architecture deux boucles se tranche sur cette mesure] [OWNER 2026-10-18 : verif 0405c9d55 (lot 3a) ; reste = Geste owner exact : trancher le débat d'architecture Hamilton AGC en deux boucles (réflexe LIF ms + allostatique s-h, capsule claude.ai pair_57cd434dff098fa1) et donner l'ordre GO pour instrumenter la mesure de latence du hot-path event_stream/byte_router.] [OUVERT 2026-10-18 : rien de pose ; suit executif_a_priorites_hamilton] P2: priorite Hamilton/AGC en deux boucles (reflexe LIF ms + allostatique s-h, plancher dur deadline/user_msg non retunable) -- capsule claude.ai pair_57cd434dff098fa1 verifiee 11/12 (bb:pair_57cd434dff098fa1_verification) ; A DEBATTRE, aucun code sans ordre owner ; premiere fibre = MESURER la latence du hot-path event_stream/byte_router et relire la calibration 1800 s (30181 vitals) avant tout tau.
```

### Examen des éléments du « reste = »
1. **Instruction des publieurs dans EventStream** : **FAIT**
   - *Preuve* : Un seul publieur identifié dans `app/forge_hybrid_cortex.py:112` ; `forge_hotpath_probe` a montré 0 événement sur 11 860 s, confirmant qu'EventStream n'est pas le chemin chaud et que le chemin chaud mesuré est le `ByteRouter` (`app/forge_byte_router.py:239`).
2. **Poser la couche réflexe Hamilton sur le ByteRouter (pas sur EventStream)** : **RESTE**
   - *Preuve* : `git grep -i "hamilton" app/forge_byte_router.py` ne renvoie aucun résultat (code de sortie 1). Aucun commit n'a introduit de couche Hamilton réflexe dans `app/forge_byte_router.py`.
3. **Flood sur le canal ByteRouter et calibrer les constantes de temps ($\tau$) sur mesure** : **RESTE**
   - *Preuve* : Seule la mesure passive de base (`forge_hotpath_probe`) a été réalisée ; aucun flood de charge ni calibration des $\tau$ n'a été exécuté sur ByteRouter.
4. **Décision d'architecture à soumettre à l'owner avant tout code** : **RESTE**
   - *Preuve* : Consigne stricte « à débattre, aucun code sans ordre owner ». La décision n'a pas encore été soumise ni tranchée par l'owner.

### Verdict
**NON CLOSABLE** — Couche réflexe sur ByteRouter non posée, flood et calibration des $\tau$ non faits, décision d'architecture non arbitrée.

---

## 3. `p1_racine_donnees_hors_paquet_2026-10-13`

### Valeur entière lue (Tableau Noir)
```text
[PARTIEL 2026-10-19 04:27 : CLIQUET LIVRE -- tests/nr/test_cliquet_racine_donnees_nr.py (f9e4982e1) fige app 245/1248 et tools 420/1325 modules derivant leur racine de DONNEES de __file__ (ne fait que descendre, temoins +/-) ; la migration un a un est ECARTEE par la decision owner du 13/10 (redirection a la source, forge_db_path.DOSSIERS_DE_DONNEES) ; reste = constater l'etape d'acceptation paquet_desinstallation verte sur les livrables (lie a roadmap_installation_complete_noob)] [PARTIEL 2026-10-18 : verif 90291b74a (lot 2) ; reste = Cliquet par organe : migrer les modules résiduels dérivant leur racine de __file__ (1386/1903 au 13/10) vers racine_donnees() et verrouiller par un test de cliquet.] [PARTIEL 2026-10-18 : racine_donnees() EXISTE (app/forge_db_path.py:437, resolue a chaque appel), db_path() s'appuie dessus (l.550), NR tests/nr/test_racine_donnees_nr.py en PURE_TESTS, etape d'acceptation paquet_desinstallation (tools/forge_install_acceptance.py:1004) ; RESTE = le cliquet PAR ORGANE : migrer les modules qui derivent encore leur racine de __file__ (1386/1903 au 13/10, compte actuel a remesurer) et le geler par cliquet] P1: racine des DONNEES hors du dossier du paquet ; mesure 13/10 : 1386 modules sur 1903 derivent leur racine de __file__ (LAFORGE_ROOT lu 6 fois) ; installe par pip, logs/sandbox/RAG s'ecrivent dans site-packages/nokido_agent, pip uninstall les laisse et le reste s'importe encore ; chantier = une seule racine_donnees() (env, clone, sinon dossier utilisateur) + cliquet par organe ; paquet_desinstallation le mesure
```

### Examen des éléments du « reste = »
1. **Redirection dynamique des dossiers de données hors du paquet** : **FAIT**
   - *Preuve* : `app/forge_db_path.py:437` (`racine_donnees()`) et `app/forge_db_path.py:550` (`db_path()`), commit `a59212047`.
2. **Cliquet par organe figeant les dérivations de `__file__`** : **FAIT**
   - *Preuve* : `tests/nr/test_cliquet_racine_donnees_nr.py:1-51`, commit `f9e4982e1` (fige app à 245/1248 et tools à 420/1325).
3. **Migration un à un des modules résiduels** : **ÉCARTÉ / FAIT**
   - *Preuve* : Décision owner du 13/10 écartant la migration fichier par fichier au profit de la redirection globale à la source via `forge_db_path.DOSSIERS_DE_DONNEES` (`a59212047`).
4. **Constater l'étape d'acceptation `paquet_desinstallation` verte sur les livrables** : **RESTE**
   - *Preuve* : L'étape `@etape("paquet_desinstallation", "paquet_install")` existe dans `tools/forge_install_acceptance.py:1004`. Elle valide le cycle de vie du wheel installé (`nokido-composants --desinstaller --purger` + `pip uninstall`) sur les livrables d'une version publiée. La dernière version publiée 0.20.12 (16/10) précède les correctifs `a59212047` et le cliquet `f9e4982e1`. Ce constat doit être dressé sur les livrables de la prochaine publication de version (lié au jalon `roadmap_installation_complete_noob`).

### Verdict
**NON CLOSABLE** — Constat de l'étape d'acceptation `paquet_desinstallation` verte en attente sur les prochains livrables publiés.
