"""
forge_critical_events.py — Append-only SQLite log for events qui doivent
survivre a un restart hub.

Phase 12 (2026-05-24). Nokido accepte la perte d'events SSE/pub-sub
volatiles sur restart hub (local-first, restart <5s). EXCEPTION : events
de classe 'critical' (quarantine, cve_detected, security_breach,
adrenaline>=0.9, cortisol>=0.9) doivent persister sur disque pour que
le sentinel au boot suivant puisse les consulter et re-armer.

Schema SQLite (sandbox/critical_events.db) :
    id INTEGER PK AUTOINCREMENT
    ts REAL                  -- unix seconds
    kind TEXT                -- 'hormone' | 'quarantine' | 'cve' | 'security_breach' ...
    severity TEXT            -- 'warn' | 'error' | 'critical'
    payload TEXT             -- JSON serialise
    processed_at REAL        -- NULL si pas encore consomme par un sentinel

API :
    persist(kind, severity, payload) -> id
    unprocessed(limit=100) -> list[dict]
    mark_processed(ids: list[int]) -> int
    purge_older_than(days=7) -> int    # nettoyage routine NREM3 (glymphatic)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("forge_critical_events")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "sandbox" / "critical_events.db"
_LOCK = threading.Lock()
_INITIALIZED = False


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), timeout=5.0)
    c.row_factory = sqlite3.Row
    return c


def _init_db() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _LOCK:
        if _INITIALIZED:
            return
        with _conn() as c:
            # Phase 22 (2026-05-24) durabilite : synchronous=FULL force fsync sur
            # chaque commit. Cout = ~10ms par insert. Pour events critiques
            # survie-restart, vaut largement le coup vs perte sur power loss.
            c.execute("PRAGMA synchronous=FULL")
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("""
                CREATE TABLE IF NOT EXISTS forge_critical_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    kind TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    processed_at REAL
                )
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_unprocessed
                ON forge_critical_events(processed_at, ts)
                WHERE processed_at IS NULL
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS alertes_owner (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL, sujet TEXT NOT NULL, gravite TEXT NOT NULL, detail TEXT NOT NULL, emetteur TEXT,
                    vu_demarrage REAL, vu_tray REAL
                )
            """)
            c.execute("CREATE TABLE IF NOT EXISTS alertes_etat (sujet TEXT PRIMARY KEY, dernier_ts REAL NOT NULL, gravite TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS alertes_flaps (jour TEXT NOT NULL, service TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (jour, service))")
        _INITIALIZED = True


def backup(suffix: str | None = None) -> dict[str, Any]:
    """Phase 22 — backup rotatif. SQLite .backup() API = consistent snapshot
    pendant que la DB est utilisee (pas un cp brut qui risque corruption).
    Retourne {ok, path, size_mb}."""
    import time as _t

    try:
        _init_db()
        suffix = suffix or _t.strftime("%Y%m%d")
        bak_path = DB_PATH.parent / f"critical_events.bak.{suffix}.db"
        with _conn() as src:
            bak = sqlite3.connect(str(bak_path), timeout=10.0)
            try:
                src.backup(bak)
            finally:
                bak.close()
        sz = bak_path.stat().st_size
        return {"ok": True, "path": str(bak_path), "size_mb": round(sz / 1024 / 1024, 2)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def rotate_backups(keep_last: int = 7) -> int:
    """Garde les keep_last backups les plus recents, supprime les anciens."""
    try:
        baks = sorted(DB_PATH.parent.glob("critical_events.bak.*.db"))
        if len(baks) <= keep_last:
            return 0
        removed = 0
        for old in baks[:-keep_last]:
            try:
                old.unlink()
                removed += 1
            except Exception:
                __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_critical_events.py', 124, exc_info=True)
        return removed
    except Exception:
        return 0


def persist(kind: str, severity: str, payload: dict | None = None) -> int:
    """Append event. Returns row id. Never raises (fail-safe)."""
    try:
        _init_db()
        payload = dict(payload or {})
        # DLP log Tier 1 : scrub PII/secrets du payload incident avant persist
        try:
            from nokido_agent.app.forge_semantic_firewall import redact_for_log as _scrub

            payload = _scrub(payload)
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            # CONTOURNEMENT DE PROTECTION DES DONNEES. Si le scrub echoue, le payload
            # part en base TEL QUEL : PII et secrets compris. Le silence faisait
            # passer un incident non expurge pour un incident expurge.
            _lg.getLogger(__name__).error(
                "[critical_events] scrub DLP IMPOSSIBLE (%s: %s) — le payload est "
                "persiste NON EXPURGE | consequence: cet enregistrement peut contenir "
                "des donnees personnelles ou des secrets, le traiter comme sensible",
                type(e).__name__, str(e)[:100])
        if "trace_id" not in payload:
            try:
                from nokido_agent.app.forge_trace_context import get_trace_id

                payload["trace_id"] = get_trace_id()
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger(__name__).warning(
                    "[critical_events] trace_id absent (%s: %s) | consequence: cet "
                    "evenement ne pourra pas etre rattache a la chaine d'appels qui "
                    "l'a produit", type(e).__name__, str(e)[:90])
        with _conn() as c:
            cur = c.execute(
                "INSERT INTO forge_critical_events (ts, kind, severity, payload) VALUES (?, ?, ?, ?)",
                (time.time(), kind, severity, json.dumps(payload, default=str)),
            )
            row_id = cur.lastrowid
        logger.info("persist kind=%s severity=%s id=%s", kind, severity, row_id)
        return row_id or 0
    except Exception as exc:
        logger.error("persist fail (event lost): %s", exc)
        return 0


def unprocessed(limit: int = 100, sauf_severites: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Plus anciens d'abord. `sauf_severites` filtre DANS la requete : filtrer apres coup
    laisserait des evenements ecartes occuper la fenetre `limit` devant une vraie panne."""
    try:
        _init_db()
        sauf = tuple(sauf_severites)
        filtre = (" AND severity NOT IN (%s)" % ",".join("?" * len(sauf))) if sauf else ""
        with _conn() as c:
            rows = c.execute(
                "SELECT id, ts, kind, severity, payload FROM forge_critical_events "
                "WHERE processed_at IS NULL" + filtre + " ORDER BY id ASC LIMIT ?",
                (*sauf, int(limit)),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
            except Exception:
                payload = {"_raw": r["payload"][:200]}
            out.append(
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "kind": r["kind"],
                    "severity": r["severity"],
                    "payload": payload,
                }
            )
        return out
    except Exception as exc:
        logger.error("unprocessed fail: %s", exc)
        return []


