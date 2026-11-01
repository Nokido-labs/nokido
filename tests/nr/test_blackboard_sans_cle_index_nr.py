# -*- coding: utf-8 -*-
"""NR -- plan d'economie de contexte (owner 1/11, etape 2) : `blackboard_read_zone` SANS cle ni prefixe sur une
zone volumineuse rendait jusqu'a ~50 000 caracteres de faits, relus a chaque tour. Au-dela d'un seuil, le handler
rend l'INDEX des cles (cle, categorie, age, taille) et dit comment cibler ; une petite zone, une cle, un prefixe ou
`full=true` rendent les faits comme avant (non regressif)."""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.forge_mcp_registry import ToolRegistry  # noqa: E402


def _faits(n, taille):
    return [{"key": "k%03d" % i, "value": "v" * taille, "category": "c", "trust": 1.0,
             "effective_trust": 1.0, "age_days": 0.5, "worker_id": "w", "updated_at": 0.0} for i in range(n)]


def _brancher(monkeypatch, faits):
    vus = []

    def _rz(zone, **kw):
        vus.append(kw)
        if kw.get("key"):
            return [f for f in faits if f["key"] == kw["key"]]
        return list(faits)

    for mod in ("nokido_agent.app.forge_swarm_blackboard", "app.forge_swarm_blackboard"):
        try:
            monkeypatch.setattr(importlib.import_module(mod), "read_zone", _rz)
        except ImportError:
            pass
    return vus


def _lire(tmp_path, **args):
    reg = ToolRegistry(root_dir=tmp_path)
    return json.loads(asyncio.run(reg.handle_blackboard_read_zone({"zone_name": "z", **args}, "CLAUDE", 0)))


def test_grosse_zone_sans_cle_rend_l_index(tmp_path, monkeypatch):
    _brancher(monkeypatch, _faits(60, 2000))  # ~120 000 car. de valeurs
    r = _lire(tmp_path)
    assert "facts" not in r
    assert r["count"] == 60 and len(r["index"]) == 60
    assert r["index"][0]["key"] == "k000" and r["index"][0]["taille"] == 2000
    assert "key=" in r["conseil"] and '"full": true' in r["conseil"]
    assert len(json.dumps(r)) < 12000


def test_petite_zone_rend_les_faits(tmp_path, monkeypatch):
    _brancher(monkeypatch, _faits(3, 50))
    r = _lire(tmp_path)
    assert len(r["facts"]) == 3 and "index" not in r


def test_executeur_cible_la_cle_du_pointer_ref(tmp_path, monkeypatch):
    """Chemin reel : `_read_spec` lisait la zone ENTIERE puis cherchait sa cle ; sur une grosse zone, il aurait
    recu l'index et pris ce JSON pour la spec, en silence. Il passe desormais la cle au hub."""
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    import forge_task_executor as T

    _brancher(monkeypatch, _faits(60, 2000) + [{"key": "spec/x", "value": "corriger tools/forge_a.py", "category": "c",
                                                 "age_days": 0.1}])
    appels = []

    def _faux_hub(outil, args, token, timeout=30):
        appels.append(args)
        return asyncio.run(ToolRegistry(root_dir=tmp_path).handle_blackboard_read_zone(args, "CLAUDE", 0))

    monkeypatch.setattr(T, "_hub_call", _faux_hub)
    monkeypatch.setattr(T, "_hub_text", lambda r: r)
    spec, cible = T._read_spec(json.dumps({"pointer_ref": "blackboard:mission/spec/x"}), "jeton-factice")
    assert appels and appels[0].get("key") == "spec/x"
    assert spec == "corriger tools/forge_a.py" and cible == "tools/forge_a.py"


def test_cle_ou_full_rendent_les_faits(tmp_path, monkeypatch):
    _brancher(monkeypatch, _faits(60, 2000))
    assert len(_lire(tmp_path, key="k007")["facts"]) == 1
    assert len(_lire(tmp_path, filter={"full": True})["facts"]) == 60  # schema intouche (cliquet de poids)
    assert len(_lire(tmp_path, key_prefix="k0")["facts"]) == 60
