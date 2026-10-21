# Enquête : Faux crash et quarantaine abusive de NokidoSkillCurator

**Date :** 2026-10-20  
**Auteur :** Antigravity (`agt_antigravity`), livraison 4701b0fb5 (tâche job_988ca3e7)  
**Fait SSoT :** Blackboard `architecture_rules`, clé `bug_skill_curator_quarantaine_faux_crash_20261020`  
**Statut :** Cause racine établie (piste initiale réfutée)

> **Verdict d'intégration (Claude, 20/10) : PARTIELLE.** Rapport intégré. Le test RED livré
> (`test_superviseur_instance_unique_pas_un_crash_nr.py`) n'est PAS intégré : il lit le source TypeScript par
> expressions régulières (une chaîne dans un commentaire le ferait passer) et son 4e cas exigeait le nom littéral
> `skill_curator` dans `supervisor.ts`, ce qui couplerait le superviseur à un service. Contrat à tester à la place,
> par comportement : l'organe DIT « instance déjà vivante » (code de sortie dédié), et le superviseur ne compte pas
> cette sortie comme un crash, ne relance pas et ne met pas en quarantaine.

---

## 1. Contexte & Symptôme Mesuré

Le 2026-10-20 à 09:20, le service `NokidoSkillCurator` a été placé en **QUARANTAINE** par le superviseur Deno (`proxy_deno/core/supervisor.ts`) après 19 relances successives.

Or, la lecture du journal du service (`logs/supervisor/NokidoSkillCurator.log`, l. 71-91) révèle la situation suivante :
1. Une instance saine tournait réellement : **PID 19412**, démarré à **08:07:52**, exécutant avec succès deux cycles d'extraction/persistance (`extracted=1 kept=1 pruned=0 persisted=1`), puis se mettant en attente physiologique (`cad.dormir()`).
2. Dès 08:13:06 (soit ~5 min 14 s après), le superviseur tente de relancer une instance (`pid 23392`).
3. Cette nouvelle instance sort immédiatement en 75 ms avec le message :  
   `[skill_curator] another instance running, exit`
4. Le superviseur interprète cette sortie comme un crash immédiat, réenclenche la boucle de redémarrage exponentielle (1 s, 2 s, 4 s) :
   - PID 408 à 08:13:07 -> sort en 68 ms avec `another instance running, exit`
   - PID 21208 à 08:13:09 -> sort en 68 ms avec `another instance running, exit`
5. Au bout de 3 sorties rapides consécutives (< 30 s), le circuit-breaker rapide du superviseur place le service en `QUICK-FAIL QUARANTINE` de 5 minutes.
6. À l'issue des 5 minutes, le superviseur le relève et tente à nouveau de le démarrer (08:18:11, 08:23:18...), reproduisant le même cycle jusqu'à atteindre le cap horaire (`MAX_RESTARTS_PER_HOUR = 10`), déclenchant alors la mise en quarantaine longue de **1 heure** (`QUARANTINE_MS = 60 * 60 * 1000`).

---

## 2. Examen de la piste initiale : le superviseur suit-il le PID du lanceur logboot ?

> **Piste énoncée :** *« Le superviseur suit le pid du lanceur (logboot), pas celui de l'enfant. »*

### Verdict : **RÉFUTÉE (FAUSSE)**

**Preuve par le code :** `tools/forge_logboot.py:180-202`

```python
def executer(cible: list) -> None:
    """Execute la cible comme le ferait l'interpreteur : sys.argv et sys.path[0] identiques."""
    if cible[0] == "-m":
        ...
        runpy.run_module(cible[1], run_name="__main__", alter_sys=True)
        return
    script = os.path.abspath(cible[0])
    sys.argv = [cible[0]] + cible[1:]
    sys.path[0] = os.path.dirname(script)
    runpy.run_path(script, run_name="__main__")

def main(argv=None) -> None:
    journal, cible = _decouper(sys.argv[1:] if argv is None else argv)
    installer(journal)
    print("[logboot] journal sans pipe : pid %d, cible %s" % (os.getpid(), " ".join(cible)[:200]), flush=True)
    executer(cible)
```

