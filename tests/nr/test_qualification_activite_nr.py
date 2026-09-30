"""Non-regression de la QUALIFICATION D'ACTIVITE (`tools/forge_organ_pulse._activite`).

CE QUE CES TESTS PROTEGENT

`_activite` repond a « cet organe bouge-t-il ? » avec TROIS reponses possibles, et la
troisieme est celle qu'on perd toujours :

    True   j'ai mesure du mouvement
    False  j'ai mesure l'inertie, sur des compteurs LISIBLES
    None   je n'ai pas pu mesurer

DEFAUT REEL QU'ILS FONT TOMBER (releve par l'owner sur le code publie en 9bf03d28c) :
quand les compteurs d'E/S etaient refuses mais le CPU lisible et plat, la fonction
rendait `False` -- c'est-a-dire « ca ne bouge pas » alors que la moitie de la mesure
manquait. Le commentaire du module disait l'inverse de ce que le code faisait. Un
organe I/O-bound (crawl, embedding distant, rebuild FTS) consomme un CPU quasi nul EN
TRAVAILLANT : il serait passe suspect, puis gele.

    ABSENCE DE PREUVE D'ACTIVITE  !=  PREUVE D'ABSENCE D'ACTIVITE

Ces cas sont SYNTHETIQUES a dessein : les branches d'illisibilite ne se produisent pas
a la demande sur une machine saine. Ils prouvent la LOGIQUE, ils ne mesurent pas le
monde -- c'est precisement pour ca qu'ils ne remplacent pas l'observation en vol, et
qu'aucun d'eux ne conclut quoi que ce soit sur l'etat reel des organes.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import pytest

_TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_organ_pulse as OP  # noqa: E402

psutil = pytest.importorskip("psutil")


class _Times:
    def __init__(self, total: float) -> None:
        self.user, self.system = total, 0.0


class _IO:
    def __init__(self, octets: float) -> None:
        self.read_bytes, self.write_bytes = octets, 0.0


class _Faux:
    """Process dont on pilote le CPU et les E/S. `io=None` => compteurs REFUSES."""

    def __init__(self, cpu: float, io) -> None:
        self._cpu, self._io = cpu, io

    def oneshot(self):
        return contextlib.nullcontext()

    def cpu_times(self):
        return _Times(self._cpu)

    def io_counters(self):
        if self._io is None:
            raise PermissionError("compteurs d'E/S refuses")
        return _IO(self._io)


@pytest.fixture(autouse=True)
def _memoire_vierge():
    """Chaque cas part sans reference : l'etat entre tours est global au module."""
    OP._ACTIVITE_PREC.clear()
    yield
    OP._ACTIVITE_PREC.clear()


def _deux_tours(monkeypatch, avant: tuple, apres: tuple):
    """Joue deux tours successifs et rend le verdict du second (le premier n'a pas
    de reference, il rend toujours None -- c'est teste a part)."""
    monkeypatch.setattr(psutil, "Process", lambda _pid: _Faux(*avant))
    premier = OP._activite("cas", 1234)
    monkeypatch.setattr(psutil, "Process", lambda _pid: _Faux(*apres))
    return premier, OP._activite("cas", 1234)


def test_premier_tour_ne_conclut_jamais(monkeypatch):
    """Sans reference, aucun delta : `None`, jamais `False`."""
    monkeypatch.setattr(psutil, "Process", lambda _pid: _Faux(10.0, 1000.0))
    actif, detail = OP._activite("cas", 1234)
    assert actif is None
    assert "reference" in detail


def test_cpu_plat_et_io_plate_donne_inertie_MESUREE(monkeypatch):
    """Cas 1 : les deux compteurs sont lisibles et immobiles -> False assume."""
    _, (actif, detail) = _deux_tours(monkeypatch, (10.0, 1000.0), (10.0, 1000.0))
    assert actif is False
    assert "io +0" in detail


def test_io_qui_augmente_donne_actif_meme_sans_cpu(monkeypatch):
    """Cas 2 : un travail I/O-bound consomme un CPU nul EN TRAVAILLANT."""
    _, (actif, detail) = _deux_tours(
        monkeypatch, (10.0, 1000.0), (10.0, 1000.0 + 10 * OP.ACT_IO_OCTETS))
    assert actif is True
    assert "io +" in detail


def test_io_illisible_avec_cpu_plat_ne_conclut_PAS_a_l_inertie(monkeypatch):
    """Cas 3 -- LE defaut du 2026-09-03. La moitie de la mesure manque : on ne sait
    pas, et on le DIT. Rendre False ici gelait un organe sain."""
    _, (actif, detail) = _deux_tours(monkeypatch, (10.0, None), (10.0, None))
    assert actif is None, "E/S illisibles + CPU plat = inconnu, jamais inerte"
    assert "ILLISIBLE" in detail and "NON" in detail


def test_cpu_qui_bouge_suffit_meme_si_les_io_sont_illisibles(monkeypatch):
    """Une preuve POSITIVE d'activite se suffit : l'illisibilite des E/S ne la
    retire pas. Rendre None ici perdrait une mesure valide."""
    _, (actif, _) = _deux_tours(
        monkeypatch, (10.0, None), (10.0 + 10 * OP.ACT_CPU_S, None))
    assert actif is True


def test_compteurs_qui_reculent_invalident_la_reference(monkeypatch):
    """Un pid reutilise par un autre process ferait un delta negatif : on ne
    fabrique pas un verdict sur une reference qui n'a plus de sens."""
    _, (actif, detail) = _deux_tours(monkeypatch, (100.0, 5000.0), (1.0, 10.0))
    assert actif is None
    assert "zero" in detail or "remplace" in detail


def test_un_process_absent_ou_sans_pid_ne_vaut_pas_une_inertie(monkeypatch):
    """Ne pas voir un organe n'est pas le voir immobile."""
    assert OP._activite("cas", None)[0] is None

    def _absent(_pid):
        raise psutil.NoSuchProcess(_pid)

    monkeypatch.setattr(psutil, "Process", _absent)
    assert OP._activite("cas", 4242)[0] is None
