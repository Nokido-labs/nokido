"""NR -- les zones de GOUVERNANCE du tableau noir ne sont jamais elaguees (incident du 2026-10-13).

Une ecriture banale a declenche le prune amorti (1 ecriture sur 20) sur `architecture_rules` : le TTL de 14 jours a
supprime 81 des 103 faits roadmap, dont des P0, BLOCKER et P1 encore OUVERTS -- le SSoT (forge_ssot_maintainer) se
derive de cette zone et a perdu ses P0 d'un coup. Restaures depuis une copie prise avant l'elagage.

Invariants :
- `_prune` sur une zone perenne ne supprime RIEN (ni par TTL, ni par plafond) ;
- controle negatif : une zone de travail (scratch) reste elaguee par TTL ;
- `gc` refuse une zone perenne explicite, et une purge par age SANS zone epargne les zones perennes.
"""
# pylint: disable=protected-access
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_swarm_blackboard as B  # noqa: E402

_SCHEMA = ("CREATE TABLE swarm_blackboard (zone TEXT, key TEXT, value TEXT, category TEXT, trust REAL, "
           "worker_id TEXT, updated_at REAL, PRIMARY KEY(zone, key))")


def _base(tmp_path):
    chemin = tmp_path / "swarm.db"
    c = sqlite3.connect(chemin, isolation_level=None)
    c.execute(_SCHEMA)
    vieux = time.time() - 40 * 86400  # bien au-dela du TTL de 14 jours
    for zone in ("architecture_rules", "active_bugs", "scratch"):
        for i in range(3):
            c.execute("INSERT INTO swarm_blackboard VALUES (?,?,?,?,?,?,?)",
                      (zone, "k%d" % i, "P0: item %d" % i, "roadmap", 0.9, "nr", vieux))
    return chemin, c


def _compte(c, zone):
    return c.execute("SELECT COUNT(*) FROM swarm_blackboard WHERE zone=?", (zone,)).fetchone()[0]


def test_le_prune_n_elague_jamais_une_zone_perenne(tmp_path):
    """Le cas de l'incident : des faits de 40 jours dans architecture_rules survivent au prune."""
    _, c = _base(tmp_path)
    B._prune(c, "architecture_rules")
    B._prune(c, "active_bugs")
    assert _compte(c, "architecture_rules") == 3
    assert _compte(c, "active_bugs") == 3


def test_controle_negatif_une_zone_de_travail_reste_elaguee(tmp_path):
    """scratch est du travail jetable : le TTL s'y applique toujours."""
    _, c = _base(tmp_path)
    B._prune(c, "scratch")
    assert _compte(c, "scratch") == 0


def test_gc_epargne_les_zones_perennes(tmp_path, monkeypatch):
    """gc explicite sur une zone perenne : refuse et dit ; gc par age sans zone : scratch purge, gouvernance intacte."""
    chemin, c = _base(tmp_path)
    monkeypatch.setattr(B, "_conn", lambda: sqlite3.connect(chemin, isolation_level=None))
    r = B.gc(zone="architecture_rules", max_age_days=1)
    assert r["deleted"] == 0 and "perenne" in r.get("note", "")
    r = B.gc(max_age_days=1)
    assert r["deleted"] == 3
    assert _compte(c, "architecture_rules") == 3 and _compte(c, "active_bugs") == 3 and _compte(c, "scratch") == 0