def mark_processed(ids: list[int]) -> int:
    if not ids:
        return 0
    try:
        _init_db()
        now = time.time()
        with _conn() as c:
            cur = c.executemany(
                "UPDATE forge_critical_events SET processed_at = ? WHERE id = ?",
                [(now, int(i)) for i in ids],
            )
            return cur.rowcount or 0
    except Exception as exc:
        logger.error("mark_processed fail: %s", exc)
        return 0


def purge_older_than(days: int = 7) -> int:
    try:
        _init_db()
        cutoff = time.time() - days * 86400
        with _conn() as c:
            cur = c.execute(
                "DELETE FROM forge_critical_events WHERE processed_at IS NOT NULL AND ts < ?",
                (cutoff,),
            )
            return cur.rowcount or 0
    except Exception as exc:
        logger.error("purge fail: %s", exc)
        return 0


# Alertes destinees a l'owner (choix du 4/11, sur volume mesure). COAGULATION et ORGAN_PULSE appelaient notify sans
# destinataire : ~480 NEED_HUMAN_APPROVAL par jour finissaient dans EVENTBUS_ARCHIVE pendant que l'emetteur journalisait
# « delivree ». Ici : resume quotidien des flaps, hors flap une alerte par sujet avec 24 h de silence, soit ~4 par jour.
_GRAVITE_RANG = {"info": 0, "warn": 1, "error": 2, "high": 2, "critical": 3}
_SILENCE_ALERTE_S = 86400.0
_SURFACES = {"demarrage": "vu_demarrage", "tray": "vu_tray"}


