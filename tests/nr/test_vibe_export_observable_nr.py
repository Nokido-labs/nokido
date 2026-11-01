"""NR du 27/10 : une execution Vibe deleguee laisse son export.json (owner : « ca suffit ces echecs repetes »).

Mesure : 3 echecs Vibe le 27/10 lisibles seulement en fouillant le flux JSON du harness et un vibe.log en UTC
(`model_stream_failed`, `ReadTimeout`, `turn_limit`). Vibe 3.0.1 sait ecrire a chaque sortie un export.json
(config effective, jetons, cout, raison d'arret, resultat) via --output-dir : l'executeur ne le demandait pas.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import forge_task_executor as T  # noqa: E402


def test_l_export_vibe_est_demande_a_cote_du_prompt():
    args = T._args_vibe("C:/wt", "C:/jobs/vibe_job_x.prompt.md")
    assert "--output-dir" in args, args
    sortie = Path(args[args.index("--output-dir") + 1])
    assert sortie.parent == Path("C:/jobs") and sortie.name.startswith("vibe_job_x"), sortie


def test_sans_prompt_pas_d_export_invente():
    assert "--output-dir" not in T._args_vibe("C:/wt")
