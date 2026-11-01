"""NR 29/10 (owner) -- toute instance OpenCode porte un modele PRINCIPAL `fournisseur/modele`. Sans lui (modele vide =
defaut integre opencode/big-pickle), l'epuisement constate ne peut pas nourrir le census (_couple_du_modele -> None) :
DEFAUT2-5 tombaient sur un quota invisible puis sur leur repli, 4 rendus faux le 29/10.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)]

import forge_task_executor as E  # noqa: E402


def test_chaque_instance_a_un_principal_consignable():
    data = json.loads((ROOT / "config" / "opencode_instances.json").read_text(encoding="utf-8"))
    sans = {k: v.get("modele") for k, v in data.items()
            if not k.startswith("_") and isinstance(v, dict) and not E._couple_du_modele(v.get("modele"))}
    assert sans == {}, "instances sans principal fournisseur/modele : %s" % sans
