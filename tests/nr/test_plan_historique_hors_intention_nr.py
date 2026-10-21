"""NR -- un doc de plan marque HISTORIQUE n'est plus une intention (decision owner 18/10).

Six des quinze ecarts doc/code du 18/10 venaient de plans anciens (MIGRATION_PLAN.md,
supervisor_phase8_plan.md, PLAN_REORGANISATION.md). Leur en-tete porte desormais le marqueur
`<!-- nokido: plan-historique -->` : le capteur unmet_intention ne les lit plus comme une
cible, et il COMPTE ce qu'il ecarte ainsi.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_autonomous_loops as al  # noqa: E402


def test_le_marqueur_en_tete_est_reconnu():
    assert al._est_plan_historique("<!-- nokido: plan-historique -->\n# Plan\n")
    assert al._est_plan_historique("# Plan X\n\n<!-- nokido: plan-historique -->\n")


def test_sans_marqueur_ou_marqueur_tardif_reste_une_intention():
    assert not al._est_plan_historique("# Plan\nforge_x.py\n")
    # un marqueur CITE loin dans le corps (ex. une doc qui en parle) ne declasse pas le doc
    assert not al._est_plan_historique("# Plan\n" + "x\n" * 2000 + "<!-- nokido: plan-historique -->\n")


def test_le_capteur_ignore_les_modules_d_un_plan_historique(tmp_path, monkeypatch):
    specs = tmp_path / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / "ancien_plan.md").write_text(
        "<!-- nokido: plan-historique -->\n# Ancien\n`forge_zz_absent.py`\n", encoding="utf-8")
    (specs / "vivant_plan.md").write_text("# Vivant\n`forge_yy_absent.py`\n", encoding="utf-8")
    monkeypatch.setattr(al, "ROOT", tmp_path)
    monkeypatch.setattr(al, "_docs_deportes", lambda: frozenset())
    modules = [d["module"] for d in al._modules_absents_des_docs()]
    assert modules == ["forge_yy_absent.py"]
