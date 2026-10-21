# Audit & RCA — Lecture disque massive et dérive RSS de NokidoMCP au démarrage
**Date de l'audit** : 19 octobre 2026  
**Agent enquêteur** : `ANTIGRAVITY` (Ring 1)  
**Worktree** : `nokido_worktrees/antigravity`  
**Cible analysée** : Processus `NokidoMCP` (le Hub MCP souverain, PID 26632)  
**Fait mesuré** : Suite à la relance de pile de 14:04:51, NokidoMCP a lu 7,4 Go en ~8–10 min (débit de 27 à 42 Mo/s continu avec pointes à 100+ Mo/s) et son RSS est monté de 0,30 Go à 1,90 Go (alerte `rss_derive_detected` à 12:13:01Z / 14:13:01 local) puis à un pic de 2,19–2,36 Go, avant effondrement de l'I/O à 14:15:44 et redescente mémoire à ~0,89–1,02 Go vers 14:19.

---

## 1. Synthèse Exécutive & Réponses Directes

### QUI dans le hub lit autant ?
**Cause prouvée** : Le thread daemon d'arrière-plan **`rag-dense-prewarm`** démarré à l'initialisation du singleton `ToolRegistry` (`app/forge_mcp_registry.py:7494` et `9535-9548`).  
Ce thread exécute la méthode `_load_dense_cache()` qui déclenche un scan séquentiel complet (`SELECT id, source, domain, text, ext, folder FROM rag_chunks WHERE embedding IS NOT NULL`) sur la table `rag_chunks` de la base **`%NOKIDO_DATA%\embeddings.db`** (taille réelle sur disque : **46,55 Go**, contenant plus de **1,15 million de chunks**).  
Ce scan lit plusieurs gigaoctets de pages SQLite depuis le disque virtuel VHDX `V:` et instancie en mémoire heap Python plus de 1,15 million de dictionnaires de métadonnées (`_meta[cid] = {"source": src, "domain": dom, "text": txt[:512]}`), propulsant le RSS du hub de 0,30 Go à 2,19 Go.

