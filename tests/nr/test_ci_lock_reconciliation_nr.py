"""NR — le lock des outils CI, et surtout la RECONCILIATION avec l'installe.

Un hash de fichier ne prouve rien sur ce qui est installe. Avec un
`laforge_py314` PERMANENT — partage avec le hub vivant, ou `ci-selfhosted.yml`
fait `pip install` sans epingler — l'ecart entre le declare et le reel est
precisement la faille (owner 2026-09-19).

Mesures qui fixent les denominateurs de ces tests :
  - `ci-selfhosted.yml` installe SEPT paquets ; la CI en DEPEND de HUIT, car
    `pytest` est supose deja present et n'est donc controle par aucun workflow ;
  - la fermeture transitive de ces huit fait QUARANTE-TROIS paquets installes,
    plus DEUX declares non installes (`exceptiongroup`,
    `backports-asyncio-runner` : conditionnels pour Python < 3.11).

Verrouiller les racines seules aurait laisse une transitive changer sans rien
signaler — c'est ce que ces tests interdisent.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
fcl = importlib.import_module("forge_ci_lock")


class _PasLa(Exception):
    pass


_PasLa.__name__ = "PackageNotFoundError"


def _faux(installes, deps, casse=()):
    def version(n):
        if n in casse:
            raise OSError("illisible")
        if n not in installes:
            raise _PasLa(n)
        return installes[n]

    def requires(n):
        return deps.get(n, [])
    return version, requires


# ──────────────────────────────── fermeture ─────────────────────────────────

def test_la_fermeture_est_TRANSITIVE_pas_seulement_les_racines():
    v, r = _faux({"pytest": "9.0.3", "pluggy": "1.6.0", "iniconfig": "2.3.0"},
                 {"pytest": ["pluggy>=1.5", "iniconfig"]})
    f = fcl.fermeture(("pytest",), version=v, requires=r)
    assert set(f["paquets"]) == {"pytest", "pluggy", "iniconfig"}, \
        "verrouiller les racines seules laisserait une transitive changer en silence"


def test_un_DECLARE_non_installe_n_est_ni_une_erreur_ni_un_paquet_du_lock():
    """`exceptiongroup` est declare par pytest pour Python < 3.11 : absent en
    3.14, et c'est normal. Le compter comme paquet rendrait le lock invalide ;
    le taire ferait disparaitre une declaration."""
    v, r = _faux({"pytest": "9.0.3"}, {"pytest": ["exceptiongroup; python_version<'3.11'"]})
    f = fcl.fermeture(("pytest",), version=v, requires=r)
    assert "exceptiongroup" not in f["paquets"]
    assert any("exceptiongroup" in x for x in f["declares_non_installes"])
    assert f["illisibles"] == []


def test_un_ILLISIBLE_ne_se_confond_pas_avec_un_NON_INSTALLE():
    v, r = _faux({"pytest": "9.0.3"}, {"pytest": ["pluggy"]}, casse={"pluggy"})
    f = fcl.fermeture(("pytest",), version=v, requires=r)
    assert f["declares_non_installes"] == []
    assert any("pluggy" in x for x in f["illisibles"]), \
        "ne pas avoir pu lire n'est pas avoir constate une absence"


def test_les_extras_ne_sont_PAS_tires():
    v, r = _faux({"pytest": "9.0.3"}, {"pytest": ["truc; extra == 'dev'"]})
    f = fcl.fermeture(("pytest",), version=v, requires=r)
    assert set(f["paquets"]) == {"pytest"} and f["declares_non_installes"] == []


# ────────────────────────────────── hash ────────────────────────────────────

def test_le_hash_porte_le_CONTENU_pas_le_texte_du_fichier():
    """Hacher le fichier ferait changer l'empreinte a chaque retouche d'en-tete :
    elle cesserait de mesurer les dependances pour mesurer un commentaire."""
    a = {"racines": ["pytest"], "paquets": {"pytest": "9.0.3", "pluggy": "1.6.0"}}
    b = {"racines": ["pytest"], "paquets": {"pluggy": "1.6.0", "pytest": "9.0.3"}}
    assert fcl.hash_lock(a) == fcl.hash_lock(b), "l'ordre d'ecriture n'est pas le contenu"
    c = {"racines": ["pytest"], "paquets": {"pytest": "9.0.4", "pluggy": "1.6.0"}}
    assert fcl.hash_lock(a) != fcl.hash_lock(c), "une version qui bouge doit se voir"


# ───────────────────────────── reconciliation ───────────────────────────────

LOCK = {"racines": ["pytest"], "paquets": {"pytest": "9.0.3", "pluggy": "1.6.0"}}


def test_CONFORME_quand_l_installe_correspond():
    etat, det = fcl.reconcilier(LOCK, {"pytest": "9.0.3", "pluggy": "1.6.0"})
    assert etat == "CONFORME" and det["ecarts"] == {} and det["manquants"] == []


def test_DIVERGENT_sur_une_version_qui_a_bouge():
    etat, det = fcl.reconcilier(LOCK, {"pytest": "9.0.3", "pluggy": "1.7.0"})
    assert etat == "DIVERGENT"
    assert det["ecarts"]["pluggy"] == {"lock": "1.6.0", "installe": "1.7.0"}


def test_DIVERGENT_sur_un_paquet_du_lock_ABSENT_de_l_environnement():
    etat, det = fcl.reconcilier(LOCK, {"pytest": "9.0.3"})
    assert etat == "DIVERGENT" and det["manquants"] == ["pluggy"]


def test_ILLISIBLE_l_emporte_sur_DIVERGENT():
    """Ne pas avoir pu lire n'est pas avoir constate un ecart : repondre
    DIVERGENT sur une lecture ratee enverrait corriger un probleme qui n'existe
    peut-etre pas."""
    etat, _ = fcl.reconcilier(LOCK, {"pytest": "9.9.9", "pluggy": None})
    assert etat == "ILLISIBLE"


def test_un_lock_VIDE_est_ILLISIBLE_pas_CONFORME():
    """Le faux vert parfait : aucun attendu, donc aucun ecart."""
    assert fcl.reconcilier({"paquets": {}}, {"pytest": "9.0.3"})[0] == "ILLISIBLE"
    assert fcl.reconcilier(None, {})[0] == "ILLISIBLE"


def test_un_paquet_HORS_lock_est_signale_sans_faire_echouer():
    """L'environnement est partage avec le hub : il contient legitimement plus
    que les outils de CI. On le COMPTE, on n'en fait pas un ecart."""
    etat, det = fcl.reconcilier(LOCK, {"pytest": "9.0.3", "pluggy": "1.6.0",
                                       "torch": "2.0"})
    assert etat == "CONFORME" and det["hors_lock"] == ["torch"]


