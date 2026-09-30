"""app/forge_guarded_change.py — gate anti-régression des mutations autonomes.

Les boucles autonomes de Nokido (memory_consolidator, auto_compact,
night_trainer, auto_evolution, auto_pilot) appliquaient leurs changements
sans AUCUN contrôle — « commit and pray » — d'où les régressions récurrentes
(« ça marchait la veille »). Cf memory roadmap-anti-regression.

`guarded_change` enveloppe une mutation :
    snapshot (optionnel) -> apply -> healthcheck -> rollback/alerte si régression.

À appeler DEPUIS les daemons (Python direct). PAS via MCP : forge_snapshot
refuse les callers LLM/MCP — et c'est voulu.

Exemple — boucle qui mute la DB RAG (memory_consolidator, auto_compact) :
    from forge_guarded_change import guarded_change
    with guarded_change("memory_consolidator: ingest", db_snapshot=True) as gc:
        _ingest_experience(...)
    if gc.regressed:
        log("ingest annulé — régression détectée + rollback")

Exemple — boucle qui touche un service (auto_pilot, auto_evolution) :
    with guarded_change("auto_pilot: heal hub",
                        post_check=lambda: {"ok": _hub_responds()}):
        _restart_hub()
"""

from __future__ import annotations

import sqlite3
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_DB = ROOT / "RAG" / "embeddings.db"
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

# En-dessous de ce ratio du nombre de chunks RAG initial -> régression.
_RAG_COLLAPSE_RATIO = 0.8


class GuardResult:
    """Résultat observable d'un guarded_change — lisible après le `with`."""

    __slots__ = ("label", "regressed", "rolled_back", "reason", "snapshot_ts")

    def __init__(self, label: str):
        self.label = label
        self.regressed = False
        self.rolled_back = False
        self.reason = ""
        self.snapshot_ts = None


def _log(label: str, msg: str, level: str = "INFO") -> None:
    # ASCII-safe : un daemon peut avoir une console cp1252 — un print
    # non-ASCII leverait UnicodeEncodeError et tuerait la boucle.
    line = f"[guarded_change:{level}] {label} - {msg}"
    print(line.encode("ascii", "replace").decode("ascii"), flush=True)


def _rag_total() -> int | None:
    try:
        conn = sqlite3.connect(str(_DB), timeout=10)
        try:
            return conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return None


def _light_health() -> dict:
    """Healthcheck léger (<2 s) — sous-ensemble de forge_health_diagnostic.
    run_cycle() complet (10-15 s) serait trop lourd pour un gate."""
    out: dict = {"ok": True, "reason": ""}
    try:
        from nokido_agent.app.forge_health_diagnostic import audit_rag_chunks, audit_tables_empty

        conn = sqlite3.connect(str(_DB), timeout=10)
        try:
            audit_rag_chunks(conn)  # smoke : ne doit pas lever
            tbl = audit_tables_empty(conn)
        finally:
            conn.close()
        crit = [t for t in tbl.get("empty_tables", []) if t in ("rag_chunks", "biblio_raw", "forge_entities")]
        if crit:
            out["ok"] = False
            out["reason"] = f"tables critiques vidées: {crit}"
    except Exception as e:  # noqa: BLE001
        # Le check lui-même plante -> fail-OPEN (ne pas casser la boucle pour
        # un check défaillant) mais on le signale.
        out["check_error"] = str(e)[:200]
    return out


def hub_alive(url: str = "http://127.0.0.1:8766/health", timeout: int = 5, retries: int = 3) -> dict:
    """post_check prêt-à-l'emploi pour les boucles qui redémarrent un service :
    le service HTTP répond-il après l'action ? Réessaie (un service met
    quelques secondes à revenir). 401/403 = vivant (juste auth-protégé)."""
    import urllib.request

    last = ""
    for _ in range(max(1, retries)):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                if 200 <= r.status < 500:
                    return {"ok": True}
                last = f"HTTP {r.status}"
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
        time.sleep(2)
    return {"ok": False, "reason": f"{url} injoignable ({last})"}


