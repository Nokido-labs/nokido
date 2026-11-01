"""NR : le hook Stop de Claude (tools/session_anchor.py) ne relance plus gemini_poll_daemon (decision owner 26/10).

Trouve le 27/10 apres la relance groupee : le demon revenait (pid neuf, mode passif) alors que le watchdog de
l'homeostasie ne le relancait plus (7af7ca566). Le second lanceur etait ce hook, qui tourne a CHAQUE fin de tour et
relancait tout demon de sa liste dont le pouls depassait 5 min : c'etait le « lanceur non identifie » du 24/10.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _demons():
    arbre = ast.parse((ROOT / "tools" / "session_anchor.py").read_text(encoding="utf-8"))
    for n in arbre.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "DAEMONS" for t in n.targets):
            return [e.elts[0].value for e in n.value.elts]
    raise AssertionError("DAEMONS introuvable")


def test_le_hook_stop_ne_relance_pas_gemini_poll():
    demons = _demons()
    assert demons, "le test ne voit plus la liste : il ne prouverait rien"
    assert "gemini_poll_daemon" not in demons
