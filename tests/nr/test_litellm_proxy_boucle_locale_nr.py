"""NR -- le proxy litellm lance par le bring-up n'ecoute que sur la boucle locale (owner 1/11).

MESURE du 31/10 : `forge_local_llm_bringup.py` lancait `litellm.exe --config ... --port 4000` sans `--host` ni
`master_key`. Defaut litellm = 0.0.0.0 : le proxy aurait servi le reseau local sans authentification, en litellm
1.96.2 (CVE-2026-114612, elevation vers proxy_admin). Dormant ce jour-la (rien sur :4000), mais a un lancement pres.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_local_llm_bringup as B  # noqa: E402

SOURCE = Path(B.__file__).read_text(encoding="utf-8")


def test_le_proxy_est_lie_a_la_boucle_locale():
    argv = B.argv_litellm("litellm.exe", "cfg.yaml")
    assert argv[argv.index("--host") + 1] == "127.0.0.1"
    assert argv[argv.index("--port") + 1] == "4000"


def test_main_construit_le_proxy_par_argv_litellm_et_nulle_part_ailleurs():
    # Le chemin REEL : une seconde liste `[..., "--port", "4000"]` dans main contournerait la fonction testee.
    arbre = ast.parse(SOURCE)
    main = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    appels = [n for n in ast.walk(main) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "argv_litellm"]
    assert appels, "main ne passe plus par argv_litellm"
    listes_4000 = [n for n in ast.walk(main) if isinstance(n, ast.List)
                   and any(isinstance(e, ast.Constant) and e.value == "4000" for e in n.elts)]
    assert listes_4000 == []
