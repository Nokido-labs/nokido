"""Contrat de representation du seuil RAM : UNIT, INTEGRATION, SIMULATION.

DEFAUT MESURE le 2026-09-13. `LAFORGE_RAM_THRESHOLD` est REEL-VALUE -- la
configuration du corps la pose a "95.0" -- et deux organes la lisaient avec des
types INCOMPATIBLES :

    forge_resource_manager.should_throttle  ->  float(...)   conforme
    forge_promotion_queue                   ->  int(...)     cassait sur "95.0"

Le defaut etait MASQUE : le seul test qui rechargeait ce module
(`test_new_modules_nr::test_orchestrator_cloud_workers`) s'appuyait sur
`importlib.reload`, inerte sur un module ponte tant que
`nokido_agent/__init__.py` n'avait pas ete repare. La ligne n'etait jamais
reevaluee et le test passait SANS RIEN VERIFIER. Reparer le rechargement a fait
remonter le defaut -- c'est la raison d'etre de ce fichier.

TROIS NIVEAUX, nommes pour etre lisibles dans le rapport :

    test_unit_*         le module interprete-t-il correctement la valeur ?
    test_integration_*  les DEUX organes en tirent-ils la meme valeur ?
    test_simulation_*   dans cet etat metabolique, la DECISION est-elle la bonne ?

La simulation est le niveau qui manquait : un parsing correct ne prouve pas une
decision correcte. Le scenario C le montre -- une troncature a 95 ferait
attendre a 95,2 % un organe que l'autre laisse passer.

CE FICHIER NE REVEILLE PAS LE CORPS. Il n'importe ni `bootstrap` (mesure du
jour : il demarre un IdleWatchdog, un IntegrityManager et bute sur le garde
d'ecriture), ni service, ni llama. Les capteurs sont injectes.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import threading
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent.parent
for _p in (str(_RACINE), str(_RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

CLE = "LAFORGE_RAM_THRESHOLD"
DEFAUT = 88.0


class _Memoire:
    """Vue minimale de psutil.virtual_memory() : seul `percent` est consulte."""

    def __init__(self, pct: float) -> None:
        self.percent = pct


@pytest.fixture(autouse=True)
def _rendre_le_module_propre():
    """Retire les DEUX clefs apres chaque test.

    Le module fige son seuil a l'import : le laisser charge avec une valeur de
    test ferait de ce fichier le pollueur qu'il denonce. Retirer les deux noms
    -- plat et ponte -- garantit un etat propre quel que soit l'etat du pont.
    """
    yield
    for clef in ("forge_promotion_queue",
                 "nokido_agent.app.forge_promotion_queue"):
        sys.modules.pop(clef, None)


def _charger(monkeypatch, valeur):
    """Recharge le module avec CETTE valeur de configuration, et rien d'autre."""
    if valeur is None:
        monkeypatch.delenv(CLE, raising=False)
    else:
        monkeypatch.setenv(CLE, valeur)
    import forge_promotion_queue as fpq

    return importlib.reload(fpq)


# ----------------------------------------------------------------- UNIT

@pytest.mark.parametrize("brut, attendu", [
    ("95", 95.0),        # forme entiere : toujours acceptee
    ("95.0", 95.0),      # forme REELLE : celle de la configuration du corps
    ("95.5", 95.5),      # reel non entier : ne doit pas etre tronque
    (None, DEFAUT),      # variable absente : defaut du module
])
def test_unit_le_seuil_accepte_la_forme_reelle(monkeypatch, brut, attendu):
    fpq = _charger(monkeypatch, brut)
    assert fpq.RAM_THRESHOLD_PCT == pytest.approx(attendu)


def test_unit_aucune_troncature_silencieuse(monkeypatch):
    """`int(float("95.5"))` rendrait 95 : une incoherence troquee contre une perte."""
    fpq = _charger(monkeypatch, "95.5")
    assert fpq.RAM_THRESHOLD_PCT == pytest.approx(95.5)
    assert fpq.RAM_THRESHOLD_PCT != 95


def test_unit_une_valeur_invalide_echoue_EXPLICITEMENT(monkeypatch):
    """Jamais de repli muet sur le defaut : une config fausse doit se voir."""
    with pytest.raises(ValueError):
        _charger(monkeypatch, "quatre-vingt-quinze")


# ---------------------------------------------------------- INTEGRATION

