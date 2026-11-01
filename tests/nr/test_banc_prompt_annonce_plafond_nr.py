"""NR : le prompt d'un banc annonce au generateur le plafond de lignes par patch (owner 30/10).

Mesure du 30/10 (job_96dfedf97d30, job_49d04d8b104d) : avec gpt-oss-120b, 4 candidats sur 6 refuses « patch too large »
(32 a 35 lignes) par la garde existante forge_self_patcher.MAX_PATCH_LINES -- le prompt ne la disait pas. La garde
reste intacte ; le generateur la connait. La valeur est LUE dans l'outil, jamais recopiee.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))
import forge_banc_amelioration as BA  # noqa: E402


def test_le_prompt_annonce_le_plafond_de_l_outil(tmp_path):
    from nokido_agent.tools.forge_self_patcher import MAX_PATCH_LINES
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    banc = {"perimetre": ["app/m.py"], "fonctions": ["f"], "juge": {"metrique": "m", "sens": "max"}}
    p = BA._prompt(banc, tmp_path, 0)
    assert "%d lignes" % MAX_PATCH_LINES in p
