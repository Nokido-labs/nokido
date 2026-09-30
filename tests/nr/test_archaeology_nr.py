"""NR — l'archeologie fonctionnelle (Phase 1).

Ce qu'on protege : (1) le classement se fait sur PREUVE, jamais « mort » par
defaut ; (2) MOVED distingue une feature migree d'une vraie suppression ; (3) le
bruit (attic/tmp/backups) est signale, jamais confondu avec du patrimoine ; (4)
un depot absent est NOMME, pas ignore en silence.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_le_bruit_est_reconnu():
    import forge_archaeology as A

    assert A._est_bruit("app/_attic/vieux.py")
    assert A._est_bruit("tools/tmp_x.py")
    assert A._est_bruit("sandbox/backups/y.py")
    assert not A._est_bruit("app/forge_regulation_learner.py")


def test_moved_vs_deleted_sur_preuve(monkeypatch, tmp_path):
    """Un module supprime ici mais vivant ailleurs = MOVED ; introuvable partout
    = DELETED. Jamais « mort » sans avoir cherche dans les autres depots."""
    import forge_archaeology as A

    # deux depots factices ; on simule leurs sorties git
    monkeypatch.setattr(A, "_est_depot", lambda p: True)
    monkeypatch.setattr(A, "head_basenames",
                        lambda repo: {"survivant.py"} if "web" in repo else set())

    def _deleted(repo):
        if "core" in repo:
            return [
                {"chemin": "app/survivant.py", "sha_suppr": "a1", "date_suppr": "2026-05-01",
                 "msg_suppr": "move to web", "bruit": False},
                {"chemin": "app/vraiment_mort.py", "sha_suppr": "a2", "date_suppr": "2026-05-02",
                 "msg_suppr": "drop", "bruit": False},
            ]
        return []

    monkeypatch.setattr(A, "deleted", _deleted)
    res = A.classer({"core": "/core", "web": "/web"})
    etats = {m["chemin"]: m["etat"] for m in res["modules"]}
    assert etats["app/survivant.py"] == "MOVED"        # vit dans web
    assert etats["app/vraiment_mort.py"] == "DELETED"  # introuvable
    moved = next(m for m in res["modules"] if m["etat"] == "MOVED")
    assert "web" in moved["vit_dans"]


def test_un_depot_absent_est_nomme(monkeypatch):
    import forge_archaeology as A

    monkeypatch.setattr(A, "_est_depot", lambda p: "present" in p)
    monkeypatch.setattr(A, "head_basenames", lambda repo: set())
    monkeypatch.setattr(A, "deleted", lambda repo: [])
    res = A.classer({"present": "/x/present", "manquant": "/y/manquant"})
    assert "manquant" in res["depots_absents"]
    assert "present" in res["depots_analyses"]


def test_le_bruit_ne_compte_pas_comme_patrimoine(monkeypatch):
    import forge_archaeology as A

    monkeypatch.setattr(A, "_est_depot", lambda p: True)
    monkeypatch.setattr(A, "head_basenames", lambda repo: set())
    monkeypatch.setattr(A, "deleted", lambda repo: [
        {"chemin": "app/_attic/x.py", "sha_suppr": "a", "date_suppr": "2026-01-01",
         "msg_suppr": "", "bruit": True}])
    res = A.classer({"r": "/r"})
    assert res["modules"][0]["etat"] == "NOISE"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
