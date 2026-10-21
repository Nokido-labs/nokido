"""NR -- le mode observer du garde d'impulsion JOURNALISE ce qu'il aurait refuse (16/10).

Mesure 16/10 : sandbox/workspace/gate_state.json ne garde que la fenetre courante (impulsion_tours) ; aucune trace des
« SERAIT REFUSE » emis. Le mode observer existe pour MESURER le bruit avant la bascule refuser (doctrine « observer
avant d'enforcer ») : sans journal, la decision owner se prendrait sur une impression.
Interface : NOKIDO_GATE_JOURNAL = fichier jsonl, une ligne par refus (observe ou applique) : ts, outil, motif, mode.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(os.environ.get("NOKIDO_GATE_HOOK_FICHIER")
            or Path(__file__).resolve().parents[2] / "tools" / "hook_capability_gate.py")
RUN = "mcp__laforge-sovereign-hub__run"


def _appel(tmp_path, t, tool_input, mode):
    env = {**os.environ, "NOKIDO_GATE_ETAT": str(tmp_path / "etat.json"), "NOKIDO_GATE_MODE": mode,
           "NOKIDO_GATE_HORLOGE": str(t), "NOKIDO_GATE_JOBS": str(tmp_path), "PYTHONNOUSERSITE": "1",
           "NOKIDO_GATE_JOURNAL": str(tmp_path / "journal.jsonl")}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"tool_name": RUN, "tool_input": tool_input}),
                          capture_output=True, text=True, errors="replace", env=env, timeout=60).returncode


def test_un_refus_observe_laisse_une_ligne_de_journal(tmp_path):
    t0 = 1_800_000_000
    for d in (0, 10, 20):
        _appel(tmp_path, t0 + d, {"action": "python", "code": "print(1)"}, "observer")
    lignes = [json.loads(x) for x in (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines() if x]
    assert len(lignes) == 1, lignes
    assert lignes[0]["mode"] == "observer" and "impulsion" in lignes[0]["motif"].lower(), lignes[0]


def test_sans_refus_pas_de_ligne(tmp_path):
    _appel(tmp_path, 1_800_000_000, {"action": "python", "code": "print(1)"}, "observer")
    j = tmp_path / "journal.jsonl"
    assert not j.exists() or j.read_text(encoding="utf-8").strip() == ""
