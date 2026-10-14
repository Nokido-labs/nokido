"""NR -- les fichiers critiques ne cachent plus leurs erreurs, et le portail n'invente plus sa part locale (14/10).

1. Definition du gate (`tools/forge_git_gate.py`) : un `except` dont le seul corps est `pass` ou `continue` est
   MUET sauf marqueur `muet-ok` sur sa ligne ou celle du corps. 24 sites dans nokido_hub.py et app/web_hub/app.py,
   dont plusieurs cachaient un effet reel : trace d'identite du videur perdue, reponse sans contexte RAG, pouls du hub
   non ecrit, repli silencieux sur le porteur brut.
2. `/api/hub/overview` rendait `local_pct = 100` PAR DEFAUT : un historique reseau ILLISIBLE s'affichait « 100 %
   local », une souverainete non mesuree presentee comme une mesure. Illisible = None ; le front dit « illisible ».
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRITIQUES = ("tools/nokido_hub.py", "app/web_hub/app.py")
FRONT = ("design_handoff_nokido/ui_kits/hub/hub-compiled.js", "design_handoff_nokido/ui_kits/hub/hub-views.ref.jsx")


def _muets(chemin: Path) -> list:
    src = chemin.read_text(encoding="utf-8")
    lignes = src.splitlines()
    out = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.ExceptHandler) and len(n.body) == 1 and isinstance(n.body[0], (ast.Pass, ast.Continue)):
            if not any("muet-ok" in lignes[k - 1] for k in {n.lineno, n.body[0].lineno}):
                out.append(n.lineno)
    return out


def test_aucun_chemin_d_erreur_muet_dans_les_fichiers_critiques():
    for rel in CRITIQUES:
        assert _muets(ROOT / rel) == [], rel


def test_une_part_locale_illisible_n_est_jamais_affichee_comme_100():
    src = (ROOT / "app" / "web_hub" / "app.py").read_text(encoding="utf-8")
    assert src.count("local_pct = 100") == 1, "le defaut de la part locale n'est plus unique : NR a reancrer"
    bloc = src[src.index("local_pct = 100"):]
    bloc = bloc[:bloc.index("return JSONResponse")]
    assert "local_pct = None" in bloc.split("except Exception", 1)[1]


def test_le_front_dit_illisible_au_lieu_d_inventer_un_chiffre():
    for rel in FRONT:
        texte = (ROOT / rel).read_text(encoding="utf-8")
        assert "ov.local_pct : 0" not in texte, rel
        assert "local : illisible" in texte, rel
