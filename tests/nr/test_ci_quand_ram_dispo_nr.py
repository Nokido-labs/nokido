# -*- coding: utf-8 -*-
"""NR — `forge_ci_quand_ram_dispo` attend la RAM, et sait QUEL refus il attend.

Mesure du 2026-09-22 qui a fait ce module : sa premiere version traitait tout
refus de la lane comme transitoire, et a boucle 23 fois sur un `unauthorized`
que le temps ne pouvait pas lever. Ce NR exerce `main()` -- le chemin reel --
avec la RAM, l'admission et l'horloge simulees : aucun appel au hub, aucune
attente reelle.
"""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
M = importlib.import_module("forge_ci_quand_ram_dispo")


def _simuler(monkeypatch, rams, reponses):
    """Rend la liste des appels d'admission ; RAM et reponses consommees dans l'ordre."""
    rams, reponses, appels = list(rams), list(reponses), []
    monkeypatch.setattr(M, "_ram", lambda: rams.pop(0) if len(rams) > 1 else rams[0])

    def _tenter(sha):
        appels.append(sha)
        return reponses.pop(0)

    monkeypatch.setattr(M, "_tenter_ci", _tenter)
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    return appels


def test_sans_sha_refuse_avec_rc_2():
    assert M.main([]) == 2


def test_unauthorized_ARRETE_au_lieu_de_boucler(monkeypatch):
    """Le defaut paye : un refus d'authentification n'est pas un manque de RAM."""
    appels = _simuler(monkeypatch, [(50.0, 8.0)],
                      [{"ok": False, "reason": "unauthorized"}] * 30)
    assert M.main(["abc1234"]) == 2
    assert appels == ["abc1234"], f"{len(appels)} tentatives sur un refus DEFINITIF"


def test_RAM_insuffisante_ne_demande_PAS_l_admission(monkeypatch):
    """Le garde de la lane n'est pas sollicite tant que la machine ne peut pas accepter."""
    appels = _simuler(monkeypatch, [(90.0, 2.0), (90.0, 2.0), (70.0, 6.0)],
                      [{"ok": True, "job_id": "job_x", "pid": 1}])
    assert M.main(["abc1234", "--seuil-go", "4.2"]) == 0
    assert appels == ["abc1234"], "admission demandee alors que la RAM etait sous le seuil"


def test_refus_TRANSITOIRE_reessaie_puis_admis(monkeypatch):
    appels = _simuler(monkeypatch, [(60.0, 8.0)],
                      [{"ok": False, "reason": "ram_saturee"},
                       {"ok": True, "job_id": "job_y", "pid": 2}])
    assert M.main(["abc1234"]) == 0
    assert len(appels) == 2


def test_RAM_ILLISIBLE_n_est_pas_une_machine_saturee(monkeypatch):
    """Trois etats : illisible -> on tente, la lane tranche. Jamais une attente sans fin."""
    appels = _simuler(monkeypatch, [(None, None)],
                      [{"ok": True, "job_id": "job_z", "pid": 3}])
    assert M.main(["abc1234"]) == 0
    assert appels == ["abc1234"]


def test_plafond_ABANDONNE_en_le_disant(monkeypatch, capsys):
    """Le silence n'est pas un succes : au-dela du plafond, rc=1 et une ligne ABANDON."""
    _simuler(monkeypatch, [(95.0, 1.0)], [])
    monkeypatch.setattr(M, "PLAFOND_S", 0)
    assert M.main(["abc1234"]) == 1
    assert "ABANDON" in capsys.readouterr().out
