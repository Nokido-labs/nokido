# Enquête : Réveil après délestage RAM dans le superviseur Deno

Date : 2026-10-30
Auteur : ANTIGRAVITY (agt_antigravity)
Fichier examiné : `proxy_deno/core/supervisor.ts`
Document de cadrage : `docs/gabarits/CONSIGNE_DELEGATION_ENQUETE.md`

---

## 1. Question fermée

> **Quand le superviseur Deno (`proxy_deno/core/supervisor.ts`) déleste un service par pression RAM (seuils `RAM_SLEEP_PCT` 88 / critique 94, délestage par coût, `_tuerArbre` pour `NokidoTaskExecutor*`), ce service est-il ensuite RÉVEILLÉ quand la RAM repasse sous `RAM_WAKE_PCT` (82) ? Sinon, quelle condition l'exclut du réveil ?**

---

## 2. Tableau des faits et preuves

| Affirmation | Preuve (`proxy_deno/core/supervisor.ts` ou `services.toml`) | État |
|---|---|---|
| Le délestage RAM sélectionne les services `running` non essentiels, sans `neverSleep`, ayant plus de 5 min d'uptime, et les trie par RSS décroissant. | `proxy_deno/core/supervisor.ts:1959-1966` : `const candidats = [...states.values()].filter((state) => !state.def.essential && !state.def.neverSleep && state.status === "running" && state.proc && Date.now() - state.lastStartMs > 5 * 60_000).map((state) => ({ state, ko: state.pid ? (_rssKoParPid.get(state.pid) ?? null) : null, })).sort((a, b) => (b.ko ?? -1) - (a.ko ?? -1));` | PROUVÉ |
| Lors du délestage, le service est arrêté (`_tuerArbre` ou `kill("SIGTERM")`), son RSS au moment du sommeil est mémorisé, et son statut est positionné à `state.status = "sleeping"`. | `proxy_deno/core/supervisor.ts:1993-2001` : `if (ko !== null) _rssKoAuSommeil.set(state.def.name, ko); if (state.def.name.startsWith("NokidoTaskExecutor") && state.pid) { const arbre = await _tuerArbre(state.pid); if (!arbre) state.proc?.kill("SIGTERM"); ... } else { state.proc?.kill("SIGTERM"); } state.status = "sleeping";` | PROUVÉ |
| Le délestage ne positionne AUCUN `sommeilVouluJusquaMs` (ce champ n'est positionné que par l'API explicite `POST /supervisor/sleep`). | `proxy_deno/core/supervisor.ts:1959-2005` (aucune mention de `sommeilVouluJusquaMs`) vs `proxy_deno/core/supervisor.ts:2914-2917` : `state.status = "sleeping"; ... state.sommeilVouluJusquaMs = Date.now() + ttlMs;` | PROUVÉ |
| Quand la RAM passe sous `RAM_WAKE_PCT` (82%), le superviseur filtre les services dont le statut est `"sleeping"`, les trie par coût croissant, et applique un filtre de réveil strict. | `proxy_deno/core/supervisor.ts:2016-2025` : `else if (memPct < RAM_WAKE_PCT) { ... const dormeurs = [...states.values()].filter((s) => s.status === "sleeping").sort((a, b) => (_rssKoAuSommeil.get(a.def.name) ?? RSS_INCONNU_KO) - (_rssKoAuSommeil.get(b.def.name) ?? RSS_INCONNU_KO));` | PROUVÉ |
| Les services délestés sont théoriquement éligibles au réveil dès que `memPct < RAM_WAKE_PCT` (82%), sous réserve de ne pas dépasser le plafond budgétaire `RAM_CIBLE_PCT` (84%) et le lot `WAKE_BATCH` (2 par cycle). | `proxy_deno/core/supervisor.ts:2029-2035` : `if (woken >= WAKE_BATCH) break; ... const tropCher = totalKo ? pct + (cout / totalKo) * 100 > RAM_CIBLE_PCT : woken >= 1; if (tropCher) break;` | PROUVÉ |
| Le filtre d'exclusion du réveil RAM écarte uniquement quatre conditions : `state.def.essential`, `state.def.llmPool`, `state.def.disabled`, et `(state.sommeilVouluJusquaMs ?? 0) > Date.now()`. | `proxy_deno/core/supervisor.ts:2042-2046` : `if (!state.def.essential && !state.def.llmPool && !state.def.disabled && !((state.sommeilVouluJusquaMs ?? 0) > Date.now()) && state.status === "sleeping")` | PROUVÉ |
| Lors du réveil, le statut passe à `"stopped"` puis appelle `startService(state)`. | `proxy_deno/core/supervisor.ts:2049-2051` : `state.status = "stopped"; state.backoffIdx = 0; startService(state); woken++;` | PROUVÉ |
| Le gestionnaire de processus asynchrone `proc.status.then(...)` écoute la terminaison du processus tué lors du délestage et exécute `scheduleRestart(state)` si `state.status !== "sleeping" && state.status !== "stopped"`. Or, `state.status` ayant été mis à `"sleeping"`, cette branche de crash/restart est bien court-circuitée. | `proxy_deno/core/supervisor.ts:1619-1621` : `if (state.status !== "sleeping" && state.status !== "stopped") { scheduleRestart(state); }` | PROUVÉ |
| La sonde de vitalité périodique `resourceLoop()` ne redémarre un PID disparu que si `st.status === "running"`. Comme le statut a été passé à `"sleeping"`, la vitalité n'interfère pas. | `proxy_deno/core/supervisor.ts:1930-1941` : `if (st.status === "running" && st.pid && !alive.has(st.pid)) { ... scheduleRestart(st); }` | PROUVÉ |
| Dans `startService()`, un service non-essentiel interroge le gate de ressource du hub (`/api/resource/should_spawn?name=...`) avant d'être lancé. Si le gate répond `should_spawn === false`, le service est différé (`scheduleDefer`) sans être démarré. | `proxy_deno/core/supervisor.ts:1389-1440` : `if (!def.essential) { ... const gj = await gr.json(); if (gj.should_spawn === false) { log(\`\${def.name}: resource gate refused (\${gj.reason ?? "throttled"}) — defer (no crash count)\`); scheduleDefer(state); return; } }` | PROUVÉ |
| Dans `startService()`, si le hub répond 401 ou 403 sur le gate de ressource (authentification / ring non configuré pour SUPERVISOR), le service est différé sans être démarré (`AUTHZ_DENIED - defer`). | `proxy_deno/core/supervisor.ts:1416-1424` : `if (gr.status === 401 || gr.status === 403) { log(\`\${def.name}: resource gate AUTHZ_DENIED (HTTP \${gr.status}) - defer...\`); scheduleDefer(state); return; }` | PROUVÉ |
| Les exécuteurs `NokidoTaskExecutor*` (ex. `NokidoTaskExecutorAntigravity`, `NokidoTaskExecutorMistral`, `NokidoTaskExecutorClaude`) sont déclarés avec `essential = false`, `disabled = false`, et sans `llmPool`. | `proxy_deno/core/services.toml:1728, 1752, 1777, 1796, 1817` (`essential = false`, `disabled = false`). | PROUVÉ |
| Les états runtime des processus et l'historique direct des journaux système non servis par le superviseur sont inaccessibles dans ce bac à sable. | Contrainte bac à sable / commandes shell refusées. | ILLISIBLE |

