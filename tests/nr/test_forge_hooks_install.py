"""Le filet de gardes doit survivre au CLONE — sinon la promesse du depot n'est
pas verifiable par celui qui l'evalue.

Mesure 2026-08-29 : `.gitignore` ignore tout `.claude/`, les hooks Claude Code
vivent dans le profil de l'owner, et `.githooks/` reste dormant tant que
`core.hooksPath` n'est pas pose. Un clone nu n'herite donc d'AUCUN garde. Ces
tests verrouillent les trois proprietes qui rendent `forge_hooks_install`
utilisable par un tiers, dont une regression deja payee le meme jour : une
source illisible qui se lit « rien ne manque ».
"""

import json
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.46)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_hooks_install as fhi  # noqa: E402


def test_reference_presente_et_non_vide():
    """La reference EST la source unique : absente, l'installeur n'installe rien."""
    cablage, motif = fhi._reference()
    assert cablage is not None, "reference de cablage %s" % motif
    assert cablage, "reference vide : aucun garde ne serait installe chez un tiers"


def test_chaque_script_reference_existe_dans_le_depot():
    """Un cablage qui nomme un script absent est un garde mort a l'installation."""
    cablage, _ = fhi._reference()
    manquants = sorted({e["script"] for e in cablage if fhi._script_path(e["script"]) is None})
    assert not manquants, "scripts references mais absents du depot : %s" % manquants


def test_clone_nu_voit_TOUS_les_cablages_comme_manquants(tmp_path, monkeypatch):
    """Un projet vierge n'a aucun garde : l'installeur doit le DIRE en entier.

    C'est la situation exacte d'un tiers qui clone. `_deja_ailleurs` est neutralise
    pour simuler une machine SANS profil utilisateur deja cable -- sinon le test
    mesurerait la machine de developpement au lieu du clone nu.
    """
    monkeypatch.setattr(fhi, "_deja_ailleurs", lambda projet: set())
    rapport = fhi.etat(str(tmp_path), sys.executable)
    cablage, _ = fhi._reference()
    attendus = {"%s/%s" % (e["event"], e["script"])
                for e in cablage if fhi._script_path(e["script"]) is not None}
    assert isinstance(rapport["manquants"], list)
    assert set(rapport["manquants"]) == attendus


def test_ne_reinstalle_pas_un_cablage_fourni_ailleurs(tmp_path, monkeypatch):
    """Regression du 2026-08-29 : 11 cablages du profil utilisateur ont ete
    DUPLIQUES dans le settings du projet, parce que l'installeur ne comparait qu'a
    sa cible. Un doublon n'est pas inerte : Claude Code fusionne les settings, donc
    chaque garde s'executait DEUX fois par evenement.
    """
    cablage, _ = fhi._reference()
    tous = {(e["event"], e["script"]) for e in cablage
            if fhi._script_path(e["script"]) is not None}
    monkeypatch.setattr(fhi, "_deja_ailleurs", lambda projet: tous)
    rapport = fhi.etat(str(tmp_path), sys.executable)
    assert rapport["manquants"] == [], (
        "des cablages deja fournis par un autre settings sont proposes a "
        "l'installation : ils tireraient deux fois")


def test_settings_illisible_nest_jamais_lu_comme_complet(tmp_path, monkeypatch):
    """Regression du 2026-08-29 : une liste VIDE se lit « rien ne manque ».

    Quand la source ne peut pas etre lue, le rapport doit dire qu'il n'a pas pu
    regarder — jamais rendre une collection vide, qui est indiscernable d'un
    filet complet. Trois etats, jamais deux.
    """
    monkeypatch.setattr(fhi, "_charge", lambda p: (None, "illisible: acces refuse"))
    rapport = fhi.etat(str(tmp_path), sys.executable)
    assert not isinstance(rapport["manquants"], list), (
        "un settings illisible rend une liste : indiscernable de « rien ne manque »")
    assert "non evaluable" in str(rapport["manquants"])


def test_dry_run_n_ecrit_rien(tmp_path):
    """`etat()` est une SONDE : elle ne doit creer ni settings ni repertoire."""
    fhi.etat(str(tmp_path), sys.executable)
    assert not (tmp_path / ".claude").exists(), "la sonde a ecrit sur le disque"


def test_commande_generee_pointe_le_depot_local(tmp_path):
    """La reference ne porte pas de chemin absolu : les commandes sont
    reconstruites avec la racine LOCALE, sinon un tiers herite des chemins de la
    machine d'origine."""
    cablage, _ = fhi._reference()
    nom = next(e["script"] for e in cablage if fhi._script_path(e["script"]))
    cmd = fhi._commande(nom, sys.executable)
    assert str(ROOT).replace("\\", "/") in cmd
    assert nom in cmd


@pytest.mark.parametrize("champ", ["reference", "hooksPath", "settings", "manquants"])
def test_rapport_porte_les_champs_de_diagnostic(tmp_path, champ):
    """Un rapport muet sur son propre perimetre ne permet aucun diagnostic."""
    assert champ in fhi.etat(str(tmp_path), sys.executable)
