"""NR 9/11 : `trusted_script tools/forge_audit_processus.py --statut` affichait
« etat non conserve, racine de donnees illisible : ModuleNotFoundError » -- le paquet `nokido_agent`
n'est pas importable sous ce lanceur. Le chemin de l'état doit se résoudre par `app.` depuis le dépôt.
"""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_etat_resolu_sans_paquet_nokido_agent(monkeypatch):
    for nom in ("nokido_agent", "nokido_agent.app", "nokido_agent.app.forge_db_path"):
        monkeypatch.setitem(sys.modules, nom, None)   # import -> ImportError, meme si deja en cache
    ap = importlib.import_module("forge_audit_processus")
    f = ap._fichier_etat()
    assert f is not None and f.name == "audit_processus_etat.json"
