#!/usr/bin/env python3
"""
app/forge_swarm_blackboard.py — Tableau noir zoné souverain du swarm.

Mémoire de travail PARTAGÉE, déterministe, thread-safe. Les workers PROPOSENT
des faits (fire-and-forget) ; le hub est l'UNIQUE write-funnel → zéro contention
SQLite "database is locked" même sous N workers concurrents. La lecture se fait
PAR ZONE, condensée, pour éviter le lost-in-the-middle (le LLM ne charge que la
zone dont il a besoin, jamais tout le tableau).

Décision archi 2026-06-04 (SQLite WAL mono-writer) réalisée SANS dépendre de
forge_event_stream : ce dernier n'a pas de singleton module-level (une instance
par AgentLoop), donc le sérialiseur d'écriture est INTERNE au module —
asyncio.Lock + asyncio.to_thread (la coroutine writer unique, off l'event loop).

Zones canoniques + ACL (ring MAX autorisé à ÉCRIRE ; ring bas = plus privilégié) :
  mission             ring<=1  (planner/system)
  architecture_rules  ring<=1
  discovered_facts    ring<=2  (swarm trusted)
  active_bugs         ring<=2
  scratch             ring<=3
Lecture = toutes zones, large (ring 4).

CLI: python forge_swarm_blackboard.py --selftest
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# DB en realpath (évite le symlink C: non-inscriptible pour certains users) :
# on dérive le dossier RAG via forge_db_path.db_path() quand dispo.
try:  # pragma: no cover - dépend de l'env hub
    from nokido_agent.app.forge_db_path import db_path as _dbp  # type: ignore

    _DB = Path(_dbp()).resolve().parent / "swarm.db"
except Exception:  # fallback hors hub
    _DB = (Path(__file__).resolve().parent.parent / "RAG" / "swarm.db")

# override explicite (tests / sandbox sans droits sur RAG/)
_env_db = os.environ.get("FORGE_SWARM_DB")
if _env_db:
    _DB = Path(_env_db)

# zone -> ring MAX du caller autorisé à écrire (caller.ring <= valeur)
_ZONE_WRITE_RING: dict[str, int] = {
    "mission": 1,
    "architecture_rules": 1,
    "discovered_facts": 2,
    "active_bugs": 2,
    "scratch": 3,
}
_DEFAULT_WRITE_RING = 2  # zone inconnue → trusted-only

# GC/TTL — le blackboard est une MÉMOIRE DE TRAVAIL, pas une archive. Auto-prune
# à chaque écriture : borne par âge (TTL) + cap des N plus récents par zone.
_FACT_TTL_S = 14 * 86400      # 14 jours (TTL dur)
_ZONE_MAX_FACTS = 300         # cap par zone
_TRUST_HALFLIFE_S = 7 * 86400  # demi-vie trust : un fait perd la moitié de sa confiance effective tous les 7j
_PRUNE_EVERY = 20              # amortit le prune (TTL+cap) : 1 write/20 au lieu de chaque (write ~7ms -> ~moyenne divisée)
_write_count = 0

_DDL = """
CREATE TABLE IF NOT EXISTS swarm_blackboard (
    zone        TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    trust       REAL NOT NULL DEFAULT 0.5,
    worker_id   TEXT NOT NULL DEFAULT 'unknown',
    updated_at  REAL NOT NULL,
    PRIMARY KEY (zone, key)
);
CREATE INDEX IF NOT EXISTS idx_bb_zone_cat ON swarm_blackboard(zone, category);
"""

_write_lock: Optional[asyncio.Lock] = None


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB), timeout=10.0, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    c.execute("PRAGMA busy_timeout=10000;")
    return c


_writer_conn: "Optional[sqlite3.Connection]" = None


def _get_writer() -> sqlite3.Connection:
    """Connexion writer PERSISTANTE (ouverte 1×, réutilisée) — supprime le churn connect+3 PRAGMA
    +close à CHAQUE write (le vrai surcoût par-write ; busy_timeout=10s + asyncio.Lock rendaient déjà
    0 contention/0 échec, cf bench job_8397087e9236). check_same_thread=False car _write_fact tourne
    dans le pool to_thread (threads variables) ; la sérialisation est garantie par l'asyncio.Lock de
    apply_fact (un seul writer à la fois). Self-heal : sur erreur, _write_fact la réinitialise."""
    global _writer_conn
    if _writer_conn is None:
        _DB.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(_DB), timeout=10.0, isolation_level=None, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA synchronous=NORMAL;")
        c.execute("PRAGMA busy_timeout=10000;")
        _writer_conn = c
    return _writer_conn


def init_db() -> None:
    c = _conn()
    try:
        c.executescript(_DDL)
    finally:
        c.close()


def _normalize(s: str) -> str:
    """Normalise pour dédup des quasi-doublons : casse, espaces multiples,
    ponctuation de bord. (Pas de dédup sémantique embeddings — sandbox bloque
    torch ; ceci attrape les reformulations triviales casse/espaces.)"""
    import re

    return re.sub(r"\s+", " ", (s or "").lower().strip()).strip(".,;:!?-– ")


def _fact_key(fact: str, category: str) -> str:
    """Clé déterministe sur fait NORMALISÉ → re-proposer un fait quasi-identique
    (casse/espaces différents) = même clé = UPSERT idempotent + dédup des proches."""
    return hashlib.sha256(
        f"{(category or '').lower()}\x00{_normalize(fact)}".encode("utf-8")
    ).hexdigest()[:16]


def _lock() -> asyncio.Lock:
    global _write_lock
    if _write_lock is None:
        _write_lock = asyncio.Lock()
    return _write_lock


def _prune(conn: sqlite3.Connection, zone: str) -> None:
    """Borne la zone à l'écriture : TTL + cap des N plus récents (travail ≠ archive)."""
    conn.execute("DELETE FROM swarm_blackboard WHERE zone=? AND updated_at < ?",
                 (zone, time.time() - _FACT_TTL_S))
    conn.execute(
        "DELETE FROM swarm_blackboard WHERE zone=? AND key NOT IN "
        "(SELECT key FROM swarm_blackboard WHERE zone=? ORDER BY updated_at DESC LIMIT ?)",
        (zone, zone, _ZONE_MAX_FACTS))


