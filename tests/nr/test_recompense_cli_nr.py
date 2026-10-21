# -*- coding: utf-8 -*-
"""NR -- tout CLI consigne un verdict et lit la force des repondeurs par le CHEMIN REEL (owner 18/10).

« un client parmi d'autres » : la recompense par resultat (0022a37b5) ne doit pas vivre dans la seule session Claude.
Le point d'entree `app/forge_motivation.py` porte deux drapeaux, traverses ici en sous-processus :
  --verdict REPONDEUR CLASSE VERDICT [--preuve TEXTE] [--minutes N]  -> une ligne au registre, JSON sur stdout ;
  --force CLASSE [--candidats A,B,..]                                -> force mesuree + ordre hedoniste, JSON.
Le registre est redirige par la variable NOKIDO_MOTIVATION_RESULTATS (jamais le vrai sandbox).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
MOD = RACINE / "app" / "forge_motivation.py"


def _cli(tmp_path, *args):
    env = {**os.environ, "NOKIDO_MOTIVATION_RESULTATS": str(tmp_path / "r.jsonl"), "PYTHONNOUSERSITE": "1",
           "NOKIDO_MOTIVATION_SANS_CORPS": "1"}
    r = subprocess.run([sys.executable, str(MOD)] + list(args), capture_output=True, text=True, errors="replace",
                       env=env, timeout=60, cwd=str(RACINE))
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_verdict_puis_force_par_le_chemin_reel(tmp_path):
    _cli(tmp_path, "--verdict", "OPENCODE_NEMOTRON", "M:ecrit", "INTEGREE", "--preuve", "c7e1f498e")
    _cli(tmp_path, "--verdict", "ANTIGRAVITY", "M:ecrit", "REJETEE", "--preuve", "1edb516b8", "--minutes", "16")
    out = _cli(tmp_path, "--force", "M:ecrit", "--candidats", "ANTIGRAVITY,NEUF,OPENCODE_NEMOTRON")
    assert out["ordre"] == ["OPENCODE_NEMOTRON", "NEUF", "ANTIGRAVITY"]
    assert out["force"]["ANTIGRAVITY"]["rejetees"] == 1
    lignes = (tmp_path / "r.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 2


def test_sans_corps_aucune_hormone_ni_base(tmp_path):
    out = _cli(tmp_path, "--verdict", "WORKER_CODE", "S:ecrit", "VIDE")
    assert out["corps"] == {"ok": False, "raison": "NOKIDO_MOTIVATION_SANS_CORPS"}
