# Heartbeat schema — supervisor.ts autodiagnostic (Phase 3, 2026-05-24)

Convention pour les daemons Nokido supervisés par `proxy_deno/core/supervisor.ts`
(LaForge-Master :8765). Chaque service déclare son fichier via `heartbeat = "sandbox/<X>.heartbeat"`
dans `services.toml`. Le supervisor le lit toutes les **30 s** et expose le résultat
dans `GET /supervisor/status.services.<name>.heartbeat`.

## Schema JSON (single-line ou pretty)

```json
{
  "service": "NokidoHebbian",
  "ts": 1779641495.27,
  "iter": 1234,
  "health": "ok",
  "stats": {
    "edges_added": 42,
    "queue_depth": 0,
    "last_error": null
  }
}
```

| Champ     | Type   | Obligatoire | Notes |
|-----------|--------|-------------|-------|
| `service` | string | non         | identique à `name` toml ; aide debugging |
| `ts`      | number | **oui**     | unix seconds float — supervisor calcule `stale_s = now - ts` |
| `iter`    | number | non         | compteur d'itération du daemon ; monotone ⇒ vie du loop |
| `health`  | string | non         | `"ok"` / `"degraded"` / `"crit"` — auto-évaluation par le daemon |
| `stats`   | object | non         | métriques custom — taille libre, kept as-is dans la réponse |
| `code_sha` | string\|null | recommandé | sha256[:12] du fichier du daemon **tel que chargé au démarrage** |
| `code_sha_now` | string\|null | recommandé | le même, relu à chaque battement |
| `code_stale` | bool\|null | recommandé | `true` = le disque a divergé depuis le démarrage ; `null` = ILLISIBLE |

### Identité du code chargé (2026-08-02)

Un battement dit si le service vit. Il ne disait pas **quel code** vit. Mesuré ce jour-là :
`forge_docker_keeper` avait été reverté sur DISQUE, mais le process en cours exécutait
toujours l'ancien code, sondait un daemon abandonné et publiait `daemon_up: true`. Le
heartbeat était sincère et trompeur à la fois — « j'ai reverté » et « le service exécute
le revert » sont deux faits distincts, et un seul était observable.

Les trois champs viennent de `tools/forge_code_identity.py` : `**fields(__file__)`.
`code_stale` vaut `null`, jamais `false`, quand le fichier est illisible (absent, ACL,
verrou) — un capteur qui répond « pas de dérive » à « je ne peux pas voir » fabrique des
faux négatifs indétectables. Un consommateur qui alerte teste donc `is True`.

Si `ts` absent : fallback sur `mtime` du fichier. Le supervisor préfère `ts`
quand présent (plus précis ; mtime peut traîner sur certains systèmes de fichiers).

## Comportement supervisor — 3 tiers (Phase 6 régulation multi-échelle)

Le champ `heartbeat_tier` de `services.toml` choisit la réactivité.
Default = `"normal"`. 1 loop dédié par tier dans supervisor.ts.

| Tier      | Poll | Degraded à | Restart à | Cible |
|-----------|------|-----------|-----------|-------|
| `fast`    | 5 s  | 30 s      | 90 s      | services critiques RT (Docker keeper, multi_llm_daemon 15s) |
| `normal`  | 30 s | 300 s     | 600 s     | défaut — daemons interactifs / cycles 1-5 min |
| `slow`    | 60 s | 1800 s    | 3600 s    | daemons longs cycles (memory_consolidator 12h, offline_trainer 6h, self_patcher 1h) |

Pour chaque tier :

| `stale_s` | Champ `health` exposé | Action supervisor |
|-----------|----------------------|-------------------|
| `< degraded_threshold`   | tel quel du daemon (default `ok`) | rien |
| `[degraded_threshold, restart_threshold)` | `degraded` (si daemon disait `ok`) | rien — visibilité TUI seulement |
| `>= restart_threshold`  | `stale`              | si `status == "running"` ET `proc != null` → SIGTERM + `scheduleRestart` |

Source : `HEARTBEAT_TIERS` dans `supervisor.ts`.

### Circuit breaker rapide (Phase 6 réflexe spinal)

Indépendant des heartbeats. Sur chaque exit de service, le supervisor
mesure `elapsed_ms = now - lastStartMs` :
- `elapsed_ms < QUICK_FAIL_THRESHOLD_MS (30s)` → incrémente `quickFailCount`
- `elapsed_ms >= QUICK_FAIL_THRESHOLD_MS` → reset `quickFailCount = 0`

Si `quickFailCount >= 3` exits rapides consécutifs → **quarantine immédiate
5 min** (sans attendre le cap horaire de 10/h). Empêche un daemon qui exit
en < 1s (lock PID stale, dep manquante, config corrompue) de saturer le
supervisor en spawns boucle.

Constantes : `QUICK_FAIL_THRESHOLD_MS = 30_000`, `QUICK_FAIL_COUNT = 3`,
`QUICK_QUARANTINE_MS = 5 * 60 * 1000`.

## Écriture côté daemon (pattern Python)

```python
import json, time, pathlib

HEARTBEAT_PATH = pathlib.Path("sandbox/<your_daemon>.heartbeat")
iter_count = 0

def _code_identity() -> dict:
    try:
        from forge_code_identity import fields
        return fields(__file__)
    except Exception:  # muet-ok : diagnostic, jamais un SPOF pour le daemon
        return {}


def write_heartbeat(stats: dict, health: str = "ok") -> None:
    HEARTBEAT_PATH.parent.mkdir(exist_ok=True)
    HEARTBEAT_PATH.write_text(json.dumps({
        "service": "<NokidoXxx>",
        "ts": time.time(),
        "iter": iter_count,
        "health": health,
        **_code_identity(),
        "stats": stats,
    }))

# Dans la boucle daemon :
while True:
    iter_count += 1
    # ... work ...
    write_heartbeat({"queue_depth": q.qsize(), "last_error": str(last_err)},
                    health="degraded" if recent_errs > 5 else "ok")
    time.sleep(60)
```

## Notes
- Fréquence de write recommandée ≥ 1× / 60 s pour rester loin de `STALE_DEGRADED_S=300`.
- `crit` n'arrête pas le service ; le daemon doit décider de planter lui-même si nécessaire.
- L'écriture du heartbeat doit **jamais** lever : try/except complet pour pas tuer le loop.
- Le champ `stale_s` est calculé côté supervisor ; le daemon ne le met pas.

Voir aussi : `[[roadmap-supervisor-autodiagnostic]]` (mémoire utilisateur).