def test_integration_les_deux_organes_lisent_le_meme_contrat(monkeypatch):
    """Chemin REEL des deux lecteurs, meme variable, meme session.

    `should_throttle` relit l'environnement A CHAQUE APPEL (bon pattern) la ou
    `forge_promotion_queue` fige a l'import : on ne compare donc pas deux
    constantes, on compare la valeur figee a la DECISION de l'autre organe.
    Tout ce qui n'est pas la RAM est neutralise -- `cortisol_threshold=1.01` est
    le contournement documente dans forge_resource_manager (L1872).
    """
    import psutil

    fpq = _charger(monkeypatch, "95.5")
    assert fpq.RAM_THRESHOLD_PCT == pytest.approx(95.5)

    import forge_resource_manager as frm

    monkeypatch.setattr(psutil, "virtual_memory", lambda: _Memoire(95.2))
    presse = frm.should_throttle(
        ram_pct_threshold=DEFAUT,      # ecrase par la variable d'environnement
        cpu_pct_threshold=999.0, gpu_pct_threshold=999.0,
        disk_pct_threshold=999.0, tdr_quarantine=False,
        cortisol_threshold=1.01,
    )
    # 95,2 < 95,5 : aucun des deux organes ne doit voir de pression.
    assert presse is False, "should_throttle freine a 95,2 % sous un seuil de 95,5"
    assert (95.2 > fpq.RAM_THRESHOLD_PCT) is False


# ----------------------------------------------------------- SIMULATION

@pytest.mark.parametrize("nom, seuil, ram, attente_attendue", [
    ("A  seuil 95.0 / RAM 90.0 -> capacite disponible", "95.0", 90.0, False),
    ("B  seuil 95.0 / RAM 96.0 -> pression, attente", "95.0", 96.0, True),
    ("C  seuil 95.5 / RAM 95.2 -> PAS d'attente (tronque a 95 : faux positif)",
     "95.5", 95.2, False),
    ("D  seuil 95.5 / RAM 95.9 -> pression, attente", "95.5", 95.9, True),
])
def test_simulation_la_decision_du_regulateur(monkeypatch, nom, seuil, ram,
                                              attente_attendue):
    """Scenarios metaboliques deterministes : on juge la DECISION, pas le parsing.

    Le scenario C est celui qui justifie le refus de `int(float(...))` : avec un
    seuil tronque a 95, une RAM a 95,2 % declencherait une attente que
    `should_throttle`, lui, ne declenche pas. Deux organes, le meme etat, deux
    decisions opposees.

    Aucun service n'est demarre : `virtual_memory` est injecte et la RAM
    redescend au tour suivant, ce qui borne la boucle.
    """
    import psutil

    fpq = _charger(monkeypatch, seuil)
    valeurs = iter([ram, 0.0, 0.0])
    appels = []

    def _vm():
        # On enregistre le FIL, pas un jeton anonyme : `psutil.virtual_memory` est
        # une fonction GLOBALE du processus. Compter ses appels sans les attribuer
        # mesure « tous les appels du process », pas « ceux de _wait_for_ram ».
        # Mesure 2026-09-19 : 25 modules du depot l'appellent depuis un thread ou
        # une boucle de fond. INSTRUMENTATION -- la semantique du test est INCHANGEE.
        appels.append(threading.get_ident())
        return _Memoire(next(valeurs, 0.0))

    monkeypatch.setattr(psutil, "virtual_memory", _vm)
    asyncio.run(fpq._wait_for_ram(fpq.RAM_THRESHOLD_PCT, check_interval=0.0))

    a_attendu = len(appels) > 1
    _fils = sorted(set(appels))
    assert a_attendu is attente_attendue, (
        "%s\n  appels=%d depuis %d fil(s) : %s\n  fil du test = %s\n"
        "  Si plus d'UN fil apparait, le compteur est CONTAMINE : le 2e appel ne "
        "vient pas de _wait_for_ram mais d'un daemon du processus."
        % (nom, len(appels), len(_fils), _fils, threading.get_ident())
    )


def test_simulation_contre_epreuve_la_troncature_changerait_la_decision(monkeypatch):
    """PREUVE QUE LA SIMULATION DISCRIMINE -- sans toucher au module.

    Ce fichier a ete ecrit APRES le correctif : ses tests n'ont donc jamais ete
    vus ROUGES, et un NR jamais rouge est exactement un candidat au faux vert.
    Cette contre-epreuve rejoue le scenario C avec le seuil TRONQUE -- la valeur
    qu'aurait produite `int(float("95.5"))` -- et exige la decision INVERSE. Si
    elle passait elle aussi, la simulation ne mesurerait rien du tout.
    """
    import psutil

    fpq = _charger(monkeypatch, "95.5")
    valeurs = iter([95.2, 0.0, 0.0])
    appels = []

    def _vm():
        appels.append(1)
        return _Memoire(next(valeurs, 0.0))

    monkeypatch.setattr(psutil, "virtual_memory", _vm)
    asyncio.run(fpq._wait_for_ram(int(fpq.RAM_THRESHOLD_PCT), check_interval=0.0))

    assert len(appels) > 1, (
        "avec un seuil TRONQUE a 95, une RAM a 95,2 % doit declencher l'attente "
        "que le seuil reel (95,5) evite -- sinon ce fichier ne discrimine rien")


def test_simulation_le_seuil_par_defaut_reste_dans_les_bornes(monkeypatch):
    """Garde de sanite : un defaut hors [50, 99] serait un seuil ingerable."""
    fpq = _charger(monkeypatch, None)
    assert 50.0 <= fpq.RAM_THRESHOLD_PCT <= 99.0
