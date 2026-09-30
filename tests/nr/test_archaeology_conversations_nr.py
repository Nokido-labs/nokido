"""NR — le crosswalk conversation <-> code <-> archeologie (Phases 3 & 4).

Ce qu'on protege : (1) une idee sans trace commit MAIS qui matche un vestige =
VESTIGE (recuperable), pas NOT_FOUND ; (2) le matching exige une vraie preuve
(>=2 tokens partages), jamais un lien fabrique ; (3) forte couverture = IMPLEMENTED.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_tokens_ignore_le_bruit():
    import forge_archaeology_conversations as C

    t = C._tokens("faire un recon_master pour Nokido avec scapy")
    assert "recon_master" in t  # les underscores sont permis : un seul token
    assert "scapy" in t
    assert "pour" not in t and "nokido" not in t  # stop-words / bruit ecarte
    assert "un" not in t  # trop court (<4)


def test_un_lien_vestige_exige_une_vraie_preuve():
    import forge_archaeology_conversations as C

    idx = C._index_vestiges([
        {"chemin": "recon_silo/recon_master.py", "depot": "nokido", "etat": "DELETED"}])
    # 2 tokens partages (recon, master) -> match
    v, inter = C._meilleur_vestige({"recon", "master", "scan"}, idx)
    assert v is not None and len(inter) >= 2
    # 1 seul token -> pas de lien fabrique
    v2, inter2 = C._meilleur_vestige({"recon", "autre_chose_sans_rapport"}, idx)
    assert v2 is None


def test_le_crosswalk_classe_sur_couverture_et_vestige(monkeypatch):
    import forge_archaeology_conversations as C

    # intentions minees factices
    monkeypatch.setattr(C, "phase3_intentions", lambda: {"ok": True, "tours_owner": 3,
        "intentions": [
            {"signature": "add:recon master scan", "occurrences": 5, "couverture_git": 0.1,
             "portee": "courte", "exemples": ["faire un recon master scan reseau"]},
            {"signature": "add:dashboard vitals", "occurrences": 2, "couverture_git": 0.9,
             "portee": "courte", "exemples": ["dashboard vitals"]},
            {"signature": "add:truc jamais code", "occurrences": 1, "couverture_git": 0.0,
             "portee": "courte", "exemples": ["un truc jamais code du tout"]},
        ]})
    monkeypatch.setattr(C, "_vestiges_non_bruit", lambda: [
        {"chemin": "recon_silo/recon_master.py", "depot": "nokido", "etat": "DELETED"}])

    res = C.crosswalk()
    etats = {r["signature"]: r["etat"] for r in res["crosswalk"]}
    assert etats["add:recon master scan"] == "VESTIGE"      # sans trace mais vestige matche
    assert etats["add:dashboard vitals"] == "IMPLEMENTED"   # couverture forte
    assert etats["add:truc jamais code"] == "NOT_FOUND"     # rien nulle part
    vest = next(r for r in res["crosswalk"] if r["etat"] == "VESTIGE")
    assert "recon_master" in vest["vestige"]


def test_intent_miner_ko_rend_indetermine(monkeypatch):
    import forge_archaeology_conversations as C

    monkeypatch.setattr(C, "phase3_intentions", lambda: {"ok": False, "raison": "base absente"})
    res = C.crosswalk()
    assert res["ok"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
