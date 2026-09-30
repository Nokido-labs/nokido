"""NR 2026-09-09 — un correctif ANNONCE n'est pas un correctif INSTALLABLE.

DEUX CAUSES DISTINCTES, LE MEME SYMPTOME. Un avis de securite nomme la version qui
corrige la faille ; il ne dit pas si on peut l'installer. Le depot a paye les deux :

  1. INTERPRETEUR (2026-09-06) — litellm 1.84.0 exige Python `>=3.10,<3.14` alors
     que l'env tourne en 3.14.4. Proposer 1.84.0 faisait echouer l'INSTALLATION
     ENTIERE des 20 paquets sur une seule ligne. Premiere version installable : 1.93.0.
  2. RETRAIT UPSTREAM (2026-09-09) — transformers 5.10.0, correctif de CVE-2026-9856,
     est YANKED par ses propres auteurs : « We pushed from a week old main branch.
     [...] uncertain its gonna be working properly and mostly it is missing a bunch
     of fixes! ». La version existe, l'avis la recommande, et l'upstream la desavoue.
     Premiere version SAINE : 5.10.1 (requires_python >=3.10.0, donc compatible).

Dans les deux cas le numero EXISTE, l'outil de securite le RECOMMANDE, et l'installer
serait une faute. Une table qui ne connaitrait que la premiere cause laisserait passer
la seconde en silence -- et c'est exactement l'etat trouve ce jour : aucune occurrence
de « yank » dans forge_deps_reconcilier.

CE QUE CE NR EXIGE : que la table nomme la BORNE REELLE, jamais la version annoncee,
et que les deux causes y soient representees. Il ne verifie pas le yank en direct :
la CI est hors ligne par conception, une verification reseau y serait UNKNOWN a chaque
run. La table est le releve d'une mesure datee, comme le socle de secrets.

Zero service externe : lecture d'une structure Python, aucun reseau, aucun pip.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE / "tools"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_deps_reconcilier as deps  # noqa: E402


def _table() -> dict:
    return getattr(deps, "INCOMPATIBLES_PYTHON", {})


def test_la_table_existe_et_n_est_pas_vide():
    """Contre-epreuve : une table vide ferait passer tous les tests suivants."""
    t = _table()
    assert t, "INCOMPATIBLES_PYTHON absente ou vide : plus aucune borne n'est connue"


def test_litellm_reste_borne_par_l_interpreteur():
    """Non-regression de la premiere cause, mesuree le 2026-09-06."""
    e = _table().get("litellm")
    assert e, "l'entree litellm a disparu : la borne Requires-Python n'est plus dite"
    annoncee, reelle, raison = e[0], e[1], e[2]
    assert annoncee == "1.84.0"
    assert reelle == "1.93.0", "la borne installable de litellm n'est plus 1.93.0"
    assert "3.14" in raison


def test_transformers_est_borne_par_le_RETRAIT_upstream():
    """Seconde cause, mesuree le 2026-09-09 : le correctif annonce est YANKED."""
    e = _table().get("transformers")
    assert e, (
        "l'entree transformers manque : pip-audit et Dependabot recommandent 5.10.0, "
        "qui est YANKED par l'upstream. Sans borne, une campagne de montee "
        "installerait une version que ses auteurs desavouent")
    annoncee, reelle, raison = e[0], e[1], e[2]
    assert annoncee == "5.10.0", "la version ANNONCEE par l'avis doit rester tracee"
    assert reelle == "5.10.1", (
        "la borne doit etre 5.10.1, premiere version SAINE >= 5.10.0 (mesure PyPI du "
        "2026-09-09) -- pas la derniere publiee : fermer une CVE n'est pas traverser "
        "six mineures")
    assert "yank" in raison.lower(), (
        "la raison doit NOMMER le retrait upstream, sinon on ne distingue pas cette "
        "cause de l'incompatibilite d'interpreteur : %r" % raison)


def test_aucune_borne_ne_vaut_la_version_annoncee():
    """L'invariant de la table : si les deux etaient egales, l'entree ne servirait a rien."""
    for paquet, e in _table().items():
        assert e[0] != e[1], (
            "%s : borne identique a la version annoncee (%s) -- l'entree ne borne rien"
            % (paquet, e[0]))


def test_chaque_entree_porte_une_raison_lisible():
    """Une borne sans motif doit etre re-instruite a chaque campagne."""
    for paquet, e in _table().items():
        assert len(e) >= 3 and e[2] and len(e[2]) > 15, (
            "%s : raison absente ou trop courte -- la borne sera re-questionnee au "
            "prochain avis" % paquet)