---

## 3. Analyse de la Question Fermée

### Est-il réveillé quand la RAM repasse sous `RAM_WAKE_PCT` (82%) ?
**OUI en théorie algorithmique**, le bloc `else if (memPct < RAM_WAKE_PCT)` (`proxy_deno/core/supervisor.ts:2016-2056`) sélectionne les services en statut `"sleeping"`, vérifie qu'ils ne sont pas `essential`, ni `llmPool`, ni `disabled`, et qu'ils n'ont pas de sommeil voulu actif (`sommeilVouluJusquaMs`).
Les exécuteurs délestés (`NokidoTaskExecutor*`) remplissent **toutes** ces conditions de réveil côté superviseur.

### Pourquoi n'ont-ils pas été réveillés lors de l'incident mesuré du 30/10 ~21h ?
L'enquête formelle dans le code met en évidence **deux mécanismes d'exclusion/blocage bien distincts** :

1. **Le verrouillage par la RAM observée (Condition d'exclusion principale dans `supervisor.ts`)** :
   - Le réveil **n'est même pas tenté** tant que `memPct` ne repasse pas strictement sous `RAM_WAKE_PCT` (82%) (`supervisor.ts:2016`). Si la RAM machine reste comprise entre 82% et 88% (ce qui est l'état courant noté `supervisor.ts:1946-1947` : *"entre RAM_WAKE_PCT et RAM_SLEEP_PCT la boucle ne disait RIEN ; trois exécuteurs sont restés endormis 40 min"*), **aucun réveil n'est déclenché**.
   - Même si `memPct < 82%`, le réveil est étalé à **`WAKE_BATCH = 2` services par cycle (60 s)** (`supervisor.ts:1796, 2029`).
   - Surtout, la condition de budget prévisionnel :
     `pct + (cout / totalKo) * 100 > RAM_CIBLE_PCT` (`supervisor.ts:2032-2035`, avec `RAM_CIBLE_PCT = 84%`).
     Si le coût au réveil estimé fait remonter la RAM projetée au-dessus de 84%, la boucle `break` immédiatement (`supervisor.ts:2035`) et **aucun service suivant de la liste des dormeurs n'est examiné** au cours de ce cycle.
     Si le RSS au moment du sommeil était illisible (`null`), `cout` vaut `RSS_INCONNU_KO` (150 Mo) (`supervisor.ts:1806, 2023`).