# ─────────────────────────────── chemin reel ────────────────────────────────

def test_lire_lock_distingue_ABSENT_de_ILLISIBLE(tmp_path):
    l, motif = fcl.lire_lock(tmp_path / "jamais.lock")
    assert l is None and motif.startswith("ABSENT")


def test_aller_retour_ecriture_relecture(tmp_path):
    f = {"racines": ["pytest"], "paquets": {"pytest": "9.0.3", "pluggy": "1.6.0"},
         "declares_non_installes": ["exceptiongroup (PackageNotFoundError)"],
         "illisibles": []}
    cible = tmp_path / "requirements-ci.lock"
    cible.write_text(fcl.rendu(f), encoding="utf-8")
    relu, motif = fcl.lire_lock(cible)
    assert relu is not None, motif
    assert relu["paquets"] == f["paquets"]
    assert fcl.hash_lock(relu) == fcl.hash_lock(f), \
        "le hash doit survivre a l'aller-retour, sinon il n'identifie rien"
    assert fcl.reconcilier(relu, f["paquets"])[0] == "CONFORME"


def test_les_HUIT_racines_sont_declarees():
    """Sept sont installees par le workflow ; `pytest` ne l'est par aucun, et
    reste pourtant un outil du contrat."""
    assert len(fcl.RACINES) == 8
    assert "pytest" in fcl.RACINES
