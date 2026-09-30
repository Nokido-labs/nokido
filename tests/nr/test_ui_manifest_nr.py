"""NR — le manifest vivant de l'interface.

Ce qu'on protege : (1) une capacite se DECLARE, jamais deduite d'un nom de
fichier -- un organe non declare reste invisible ; (2) l'etat reflete la
LIVENESS reelle, jamais un faux « live » ; (3) la nouveaute decroit ; (4) une
surface dormant/absent pese moins qu'une vivante.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_une_capacite_se_declare_jamais_ne_s_infere():
    """Chaque surface visible vient du registre-contrat, avec des capacites
    explicites. Rien n'apparait par magie depuis un nom de fichier."""
    import forge_ui_manifest as M

    assert M.SURFACES, "registre vide"
    for nom, s in M.SURFACES.items():
        assert s.get("capabilities"), f"{nom} sans capacite declaree"
        assert "probe" in s


def test_l_etat_reflete_la_liveness_reelle(monkeypatch):
    import forge_ui_manifest as M

    # port ouvert -> live ; ferme -> dormant
    monkeypatch.setattr(M, "_port_ouvert", lambda p: p == 7500)
    assert M._etat({"probe": ("port", 7500)}) == "live"
    assert M._etat({"probe": ("port", 7430)}) == "dormant"
    # in-process -> internal ; chemin absent -> absent
    assert M._etat({"probe": ("internal", None)}) == "internal"
    monkeypatch.setattr("os.path.isdir", lambda p: False)
    assert M._etat({"probe": ("path", "laforge-redteam")}) == "absent"


def test_un_backend_eteint_n_est_jamais_live(monkeypatch):
    """Un backend réseau dont le port ne répond pas doit être DORMANT, jamais
    live -- c'est la racine du problème « onglet mort qui promet une capacité
    absente ». (Les surfaces offensives ctf/recon ont quitté le cœur le
    2026-09-01 ; on garde l'invariant sur les backends réseau subsistants.)"""
    import forge_ui_manifest as M

    monkeypatch.setattr(M, "_port_ouvert", lambda p: False)
    m = M.manifest(persist=False)
    etats = {s["surface"]: s["etat"] for s in m["surfaces"]}
    assert etats["graph"] == "dormant"
    assert etats["dashboard"] == "dormant"
    assert m["resume"]["vivants"] >= 2  # les organes internal restent vivants


def test_la_nouveaute_decroit(tmp_path, monkeypatch):
    import forge_ui_manifest as M

    seen = {}
    n0, seen = M._novelty("x", seen, 1000.0)
    assert n0 == 1.0  # premiere apparition
    n_plus_tard, _ = M._novelty("x", seen, 1000.0 + 24 * 3600)  # 24h plus tard
    assert n_plus_tard < n0


def test_dormant_pese_moins_qu_une_surface_vivante(monkeypatch):
    """L'importance effective baisse pour une surface sans rien a montrer."""
    import forge_ui_manifest as M

    # tout dormant
    monkeypatch.setattr(M, "_port_ouvert", lambda p: False)
    monkeypatch.setattr("os.path.isdir", lambda p: False)
    m = M.manifest(persist=False)
    imp = {s["surface"]: s["importance"] for s in m["surfaces"]}
    # regulation (internal, base 0.75) doit peser plus que graph (dormant, base 0.5)
    assert imp["regulation"] > imp["graph"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
