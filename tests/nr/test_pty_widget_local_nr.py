# -*- coding: utf-8 -*-
"""Non-regression — le widget terminal sait consommer une session LOCALE.

Mesure 2026-08-29 : `LocalPTYSession` (ConPTY Windows) existait, fonctionnelle —
`connect()` en 0,6 s, un `echo` renvoye par le shell en 3,7 s, HAS_WINPTY vrai.
`PTYTerminalWidget` existait aussi, et c'est un VRAI terminal (`on_key` envoie les
touches a la session, pyte rend l'ecran). Mais le widget ne pouvait construire
qu'une `PTYSession` SSH : le terminal LOCAL etait inatteignable depuis
l'interface, faute d'un seul parametre. Deux moities qui ne se rejoignaient pas.

CE FICHIER NE MONTE PAS DE PTY. Mesure du meme jour : une sonde qui ouvre une
session locale n'a jamais rendu la main (process encore vivant apres cinq
minutes, tue a la main). La piste est la boucle de lecture, qui attend dans
`asyncio.to_thread(self._proc.read, ...)` alors que l'executor par defaut n'est
pas daemon — mais cette sonde-la appelait aussi `bytes_received()` comme une
methode alors que c'est une PROPERTY, donc elle etait fautive et la cause exacte
n'est PAS etablie. Ce qui est certain : le process ne s'est pas termine.

On verifie donc le CABLAGE, pas le vivant. Un test qui monterait un PTY risquerait
de pendre la CI, et l'arret propre reste a instruire AVANT tout montage dans la
TUI — un terminal qui empeche de quitter serait pire que pas de terminal.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FPW = pytest.importorskip("forge_pty_widget")


def test_les_deux_transports_existent():
    """SSH et LOCAL : le second est celui qui manquait a l'interface."""
    assert hasattr(FPW, "PTYSession"), "transport SSH disparu"
    assert hasattr(FPW, "LocalPTYSession"), "transport LOCAL disparu"


def test_le_widget_accepte_une_cible_locale():
    if not getattr(FPW, "HAS_TEXTUAL", False):
        pytest.skip("textual absent")
    params = inspect.signature(FPW.PTYTerminalWidget.__init__).parameters
    assert "argv" in params, (
        "sans `argv`, le widget ne sait construire qu'une session SSH et le "
        "terminal local reste inatteignable depuis l'interface")
    assert params["argv"].default is None, "le mode local doit rester OPT-IN"


def test_le_mode_ssh_reste_par_defaut():
    """Retro-compatibilite : l'appel historique ne doit rien changer."""
    if not getattr(FPW, "HAS_TEXTUAL", False):
        pytest.skip("textual absent")
    params = inspect.signature(FPW.PTYTerminalWidget.__init__).parameters
    assert params["host"].default == "", "host doit rester acceptable en premier"
    src = inspect.getsource(FPW.PTYTerminalWidget.__init__)
    assert "LocalPTYSession(" in src and "PTYSession(" in src, (
        "les deux transports doivent rester joignables depuis le widget")


def test_le_terminal_dit_a_quoi_il_est_attache():
    """Un ecran de terminal sans en-tete ne dit pas OU l'on tape — local ou SSH,
    la difference n'est pas cosmetique."""
    if not getattr(FPW, "HAS_TEXTUAL", False):
        pytest.skip("textual absent")
    assert hasattr(FPW.PTYTerminalWidget, "cible")


def test_la_session_locale_expose_ce_qu_un_terminal_exige():
    """Sans ces methodes, le widget ne peut ni ecrire, ni lire, ni redimensionner."""
    for meth in ("connect", "disconnect", "send_bytes", "get_display", "resize",
                 "is_alive"):
        assert callable(getattr(FPW.LocalPTYSession, meth, None)), meth
    # L'API MELANGE les deux formes : `is_alive` est une methode, `bytes_received`
    # une PROPERTY. Les appeler l'une comme l'autre leve un TypeError — ma propre
    # sonde s'y est prise ainsi le 2026-08-29. Un contrat se verifie, il ne se
    # suppose pas ; ce test fige la forme de chacun pour le prochain lecteur.
    assert isinstance(getattr(FPW.LocalPTYSession, "bytes_received", None), property)


def test_la_fermeture_debloque_la_lecture_avant_d_annuler():
    """`read` est BLOQUANT (pywinpty) : annuler la tache sans terminer le process
    laisserait un thread suspendu, et l'interpreteur ne pourrait plus sortir.
    L'ordre terminate-puis-cancel est le remede — il doit le rester."""
    src = inspect.getsource(FPW.LocalPTYSession.disconnect)
    i_term = src.find("terminate")
    i_cancel = src.find("cancel")
    assert i_term != -1 and i_cancel != -1, src[:200]
    assert i_term < i_cancel, "terminate doit preceder cancel, sinon le read pend"