def _write_fact(zone: str, key: str, value: str, category: str,
                trust: float, worker_id: str) -> None:
    global _writer_conn, _write_count
    c = _get_writer()  # connexion PERSISTANTE (réutilisée, plus de churn connect+PRAGMA+close/write)
    try:
        c.execute(
            "INSERT INTO swarm_blackboard"
            "(zone,key,value,category,trust,worker_id,updated_at) "
            "VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(zone,key) DO UPDATE SET "
            "value=excluded.value, category=excluded.category, "
            "trust=excluded.trust, worker_id=excluded.worker_id, "
            "updated_at=excluded.updated_at",
            (zone, key, value, category, float(trust), worker_id, time.time()),
        )
        _write_count += 1
        if _write_count % _PRUNE_EVERY == 0:  # prune amorti (cap soft +N transitoire, OK)
            _prune(c, zone)
    except Exception:
        try:
            c.close()
        except Exception:
            pass
        _writer_conn = None  # connexion cassée -> réouverte au prochain write (self-heal)
        raise


async def apply_fact(zone: str, fact: str, *, category: str = "", trust: float = 0.5,
                     key: Optional[str] = None, source: str = "unknown",
                     ring: int = 4) -> dict:
    """Write-funnel : ACL par ring, puis UPSERT sérialisé (single-writer).

    Retourne {ok, zone, key, trust} ou {error}. La clé est déterministe (hash du
    fait) si non fournie → idempotence via PRIMARY KEY(zone,key).
    """
    zone = (zone or "").strip()
    if not zone:
        return {"error": "zone requise"}
    if not fact:
        return {"error": "fact requis"}
    need = _ZONE_WRITE_RING.get(zone, _DEFAULT_WRITE_RING)
    if int(ring) > need:
        return {"error": f"ACL: zone '{zone}' exige ring<={need}, appelant ring={ring}"}
    k = key or _fact_key(fact, category or "")
    async with _lock():  # un seul writer à la fois → pas de "database is locked"
        await asyncio.to_thread(_write_fact, zone, k, fact, category or "",
                                float(trust), source or "unknown")
    # Journal d'intention UNIFIE (audit-trail SSoT, forge_intention_journal) — guarded,
    # ne casse JAMAIS l'ecriture. Chaque fait blackboard = une intention tracee.
    try:
        from nokido_agent.app import forge_intention_journal as _ij
        _ij.record(agent=source or "unknown", intent_type="blackboard_write",
                   target=f"{zone}/{k}", payload={"category": category, "trust": float(trust)},
                   decision="validated")
    except Exception:
        pass
    return {"ok": True, "zone": zone, "key": k, "trust": float(trust)}


