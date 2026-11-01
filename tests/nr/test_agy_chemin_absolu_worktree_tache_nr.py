"""NR : la consigne que l'executeur ajoute pour AGY porte le chemin ABSOLU du worktree de tache (owner 29/10).

Mesure du 29/10 : depuis le worktree par tache (520ef7f39), agy est lance avec cwd et --add-dir sur
nokido_worktrees/taches/antigravity_<id>, mais il ecrivait ses livrables relativement a SON espace habituel
(nokido_worktrees/antigravity) : 3 audits reels (oauth, coffre, ACP) juges RIEN_PRODUIT, le worktree mesure etant vide.
Le chemin absolu dans la consigne lui dit ou ecrire ; ce NR tient la consigne ET son emploi dans la commande agy.
"""
import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
SRC = RACINE / "tools" / "forge_task_executor.py"


def test_la_consigne_porte_le_chemin_absolu():
    import forge_task_executor as TE
    wd = r"C:\x\nokido_worktrees\taches\antigravity_abc123"
    c = TE._consigne_agy(wd)
    assert wd in c
    assert "AUCUNE commande" in c and "OK_DONE" in c


def test_la_commande_agy_emploie_la_consigne_du_workdir():
    arbre = ast.parse(SRC.read_text(encoding="utf-8"))
    appels = [n for n in ast.walk(arbre) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_consigne_agy"]
    assert any(a.args and isinstance(a.args[0], ast.Name) and a.args[0].id == "workdir" for a in appels)
    noms = {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)}
    assert "_CONSIGNE_SANS_COMMANDE_AGY" not in noms or "_consigne_agy" in noms
