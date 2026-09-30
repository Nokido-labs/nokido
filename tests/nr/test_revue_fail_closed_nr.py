# -*- coding: utf-8 -*-
"""NR — #9 : une revue ne peut plus etre approuvee sans que la separation ait ete verifiee.

Mesure du 24/09 (audit #9, contrat AUTH-6/AUTH-4) : `forge_review` JOURNALISAIT une revue
anonyme puis APPROUVAIT quand meme ; idem executant illisible ou garde introuvable. Et sa
branche `amended_results` melangeait parametres SQL nommes et positionnels (sqlite3 refuse :
elle levait a chaque appel).

Chemin reel : `forge_task_bus` et `forge_separation` REELS, base de taches temporaire.
Jumeau negatif (le seul decisif) : les voies faibles ne rendent PAS la meme autorite.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "app"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_task_bus as tb  # noqa: E402


@pytest.fixture
def bus(tmp_path, monkeypatch):
    monkeypatch.setattr(tb, "_DB_PATH", tmp_path / "tasks_nr.db")
    tb.ensure_schema()
    return tb


def _tache(bus, executeur="GEMINI"):
    t = bus.create_task(title="nr", description="d", executor=executeur)
    bus.submit_result(t["id"], [{"step": 1, "output": "x", "ok": True}])
    return t["id"]


def test_revue_anonyme_refusee(bus):
    tid = _tache(bus)
    assert bus.forge_review(tid, "approved") is False
    assert bus.get_task(tid)["status"] != "done", "une revue anonyme a clos la tache"


def test_auto_revue_refusee(bus):
    tid = _tache(bus, executeur="GEMINI")
    assert bus.forge_review(tid, "approved", acteur="GEMINI") is False


def test_executant_inconnu_refuse(bus):
    assert bus.forge_review("tache_inexistante", "approved", acteur=bus.ACTEUR_FORGE) is False


def test_juge_distinct_accepte(bus):
    """Contre-epreuve : le cas legitime doit toujours passer."""
    tid = _tache(bus, executeur="GEMINI")
    assert bus.forge_review(tid, "approved", acteur=bus.ACTEUR_FORGE) is True
    assert bus.get_task(tid)["status"] == "done"


def test_branche_amended_ne_leve_plus(bus):
    tid = _tache(bus, executeur="CLAUDE")
    assert bus.forge_review(tid, "amended", notes="corrige",
                            amended_results=[{"step": 1, "output": "y", "ok": True}],
                            acteur=bus.ACTEUR_FORGE) is True


def test_les_modes_de_collaboration_passent_un_acteur():
    """Aucun appel de forge_review sans acteur dans app/collab_modes (AST)."""
    import ast
    fautes = []
    for f in sorted((ROOT / "app" / "collab_modes").glob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "forge_review"
                    and not any(k.arg == "acteur" for k in n.keywords)):
                fautes.append("%s:%d" % (f.name, n.lineno))
    assert not fautes, "forge_review sans acteur : %s" % fautes