def _anchor(label: str, detail: str, rolled_back: bool) -> None:
    try:
        from nokido_agent.app.forge_self_correction import anchor_error

        anchor_error(
            error_msg=f"Régression mutation autonome: {label}",
            context=f"guarded_change | {detail}"[:1500],
            solution=("snapshot restauré (rollback OK)" if rolled_back else "PAS de rollback — inspecter manuellement"),
            domain="systeme",
        )
    except Exception as e:  # noqa: BLE001
        _log(label, f"anchor_error échoué: {e}", "WARN")


def _rollback(res: GuardResult) -> None:
    try:
        from nokido_agent.app.forge_snapshot import cold_restore

        r = cold_restore(res.snapshot_ts, mode="knowledge", dry_run=False, caller="cli")
        res.rolled_back = bool(r.get("ok"))
        _log(
            res.label,
            f"ROLLBACK {'OK' if res.rolled_back else 'ECHEC: ' + str(r)[:200]}",
            "WARN" if res.rolled_back else "ERROR",
        )
    except Exception as e:  # noqa: BLE001
        _log(res.label, f"ROLLBACK exception: {e}", "ERROR")


@contextmanager
def guarded_change(label: str, *, db_snapshot: bool = False, post_check=None):
    """Gate anti-régression autour d'une mutation autonome.

    label       : identifie la boucle/mutation (logs + ancrage RAG).
    db_snapshot : True -> cold_backup(knowledge) avant + cold_restore si
                  régression. Réservé aux mutations de la DB RAG.
    post_check  : callable -> dict {"ok": bool, "reason": str}. Défaut =
                  _light_health(). Pour une boucle qui touche un service,
                  passer un check de liveness dédié.

    Yield un GuardResult ; après le `with`, lire .regressed / .rolled_back.
    """
    res = GuardResult(label)
    t0 = time.time()
    base_total = _rag_total()

    if db_snapshot:
        try:
            from nokido_agent.app.forge_snapshot import cold_backup

            snap = cold_backup(mode="knowledge", label=label[:40], caller="cli")
            res.snapshot_ts = snap.get("timestamp")
            _log(label, f"snapshot knowledge pris ({res.snapshot_ts})")
        except Exception as e:  # noqa: BLE001
            # Pas de filet -> on n'applique PAS la mutation (fail-closed).
            _log(label, f"snapshot impossible: {e} — mutation BLOQUÉE", "ERROR")
            raise RuntimeError(f"guarded_change: snapshot requis échoué ({e})")

    try:
        yield res
    except Exception as e:  # noqa: BLE001
        res.regressed = True
        res.reason = f"exception: {e}"
        _log(label, f"mutation a levé une exception: {e}", "ERROR")
        if res.snapshot_ts:
            _rollback(res)
        _anchor(label, f"{res.reason}\n{traceback.format_exc()[:600]}", res.rolled_back)
        raise

    # --- post-mutation : healthcheck ---
    try:
        chk = post_check() if post_check else _light_health()
    except Exception as e:  # noqa: BLE001
        chk = {"ok": True, "check_error": str(e)[:200]}  # fail-open
    if not chk.get("ok", True):
        res.regressed = True
        res.reason = str(chk.get("reason", chk))

    # effondrement du nombre de chunks RAG
    if base_total and base_total > 100:
        now_total = _rag_total()
        if now_total is not None and now_total < base_total * _RAG_COLLAPSE_RATIO:
            res.regressed = True
            res.reason += f" | chunks RAG {base_total}->{now_total} (-{base_total - now_total})"

    if res.regressed:
        _log(label, f"RÉGRESSION — {res.reason}", "ERROR")
        if res.snapshot_ts:
            _rollback(res)
        _anchor(label, res.reason, res.rolled_back)
    else:
        _log(label, f"OK ({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    # Smoke test : mutation no-op, sans snapshot.
    with guarded_change("smoke-test", db_snapshot=False) as _gc:
        pass
    print(f"smoke: regressed={_gc.regressed} reason={_gc.reason!r}")
