# Oscillation sommeil/réveil : cause prouvée, correctif — 07/11/2026 (CLAUDE_HEADLESS, EXECUTOR)

Les numéros de ligne renvoient à HEAD, avant correctif. Les heures sont en UTC dans les `.jsonl` et en heure locale (UTC+1) dans `laforge-master.log`.

## 1. Qui envoie les POST : c'est prouvé

**C'est l'exécutif Hamilton armé, dans le hub (RESOURCE_MANAGER), qui envoie les ordres de sommeil comme de réveil.** Ni le superviseur ni l'éviction n'y sont pour quelque chose.

Trois preuves concordent :

- **`sandbox/supervisor_ordres.jsonl`** (écrit par `_journalOrdre`, supervisor.ts:2659-2673). Les 19 ordres sur NokidoCaddyTLS du 6/11 21:57Z au 7/11 00:55Z portent tous `agent_declare: RESOURCE_MANAGER` et `secret_presente: supervisor`. Les `trace`/`parent` du journal maître ne désignent personne : sans en-tête traceparent, `_extractTrace` en tire au hasard (un parent différent par POST). C'est ce journal des ordres qui nomme l'appelant.
- **`sandbox/lifecycle_actions.jsonl`**, pile d'appel `forge_resource_manager.py:_regulation_hamilton_tick:6037` :
  - 00:33:58Z `hamilton_arme` : « pression SOI : 33 a ceder … 33 service(s) pour 4920 Mo a rendre (1861 Mo vises) ». Les gestes listent `NokidoCaddyTLS: SUSPENDRE`. Au journal maître, 33 `POST /supervisor/sleep/*` partent en 3 s (01:33:55-01:33:58 locales), à environ 80 ms d'écart : une boucle séquentielle.
  - 00:53:18Z : `forge_docker_keeper` fait un `vidage_ws_qdrant` (EmptyWorkingSet, gain 5,43 Go de cache mappé, RAM 84,1 %).
  - 00:53:29Z `hamilton_arme` : « RAM 58.3 % < seuil 78 % … **33 reprise(s) dans le budget (plafond 73 %)** ». `POST /service/start/NokidoCaddyTLS` part à 00:53:29.710Z.
  - 00:55:40Z `hamilton_arme` : « 35 service(s) pour 3733 Mo a rendre (1766 Mo vises) », Caddy à nouveau SUSPENDRE (POST à 00:55:37Z).
- **Le chemin dans le code** :
  - Sommeil : `_regulation_hamilton_tick` (6012-6013) appelle `_ordre_superviseur(svc, "SUSPENDRE")`, qui envoie `POST {_SUPERVISOR_URL}/sleep/<svc>` (**app/forge_resource_manager.py:5681-5682**).
  - Réveil : `_ordre_superviseur(svc, "REPRENDRE")` envoie `_url_reveil`, c'est-à-dire `POST /service/start/<svc>` (**5683-5684**, 4553-4555).
  - La docstring de 5675 dit « REPRENDRE -> POST /wake » : elle est périmée, le code appelle `/service/start`.

**Défaut 1 : le sommeil part en bloc** (`regulation_hamilton_ram`, app/forge_resource_manager.py:5946-5958). La boucle prend les candidats jusqu'à ce que `rendu >= besoin_mb`. Les 33 DIFFERABLE ne pèsent ensemble que 1,86 Go (environ 56 Mo chacun), pour un besoin de 4,9 Go. La condition d'arrêt n'est donc jamais remplie et ils partent tous. Aucun plancher de gain : Caddy, qui pèse quelques dizaines de Mo et porte l'OAuth publique, part avec eux. Le libellé « Mo vises » désigne en fait le gain cumulé.

**Défaut 2 : le réveil part en bloc sur une chute artificielle** (`gestes_observes` 5346-5360 et `_admettre_reprises` 5273-5304). Le budget est bien projeté, mais :
- il n'y a aucun plafond par tick : 33 × 56 Mo ≈ 7,7 points de 23,7 Go, et 58,3 + 7,7 < 73 ;
- il n'y a aucune durée minimale de sommeil, seulement 120 s de calme ;
- la RAM prise en compte est le plancher sur 60 s (5986). C'est la valeur la plus optimiste, et c'est justement celle que le vidage du cache Qdrant fait tomber pour environ 2 minutes.

