"""NR — un refus d'admission doit dire s'il MESURE ou s'il ne SAIT PAS.

INCIDENT DU 2026-09-08. Le garde a refuse une admission avec le motif
« RISQUE EMBOLIE CPU (100.0% > 90.0%) ». L'owner : « non 13% ce cpu ! ». Mesure
faite dans la foulee : 21-26 % en moyenne machine, un seul coeur sur 16 a 85,9 %.

TROIS DEFAUTS, dont deux que j'ai d'abord mal diagnostiques.

1. `100.0` est AMBIGU PAR CONSTRUCTION. C'est a la fois une valeur de mesure
   possible ET la sentinelle du fail-closed (`_get_system_health` rend
   `{"cpu_pct": 100.0, ..., "degraded": True}` quand la mesure echoue). Le motif
   de refus ne distingue pas les deux : il envoie chercher une saturation CPU
   quand la cause peut etre « je n'ai pas pu mesurer ». C'est `UNKNOWN` presente
   comme `NO`, l'invariant numero un de la constitution semantique.

2. LE REFUS N'EST JOURNALISE NULLE PART. Mesure : `0` occurrence de
   « EMBOLIE CPU » dans 8736 journaux, alors qu'un refus venait d'etre emis.
   Consequence directe : l'incident du jour est IRRECUPERABLE -- impossible de
   dire apres coup si la mesure etait vraie, degradee ou sentinelle. Un garde
   sans trace n'est pas auditable, et « un garde n'est utile que s'il a un signal
   FIABLE, une portee DEFINIE et un effet OBSERVABLE ».

3. LE CPU EST PRIS SUR UN ECHANTILLON DE 100 ms (`cpu_percent(interval=0.1)`),
   et c'est sur lui qu'on refuse. Un echantillon si court est domine par le bruit
   d'ordonnancement : le refus est tombe pile au demarrage d'une CI qui collecte
   8815 tests. Le commentaire du code montre que l'auteur avait corrige le piege
   INVERSE (`interval=None` rend 0.0 au premier appel, le garde ne tirait jamais)
   -- une sous-estimation remplacee par une surestimation symetrique. La parade
   est celle deja ecrite dans le corps pour les debits : mesurer une FENETRE,
   jamais un instant.

CE QUE CE NR NE FAIT PAS : il ne desarme pas le garde et ne touche pas aux
seuils. Un garde peut etre BON et son diagnostic FAUX -- on corrige le diagnostic,
jamais on ne contourne le garde.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "app" / "forge_lane_admission.py"

# "sampler" (2026-10-01) : CPU lu dans l'instantane de forge_resource_manager au lieu
# d'une mesure dormante sur la boucle du hub (test_admission_sans_gel_de_boucle_nr).
SOURCES_ATTENDUES = {"sampler", "inspecteur", "psutil", "indisponible"}


def _module():
    import sys

    for chemin in (RACINE, RACINE / "app"):
        if str(chemin) not in sys.path:
            sys.path.insert(0, str(chemin))
    return pytest.importorskip("app.forge_lane_admission")


def test_la_sante_nomme_sa_source():
    """Sans source, une sentinelle est indiscernable d'une mesure."""
    m = _module()
    sante = m._get_system_health()
    assert "source" in sante, (
        "_get_system_health doit dire D'OU vient la mesure : sans ca, 100.0 peut "
        "etre une charge reelle comme une sentinelle d'echec"
    )
    assert sante["source"] in SOURCES_ATTENDUES, (
        f"source inattendue : {sante['source']!r}, attendu l'une de {sorted(SOURCES_ATTENDUES)}"
    )