# Taches posees par apply_fact_sync sur une boucle deja active : la reference forte
# empeche le ramasse-miettes de les detruire avant la fin de l'ecriture.
_TACHES_FOND: set = set()


def apply_fact_sync(zone: str, fact: str, **kw: Any) -> dict:
    """`apply_fact` depuis du code SYNCHRONE, qu'une boucle asyncio tourne ou non.

    `propose_fact` n'a jamais existe dans ce module : deux appelants synchrones
    (forge_comm_watch, forge_presence) l'importaient et l'ImportError tombait dans leur
    except -- aucun de leurs faits n'a jamais atteint le tableau noir (851 avertissements
    de comm_watch le 2026-10-01). Les memes parametres que `apply_fact`, `ring` compris :
    discovered_facts exige ring<=2, le defaut 4 rend {"error": "ACL..."} sans exception.

    Sans boucle (script, daemon) : asyncio.run, le resultat revient tel quel.
    Dans une boucle (hub, gate) : asyncio.run leverait RuntimeError, et une ecriture
    synchrone figerait la boucle -- la tache est posee sur la boucle courante (meme verrou
    que les autres ecritures du hub) et le retour est {"ok": None, "planifie": True} :
    DEMANDE, pas ATTEINT. Un refus ulterieur est ecrit sur stderr, jamais avale.
    """
    try:
        boucle = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(apply_fact(zone, fact, **kw))
    tache = boucle.create_task(apply_fact(zone, fact, **kw))
    _TACHES_FOND.add(tache)
    tache.add_done_callback(_fin_tache_fond)
    return {"ok": None, "planifie": True, "zone": zone}


def _fin_tache_fond(tache: "asyncio.Task") -> None:
    _TACHES_FOND.discard(tache)
    if tache.cancelled():
        r: Any = {"error": "tache annulee avant l'ecriture"}
    elif tache.exception() is not None:
        e = tache.exception()
        r = {"error": f"{type(e).__name__}: {e}"}
    else:
        r = tache.result()
    if not (r or {}).get("ok"):
        print(f"[blackboard] fait planifie NON ecrit : {str(r)[:200]}", file=sys.stderr, flush=True)


def read_zone(zone: str, *, category: Optional[str] = None,
              min_trust: Optional[float] = None, limit: int = 200) -> list[dict]:
    """Lecture condensée d'UNE zone (anti lost-in-the-middle)."""
    zone = (zone or "").strip()
    if not zone:
        return []
    q = ("SELECT key,value,category,trust,worker_id,updated_at "
         "FROM swarm_blackboard WHERE zone=?")
    args: list[Any] = [zone]
    if category:
        q += " AND category=?"
        args.append(category)
    if min_trust is not None:
        q += " AND trust>=?"
        args.append(float(min_trust))
    q += " ORDER BY updated_at DESC LIMIT ?"
    args.append(int(limit))
    c = _conn()
    try:
        rows = c.execute(q, args).fetchall()
    finally:
        c.close()
    now = time.time()

    def _epoch(v) -> float:
        """`updated_at` en epoch, quelle que soit sa forme stockee.

        ZONE MORTE MESUREE (2026-07-26) : cinq faits ecrits le 2026-07-05 portent
        un horodatage TEXTE ISO au lieu d'un flottant. `now - r[5]` levait alors
        TypeError et faisait echouer la lecture de la zone ENTIERE ; comme
        l'appelant (`forge_ssot_maintainer._read_arch_rules`) enveloppe tout dans
        un `except`, le domaine `rules` du SSoT ne contenait plus qu'une erreur
        -- silencieusement, depuis trois semaines. Cinq lignes mal typees
        aveuglaient 412 faits.
        On REPARE LE LECTEUR plutot que de reecrire l'historique : les donnees
        anciennes restent intactes et lisibles. Illisible malgre tout -> age 0,
        donc trust plein : on n'invente pas une vetuste qu'on ne sait pas mesurer.
        """
        if isinstance(v, (int, float)):
            return float(v)
        try:
            from datetime import datetime as _dt

            return _dt.fromisoformat(str(v)).timestamp()
        except Exception:  # noqa: BLE001
            return now

    # trust EFFECTIF = trust stocké × décroissance exponentielle (demi-vie 7j).
    # Non destructif : trust brut conservé en DB, le decay est calculé au read.
    out = []
    for r in rows:
        _ts = _epoch(r[5])
        out.append(
            {"key": r[0], "value": r[1], "category": r[2], "trust": r[3],
             "effective_trust": round((r[3] or 0.0) * (0.5 ** ((now - _ts) / _TRUST_HALFLIFE_S)), 3),
             "age_days": round((now - _ts) / 86400, 2),
             "worker_id": r[4], "updated_at": r[5]}
        )
    return out


