"""NR : l'executeur rapatrie dans le worktree de TACHE ce qu'AGY a ecrit dans son worktree HABITUEL pendant la tache.

Mesure du 29-30/10 : 5 livraisons reelles d'AGY (audits oauth/coffre/ACP, etude identite, reparation du NR ctl) jugees
RIEN_PRODUIT -- AGY ecrit relativement a SON espace (nokido_worktrees/antigravity) quel que soit le chemin donne, meme
absolu dans la consigne (_consigne_agy, insuffisant). Rapatriement : seul ce qui est APPARU ou devenu modifie pendant la
tache est copie (l'etat d'avant est releve) ; rien n'est supprime dans le worktree habituel.
"""
import ast
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))


def _depot(d: Path) -> Path:
    d.mkdir(parents=True)
    for cmd in (["init", "-q"], ["config", "user.email", "nr@local"], ["config", "user.name", "nr"]):
        subprocess.run(["git", "-C", str(d)] + cmd, check=True, capture_output=True)
    (d / "suivi.txt").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(d), "add", "suivi.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "init"], check=True, capture_output=True)
    return d


def test_les_ecrits_de_la_tache_sont_rapatries_et_pas_le_reste(tmp_path):
    import forge_task_executor as TE
    habituel, tache = _depot(tmp_path / "habituel"), _depot(tmp_path / "tache")
    (habituel / "deja_sale.txt").write_text("avant la tache\n", encoding="utf-8")
    avant = TE._chemins_status(str(habituel))
    (habituel / "docs").mkdir()
    (habituel / "docs" / "livrable.md").write_text("ecrit par AGY\n", encoding="utf-8")
    (habituel / "suivi.txt").write_text("v2 par AGY\n", encoding="utf-8")
    copies = TE._rapatrier_ecrits_hors_tache(str(habituel), str(tache), avant)
    assert sorted(copies) == ["docs/livrable.md", "suivi.txt"]
    assert (tache / "docs" / "livrable.md").read_text(encoding="utf-8") == "ecrit par AGY\n"
    assert (tache / "suivi.txt").read_text(encoding="utf-8") == "v2 par AGY\n"
    assert not (tache / "deja_sale.txt").exists()  # sale AVANT la tache : pas le travail de la tache
    assert (habituel / "docs" / "livrable.md").exists()  # rien supprime dans le worktree habituel


def test_meme_worktree_ou_etat_illisible_ne_fait_rien(tmp_path):
    import forge_task_executor as TE
    d = _depot(tmp_path / "d")
    assert TE._rapatrier_ecrits_hors_tache(str(d), str(d), frozenset()) == []
    assert TE._rapatrier_ecrits_hors_tache(str(d), str(tmp_path / "autre"), None) == []


def test_la_delegation_agy_rapatrie_avant_de_juger():
    src = (RACINE / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_delegate_to_agy")
    noms = [c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
    assert "_rapatrier_ecrits_hors_tache" in noms
    assert noms.index("_rapatrier_ecrits_hors_tache") < noms.index("_juger_livraison")
