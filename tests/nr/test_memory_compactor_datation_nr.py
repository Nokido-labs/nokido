"""NR -- datation des memoires : les invariants qui decident ce qui part au froid.

POURQUOI. Une revue externe du 2026-08-20 a pointe quatre defauts de `_classify`
et de la datation ; verification faite sur le code, trois etaient reels et le
quatrieme partiellement. Aucun n'etait couvert par un test -- le lot NR de la
veille testait les outils NEUFS, pas les invariants COGNITIFS du compacteur.

Ce qui est verrouille ici tient en une phrase : **une memoire ne part au froid
que si on SAIT qu'elle est ancienne.** Ni l'ignorance, ni le passage a l'annee
suivante, ni la presence d'une vieille date a cote d'une neuve ne doivent
suffire a la declarer perimee.
"""
from __future__ import annotations

import datetime
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

for _zone in ("tools", "app"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _mc():
    chemin = ROOT / "tools" / "forge_memory_compactor.py"
    assert chemin.exists(), "module absent : %s" % chemin
    spec = importlib.util.spec_from_file_location("forge_memory_compactor", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forge_memory_compactor"] = mod
    sys.modules["nokido_agent.tools.forge_memory_compactor"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_une_entree_sans_date_n_est_jamais_archivee():
    """SANS DATE = PAS DE DECISION. Le code rendait True : il convertissait
    « je ne sais pas quand » en « assez vieux pour partir »."""
    m = _mc()
    ligne = "- **Un principe sans date** : [tient toujours](un_principe_quelconque.md)"
    assert m._classify(ligne, "2026-08-19") is False


def test_la_plus_recente_des_dates_iso_gagne():
    """Une entree porte souvent plusieurs fichiers dates. `search` ne rendait que
    le premier, donc la plus ANCIENNE date decidait du sort de l'entree."""
    m = _mc()
    txt = "- [vieux](a_2026-06-01.md) · [recent](b_2026-08-20.md)"
    assert m._date_entree(txt) == "2026-08-20"


def test_une_memoire_retouchee_ne_part_pas_au_froid_a_cause_de_sa_naissance():
    """L'effet de bout en bout du test precedent, sur la decision reelle."""
    m = _mc()
    ligne = "- [constat de juin](x_2026-06-01.md) · [corrige hier](y_2026-08-20.md)"
    assert m._classify(ligne, "2026-08-19") is False


def test_une_date_de_l_annee_suivante_est_reconnue():
    """Le motif etait fige sur 2026 : au 1er janvier 2027 plus aucune date ISO
    n'etait vue, tout devenait « sans date », et l'index chaud se vidait."""
    m = _mc()
    assert m._date_entree("- [note](sujet_2027-01-14.md)") == "2027-01-14"
    assert m._classify("- [note](sujet_2027-01-14.md)", "2026-08-19") is False


def test_une_date_iso_ancienne_reste_archivable():
    """Le garde doit toujours MORDRE : sans ce test, tout rendre False passerait."""
    m = _mc()
    assert m._classify("- [vieux constat](incident_2026-05-02.md)", "2026-08-19") is True


def test_le_libelle_est_date_sur_l_annee_courante_pas_sur_2026():
    """« 14/01 » lu en 2027 devenait « 2026-01-14 » : une entree vieillie d'un an
    par son seul lecteur."""
    m = _mc()
    attendu = "%s-01-14" % datetime.date.today().year
    assert m._date_libelle("- **14/01 (REGRESSION)** : [note](n.md)") == attendu
    assert m._date_libelle("- **14/01**", annee="2031") == "2031-01-14"


def test_les_arbitrages_owner_sont_intemporels():
    """Une decision ne se perime pas parce qu'elle a deux jours ; un CONSTAT si."""
    m = _mc()
    vieux = "2026-01-01"
    for prefixe in ("feedback_", "reference_", "vision_", "loi_", "doctrine_",
                    "decision_", "politique_"):
        ligne = "- [arbitrage](%ssujet_%s.md)" % (prefixe, vieux)
        assert m._classify(ligne, "2026-08-19") is False, prefixe