### Les pistes écartées, preuve à l'appui

- **supervisor.ts, réveil RAM (802, 2019-2058) : fausse piste pour Caddy.** Un `POST /supervisor/sleep` pose `sommeilVouluJusquaMs = now + 1 h` (2917-2920), et le réveil RAM l'ignore tant que l'échéance n'est pas passée (2047). Or les cycles de Caddy durent de 3 à 20 minutes, aucune ligne `Waking NokidoCaddyTLS` n'apparaît au journal maître, et tous les démarrages sont des `POST /service/start` venus de RESOURCE_MANAGER. Ce réveil borne d'ailleurs déjà les lots (`WAKE_BATCH = 2`) et le gain minimal (`DELESTAGE_GAIN_MIN_KO = 64 Mo`). Il est conforme, il n'est pas la cause.
- **Ligne 4511 (`_sleep_service_verdict`, éviction de `request_resources`) : pas la source des rafales.** Ses entrées d'audit sur la fenêtre sont des `evict_skipped` (« pas d'urgence », 00:53:09Z). Les quatre audits qui citent Caddy viennent tous de `_regulation_hamilton_tick`.
- **Ligne 4758 (`_wake_service`, `/wake`) : n'intervient pas.** Elle ne sert qu'à `_restart_pillar` (piliers RAG), aucune trace.
- **Lignes 5675-5682 (`_ordre_superviseur`) : c'est bien l'émetteur.** Mais celui qui décide, c'est Hamilton. La régulation disque passe par la même fonction ; ses audits `regulation_disque` sont absents de la fenêtre.

## 2. Règle owner du 31/10 : ce qui la viole aujourd'hui

Rappel de la règle : réveil par la demande, par utilité, avec un budget projeté, jamais en bloc ni sur un seul seuil.

- **Réveil en bloc.** `_admettre_reprises` n'a pas de plafond par appel, d'où « 33 reprise(s) » en un seul tick. Même défaut dans `_reveiller_les_evinces` et `_honorer_demandes_circadiennes`, qui utilisent la même admission. *Corrigé.*
- **Réveil sur un seuil seul.** La seule condition est le plancher 60 s passé sous le plafond. Une chute de RAM due au vidage d'un cache mappé (`vidage_ws_qdrant`) suffit, alors qu'aucune demande n'a changé. *Atténué* par le lot, la durée minimale de sommeil et la RAM relue à chaque tick.
- **Demande inconnue admise.** `_demande_du_service` ne connaît une demande que pour les exécuteurs dédiés ; tout le reste vaut `None`, qui est admis (doctrine UNKNOWN != NO). *Non changé* : exiger `True` laisserait endormis pour toujours tous les services qui n'ont pas d'émetteur de demande. Voir « Ce qui reste ».
- **Sommeil sans gain.** Des organes de 20 à 60 Mo sont endormis par dizaines, ce qui ne libère presque rien et coupe des clients. *Corrigé.*

## 3. Correctif minimal (Python d'abord, aucun supervisor.ts)

NR rouge d'abord, par le chemin réel : `tests/nr/test_oscillation_sommeil_reveil_nr.py`. Le test appelle `_regulation_hamilton_tick`, qui enchaîne `regulation_hamilton_ram`, `gestes_observes`, `_admettre_reprises` puis `_ordre_superviseur` (capturé). Le plan est fabriqué par le vrai `ordre_delestage` sur la fenêtre du 7/11 : 30 petits services, Caddy et 3 gros. **5 échecs avant correctif, 5 succès après.**