1. `tools/forge_logboot.py` est un amorceur **in-process**. Il ne crée **aucun sous-processus** (aucun appel à `subprocess.Popen` pour la cible).
2. Il redirige les descripteurs 1 et 2 vers un pipe interne avec un thread de relais, puis exécute le script cible directement dans l'interpréteur courant via `runpy.run_path(script, run_name="__main__")`.
3. Le PID du lanceur logboot est donc **strictement identique** au PID du script `app/forge_skill_curator.py` :
   - Journalisé à 08:07:52 : `[logboot] journal sans pipe : pid 19412`
   - Le PID enregistré dans `sandbox/skill_curator.pid` par `_acquire_pidfile()` est `19412`.
   - Le PID enregistré par Deno dans `state.pid` lors du spawn est également `19412`.
4. Il n'y a donc aucun décalage de PID entre un prétendu "parent logboot" et un "enfant curator".

---

## 3. Causes Racines Établies (avec fichier:ligne)

L'enquête démontre que la mise en quarantaine abusive résulte de la conjonction de quatre facteurs précis :

### Cause 1 : Sortie propre code 0 de l'instance concurrente
*Fichier :* `app/forge_skill_curator.py:405-416` et `app/forge_skill_curator.py:448-450`

```python
def _acquire_pidfile() -> bool:
    pid = os.getpid()
    if PIDFILE.exists():
        try:
            old = int(PIDFILE.read_text().strip())
            if old != pid and _pid_alive_win(old):
                return False
        except Exception:
            ...
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(pid))
    return True

...
    if args.daemon and not _acquire_pidfile():
        print("[skill_curator] another instance running, exit", flush=True)
        return 0
```
Quand un nouveau processus est lancé alors que PID 19412 tourne toujours, `_acquire_pidfile()` détecte que l'ancien PID est vivant via `_pid_alive_win()`. Le nouveau processus affiche le message et effectue un `return 0` (exit code 0) propre en moins de 80 ms pour ne pas entrer en conflit.

### Cause 2 : Le superviseur traite toute sortie rapide comme un crash (code de sortie ignoré)
*Fichier :* `proxy_deno/core/supervisor.ts:1549-1585`

```typescript
    proc.status.then(async (s) => {
      const elapsedMs = Date.now() - state.lastStartMs;
      const elapsed = Math.round(elapsedMs / 1000);
      log(
        `${def.name}: exited code=${s.code} after ${elapsed}s (restart #${state.restartCount})`,
      );
      ...
      // Phase 6 reflexe spinal : track exits rapides consecutifs.
      if (elapsedMs < QUICK_FAIL_THRESHOLD_MS) {
        state.quickFailCount++;
      } else {
        state.quickFailCount = 0;
      }
      state.logFile = null;
      state.proc = null;
      state.pid = null;
      if (state.status !== "sleeping" && state.status !== "stopped") {
        scheduleRestart(state);
      }
    });
```
- Le superviseur ne regarde **jamais** si `s.code === 0` ou si la sortie est volontaire (protection instance unique).
- Tout arrêt survenu en moins de 30 secondes (`elapsedMs < QUICK_FAIL_THRESHOLD_MS`, ligne 1574) incrémente **inconditionnellement** `state.quickFailCount++`.
- Ensuite, `scheduleRestart(state)` est invoqué inconditionnellement dès lors que le service n'était pas manuellement arrêté ou endormi (ligne 1583).

### Cause 3 : L'escalade automatique vers la quarantaine
*Fichier :* `proxy_deno/core/supervisor.ts:1604-1652`

```typescript
  if (state.quickFailCount >= QUICK_FAIL_COUNT) {
    state.status = "quarantine";
    state.quarantineUntilMs = now + QUICK_QUARANTINE_MS;
    log(
      `${state.def.name}: QUICK-FAIL QUARANTINE — ${state.quickFailCount} exits < ${
        QUICK_FAIL_THRESHOLD_MS / 1000
      }s. Released in ${Math.round(QUICK_QUARANTINE_MS / 60000)}min.`,
    );
    setTimeout(() => {
      if (state.status === "quarantine") {
        ...
        _relancerApresQuarantaine(state);
      }
    }, QUICK_QUARANTINE_MS);
    return;
  }