def list_zones() -> list[dict]:
    c = _conn()
    try:
        rows = c.execute(
            "SELECT zone, COUNT(*), MAX(updated_at) FROM swarm_blackboard "
            "GROUP BY zone ORDER BY 3 DESC"
        ).fetchall()
    finally:
        c.close()
    return [{"zone": r[0], "facts": r[1], "last_update": r[2]} for r in rows]


def gc(zone: str | None = None, max_age_days: float | None = None,
       min_trust: float | None = None) -> dict:
    """Purge ciblée (manuelle/daemon) : par zone, âge (jours), et/ou trust mini.
    L'auto-prune à l'écriture borne déjà les zones ; gc = nettoyage explicite."""
    cond: list[str] = []
    args: list = []
    if zone:
        cond.append("zone=?"); args.append(zone)
    if max_age_days is not None:
        cond.append("updated_at < ?"); args.append(time.time() - max_age_days * 86400)
    if min_trust is not None:
        cond.append("trust < ?"); args.append(float(min_trust))
    if not cond:
        return {"deleted": 0, "note": "aucun critère"}
    c = _conn()
    try:
        before = c.execute("SELECT COUNT(*) FROM swarm_blackboard").fetchone()[0]
        c.execute("DELETE FROM swarm_blackboard WHERE " + " AND ".join(cond), args)
        after = c.execute("SELECT COUNT(*) FROM swarm_blackboard").fetchone()[0]
    finally:
        c.close()
    return {"deleted": before - after}


def _selftest() -> int:
    global _ZONE_MAX_FACTS
    init_db()

    async def _checks():
        ok = await apply_fact(
            "discovered_facts", "API changed: UserEvent->SystemEvent",
            category="api", trust=0.9, source="tester", ring=2)
        reject = await apply_fact("mission", "tentative non autorisée", ring=3)
        again = await apply_fact(
            "discovered_facts", "API changed: UserEvent->SystemEvent",
            category="api", trust=0.9, source="tester", ring=2)
        for i in range(25):  # déborde le cap → teste l'auto-prune
            await apply_fact("scratch", f"fact numero {i}", category="t", ring=3)
        return ok, reject, again

    _ZONE_MAX_FACTS = 20  # cap abaissé pour le test
    try:
        ok, reject, again = asyncio.run(_checks())
        scratch = read_zone("scratch", limit=1000)
    finally:
        _ZONE_MAX_FACTS = 300

    assert ok.get("ok"), ok
    assert "error" in reject and "ACL" in reject["error"], reject
    assert ok["key"] == again["key"], (ok, again)  # idempotent
    assert len(scratch) <= 20, f"auto-prune cap KO: {len(scratch)}"

    rows = read_zone("discovered_facts", category="api")
    assert any("UserEvent" in r["value"] for r in rows), rows
    dup = [r for r in rows if r["key"] == ok["key"]]
    assert len(dup) == 1, f"idempotence cassée: {len(dup)} copies"

    g = gc(zone="scratch")
    print("SELFTEST OK", json.dumps(
        {"wrote": ok, "acl_reject": reject["error"], "scratch_capped": len(scratch),
         "gc_scratch_deleted": g, "zones": list_zones()}, ensure_ascii=False))
    return 0


# init idempotent à l'import (côté hub) — CREATE IF NOT EXISTS, coût négligeable.
# Best-effort : un contexte sans droits d'écriture ne doit pas casser l'import.
try:
    init_db()
except Exception:
    pass


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
