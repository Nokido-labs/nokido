"""NR — un pouls SANS service declare ET d'agent joker « * » est ORPHELIN, pas « cense tourner » (2026-11-07).

Mesure : `sandbox/hb.heartbeat` (57 o, pid 18944, agent « * ») ; aucun service `hb`. AUTEUR : le test
`test_executeur_delegations_paralleles_nr` remplace `_hb_file` par `tmp_path/"hb"` -> `.stem == "hb"` ->
`beat_daemon("hb", agent="*")` ecrit dans le VRAI sandbox (`_ROOT` de forge_heartbeat n'etait pas isole).
Symetrie : un autre pouls sans identite (agent reel, ou absent) reste une panne visible, jamais masque.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import forge_health_diagnostic as HD  # noqa: E402


def _pouls(sandbox: Path, nom: str, **extra) -> None:
    vieux = (datetime.now() - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%S")
    (sandbox / f"{nom}.heartbeat").write_text(json.dumps({"ts": vieux, "pid": 1, **extra}), encoding="utf-8")


def _auditer(tmp_path, monkeypatch):
    sb = tmp_path / "sandbox"
    sb.mkdir()
    _pouls(sb, "hb", agent="*")
    _pouls(sb, "sans_identite")                    # pas d'agent
    _pouls(sb, "agent_reel", agent="claude")        # agent nomme, pas de service
    monkeypatch.setattr(HD, "SANDBOX", sb)
    monkeypatch.setattr(HD, "_hb_declares_par_services_toml", lambda: {"x": "sandbox/autre.heartbeat"})
    monkeypatch.setattr(HD, "_service_desactive", lambda nom: None)
    return HD.audit_workers_heartbeat()


def test_pouls_joker_sans_service_est_orphelin(tmp_path, monkeypatch):
    w = _auditer(tmp_path, monkeypatch)
    assert w["hb"].get("orphelin") is True
    assert not w["sans_identite"].get("orphelin")
    assert not w["agent_reel"].get("orphelin")


def _gaps(workers):
    class Tolerant(defaultdict):
        def get(self, k, d=None):
            return self[k] if k in self else (d if d is not None else 0)

    for _op in ("__gt__", "__lt__", "__ge__", "__le__"):
        setattr(Tolerant, _op, lambda self, o: False)

    def _t():
        return Tolerant(_t)

    class Audit(dict):
        def __missing__(self, k):
            return _t()
    a = Audit(workers_heartbeat=workers, rag_chunks={"vector_pending": 0, "non_vectorized": 0},
              biblio={"topics_total": 1, "raw_by_status": {}}, tables_empty={"empty_tables": []})
    return HD.compute_score_and_gaps(a)[1]


def test_orphelin_affiche_a_part_et_autres_restent_en_panne(tmp_path, monkeypatch):
    w = _auditer(tmp_path, monkeypatch)
    gaps = _gaps(w)
    censes = [g for g in gaps if "CENSES TOURNER" in g]
    assert censes, "les pouls sans identite non joker doivent rester accuses"
    assert "'hb'" not in censes[0], "l'orphelin ne doit pas etre compte comme organe cense tourner"
    assert "'sans_identite'" in censes[0] and "'agent_reel'" in censes[0]
    orph = [g for g in gaps if "ORPHELIN" in g]
    assert orph and "'hb'" in orph[0]
