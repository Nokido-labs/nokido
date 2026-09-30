"""Non-regression : une phase circadienne ne se solde que si elle a REELLEMENT guéri.

Defaut mesure le 2026-08-25 dans `forge_circadian.fire_phase` : `mark_completed(phase)`
etait appele inconditionnellement, en fin de fonction. Deux consequences distinctes :

  1. une phase dont TOUTES les actions echouaient effacait quand meme la dette de
     sommeil — le corps se croyait repose sans avoir gueri ;
  2. l'appel avait lieu AUSSI en `dry_run`. Une simulation mutait donc l'etat
     physiologique. Un banc d'essai qui modifie le patient n'est pas un banc d'essai.

Meme famille que le watchdog corrige le meme jour : parcourir une action n'est pas
l'avoir reussie. Un effecteur qui journalise son succes sans mesurer son effet rend
toute la boucle de regulation aveugle a ses propres echecs.

Hermetique : actions et etat sont des doublures. Aucun service n'est redemarre, et
`sandbox/circadian_state.json` n'est jamais touche.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import forge_circadian as fc  # noqa: E402


class _Action:
    """Doublure minimale : `fire_phase` ne lit que ces quatre attributs. On evite
    ainsi de dependre de la signature exacte de `PhaseAction`, qui n'est pas le sujet
    du test."""

    def __init__(self, name, handler=None, service=None, organ="test"):
        self.name = name
        self.handler = handler
        self.service = service
        self.organ = organ


class _Etat:
    """Etat physiologique en memoire : on observe s'il a ete solde, sans jamais
    ecrire le fichier reel."""

    def __init__(self):
        self.soldees = []
        self.dette = True

    def mark_completed(self, phase):
        self.soldees.append(phase)
        self.dette = False

    def has_sleep_debt(self):
        return self.dette


@pytest.fixture()
def phase(monkeypatch):
    p = list(fc.Phase)[0]
    monkeypatch.setattr(fc, "PHASE_PROGRAM", dict(fc.PHASE_PROGRAM))
    return p


def test_une_simulation_ne_solde_jamais_la_phase(phase, monkeypatch):
    """Le defaut le plus tranchant : `--dry-run` effacait la dette de sommeil sans
    qu'aucune action n'ait lieu."""
    appelee = []
    fc.PHASE_PROGRAM[phase] = [_Action("janitor", handler=lambda: appelee.append(1))]
    etat = _Etat()
    r = fc.fire_phase(phase, state=etat, dry_run=True)
    assert appelee == [], "une simulation a execute une action"
    assert etat.soldees == [], "une simulation a solde la phase"
    assert r["completed"] is False
    assert etat.has_sleep_debt() is True


def test_une_phase_en_echec_conserve_la_dette(phase):
    """La dette de sommeil est le SEUL signal qui reclame une reprise. L'effacer sur
    un echec, c'est supprimer la demande de soin en meme temps que le soin."""

    def _casse():
        raise RuntimeError("janitor indisponible")

    fc.PHASE_PROGRAM[phase] = [_Action("ok", handler=lambda: {"ok": True}),
                               _Action("janitor", handler=_casse)]
    etat = _Etat()
    r = fc.fire_phase(phase, state=etat)
    assert etat.soldees == []
    assert r["completed"] is False
    assert r["echecs"] == ["janitor"]
    assert etat.has_sleep_debt() is True


def test_une_action_qui_rend_ok_false_compte_comme_echec(phase):
    """Un effecteur qui REND un echec vaut une exception : ne compter que les
    exceptions laisserait passer tous les refus polis."""
    fc.PHASE_PROGRAM[phase] = [_Action("restart", handler=lambda: {"ok": False})]
    etat = _Etat()
    r = fc.fire_phase(phase, state=etat)
    assert r["completed"] is False
    assert etat.soldees == []


def test_une_phase_reussie_est_bien_soldee(phase):
    """Temoin indispensable : la post-condition doit laisser passer le succes, sinon
    la dette ne redescendrait JAMAIS et le corps ne dormirait plus."""
    fc.PHASE_PROGRAM[phase] = [_Action("ok", handler=lambda: {"ok": True}),
                               _Action("symbolique")]
    etat = _Etat()
    r = fc.fire_phase(phase, state=etat)
    assert etat.soldees == [phase]
    assert r["completed"] is True
    assert r["echecs"] == []
    assert etat.has_sleep_debt() is False


def test_le_motif_du_refus_est_explicite(phase):
    """Un refus muet se lit comme une panne du circadien lui-meme. La raison voyage
    avec le verdict."""
    fc.PHASE_PROGRAM[phase] = [_Action("x", handler=lambda: {"ok": False})]
    r = fc.fire_phase(phase, state=_Etat())
    assert r["motif"] and "echec" in r["motif"].lower()
