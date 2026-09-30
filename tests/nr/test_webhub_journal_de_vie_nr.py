# -*- coding: utf-8 -*-
"""Non-regression — le webhub DIT qu'il demarre, et dit comment il meurt.

Mesure 2026-08-29 : le webhub n'ecrivait RIEN. Il a redemarre deux fois en deux
minutes (19:07 puis 19:09) sans que rien ne dise pourquoi, ni meme qu'il avait
redemarre — seule une trace ajoutee a la main l'a revele. Un organe muet ne se
diagnostique pas : on ne distingue meme pas « il tourne depuis le debut » de
« il vient de renaitre », et toute enquete part alors d'une hypothese au lieu
d'un fait. Une journee entiere a bute la-dessus.

Le journal couvre les TROIS facons de mourir, la ou le hub n'en couvrait qu'une :
l'exception qui remonte, la mort DURE (faulthandler, que `except` ne voit jamais
passer), et le process tue de l'exterieur — ce dernier ne s'ecrit pas, et c'est
justement l'information : un DEMARRAGE sans arret qui le precede se lit comme une
mort violente. D'ou la ligne de demarrage, qui n'est pas decorative.
"""

from __future__ import annotations

import faulthandler
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

M = pytest.importorskip("nokido_web_hub")


@pytest.fixture
def journal(tmp_path, monkeypatch):
    """Isole le journal ET restaure le faulthandler du process de test."""
    etait_actif = faulthandler.is_enabled()
    monkeypatch.setattr(M, "ROOT", tmp_path)
    monkeypatch.setattr(M, "_JOURNAL_OUVERT", None)
    yield tmp_path / "logs" / "webhub_vie.log"
    if M._JOURNAL_OUVERT is not None:
        try:
            M._JOURNAL_OUVERT.close()
        except OSError:
            pass
    faulthandler.disable()
    if etait_actif:
        faulthandler.enable()


def test_le_demarrage_est_date_et_porte_le_pid(journal):
    """Sans pid ni horodatage, deux demarrages consecutifs sont indistinguables."""
    M._journal_de_vie("127.0.0.1", 7400)
    texte = journal.read_text(encoding="utf-8")
    assert "DEMARRAGE" in texte
    assert "pid=%d" % os.getpid() in texte
    assert "127.0.0.1:7400" in texte


def test_deux_demarrages_laissent_DEUX_lignes(journal):
    """Le journal s'AJOUTE : ecraser effacerait la trace du redemarrage precedent,
    c'est-a-dire exactement ce qu'on cherche a voir."""
    M._journal_de_vie("127.0.0.1", 7400)
    M._JOURNAL_OUVERT.close()
    M._JOURNAL_OUVERT = None
    M._journal_de_vie("127.0.0.1", 7400)
    assert journal.read_text(encoding="utf-8").count("DEMARRAGE") == 2


def test_la_mort_dure_est_armee(journal):
    """faulthandler capte abort, acces memoire, recursion — ce qu'`except` ne voit
    jamais passer. C'est le cas qui expliquerait un redemarrage silencieux."""
    M._journal_de_vie("127.0.0.1", 7400)
    assert faulthandler.is_enabled(), "les morts dures resteraient muettes"


def test_un_crash_est_consigne_avec_sa_trace(journal):
    M._journal_de_vie("127.0.0.1", 7400)
    try:
        raise RuntimeError("boum de test")
    except RuntimeError as ex:
        M._consigner_crash(ex)
    texte = journal.read_text(encoding="utf-8")
    assert "CRASH" in texte and "boum de test" in texte
    assert "RuntimeError" in texte, "la trace doit nommer le type"


def test_un_journal_inaccessible_ne_TUE_PAS_le_lanceur(tmp_path, monkeypatch, capsys):
    """Le diagnostic est un confort : son absence ne doit jamais empecher le
    service de demarrer. L'inverse serait un garde qui coute le patient."""
    fichier = tmp_path / "occupe"
    fichier.write_text("", encoding="utf-8")
    monkeypatch.setattr(M, "ROOT", fichier)      # logs/ sous un FICHIER : mkdir echoue
    monkeypatch.setattr(M, "_JOURNAL_OUVERT", None)
    M._journal_de_vie("127.0.0.1", 7400)         # ne doit pas lever
    assert "journal de vie indisponible" in capsys.readouterr().out


def test_consigner_sans_journal_ouvert_ne_leve_pas(monkeypatch, capsys):
    monkeypatch.setattr(M, "_JOURNAL_OUVERT", None)
    M._consigner_crash(RuntimeError("sans journal"))
    assert "CRASH" in capsys.readouterr().out, "le crash doit au moins etre imprime"
