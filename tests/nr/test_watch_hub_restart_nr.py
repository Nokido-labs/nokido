"""NR : la veille des delegations signale un restart du hub.

Owner 6/11 : « quand tu emets des demandes de restart hub, il serait bien que tu captes que c'est fait ».
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import forge_job_watch_cli as W  # noqa: E402


def test_pid_du_hub_lu_au_superviseur_par_son_port():
    services = {"NokidoAutre": {"port": 8099, "pid": 1}, "LaForgeMCP": {"port": 8766, "pid": 42, "status": "running"}}
    assert W.pid_hub_depuis(services) == 42
    assert W.pid_hub_depuis({"NokidoAutre": {"port": 8099, "pid": 1}}) is None
    assert W.pid_hub_depuis(None) is None


def test_changement_de_pid_signale_une_fois():
    assert W.ligne_hub(None, 42) is None  # premiere lecture : reference, pas un restart
    assert W.ligne_hub(42, 42) is None
    assert "REDEMARRE" in W.ligne_hub(42, 77) and "77" in W.ligne_hub(42, 77)


def test_pid_illisible_nest_pas_un_restart_mais_se_dit():
    assert W.ligne_hub(42, None) is None  # le superviseur muet ne prouve pas un restart
    # le retour apres un silence avec un autre pid reste un restart
    assert "REDEMARRE" in W.ligne_hub(42, 77)


def test_la_veille_emet_la_ligne(monkeypatch):
    pids = iter([42, 42, 77])
    lignes = []
    monkeypatch.setattr(W, "lire_pid_hub", lambda: next(pids, 77))
    monkeypatch.setattr(W, "_lire_taches", lambda **k: ([], None))
    t = {"v": 0.0}

    def horloge():
        t["v"] += 5.0
        return t["v"]

    W.suivre_delegations(max_s=12, intervalle=0, ecrire=lignes.append, horloge=horloge, dormir=lambda s: None, barriere=False)
    assert any("REDEMARRE" in x for x in lignes)
    assert sum("REDEMARRE" in x for x in lignes) == 1


def test_la_barriere_garde_le_redemarrage(monkeypatch):
    pids = iter([42, 42, 77])
    lignes = []
    monkeypatch.setattr(W, "lire_pid_hub", lambda: next(pids, 77))
    monkeypatch.setattr(W, "_lire_taches", lambda **k: ([], None))
    t = {"v": 0.0}

    def horloge():
        t["v"] += 5.0
        return t["v"]

    W.suivre_delegations(max_s=12, intervalle=0, ecrire=lignes.append, horloge=horloge, dormir=lambda s: None, barriere=True)
    import json as _j
    # parser la derniere ligne recue par ecrire en JSON
    redemarres = _j.loads(lignes[-1])["hub_redemarre"]
    assert len(redemarres) == 1 and "REDEMARRE" in redemarres[0]
    # aucune autre ligne ecrite
    assert len(lignes) == 1