def test_une_mesure_indisponible_ne_s_annonce_pas_comme_une_charge(monkeypatch):
    """Le coeur du defaut : ne pas envoyer chercher un CPU qui va bien."""
    m = _module()
    monkeypatch.setattr(
        m, "_get_system_health",
        lambda: {"cpu_pct": 100.0, "ram_pct": 100.0, "ram_dispo_gb": 0.0,
                 "degraded": True, "source": "indisponible"},
    )
    verdict = m.check_ressources(heavy=True)
    assert verdict.get("ok") is False, "une mesure indisponible doit rester fail-closed"
    motif = str(verdict.get("reason", "")).lower()
    assert "mesure" in motif or "indisponible" in motif, (
        f"le motif doit NOMMER l'indisponibilite de la mesure, recu : {verdict.get('reason')!r}"
    )


def test_une_vraie_saturation_nomme_toujours_le_cpu(monkeypatch):
    """La symetrie : on ne remplace pas un faux positif par un garde muet."""
    m = _module()
    monkeypatch.setattr(
        m, "_get_system_health",
        lambda: {"cpu_pct": 97.5, "ram_pct": 40.0, "ram_dispo_gb": 12.0,
                 "degraded": False, "source": "psutil"},
    )
    verdict = m.check_ressources(heavy=True)
    assert verdict.get("ok") is False
    motif = str(verdict.get("reason", ""))
    assert "CPU" in motif.upper() and "97.5" in motif, (
        f"une saturation MESUREE doit nommer le CPU et son chiffre, recu : {motif!r}"
    )


def test_une_machine_saine_est_admise(monkeypatch):
    """Le garde ne doit pas se mettre a refuser tout le monde."""
    m = _module()
    monkeypatch.setattr(
        m, "_get_system_health",
        lambda: {"cpu_pct": 13.0, "ram_pct": 60.0, "ram_dispo_gb": 9.0,
                 "degraded": False, "source": "inspecteur"},
    )
    assert m.check_ressources(heavy=True).get("ok") is True


def test_le_refus_est_journalise(monkeypatch):
    """Un refus sans trace est un refus qu'on ne peut pas instruire.

    Mesure du 2026-09-08 : 0 occurrence de « EMBOLIE CPU » dans 8736 journaux,
    alors qu'un refus venait d'etre emis.
    """
    m = _module()
    assert hasattr(m, "_journaliser_refus"), (
        "aucune fonction de journalisation du refus : l'incident du jour a ete "
        "irrecuperable faute de trace"
    )
    vus = []
    monkeypatch.setattr(m, "_journaliser_refus", lambda *a, **k: vus.append((a, k)))
    monkeypatch.setattr(
        m, "_get_system_health",
        lambda: {"cpu_pct": 99.0, "ram_pct": 40.0, "ram_dispo_gb": 12.0,
                 "degraded": False, "source": "psutil"},
    )
    m.check_ressources(heavy=True)
    assert vus, "le refus CPU n'a rien journalise"


def test_la_fenetre_cpu_n_est_pas_un_echantillon():
    """Un refus ne se decide pas sur 100 ms de bruit d'ordonnancement."""
    m = _module()
    assert hasattr(m, "FENETRE_CPU_S"), (
        "la duree de mesure du CPU doit etre une constante NOMMEE, pas un litteral "
        "enfoui dans l'appel"
    )
    assert m.FENETRE_CPU_S >= 0.5, (
        f"fenetre de {m.FENETRE_CPU_S} s : trop courte pour distinguer une charge "
        "d'un pic. Mesure du 2026-09-08 : refus a 100 % pendant que la machine "
        "tenait 21-26 %, un seul coeur sur 16 charge"
    )


def test_la_sentinelle_reste_fail_closed():
    """On ne troque pas un faux refus contre une admission dangereuse.

    La sentinelle doit continuer a REFUSER ; ce NR n'exige que de la NOMMER.
    """
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8", errors="replace"))
    litteraux = {
        n.value for n in ast.walk(arbre)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
    }
    assert 100.0 in litteraux, (
        "la sentinelle saturee a disparu : le fail-closed doit rester, seul son "
        "NOM devait changer"
    )