def _jour(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _rang(gravite: str) -> int:
    return _GRAVITE_RANG.get(str(gravite).lower(), 1)


def _resumer_flaps(c: sqlite3.Connection, maintenant: float) -> None:
    """Un jour termine devient UNE alerte : le nombre de services et les plus instables. Les evenements restent en base."""
    lignes = c.execute("SELECT jour, service, n FROM alertes_flaps WHERE jour < ? ORDER BY jour, n DESC", (_jour(maintenant),)).fetchall()
    jours: dict = {}
    for r in lignes:
        jours.setdefault(r["jour"], []).append((r["service"], r["n"]))
    for jour, services in jours.items():
        noms = ", ".join("%s (%d)" % s for s in services[:12])
        reste = len(services) - 12
        detail = "%d services ont flappe le %s : %s%s" % (len(services), jour, noms, " et %d autres" % reste if reste > 0 else "")
        c.execute("INSERT INTO alertes_owner (ts, sujet, gravite, detail, emetteur) VALUES (?, ?, 'warn', ?, 'COAGULATION')",
                  (maintenant, "flaps:%s" % jour, detail))
        c.execute("DELETE FROM alertes_flaps WHERE jour = ?", (jour,))


def alerter_owner(sujet: str, gravite: str, detail: str, emetteur: str = "?", maintenant: float | None = None) -> str:
    """Rend emise | silence | regroupee | echec, et ne leve jamais : l'appelant journalise ce qui s'est vraiment passe.
    Une gravite qui monte est un changement d'etat : elle passe le silence."""
    t = time.time() if maintenant is None else float(maintenant)
    sujet, c = str(sujet), None
    try:
        _init_db()
        c = _conn()
        with c:
            if "flap:" in sujet:
                service = sujet.split("flap:", 1)[1][:80]
                c.execute("INSERT INTO alertes_flaps (jour, service, n) VALUES (?, ?, 1) "
                          "ON CONFLICT (jour, service) DO UPDATE SET n = n + 1", (_jour(t), service))
                _resumer_flaps(c, t)
                return "regroupee"
            _resumer_flaps(c, t)
            prec = c.execute("SELECT dernier_ts, gravite FROM alertes_etat WHERE sujet = ?", (sujet,)).fetchone()
            if prec and t - prec["dernier_ts"] < _SILENCE_ALERTE_S and _rang(gravite) <= _rang(prec["gravite"]):
                return "silence"
            try:
                from nokido_agent.app.forge_semantic_firewall import redact_for_log as _scrub

                detail = _scrub({"detail": str(detail)})["detail"]
            except Exception as e:  # noqa: BLE001
                logger.error("[alertes] scrub DLP impossible (%s) : detail remplace, jamais stocke non expurge", type(e).__name__)
                detail = "detail non expurge, voir critical_events"
            c.execute("INSERT INTO alertes_owner (ts, sujet, gravite, detail, emetteur) VALUES (?, ?, ?, ?, ?)",
                      (t, sujet, str(gravite), str(detail)[:500], str(emetteur)))
            c.execute("INSERT INTO alertes_etat (sujet, dernier_ts, gravite) VALUES (?, ?, ?) "
                      "ON CONFLICT (sujet) DO UPDATE SET dernier_ts = excluded.dernier_ts, gravite = excluded.gravite",
                      (sujet, t, str(gravite)))
        return "emise"
    except Exception as exc:  # noqa: BLE001
        logger.error("[alertes] alerte PERDUE (%s: %s) : %s", type(exc).__name__, str(exc)[:120], sujet)
        return "echec"
    finally:
        if c is not None:
            c.close()


def alertes_recentes(limit: int = 20, gravite_min: str = "info") -> dict[str, Any]:
    """Alertes les plus recentes, pour tout client : n'ecrit RIEN, ni `vu_*` ni resume de flaps ; ce qui est coupe se compte."""
    try:
        c = _conn()
        try:
            lignes = c.execute("SELECT id, ts, sujet, gravite, detail, emetteur FROM alertes_owner ORDER BY id DESC").fetchall()
        finally:
            c.close()
    except sqlite3.Error as exc:
        return {"etat": "ILLISIBLE", "raison": f"{type(exc).__name__}: {str(exc)[:120]}"}
    filtrees = [dict(r) for r in lignes if _rang(r["gravite"]) >= _rang(gravite_min)]
    borne = max(1, min(int(limit), 100))
    return {"etat": "OK", "total": len(filtrees), "coupees": max(0, len(filtrees) - borne), "alertes": filtrees[:borne]}


def alertes_en_attente(surface: str, gravite_min: str = "info", limit: int = 20, maintenant: float | None = None) -> list[dict[str, Any]]:
    """Alertes non encore montrees a cette surface. Une surface inconnue leve : la colonne vient de cette table fermee."""
    if surface not in _SURFACES:
        raise ValueError("surface inconnue : %s" % surface)
    t = time.time() if maintenant is None else float(maintenant)
    _init_db()
    c = _conn()
    try:
        with c:
            _resumer_flaps(c, t)
        lignes = c.execute("SELECT id, ts, sujet, gravite, detail, emetteur FROM alertes_owner WHERE %s IS NULL ORDER BY id" % _SURFACES[surface]).fetchall()
    finally:
        c.close()
    return [dict(r) for r in lignes if _rang(r["gravite"]) >= _rang(gravite_min)][:int(limit)]


def marquer_vues(ids: list[int], surface: str, maintenant: float | None = None) -> None:
    if surface not in _SURFACES:
        raise ValueError("surface inconnue : %s" % surface)
    t = time.time() if maintenant is None else float(maintenant)
    c = _conn()
    try:
        with c:
            c.executemany("UPDATE alertes_owner SET %s = ? WHERE id = ?" % _SURFACES[surface], [(t, int(i)) for i in ids])
    finally:
        c.close()


def purger_alertes(jours: int = 30, maintenant: float | None = None) -> int:
    """Retire les alertes anciennes deja vues par les surfaces qui les concernent. Une alerte jamais vue n'est jamais purgee.
    Le tray ne montre que high et critical : un `warn` n'attend donc pas sa lecture. Rend le nombre d'alertes retirees."""
    coupure = (time.time() if maintenant is None else float(maintenant)) - int(jours) * 86400
    try:
        _init_db()
        c = _conn()
        try:
            with c:
                n = c.execute("DELETE FROM alertes_owner WHERE ts < ? AND vu_demarrage IS NOT NULL "
                              "AND (vu_tray IS NOT NULL OR gravite NOT IN ('high', 'error', 'critical'))", (coupure,)).rowcount
                c.execute("DELETE FROM alertes_etat WHERE dernier_ts < ?", (coupure,))
            return n or 0
        finally:
            c.close()
    except Exception as exc:  # noqa: BLE001
        logger.error("[alertes] purge impossible (%s: %s)", type(exc).__name__, str(exc)[:120])
        return 0


def stats() -> dict[str, Any]:
    try:
        _init_db()
        with _conn() as c:
            total = c.execute("SELECT COUNT(*) FROM forge_critical_events").fetchone()[0]
            unproc = c.execute("SELECT COUNT(*) FROM forge_critical_events WHERE processed_at IS NULL").fetchone()[0]
            by_kind = c.execute("SELECT kind, COUNT(*) FROM forge_critical_events GROUP BY kind").fetchall()
        return {
            "db_path": str(DB_PATH),
            "total": total,
            "unprocessed": unproc,
            "by_kind": {r[0]: r[1] for r in by_kind},
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}


if __name__ == "__main__":
    print(json.dumps(stats(), indent=2))