2. **Le verrouillage en aval au démarrage (`startService`)** :
   - Quand le superviseur décide enfin de réveiller un service (`supervisor.ts:2047-2051`), il bascule `state.status = "stopped"` et appelle `startService(state)`.
   - `startService()` interroge le hub souverain via `GET /api/resource/should_spawn?name=...` (`supervisor.ts:1391-1406`).
   - Si le hub est saturé ou refuse le spawn (`gj.should_spawn === false`), ou si la requête d'autorisation échoue (`AUTHZ_DENIED` 401/403), le superviseur n'exécute pas le spawn et appelle `scheduleDefer(state)` (`supervisor.ts:1422, 1437`), qui reprogramme un départ 30 s plus tard sans changer le statut en `"running"`.

---

## 4. Cause prouvée

La cause racine pour laquelle un service délesté n'est pas réveillé est double selon l'état du système :
1. **Au niveau de la boucle de supervision (`resourceLoop`)** :
   Le service est exclu du réveil tant que `memPct >= 82%`.
   Dès que `memPct < 82%`, le service est exclu si `pct + (cout / totalKo) * 100 > 84%` (`supervisor.ts:2033`), ou différé si un autre dormeur moins coûteux a consommé le budget de 2 réveils par cycle (`WAKE_BATCH = 2`).
2. **Absence d'exclusion intrinsèque par statut ou TTL** :
   Le délestage RAM **n'écrit pas** de `sommeilVouluJusquaMs` (`supervisor.ts:1993-2001`). Le service reste donc en `status = "sleeping"` pur, attendant que la condition `memPct < 82%` soit satisfaite. Si la machine reste sous une charge de fond supérieure à 82% (venue par exemple d'autres processus hors Nokido, d'un navigateur ou d'allocations volumineuses), les services délestés restent endormis indéfiniment jusqu'à intervention manuelle (`POST /supervisor/wake/<name>`).

---

## 5. Correctif proposé (non appliqué)

### Problème ciblé
Un exécuteur de tâches critique pour l'organisme (`NokidoTaskExecutor*`) ne devrait pas rester indéfiniment endormi si une intention de travail existe (tâche assignée en attente dans la file) ou s'il s'agit d'un organe d'exécution essentiel qui subit une pression RAM externe prolongée alors que son absence bloque l'organisme. De plus, dans la boucle de réveil (`supervisor.ts:2035`), un `break` brutal sur `tropCher` bloque l'évaluation des autres dormeurs qui pourraient être moins volumineux si le tri n'était pas parfait ou si totalKo est manquant.

### Modification proposée
1. **Dans `proxy_deno/core/services.toml`** :
   Si les exécuteurs de tâches de code (ex. `NokidoTaskExecutorAntigravity`) ne doivent jamais être tués par le délestage automatique lors de pics temporaires car leur mort interrompt le pipeline de livraison de tâches, ajouter `neverSleep = true` à leur définition dans `services.toml`, à l'instar de `NokidoCIRunner` (`services.toml:2479`) ou `NokidoOpenAIProxy` (`services.toml:1429`).
2. **Dans `proxy_deno/core/supervisor.ts` (fonction `resourceLoop`, bloc de réveil L2028-2055)** :
   Remplacer le `break` de la ligne 2035 par un `continue` pour ne pas bloquer les autres candidats si l'un d'eux dépasse la marge, ou introduire un réveil forcé sur intention fraîche / présence de tâches en file.

### Non-régression (NR) qui prouverait le correctif
- Test unitaire/d'intégration dans `tests/nr/test_reveil_delestage_ram_nr.py` simulant :
  1. `memPct` passant à 90% -> constat du passage en `sleeping` des services non essentiels.
  2. `memPct` redescendant à 80% -> constat que les `NokidoTaskExecutor*` reçoivent bien `Waking` et que leur statut redevient `running` / `starting`.
  3. Vérification que si `state.def.neverSleep = true` est positionné, `memPct > 88%` ne provoque aucun arrêt sur les exécuteurs.
