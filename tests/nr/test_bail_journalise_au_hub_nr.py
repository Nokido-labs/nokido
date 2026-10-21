# -*- coding: utf-8 -*-
"""NR 20/10 -- chaque decision de `POST /api/resource/request` (bail) est JOURNALISEE cote hub.

Mesure du 20/10 : sandbox/hub.log* ne portait AUCUNE ligne de bail du 16/10 au 20/10, alors que la CI de
reference lisait « PRIS bail_... (ARME) ». Un refus 403 etait tout aussi invisible cote hub. Contrat : accord,
refus et entree invalide laissent une ligne (principal, action, statut) ; jamais de silence.
"""
import logging
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402


def _lignes(caplog):
    return [r.getMessage() for r in caplog.records if "bail" in r.getMessage()]


def test_entree_invalide_journalisee(caplog):
    caplog.set_level(logging.INFO)
    code, _, _ = rm._decider_bail("CI_REF", 2, {"action": "voler"})
    assert code == 400
    assert any("CI_REF" in l and "400" in l for l in _lignes(caplog))


def test_refus_arme_journalise(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(rm, "_bail_arme", lambda: True)
    code, _, _ = rm._decider_bail("SERVICE", 5, {"action": "acquerir", "motif": "x"})
    assert code == 403
    assert any("SERVICE" in l and "403" in l and "acquerir" in l for l in _lignes(caplog))


def test_accord_journalise_avec_l_identifiant(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(rm, "_bail_arme", lambda: False)
    monkeypatch.setattr(rm, "acquerir_bail", lambda p, m, c, t: {"etat": "ACTIF", "id": "bail_temoin"})
    code, _, _ = rm._decider_bail("CI_REF", 2, {"action": "acquerir", "motif": "CI"})
    assert code == 200
    assert any("CI_REF" in l and "200" in l and "bail_temoin" in l for l in _lignes(caplog))
