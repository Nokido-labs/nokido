# -*- coding: utf-8 -*-
"""NR — le vide documentaire ne peut plus GRANDIR.

MESURE 2026-09-16 : 2524 modules scannes, 923 sans docstring. Apres avoir
ecarte le jetable (backups, archives, tmp_, vendored), il reste **871 modules
VIVANTS sans docstring** — le bruit n'expliquait que 52 cas sur 923.

POURQUOI UN CLIQUET, PAS UNE CIBLE. Exiger de combler 871 docstrings produirait
l'un ou l'autre de ces deux echecs :
  - un gate rouge en permanence, donc desarme au premier agacement ;
  - des docstrings INVENTEES depuis le nom du fichier. Ce filet a ete essaye le
    2026-07-25 puis RETIRE : sur de la prose il rangeait `forge_adb` dans
    l'immunitaire parce que la phrase disait « privilegie ». Une etiquette
    inventee se propage en RAG et dans l'atlas, ou plus rien ne la distingue
    d'une mesure.

Le cliquet n'exige donc pas de combler. Il interdit d'AGGRAVER : un module NEUF
porte sa docstring, parce qu'elle est la seule source de sa definition au wiki.

HERMETICITE — et ce n'est pas theorique. Le meme soir, un NR de vitalite lisait
le registre de PRODUCTION parce que la fixture ne patchait qu'UNE des deux
sources : il rendait LU/FRESH/FULL sans qu'aucun fichier de test existe. Ici on
patche `RATCHET` **et** `collecter`, donc ni le fichier de reference reel ni le
corpus reel ne sont touches.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_wiki_modules as W  # noqa: E402


def _corpus(n_sans: int, n_avec: int = 5):
    fiches = [{"chemin": "app/avec%d.py" % i, "nom": "avec%d" % i,
               "doc": "Fait quelque chose.", "publics": [], "loc": 10}
              for i in range(n_avec)]
    fiches += [{"chemin": "app/sans%d.py" % i, "nom": "sans%d" % i,
                "doc": "", "publics": [], "loc": 10} for i in range(n_sans)]
    return fiches


@pytest.fixture
def bac(tmp_path, monkeypatch):
    """Isole les DEUX surfaces : le fichier de reference ET le corpus scanne."""
    cible = tmp_path / "docstring_ratchet.json"
    monkeypatch.setattr(W, "RATCHET", cible)
    return cible


def _poser(cible, plafond):
    cible.write_text(json.dumps({"plafond_sans_docstring": plafond}),
                     encoding="utf-8")


def test_un_plafond_absent_ne_vaut_pas_un_succes(bac, monkeypatch, capsys):
    """NON MESURE se DIT. Un cliquet sans reference qui rendrait 0 en silence
    serait indistinguable d'un cliquet tenu."""
    monkeypatch.setattr(W, "collecter", lambda: _corpus(10))
    assert W.verifier_ratchet() == 0
    assert "ABSENT" in capsys.readouterr().out


def test_le_mode_d_emploi_affiche_FONCTIONNE_vraiment(bac, monkeypatch):
    """DEFAUT REEL corrige le 2026-09-16, trouve en empruntant le chemin reel.

    La branche « plafond absent » rendait 0 sans rien ecrire, alors que son
    propre message disait « L'initialiser : --ratchet --abaisser ». Le message
    promettait un geste que le code ne faisait pas — meme famille que le
    commentaire qui promet un garde absent, paye le meme jour sur le gate UI.
    Un mode d'emploi qui ne marche pas est pire qu'une absence de mode d'emploi.
    """
    assert not bac.exists()
    monkeypatch.setattr(W, "collecter", lambda: _corpus(12))
    assert W.verifier_ratchet(abaisser=True) == 0
    assert bac.exists(), "--abaisser n'a pas initialise le plafond absent"
    assert json.loads(bac.read_text(encoding="utf-8"))["plafond_sans_docstring"] == 12


def test_le_vide_qui_grandit_fait_ECHOUER(bac, monkeypatch):
    _poser(bac, 10)
    monkeypatch.setattr(W, "collecter", lambda: _corpus(11))
    assert W.verifier_ratchet() == 1


def test_le_vide_stable_passe(bac, monkeypatch):
    _poser(bac, 10)
    monkeypatch.setattr(W, "collecter", lambda: _corpus(10))
    assert W.verifier_ratchet() == 0


def test_un_progres_passe_mais_n_abaisse_PAS_tout_seul(bac, monkeypatch):
    """Un fichier de reference qui se reecrit a chaque run salit l'arbre — et
    un arbre sale empeche la CI de capturer un sha (mesure du 2026-09-06)."""
    _poser(bac, 10)
    avant = bac.read_text(encoding="utf-8")
    monkeypatch.setattr(W, "collecter", lambda: _corpus(7))
    assert W.verifier_ratchet() == 0
    assert bac.read_text(encoding="utf-8") == avant, (
        "le plafond a ete abaisse SANS --abaisser")


def test_abaisser_grave_le_gain(bac, monkeypatch):
    _poser(bac, 10)
    monkeypatch.setattr(W, "collecter", lambda: _corpus(7))
    assert W.verifier_ratchet(abaisser=True) == 0
    assert json.loads(bac.read_text(encoding="utf-8"))["plafond_sans_docstring"] == 7


def test_abaisser_ne_REMONTE_jamais_le_plafond(bac, monkeypatch):
    """Sinon le cliquet se desarme lui-meme : une regression graverait son
    propre plafond et le gate redeviendrait vert sur un corps degrade."""
    _poser(bac, 10)
    monkeypatch.setattr(W, "collecter", lambda: _corpus(15))
    assert W.verifier_ratchet(abaisser=True) == 1
    assert json.loads(bac.read_text(encoding="utf-8"))["plafond_sans_docstring"] == 10


def test_le_drapeau_ratchet_traverse_le_point_d_entree(bac, monkeypatch):
    """Cliquet niveau 4 : `check()` passait ses tests pendant que `--check`
    mourait en NameError. Tout drapeau CLI a un test qui l'emprunte."""
    _poser(bac, 10)
    monkeypatch.setattr(W, "collecter", lambda: _corpus(10))
    assert W.main(["--ratchet"]) == 0


def test_le_jetable_est_ECARTE_et_COMPTE():
    """Ecarter n'autorise pas a se taire : un filtre qui retire des donnees le
    DIT, sinon la couverture est surestimee en silence."""
    assert W._est_jetable(Path("app/backups/auto_boot.py")).startswith("dossier:")
    assert W._est_jetable(Path("tools/tmp_essai.py")).startswith("prefixe:")
    assert W._est_jetable(Path("app/forge_rag_engine.py")) == ""
