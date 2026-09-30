"""tools/arm_applier.py — arme l'etage REFLEXE de l'applicateur (owner 2026-08-27).

Pose `LAFORGE_APPLIER_ARMED=1` dans Nokido.env (idempotent, reversible). Ce flag arme
UNIQUEMENT l'etage REFLEXE de forge_proposal_applier : actions REVERSIBLES PURES
(`reclaim_cache`, `unload_idle`), confiance >= 0.75, sante globale LISIBLE requise.

Il n'arme PAS l'etage CORTICAL (`stop_service`, `topology_change`, et tout type inconnu
= le defaut) qui reste owner-gated. Il ne touche pas non plus le chemin de MUTATION de
code (MutationCycle -> juger_module_avec_gain), opt-in et cortical par nature.

Effet au PROCHAIN restart (l'env est charge au boot). Desarmer = retirer la ligne.
Verifie AVANT : `forge_proposal_applier.appliquer(dry_run=True)` -> plan reflexe seul.
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/config : arme l'etage reflexe de l'applicateur (Nokido.env)"  # organe declare le 2026-09-06 (audit de raccordement)

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "Nokido.env"


def main() -> int:
    txt = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    if "LAFORGE_APPLIER_ARMED" in txt:
        print("SKIP : LAFORGE_APPLIER_ARMED deja present dans Nokido.env")
        return 0
    sep = "" if (not txt or txt.endswith("\n")) else "\n"
    bloc = (sep
            + "\n# Arme l'etage REFLEXE de l'applicateur (reclaim_cache/unload_idle,\n"
            + "# reversibles purs, conf >= 0.75, sante lisible). PAS le cortical.\n"
            + "# Owner 2026-08-27, apres verification dry-run. Retirer cette ligne desarme.\n"
            + "LAFORGE_APPLIER_ARMED=1\n")
    ENV.write_text(txt + bloc, encoding="utf-8")
    relu = ENV.read_text(encoding="utf-8")
    if "LAFORGE_APPLIER_ARMED=1" not in relu:
        raise AssertionError("RELECTURE sans le flag — ecriture perdue")
    print("ARME : LAFORGE_APPLIER_ARMED=1 pose dans Nokido.env — effet au prochain restart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