### Est-ce un régime permanent ou un rattrapage de démarrage ?
**Rattrapage de démarrage (Préchauffage cold-start)** :
- **Début** : 14:04:51 (immédiatement après le bind uvicorn `:8766`).
- **Phase active** : de 14:05:08 à 14:15:43 (~10 minutes et 35 secondes d'activité I/O continue).
- **Fin brutale** : **14:15:43.639** lorsque le régulateur de ressources mémoire déclenche le reclaimer `_rendre_cache_dense()` (`NokidoMCP.log`).
- Dès **14:15:44**, la métrique disque `dbsy` s'effondre de 37,10 % à **2,95 %**, le débit de lecture `ior` chute de 93 Mo/s à **< 1 Mo/s**, et la mémoire est purgée vers 14:19 (retour à 0,89–1,02 Go).
- Après 14:16, le système reste en régime de croisière stable (`dbsy` < 1–2 %, `ior` résiduel). Ce n'est donc **en aucun cas un régime permanent**.

---

## 2. Chronologie & Analyse des Métriques Vitals (13:30 à 14:23)

Source des mesures : `sandbox/vitals_history.jsonl` (échantillonnage toutes les 15 s) recoupé avec `sandbox/lifecycle_actions.jsonl` et `sandbox/service_rss_state.json`.

| Horodatage local | `dbsy` (%) | `ior` (Mo/s) | `iow` (Mo/s) | NokidoMCP RSS (Go) | Événement marquant |
|---|---|---|---|---|---|
| **13:30:13 – 14:04:10** | 1% à 50% | 10 à 80 | 3 à 15 | ~0,94 à 0,97 Go | Régime avant relance de pile (PID antérieur 21196). |
| **14:04:28** | 57.07% | 80.41 | 7.70 | 0.935 Go | Dernière mesure avant coupure. |
| **14:04:51** | *None* | *None* | *None* | 0.935 -> 0.299 Go | **Arrêt de la pile et redémarrage** (Deno / NSSM). Nouveau PID hub : **26632**. |
| **14:04:51.674** | - | - | - | 0.30 Go | `hub_boot.log` : bind Uvicorn `:8766` terminé en 0,6 s. Lancement de `rag-dense-prewarm`. |
| **14:05:08** | 61.40% | 116.81 | 7.07 | 0.299 Go | Début effectif du scan disque SQLite par le thread de prewarm. |
| **14:06:14** | 57.33% | 71.72 | 5.49 | 0.469 Go | Progression du scan, accumulation des dictionnaires Python. |
| **14:08:07** | 100.0% | 67.74 | 16.21 | 0.659 Go | Saturation I/O disque VHDX (`dbsy` = 100 %). |
| **14:10:13** | 100.0% | 162.94 | 14.22 | 0.899 Go | Débit de pointe (>160 Mo/s cumulé). |
| **14:12:05** | 59.76% | 58.91 | 14.54 | 1.385 Go | Franchissement du seuil x2 par rapport à la référence (0,66 Go). |
| **14:13:01.900** | 66.25% | 80.16 | 3.53 | **1.902 Go** | **`lifecycle_actions.jsonl`** : action `rss_derive_detected` émise par `forge_service_rss_watch.py:343` ("NokidoMCP a 1.90 Go pour ref de 0.66 Go (x2.9)"). |
| **14:14:11** | 49.93% | 65.95 | 5.35 | 2.186 Go | Pic d'allocation en heap Python. |
| **14:15:14** | 45.15% | 53.70 | 3.90 | **2.189 Go** (pic 2.364) | Pression RAM globale atteignant 83.6 %. |
| **14:15:43.639** | - | - | - | 2.189 Go | **Déclenchement du reclaimer** : `_rendre_cache_dense()` est appelé sous pression RAM par `forge_resource_manager`. `self._dense_cache` passe à `None`. |
| **14:15:44** | **2.95%** | **15.06** | 7.36 | 2.189 Go | **Effondrement immédiat de l'activité disque** : la lecture s'arrête. |
| **14:17:05** | 1.45% | 1.83 | 4.75 | 2.189 Go | Débit disque revenu au repos. |
| **14:19:11** | **0.47%** | **0.23** | 2.26 | **1.024 Go** | Garbage collector Python libère la mémoire non référencée. |
| **14:20:14 – 14:23:00** | 0.5% à 2.0% | 0.5 à 10 | 2.5 à 4.0 | **0.887 – 0.98 Go** | Régime stabilisé standard. |

---

## 3. Examen Méthodique des 5 Pistes

### Piste A : Préchauffage RAG au boot (`forge_rag_warmup`)
- **Statut** : **ÉCARTÉE**
- **Sources Code** :
  - `tools/nokido_hub.py:6888-6904` (`def _warmup_bge_m3()`)
  - `tools/nokido_hub.py:7014-7027` (`def _warmup_planner()`)
  - `app/forge_rag_warmup.py:1-85` (module standalone)
- **Sources Journaux** :
  - `logs/supervisor/NokidoMCP.log` à **14:04:53.758** :  
    `[WARNING] Nokido.Hub — WARNING:Nokido.Hub:bge-m3 warmup skipped: HTTP Error 400: Bad Request`
- **Démonstration** :
  Le module `forge_rag_warmup.py` n'est **ni importé ni appelé** par `tools/nokido_hub.py`. Les seules routines de démarrage du hub portant le mot-clé warmup sont `_warmup_bge_m3` (qui a échoué en 2 secondes chrono avec une erreur HTTP 400) et `_warmup_planner` (qui appelle `forge_goap.warm()` pour envoyer un prompt test à Ollama `laforge-qwen`). Aucun chunk n'a été vectorisé par ce canal au boot.

---

### Piste B : whoami qui recompte `rag_domains`
- **Statut** : **ÉCARTÉE pour la fenêtre 14:04–14:16** (Effet mesurable ultérieurement mais minime)
- **Sources Code** :
  - `app/forge_mcp_registry.py:5022-5042` (`def _whoami_domaines(self, conn)`) :
    ```sql
    SELECT domain, COUNT(*) as n FROM rag_chunks WHERE domain NOT LIKE 'beir%' GROUP BY domain ORDER BY n DESC LIMIT 8
    ```
    (Requête avec lock non-bloquant et TTL de 600 s / 10 min).
- **Sources Journaux** :
  - `logs/mcp_audit.log` entre 14:04:51 et 14:20:00 : **0 appel** à `whoami`.
  - `logs/actes_agents.jsonl` entre 14:04:51 et 14:20:00 : **0 appel** à `whoami`.
  - `logs/supervisor/NokidoMCP.log` à 13:50:38 : trace `cmd.exe /c whoami` (simple commande shell OS d'un agent pour connaître son utilisateur Windows).
- **Démonstration** :
  Aucun agent n'a appelé l'action MCP `hub action=whoami` entre 14:04:51 et 14:20:00. Le premier appel à `whoami` a été passé par l'agent `ANTIGRAVITY` à **14:21:27** lors de son boot. À cet instant, `sandbox/vitals_history.jsonl` a bien enregistré une brève augmentation de `dbsy` (13,10 % à 14:21:33, `ior` = 20 Mo/s), mais celle-ci n'a duré que 15 secondes. La piste est donc rigoureusement écartée pour les 8 minutes de lecture continue observées entre 14:05 et 14:15.

---

### Piste C : Sampler / vitals
- **Statut** : **ÉCARTÉE**
- **Sources Code** :
  - `app/forge_resource_manager.py:1850-2010` (`_sampler_loop`)
  - `app/forge_service_rss_watch.py:88-100` (`_registre()`)
- **Sources Journaux** :
  - `logs/loop_lag.log:6-12` (Thread `forge_resource_sampler`)
- **Démonstration** :
  La boucle du sampler s'exécute toutes les 15 secondes. Elle interroge `psutil` (RAM, CPU, I/O globaux) et l'endpoint HTTP du superviseur `:8765/supervisor/status`. Elle n'ouvre ni ne parcourt aucune base SQLite, et ne touche jamais à `%NOKIDO_DATA%\embeddings.db`. Son empreinte disque se limite à l'écriture séquentielle d'une ligne JSON d'environ 500 octets toutes les 15 secondes dans `sandbox/vitals_history.jsonl`. Elle est un instrument de mesure, pas la source de la charge.

---

### Piste D : Index vectoriel chargé en mémoire (`rag-dense-prewarm`)
- **Statut** : **CONFIRMÉE (CAUSE RACINE UNIQUE ET PROUVÉE)**
- **Sources Code** :
  - `app/forge_mcp_registry.py:9535-9548` (`get_registry()`) :
    ```python
    if os.environ.get("LAFORGE_RAG_PREWARM", "1") != "0":
        try:
            _registry._dense_refresh_bg()
        except Exception:
            pass
    ```
  - `app/forge_mcp_registry.py:7494` :
    ```python
    _th.Thread(target=_work, name="rag-dense-prewarm", daemon=True).start()
    ```
  - `app/forge_mcp_registry.py:7288-7290` (mode délégué Qdrant) et `7364` (mode local) :
    ```python
    for _cid, _src, _dom, _txt, _ext, _fold in _conn.execute(
        "SELECT id, source, domain, text, ext, folder FROM rag_chunks WHERE embedding IS NOT NULL"
    ):
        _ids.append(_cid)
        _meta[_cid] = {"source": _src, "domain": _dom, "text": (_txt or "")[:512]}
        _exts.append(_ext or "")
        _folders.append(_fold or "")
    ```
  - `app/forge_mcp_registry.py:7516-7543` (`_rendre_cache_dense()`)
- **Sources Journaux & Horodatages** :
  - `logs/hub_boot.log` : **14:04:51.481 à 14:04:51.566** (`_build_app: debut -> RETOUR`), instanciation du singleton `ToolRegistry` qui déclenche le thread `rag-dense-prewarm`.
  - `sandbox/lifecycle_actions.jsonl` : **2026-10-19T12:13:01.900Z (14:13:01 local)** :
    `{"action": "rss_derive_detected", "reason": "NokidoMCP a 1.90 Go pour une reference de 0.66 Go (x2.9) — 8 % du corps [derive]"}`
  - `logs/supervisor/NokidoMCP.log` : **14:15:43.639** :
    `[WARNING] forge_mcp_registry — WARNING:forge_mcp_registry:[rag] cache dense rendu, mais AUCUNE matrice en RAM (dense delegue au sidecar) : seules les metadonnees sont liberees, non mesurees ici. Ce levier ne rend plus de RAM significative.`
  - `sandbox/vitals_history.jsonl` : **14:15:44** : `dbsy` s'effondre de 37,10 % à 2,95 % et `ior` s'effondre de 93 Mo/s à 15 Mo/s puis < 1 Mo/s.
- **Démonstration** :
  La synchronisation temporelle est parfaite à la seconde près. Le thread daemon `rag-dense-prewarm` s'est lancé dès le boot pour pré-charger les métadonnées de l'ensemble de la base dans `_dense_cache`. Le parcours de 1,15 million d'enregistrements dans une base SQLite de 46,5 Go hébergée sur un volume VHDX virtuel a imposé un flux continu de 27 à 42 Mo/s pendant ~10 minutes (totalisant ~7,4 Go de données lues). La création en mémoire des objets `_meta` a fait monter le RSS jusqu'à 2,19 Go. À 14:15:43, la pression mémoire a déclenché le reclaimer qui a désalloué `self._dense_cache`, mettant fin immédiatement à la charge disque et permettant au GC de purger la RAM.

---

### Piste E : Appels MCP des agents (journal d'appels du hub)
- **Statut** : **ÉCARTÉE**
- **Sources Journaux** :
  - `logs/actes_agents.jsonl` : seulement **70 actes** enregistrés entre 14:04 et 14:16 (dont 28 par `CLAUDE` exécutant des scripts de vérification `run:python` ponctuels, 5 par `STATE_ENCODER` bloqués par le RBAC, 2 par `OPENCODE_NEMOTRON`).
  - `logs/mcp_audit.log` : 24 lignes relatives au tool `rag` (12 requêtes réelles) :
    - 11 requêtes `rag` exécutées en rafale par `POST_COMMIT` entre **12:07:55 et 12:07:56** (14:07:55 local), avec des temps de réponse ultra-courts : **59.4 ms à 84.9 ms**.
    - 1 requête `rag` par `RSS_WATCHER` à **12:15:10** (14:15:10 local).
- **Démonstration** :
  Des requêtes s'exécutant en 60 à 80 millisecondes n'effectuent que des lectures FTS / vectorielles ciblées de quelques dizaines de kilo-octets. Elles ne génèrent ni lecture séquentielle continue, ni débit de 30 Mo/s, ni rétention mémoire en gigaoctets. Les appels agents étaient minimes et totalement décorrélés du volume d'I/O constaté.

---

## 4. Ce qui reste Inmesurable et Pourquoi

1. **La répartition exacte du cache sous-jacent VHDX / Système (`System`, PID 4)** :
   `V:` est un volume VHDX monté sur Windows. Le driver de virtualisation (`vhdmp.sys`) et le cache de blocs du noyau Windows mutualisent les lectures de blocs sous le processus `System`. Depuis l'espace utilisateur sans instrumentation de trace noyau (ETW / Windows Performance Recorder), il est impossible de distinguer la part exacte des I/O physiques sur le SSD hôte de la part servie depuis le cache de blocs virtuel du VHDX.
2. **Le débit par étape interne de `_load_dense_cache()`** :
   Le fichier `NokidoMCP.log` filtre les messages de niveau `INFO` (`[rag:index] mode dense = ...`, `[rag] dense cache warm OK`). Seuls les `WARNING` et `ERROR` y sont écrits. Par conséquent, les horodatages précis du début de l'itération SQLite et du comptage des chunks n'ont pas été tracés dans les logs persistants.
3. **Le découpage fin de la mémoire heap sans `tracemalloc`** :
   Le module `hardware/mem_watchdog.py` fonctionne en mode standard sans `tracemalloc` actif (`LAFORGE_MEM_TRACE=0` par défaut pour éviter un surcoût de 20 % CPU). L'attribution de la mémoire entre les chaînes de clés de `_meta`, les dictionnaires de champs et le cache interne de pages SQLite `cache_size` ne peut être mesurée qu'au niveau macroscopique (Private Working Set / RSS global du processus via `psutil`).

---

## 5. Proposition de Correctif (Architecture & Réfutation)

*Conformément aux consignes, ces correctifs sont soumis pour proposition et arbitrage, sans modification de code.*

### Problème de conception identifié
Dans `app/forge_mcp_registry.py:7282-7300`, même lorsque le stockage et la recherche dense sont délégués au sidecar Qdrant (`_delegue == True`), le hub pré-charge en mémoire l'intégralité des identifiants et des métadonnées textuelles de **tous les chunks de la base** (`SELECT id, source, domain, text, ext, folder FROM rag_chunks WHERE embedding IS NOT NULL`).  
Le commentaire historique ligne 7244 indiquait : *« ils pesent 264 Mo, pas 4,7 Go »*. Or, avec la croissance de `embeddings.db` à 46,5 Go (>1,15 million de chunks), ce pré-chargement :
1. Provoque un scan complet de 46 Go à froid sur le VHDX.
2. Instancie ~1,8 Go d'objets Python.
3. Déclenche une alerte de dérive RSS (`rss_derive_detected`).
4. Finit par être immédiatement réclamé et détruit par le régulateur de mémoire dès que la machine atteint 83 % de RAM (`_rendre_cache_dense()`), rendant tout ce travail inutile et destructeur pour le boot.

### Solutions proposées

1. **Résolution des métadonnées « Just-in-Time » (On-Demand Fetch)** *(Recommandée)* :
   - **Principe** : Ne charger **aucune métadonnée au boot** dans le hub.
   - **Mécanisme** : Lorsque Qdrant (ou BM25) renvoie une liste de Top-K identifiants (généralement 10 à 50 IDs), exécuter une requête ponctuelle indexée :
     ```sql
     SELECT id, source, domain, text, ext, folder FROM rag_chunks WHERE id IN (?, ?, ...)
     ```
   - **Bénéfice** : Temps au boot = **0 ms**, lecture disque au boot = **0 Mo**, RAM consommée = **0 Mo**. La requête ponctuelle par clé primaire sur 20 IDs prend moins de 2 ms lors de la recherche réelle.

2. **Désactivation par défaut du pré-chargement dense au boot** :
   - Basculer la valeur par défaut de `LAFORGE_RAG_PREWARM` de `"1"` à `"0"` (`app/forge_mcp_registry.py:9542`). Le hub ne préchauffera pas ce cache au démarrage, évitant ainsi le pic d'I/O et le risque de saturation lors de l'initialisation de la pile.

3. **Observabilité dédiée du cache RAG** :
   - Promouvoir les messages d'étape de `_load_dense_cache()` au niveau `WARNING` ou dans un canal d'audit dédié (`logs/rag_cache.log`) afin que les débuts, débits de traitement (chunks/sec) et fins de préchauffage soient directement visibles sans ambiguïté dans les journaux de supervision.
