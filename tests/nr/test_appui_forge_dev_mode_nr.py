# -*- coding: utf-8 -*-
"""Test d'APPUI GENERE-APPUI — genere, pas ecrit.

Couvre `tools/forge_dev_mode.py`. Il verifie que le module se CHARGE, rien de plus.

Ce qu'il apporte : un perimetre de mesure, sans lequel `juger_module_avec_gain`
ne peut rendre que GAIN_INDECIDABLE sur ce module ; et la detection des erreurs
de chargement (NameError, ImportError) sur un chemin que personne n'execute.

Ce qu'il NE prouve PAS : aucun comportement. Il ne compte donc jamais dans la
metrique `couverture prouvee` — le marqueur en tete sert exactement a l'en
exclure. Le remplacer par un vrai test de comportement est un progres ; le
supprimer sans le remplacer rend le module non mesurable.
"""

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_le_module_se_charge():
    assert importlib.import_module("forge_dev_mode") is not None


# ---------------------------------------------------------------------------
# COMPORTEMENT : un garde ne doit pas pouvoir enfermer le systeme (2026-09-19)
# ---------------------------------------------------------------------------

def test_arm_sans_autorite_ne_laisse_AUCUN_residu(monkeypatch, tmp_path):
    """Un refus ne doit jamais creer ce qu'il ne saura pas reprendre.

    Mesure du 2026-09-19, apres avoir cree l'impasse pour de vrai : `arm()`
    ecrivait le jeton, POSAIT l'ACL SYSTEM+Administrateurs, PUIS refusait si
    l'ACL n'avait pas mordu. Un compte sandbox se rendait ainsi son propre
    fichier inaccessible -- et se retrouvait sans issue : plus d'armement (le
    fichier existe), plus de desarmement (l'ACL l'interdit). Seule une console
    admin pouvait defaire ce que le garde avait fait.

    REGLE : on ne pose pas un verrou avant d'avoir verifie qu'on saura le
    reprendre. L'autorite se teste AVANT la moindre ecriture.
    """
    m = importlib.import_module("forge_dev_mode")
    monkeypatch.setattr(m, "TOKEN_FILE", tmp_path / ".jeton")
    monkeypatch.setattr(m, "_est_admin", lambda: False)
    assert m._est_admin() is False, "la substitution d'autorite n'a pas mordu"

    with pytest.raises(SystemExit) as capture:
        m.arm()

    assert "ADMINISTRATEUR" in str(capture.value), str(capture.value)[:200]
    assert not (tmp_path / ".jeton").exists(), (
        "un jeton a ete ecrit malgre le refus : le compte vient de se creer une impasse")
    assert not any(tmp_path.iterdir()), (
        "le refus a laisse un residu dans %s" % tmp_path)


def test_un_jeton_deja_protege_est_signale_AVEC_sa_sortie(monkeypatch, tmp_path):
    """Un blocage doit nommer la commande qui en sort, sinon il est une impasse.

    CONTRE-EPREUVE du test precedent : sans elle, un `arm()` qui refuserait TOUT
    passerait le premier test sans rien prouver. Ici le jeton existe et n'est pas
    lisible -- le refus doit porter la voie de sortie, pas seulement l'echec.
    """
    m = importlib.import_module("forge_dev_mode")
    jeton = tmp_path / ".jeton"
    jeton.write_text("peu importe", encoding="utf-8")
    monkeypatch.setattr(m, "TOKEN_FILE", jeton)

    def _illisible(*_a, **_k):
        raise PermissionError(13, "refus simule")

    monkeypatch.setattr(type(jeton), "read_text", _illisible, raising=False)

    with pytest.raises(SystemExit) as capture:
        m.arm()
    motif = str(capture.value)
    assert "disarm" in motif, (
        "le refus doit nommer la commande de SORTIE, sinon c'est une impasse : %s" % motif[:200])
