"""NR -- `nokido-composants --installer-chiffrement` : provisionnement OPT-IN du chiffrement at-rest hors CI.

Seul ce drapeau explicite sort provisionner_chiffrement du « CI seulement ». La commande est AFFICHEE avant d'etre
jouee, puis chiffrement_present() est resonde. Sans drapeau : aucune commande, rc 2, message qui cite le drapeau.
Executeur simule : aucune vraie installation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture
def banc(monkeypatch):
    for v in ("CI", "GITHUB_ACTIONS"):
        monkeypatch.delenv(v, raising=False)
    spec = importlib.util.spec_from_file_location("composants_opt_in_nr", RACINE / "tools" / "forge_composants.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    etat = {"poses": 0, "commandes": [], "present": False, "rc": 0}

    def poseur():
        etat["poses"] += 1
        return True, "ok"

    def executeur(cmd, **kw):
        etat["commandes"].append(list(cmd))
        if etat["rc"] == 0:
            etat["present"] = True
        return type("R", (), {"returncode": etat["rc"]})()
    monkeypatch.setattr(m, "COMPOSANTS", ("factice",))
    monkeypatch.setattr(m, "POSEURS", {"factice": poseur})
    monkeypatch.setattr(m, "chiffrement_present", lambda: etat["present"])
    monkeypatch.setattr(m, "refus_chiffrement", lambda: None)
    monkeypatch.setattr(m, "consigner_refus_chiffrement", lambda motif: "f")
    monkeypatch.setattr(m, "EXECUTEUR", executeur)
    monkeypatch.setattr(m, "systeme_nom", lambda: "Linux")
    return m, etat


def test_avec_drapeau_hors_ci_commande_jouee_une_fois_puis_pose(banc, capsys):
    m, etat = banc
    assert m.main(["--composant", "factice", "--installer-chiffrement"]) == 0
    assert len(etat["commandes"]) == 1 and "cryptsetup" in etat["commandes"][0]
    assert etat["poses"] == 1
    assert "cryptsetup" in capsys.readouterr().out, "la commande est affichee avant d'etre jouee"


def test_sans_drapeau_aucune_commande_rc2_et_drapeau_cite(banc, capsys):
    m, etat = banc
    rc = m.main(["--composant", "factice"])
    s = capsys.readouterr()
    assert rc == 2 and etat["commandes"] == [] and etat["poses"] == 0
    assert "--installer-chiffrement" in s.out + s.err


def test_commande_en_echec_rc2_aucun_poseur_motif_cite(banc, capsys):
    m, etat = banc
    etat["rc"] = 7
    rc = m.main(["--composant", "factice", "--installer-chiffrement"])
    s = capsys.readouterr()
    assert rc == 2 and len(etat["commandes"]) == 1 and etat["poses"] == 0
    assert "rc=7" in s.out + s.err
