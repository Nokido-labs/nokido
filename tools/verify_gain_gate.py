"""tools/verify_gain_gate.py — vérif RÉELLE du gain-gate sur un vrai fichier.

En action=python, subprocess est bloque (WORKSPACE_GUARD) donc patron_sain (git HEAD)
echoue et le juge rend REFUSE : verdict inconcluant. Ici (trusted_script) subprocess
marche. On exerce le gate de bout en bout sur une cible SURE et mutable (ce fichier
lui-meme via une copie ? non : on prend tools/arm_applier.py, petit, committe, sans
dependance) : mutation CASSEE -> MEURT (revert) ; NO-OP -> SURVIT_SANS_GAIN/NEUTRE
(revert). Prouve que le gate est CONSERVATEUR (ne garde ni cassé ni sans-gain) sur du
reel. Le fichier doit rester INTACT. Puis on affiche le tableau de bord.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_mutation_judge as mj  # noqa: E402

CIBLE = "tools/arm_applier.py"
p = ROOT / CIBLE
orig = p.read_text(encoding="utf-8")


def main() -> int:
    r_casse = mj.juger_module_avec_gain(CIBLE, orig + "\ndef (:\n", [])
    intact1 = p.read_text(encoding="utf-8") == orig
    r_noop = mj.juger_module_avec_gain(CIBLE, orig, [])
    intact2 = p.read_text(encoding="utf-8") == orig
    print("CAS casse  -> verdict=%s cause=%s | fichier intact=%s"
          % (r_casse.get("verdict"), r_casse.get("cause"), intact1))
    print("CAS no-op  -> verdict=%s | fichier intact=%s"
          % (r_noop.get("verdict"), intact2))
    print("garde-t-il du junk ? %s (attendu: NON)"
          % any(x.get("verdict") == "AMELIORE" for x in (r_casse, r_noop)))
    import json
    print("DASHBOARD:", json.dumps(mj.tableau_de_bord(), ensure_ascii=False))
    # restauration de securite si un cas a laisse le fichier modifie
    if p.read_text(encoding="utf-8") != orig:
        p.write_text(orig, encoding="utf-8")
        print("RESTAURE (securite)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