| | Changement | Où |
|---|---|---|
| (a) | **Plancher de gain** `_HAMILTON_GAIN_MIN_MB = 64` (env `NOKIDO_HAMILTON_GAIN_MIN_MB`). Un service dont le gain **mesuré** est inférieur n'est pas endormi, sauf au palier CRITIQUE. La mesure est celle déjà en place (`rss_mb` du plan, mémoire privée de `_memoire_privee_mb`), avec la même grandeur que `DELESTAGE_GAIN_MIN_KO` du superviseur. Un gain illisible reste ordonné en dernier, comme avant. Le motif annonce « N epargne(s) a gain negligeable ». | `regulation_hamilton_ram` |
| (a) | **NokidoCaddyTLS passe `neverSleep = true`** dans le registre existant (`proxy_deno/core/services.toml`), comme les autres portes d'entrée (NokidoWebHub, :7777). `classe_hamilton` la classe alors VITAL : elle n'est plus jamais candidate. Pas de second registre. | services.toml |
| (b) | **Réveil par petits lots** : au plus `_HAMILTON_REPRISE_LOT = 2` admis par appel (env `NOKIDO_HAMILTON_REPRISE_LOT`), c'est-à-dire par tick de 60 s avec la RAM relue à chaque fois. Même valeur que `WAKE_BATCH` du superviseur. S'applique aussi à `_reveiller_les_evinces` et aux demandes circadiennes, qui partagent l'admission. | `_admettre_reprises` |
| (b) | **Durée minimale de sommeil** `_HAMILTON_SOMMEIL_MIN_S = 600` (env `NOKIDO_HAMILTON_SOMMEIL_MIN_S`) : aucune reprise avant 10 minutes depuis `pause_ts`. Le paramètre `sommeil_min_s` de `gestes_observes` vaut 0 par défaut, pour que la primitive pure et les tests d'hystérésis restent inchangés ; l'exécutif armé passe la constante. | `gestes_observes`, `regulation_hamilton_ram` |
| (c) | **Journal par service.** `regulation_hamilton_ram` rend `journal` : service, geste, `gain_mb`, motif (seuil, lot, demande PROUVEE/INCONNUE, RAM, plafond). Le tick écrit une ligne `logging.info("[hamilton] sommeil|reveil …")` et un audit **`hamilton_sommeil` / `hamilton_reveil`** (`target`, `gain_mb`) dans `sandbox/lifecycle_actions.jsonl`. Avant, l'audit `hamilton_arme` agrégé était tronqué à 300 caractères. | `_regulation_hamilton_tick` |

Ce qu'on peut attendre sur la fenêtre du 7/11, selon le scénario du NR :
- au sommeil, seuls les 3 services de 64 Mo ou plus partent, au lieu de 34, et Caddy jamais ;
- à la chute à 58,3 %, 2 reprises par minute au plus, au lieu de 33. Le cache Qdrant se remplit en environ 2 minutes, donc 4 à 6 réveils au plus avant que la pression revienne, et seulement pour des services endormis depuis plus de 10 minutes.

Retouches annexes, signalées parce qu'elles touchent des NR existants :
- `test_hamilton_arme_nr` : la reprise est maintenant attendue après la durée minimale de sommeil.
- `test_hamilton_reprise_utile_dans_le_budget_nr` : 4 reprises d'un coup deviennent `min(4, lot)`.
- `test_regulation_replay_nr` et `tools/forge_regulation_replay.py` :
  - nouveaux seuils injectables `gain_min_mb`, `reprise_lot`, `sommeil_min_s`, pour rejouer la politique d'alors ;
  - le rejeu ne lit plus le tasks.db vivant via `_travail_en_vol`. Défaut constaté : 3 tests du rejeu échouaient dès qu'une tâche était en cours, l'exécuteur générique étant alors le seul endormi.

**Tests lancés (fichiers NR concernés seulement) : 90 + 70 réussis.** Fichiers : oscillation, hamilton_*, journal_regulation_par_tick, regulation_graduee, regulation_pression_disque, regulation_replay, reveil_evinces, delegation_veto, regulation_reveille, circadien, bail_priorite, delestage_ram_par_cout, executif_hamilton_priorites, runner_ci, soif, sommeil_neversleep, travail_differe.

