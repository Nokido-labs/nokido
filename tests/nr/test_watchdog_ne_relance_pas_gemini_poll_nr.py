"""NR : le watchdog de l'homeostasie ne relance plus gemini_poll_daemon (decision owner 26/10).

Constat 24/10 : NokidoGeminiDaemon `enabled = false` dans services.toml mais VIVANT, ecrivant
~/.gemini/inbox.md (39 Mo) que personne ne lit (AGY recoit son courrier par le hub, mesure 26/10).
Le relanceur etait DAEMON_WATCHDOGS : il respawnait le demon des que son pouls passait 600 s,
sans lire le drapeau du superviseur. Arreter le service sans retirer l'entree = il revient.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _noms_surveilles() -> list:
    arbre = ast.parse((ROOT / "app" / "forge_homeostasis_orchestrator.py").read_text(encoding="utf-8"))
    for n in arbre.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "DAEMON_WATCHDOGS" for t in n.targets):
            noms = []
            for d in n.value.elts:
                for k, v in zip(d.keys, d.values):
                    if isinstance(k, ast.Constant) and k.value == "name":
                        noms.append(v.value)
            return noms
    raise AssertionError("DAEMON_WATCHDOGS introuvable")


def test_gemini_poll_daemon_n_est_plus_relance():
    noms = _noms_surveilles()
    assert noms, "le test ne voit plus aucune entree : il ne prouverait rien"
    assert "gemini_poll_daemon" not in noms
