"""NR — SWE-bench vit HORS de RAG/, et tous ses runners le prennent au meme resolveur.

Decision owner du 2026-09-27 : SWE-bench n'a plus rien a faire dans RAG/ (= V:, le volume
chiffre du savoir, taille fixe). Ses 1,98 Go etaient a ~99 % des clones git regenerables,
0 resolu sur 23 puis sur 10 ; l'historique est archive, verifie au sha256, sur E:.
Avant : cinq sites construisaient `ROOT / "RAG" / "swebench"` chacun de leur cote, et le
runner LATS ignorait meme SWEBENCH_DIR que les lanceurs posent.

Invariants :
- le defaut n'est PAS sous RAG/ ; SWEBENCH_DIR et SWEBENCH_CACHE_DIR le deplacent, relus a
  chaque appel ;
- `swebench_score` lit ses evaluations dans ce dossier-la ;
- CHEMIN REEL : chaque runner, importe par son point d'entree dans un processus neuf,
  resout son dossier au resolveur (pas de lecture de source seule) ;
- aucun des sites ne reconstruit `"RAG" / "swebench"`.
Hermetique : les dossiers de travail pointent dans tmp_path.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_benchmark_adapter as ba  # noqa: E402

# (fichier, attribut de module qui porte le dossier, variable qui le pilote)
SITES = (
    ("tools/forge_swebench_runner.py", "SWE_DIR", "SWEBENCH_DIR"),
    ("tools/forge_swebench_lats_runner.py", "SWE_DIR", "SWEBENCH_DIR"),
    ("tools/forge_swebench_repo_cache.py", "CACHE_ROOT", "SWEBENCH_CACHE_DIR"),
    ("tools/forge_sft_export.py", "SWE", "SWEBENCH_DIR"),
)
MODAL = "tools/forge_swebench_modal.py"


def test_defaut_hors_de_rag(monkeypatch):
    monkeypatch.delenv("SWEBENCH_DIR", raising=False)
    monkeypatch.delenv("SWEBENCH_CACHE_DIR", raising=False)
    rag = (ROOT / "RAG").resolve()
    for d in (ba.swebench_dir(), ba.swebench_cache_dir()):
        assert rag not in d.resolve().parents and d.resolve() != rag, d
        assert d.parent == ROOT / "sandbox" / "workspace", d


def test_variables_relues_a_chaque_appel(monkeypatch, tmp_path):
    monkeypatch.setenv("SWEBENCH_DIR", str(tmp_path / "swe"))
    monkeypatch.delenv("SWEBENCH_CACHE_DIR", raising=False)
    assert ba.swebench_dir() == tmp_path / "swe"
    assert ba.swebench_cache_dir() == tmp_path / "swebench_cache"
    monkeypatch.setenv("SWEBENCH_CACHE_DIR", str(tmp_path / "cache"))
    assert ba.swebench_cache_dir() == tmp_path / "cache"


def test_score_lu_dans_le_dossier_resolu(monkeypatch, tmp_path):
    monkeypatch.setenv("SWEBENCH_DIR", str(tmp_path))
    assert ba.swebench_score() is None  # rien d'ecrit : absent, pas zero
    (tmp_path / "eval_lats_20260927.json").write_text(
        json.dumps({"resolve_rate": 12.5}), encoding="utf-8")
    assert ba.swebench_score() == 12.5
    assert ba.latest_scores().get("swebench") == 12.5


@pytest.mark.timeout(120)
@pytest.mark.parametrize("fichier,attr,var", SITES)
def test_chemin_reel_chaque_runner_prend_le_resolveur(tmp_path, fichier, attr, var):
    """Import par le point d'entree, processus neuf : la valeur du module suit la variable."""
    cible = tmp_path / "dossier_pilote"
    env = {**os.environ, "PYTHONNOUSERSITE": "1",
           "SWEBENCH_DIR": str(tmp_path / "swe"), var: str(cible)}
    code = ("import runpy, sys\nsys.argv = ['x']\n"
            f"g = runpy.run_path({str(ROOT / fichier)!r}, run_name='nr_import')\n"
            f"print('VALEUR=' + str(g[{attr!r}]))\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       errors="replace", timeout=110, env=env, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr[-2000:]
    valeur = [ln for ln in r.stdout.splitlines() if ln.startswith("VALEUR=")]
    assert valeur, r.stdout[-2000:]
    assert Path(valeur[-1][len("VALEUR="):]) == cible


def test_aucun_site_ne_reconstruit_rag_swebench():
    motif = re.compile(r"""["']RAG["']\s*/\s*["']swebench|RAG[/\\]swebench""")
    for fichier in [s[0] for s in SITES] + [MODAL]:
        src = (ROOT / fichier).read_text(encoding="utf-8")
        assert not motif.search(src), fichier
    assert "r.SWE_DIR /" in (ROOT / MODAL).read_text(encoding="utf-8")
