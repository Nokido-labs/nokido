"""NR -- le profil public bloque les journaux d'agents de TOUT dossier .agents/<role>/, jamais .agents/skills/.

Mesure 9/11 : la decision owner (10) du 8/11 enumerait 8 dossiers .agents/<role>_<lot>/ ; .agents/orchestrator/ et
.agents/sentinel/ (BRIEFING, handoff, progress, ORIGINAL_REQUEST) etaient publiables, le gate de release disait
« profil public ne bloque plus : telemetrie ». Le blocage se fait par NOM de journal : un role neuf ne fuit plus.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "app"), str(ROOT)]

import forge_git_egress as E  # noqa: E402


def _bloque(chemin):
    return bool(E._path_blocked(chemin, E.load_manifest()["profiles"]["public"]["blocked_paths"]))


def test_journaux_de_tout_role_bloques():
    for role in ("orchestrator", "sentinel", "role_neuf_jamais_vu"):
        for nom in ("BRIEFING.md", "ORIGINAL_REQUEST.md", "PROJECT.md", "handoff.md", "progress.md"):
            assert _bloque(".agents/%s/%s" % (role, nom)), (role, nom)


def test_skills_restent_publies():
    assert not _bloque(".agents/skills/forge-hub/SKILL.md")