Interdits respectés : seuils 82/88 inchangés (le 78 Python aussi), aucun service redémarré, ni tasks ni jobs touchés, `agent_identities.json`, `forge_docker_keeper.py` et `%NOKIDO_DATA%\embeddings.db` non touchés, pas de push.

## 4. Ce qui devient actif sans full stack

- **Python (`forge_resource_manager.py`)** : actif au prochain chargement du module par le hub, une fois le commit intégré à l'arbre principal. Il suffit de l'ordre `restart-hub` (geste owner, hub seul), pas d'un full stack.
- **`neverSleep` de Caddy** :
  - côté Hamilton, actif dès l'intégration : `_services_du_toml()` relit services.toml à chaque tick ;
  - côté superviseur (rafale > 88 %), pris en compte seulement au rechargement du TOML, donc au full stack. Ce côté n'est pas la cause : Caddy, sous 64 Mo, est déjà écarté de la rafale hors CRITIQUE.
- **supervisor.ts : non modifié.** Aucun geste full stack n'est requis par ce correctif.

## 5. Mesure avant / après : compter les bascules par heure

Source : `sandbox/supervisor_ordres.jsonl`, lignes `agent_declare == "RESOURCE_MANAGER"` dont `chemin` contient `/supervisor/sleep/` ou `/supervisor/service/start/`, groupées par `ts[:13]` (heure UTC), au total et pour NokidoCaddyTLS seul.

**Avant (6/11 et 7/11, 14 heures couvertes)** :
- **1 684 bascules RM**, soit **120/h en moyenne** et **259/h au pire** (6/11 20h UTC) ;
- **NokidoCaddyTLS : 61 bascules en 11 heures** (environ 5,5/h, soit près de 3 cycles sommeil/réveil par heure).

**Après** : même requête sur une fenêtre équivalente, au moins 24 h après `restart-hub`. On attend 0 pour Caddy et au plus 2 `service/start` par minute venant de Hamilton.

Contre-mesure plus fine par service, via le nouvel audit : compter `action in ("hamilton_sommeil", "hamilton_reveil")` par heure et par `extra.target` dans `sandbox/lifecycle_actions.jsonl`. Un même service qui alterne sommeil et réveil en moins de 15 minutes signale une oscillation résiduelle.

Recoupement côté superviseur : la ligne « RAM lue … N dormeur(s) » de `laforge-master.log` (une toutes les 10 minutes) ne devrait plus sauter de 5 à 36 dormeurs entre deux relevés.

## 6. Ce qui reste

1. **Demande des services non exécuteurs.** `_demande_du_service` rend `None` pour tous les services hors exécuteurs dédiés ; le réveil reste donc « utile par défaut » (UNKNOWN != NO). Il faudra un émetteur de demande, par exemple les intentions fraîches par port déjà lues par supervisor.ts (`_intentionFraiche`), avant de pouvoir exiger une demande prouvée.
2. **RAM retenue pour le réveil.** Le réveil décide sur le plancher 60 s, la valeur la plus optimiste. Il serait plus juste qu'il décide sur un maximum de fenêtre (pessimiste) ou qu'il s'abstienne pendant environ 3 minutes après un `vidage_ws_qdrant`. Je ne l'ai pas fait : `forge_docker_keeper.py` est interdit, et cela demande un second capteur de fenêtre. À mesurer avant.
3. **Sommeil sans plafond par tick.** Si beaucoup de gros services pèsent tous 64 Mo ou plus, ils peuvent encore partir ensemble. Le superviseur, lui, borne à `DELESTAGE_MAX_PAR_CYCLE = 3`. À aligner si la mesure d'après le montre.
4. **Docstring périmée** de `_ordre_superviseur` (« REPRENDRE -> POST /wake ») : le code appelle `/service/start`. Non corrigée, pour garder un diff minimal.
5. **Fichiers hors périmètre.** `sandbox/enquetes/` (non suivi) est apparu dans le worktree pendant les tests ; il ne fait pas partie de ce livrable et l'exécuteur ne doit pas le committer. Même chose pour `.claude_headless_mcp.json`.

{"intent":"OK_DONE","pointer_ref":"rendu_oscillation_sommeil_20261107.md"}
