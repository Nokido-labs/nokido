"""NR -- chaque raccourci des TUI Textual est ATTEIGNABLE depuis un vrai terminal.

Mesures du 2026-09-25 (Textual 8.2.5, octets reels decodes par XTermParser) :
  - un terminal envoie `\\r` pour Ctrl+M comme pour Entree, `\\x08` pour Ctrl+H -- decodes
    `enter` / `backspace` : les bascules RAG et Health de tools/nokido_tui.py ne se declenchaient
    JAMAIS (0 declenchement mesure), alors que l'aide les annoncait ;
  - la TUI v13 (app/Nokido.py, servie par le bridge :7440) : Ctrl+1 -> « 1 », Ctrl+2 -> NUL
    (ctrl+@), Ctrl+3 -> ESC, Ctrl+Maj+A -> \\x01 (ctrl+a). Quatre raccourcis inatteignables.
Pilot `press("ctrl+m")` les declenchait : le test simule injectait un nom de touche qu'aucun
terminal n'emet -- d'ou « non prouve » jusqu'a cette mesure.

Regle : un Binding passe si AU MOINS UNE de ses alternatives (« a,b ») est emise par un terminal
classique ET decodee telle quelle. Les Binding sont lus par AST : app/Nokido.py ouvre son journal
dans logs/ a l'import, ce que le compte de CI ne peut pas faire.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from textual._xterm_parser import XTermParser

RACINE = Path(__file__).resolve().parents[2]
TUIS = (RACINE / "tools" / "nokido_tui.py", RACINE / "app" / "Nokido.py")
# Sequences qu'un terminal classique (xterm, xterm.js) emet pour les touches F.
SEQ_F = {"f1": "\x1bOP", "f2": "\x1bOQ", "f3": "\x1bOR", "f4": "\x1bOS", "f5": "\x1b[15~",
         "f6": "\x1b[17~", "f7": "\x1b[18~", "f8": "\x1b[19~", "f9": "\x1b[20~", "f10": "\x1b[21~"}


def _decode(octets: str) -> list[str]:
    params = inspect.signature(XTermParser.__init__).parameters
    parser = XTermParser(False) if len(params) == 2 else XTermParser()
    return [getattr(e, "key", type(e).__name__) for e in parser.feed(octets)]


def _emise(touche: str) -> bool:
    """La touche est-elle EMISE par un terminal classique et decodee telle quelle ?"""
    t = touche.strip().lower()
    if re.fullmatch(r"ctrl\+[a-z]", t):
        return _decode(chr(ord(t[-1]) - 96)) == [t]
    if t in SEQ_F:
        return _decode(SEQ_F[t]) == [t]
    if t.startswith("ctrl+") or "shift+" in t or "alt+" in t:
        return False  # ctrl+chiffre, ctrl+maj+x... : pas d'octet distinct en terminal classique
    return True  # touche nommee ordinaire (tab, enter, chiffre, lettre, f11/f12...)


def _bindings(chemin: Path) -> list[tuple[str, str]]:
    """(cles, action) de chaque Binding(...) litteral du fichier."""
    out = []
    for n in ast.walk(ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Binding" and len(n.args) >= 2:
            if all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in n.args[:2]):
                out.append((n.args[0].value, n.args[1].value))
    return out


def test_garde_du_garde_le_terminal_confond_ctrl_m_et_entree():
    assert _decode("\r") == ["enter"], "Ctrl+M = Entree cote terminal : la mesure fondatrice a change"
    assert _emise("ctrl+k") and _emise("f2")
    assert not _emise("ctrl+m") and not _emise("ctrl+h") and not _emise("ctrl+1") and not _emise("ctrl+shift+a")


def test_chaque_raccourci_a_une_alternative_emise_par_un_terminal():
    fautes, vus = [], 0
    for chemin in TUIS:
        for cles, action in _bindings(chemin):
            vus += 1
            if not any(_emise(k) for k in cles.split(",")):
                fautes.append("%s : %r (action %s)" % (chemin.name, cles, action))
    assert vus >= 30, "lecteur de Binding aveugle : %d vus" % vus
    assert not fautes, "raccourcis INATTEIGNABLES depuis un vrai terminal :\n  " + "\n  ".join(fautes)


def test_l_aide_n_annonce_pas_un_raccourci_inatteignable():
    src = (RACINE / "tools" / "nokido_tui.py").read_text(encoding="utf-8")
    i = src.index("def action_help")
    aide = src[i:src.index("\n    def ", i + 10)]
    for mort in ("Ctrl+M ", "Ctrl+H "):
        assert mort not in aide, "l'aide annonce %s, que le terminal ne peut pas emettre" % mort.strip()
