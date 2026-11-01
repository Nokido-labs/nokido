"""NR -- le palier OpenCode propose TOUTES les instances configurees, pas seulement les 3 nommees en dur.

Enquete OPENCODE_DEFAUT3 du 27/10 (docs/enquetes/reaffectation_aucun_vivant_20261027.md) : OPENCODE_DEFAUT2..5 sont
dans config/opencode_instances.json mais absents de _OPENCODE_ECRITURE ; une reaffectation ne pouvait donc jamais les
choisir, et le journal ecrivait « aucun autre executeur vivant » alors que quatre l'etaient.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as te  # noqa: E402

INSTANCES = {k: {} for k in ("OPENCODE_GPTOSS", "OPENCODE_NEMOTRON", "OPENCODE_GLM",
                            "OPENCODE_DEFAUT2", "OPENCODE_DEFAUT3")}


def test_les_instances_configurees_sont_candidates(monkeypatch):
    monkeypatch.setattr(te, "_instances_opencode", lambda: INSTANCES)
    ordre = te._palier_executeurs("S", True)
    assert {"OPENCODE_DEFAUT2", "OPENCODE_DEFAUT3"} <= set(ordre)
    assert ordre[:3] == te._OPENCODE_ECRITURE, "les instances nommees gardent la priorite"
    assert len(ordre) == len(set(ordre))


def test_registre_illisible_garde_l_ordre_nomme(monkeypatch):
    def ko():
        raise OSError("illisible")
    monkeypatch.setattr(te, "_instances_opencode", ko)
    assert te._palier_executeurs("S", True) == te._OPENCODE_ECRITURE
