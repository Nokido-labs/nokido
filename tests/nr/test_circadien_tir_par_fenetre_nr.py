"""NR -- le superviseur tire une phase circadienne si elle n'a pas encore tire dans SA fenetre courante.

Mesure 19/10 02:06 (journal superviseur, aucun `[circadian] FIRE` de 02:00 a 02:06) : NREM3 n'a pas tire parce que
son dernier tir etait un RATTRAPAGE de la veille vers 10:27 et que la regle etait « dernier tir >= 20 h » (15,6 h).
Le rattrapage suivant aurait encore tire a contretemps : cycle decale en permanence, NightTrainer/OfflineTrainer
jamais reveilles la nuit (P0 circadien). La logique vit dans proxy_deno/core/circadian_fenetre.ts (pure, testee par
circadian_fenetre_test.ts) ; ce NR fige le branchement et joue le test Deno quand Deno est lisible -- sinon il est
SAUTE en le disant (Deno vit dans le profil owner : illisible n'est pas vert).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "proxy_deno" / "core"


def test_la_boucle_circadienne_decide_par_la_fenetre():
    src = (CORE / "supervisor.ts").read_text(encoding="utf-8")
    boucle = src[src.index("async function circadianLoop"):src.index("function circadianStatus")]
    assert "doitTirer(" in boucle, "la boucle doit appeler doitTirer"
    assert not re.search(r"hoursSince\s*>=\s*20", boucle), "la regle des 20 h est encore la"
    assert re.search(r'import\s*\{[^}]*doitTirer[^}]*\}\s*from\s*"\./circadian_fenetre\.ts"', src)


def test_le_module_pur_exporte_la_regle():
    mod = (CORE / "circadian_fenetre.ts").read_text(encoding="utf-8")
    assert "export function doitTirer" in mod and "export function debutFenetre" in mod


def _deno() -> str:
    """Meme recherche que le gate git (tools/forge_git_gate.py) : copie PARTAGEE d'abord, le profil owner etant
    invisible des comptes de service."""
    for cand in ("C:/ProgramData/deno/deno.exe", "C:/ProgramData/Nokido/deno.exe",
                 shutil.which("deno") or "", os.path.expanduser("~/.deno/bin/deno.exe")):
        try:
            if cand and os.path.exists(cand):
                return cand
        except OSError:
            continue
    return ""


def test_le_test_deno_passe_quand_deno_est_lisible():
    deno = _deno()
    if not deno:
        pytest.skip("deno ILLISIBLE depuis ce compte : verification TS a faire par l'owner (deno test)")
    env = dict(os.environ)
    if os.path.isdir("C:/ProgramData/deno/cache"):
        env.setdefault("DENO_DIR", "C:/ProgramData/deno/cache")
    # borne SOUS le --timeout=30 de la suite : un deno bloque (mesure 20/10, rejoue seul en 0,8 s) abattait la suite
    try:
        r = subprocess.run([deno, "test", "--quiet", str(CORE / "circadian_fenetre_test.ts")], capture_output=True,
                           text=True, errors="replace", timeout=20, env=env)
    except subprocess.TimeoutExpired:
        pytest.skip("deno n'a pas repondu en 20 s : ILLISIBLE (pas vert) -- verification TS a refaire (deno test)")
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