```
- Avec `QUICK_FAIL_COUNT = 3` (ligne 305) et des backoffs de 1 s et 2 s (ligne 253), trois tentatives avortent en moins de 4 secondes cumulées.
- Le service bascule en `quarantine` pour 5 minutes (`QUICK_QUARANTINE_MS = 300_000`, ligne 306).
- À la levée de la quarantaine, `_relancerApresQuarantaine(state)` (lignes 1598-1602) relance automatiquement le service... qui percute à nouveau le pidfile de PID 19412, subit 3 rejets, et repart en quarantaine.
- Après 10 relances accumulées dans l'heure (`state.restartHistory.length > MAX_RESTARTS_PER_HOUR`, ligne 1634), le superviseur déclenche la quarantaine de **1 heure** (`QUARANTINE_MS = 3_600_000`, ligne 259).

### Cause 4 : Angle mort du superviseur sur l'adoption des services sans port réseau
*Fichier :* `proxy_deno/core/supervisor.ts:1266-1325`

Dans `startService()` :
- Pour les services exposant un port réseau (`def.port`), le superviseur sonde `isPortOpen(def.port)` et adopte le service existant (`state.status = "running"`, `skipping start`) sans spawner de doublon.
- En revanche, pour les démons autonomes **sans port réseau** (`def.port === undefined`), comme `NokidoSkillCurator`, il n'existe **aucun mécanisme de vérification préalable** de l'existence d'une instance active (pas de lecture du `pidfile`, pas d'interrogation de l'OS).
- Si le superviseur redémarre ou réconcilie son état alors qu'une instance tourne en tâche de fond sous Windows, il tente aveuglément d'en spawner une seconde. Celle-ci sort aussitôt par son garde d'instance unique, ce qui enclenche la fausse boucle de crash et la quarantaine.

---

## 4. Synthèse

| Composant | Comportement réel | Diagnostic |
|---|---|---|
| **`forge_logboot.py`** | Exécute la cible dans le même process (`runpy.run_path`), PID unique | **Hors de cause** (piste réfutée) |
| **`NokidoSkillCurator` (PID 19412)** | Tourne normalement, écrit son heartbeat/cadence, traite les cycles | **Vivant et sain** |
| **Doublon lancé par le superviseur** | Détecte PID 19412, refuse de créer un conflit, quitte code 0 | **Comportement nominal** |
| **`supervisor.ts` (exit handler)** | Voit un exit < 30 s, ignore exit code 0, incrémente `quickFailCount` | **DÉFECTUEUX** (faux positif de crash) |
| **`supervisor.ts` (quarantaine)** | Met en quarantaine un service dont l'instance vit parfaitement | **DÉFECTUEUX** (quarantaine abusive) |

Question ouverte (non instruite par l'enquête) : pourquoi le superviseur relance-t-il à 08:13:06 une instance qui vit
depuis 08:07:52 ? Il ne relance qu'après une sortie, ou en réconciliation : l'événement déclencheur reste à lire
dans le journal du superviseur.

---

## 5. Préconisations pour la phase GREEN (correctif ultérieur)

1. **Dans `proxy_deno/core/supervisor.ts` :**
   - Dans le handler `proc.status.then(s => ...)` : ne PAS incrémenter `quickFailCount` ni appeler `scheduleRestart` si le code de sortie indique une sortie normale d'instance déjà active.
   - Dans `startService` : pour les services sans port déclarant un pidfile ou un heartbeat, vérifier si le PID du fichier est vivant dans l'OS avant de lancer un doublon. Si le PID est vivant, adopter le statut `running` plutôt que de forcer un nouveau spawn.
2. **Dans `app/forge_skill_curator.py` :**
   - Formaliser un code de sortie dédié lors d'un refus d'instance unique, reconnu par le superviseur (la propriété se DEMANDE à l'organe, elle ne se déduit pas d'un code 0 qui peut aussi signifier « rien à faire »).
