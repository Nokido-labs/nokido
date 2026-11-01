# -*- coding: utf-8 -*-
"""NR -- le journal de refus de la garde porte `cmd` (<= 80 car., caviardee) et `est_sonde` (decision owner 22/10 :
mesurer les faux refus). Mode et seuil inchanges (observer, refus au 3e tour)."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
HOOK = RACINE / "tools" / "hook_capability_gate.py"
# Faux jeton FABRIQUE a l'execution (1/11) : en un bloc, l'audit du snapshot public le lisait comme une cle Anthropic
# et refusait de publier. Valeur a l'execution inchangee.
FAUX_JETON = "sk-" + "ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef"


def _appel(tmp_path, t, entree):
    env = {**os.environ, "NOKIDO_GATE_ETAT": str(tmp_path / "etat.json"), "NOKIDO_GATE_MODE": "observer",
           "NOKIDO_GATE_HORLOGE": str(t), "NOKIDO_GATE_JOBS": str(tmp_path / "jobs"), "PYTHONNOUSERSITE": "1",
           "NOKIDO_GATE_JOURNAL": str(tmp_path / "journal.jsonl")}
    subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"tool_name": "Bash", "tool_input": entree}),
                   capture_output=True, text=True, errors="replace", env=env, timeout=60)


def _lignes(tmp_path):
    j = tmp_path / "journal.jsonl"
    return [json.loads(x) for x in j.read_text(encoding="utf-8").splitlines()] if j.exists() else []


def test_refus_porte_cmd_caviardee_et_est_sonde(tmp_path):
    cmd = "curl -s -H 'Authorization: Bearer " + FAUX_JETON + "' http://127.0.0.1:8766/health " + "x" * 200
    t0 = 1_800_000_000
    for d in (0, 10, 20):
        _appel(tmp_path, t0 + d, {"command": cmd})
    lignes = _lignes(tmp_path)
    assert len(lignes) == 1  # seuil inchange : refus au 3e tour seulement
    L = lignes[0]
    assert L["mode"] == "observer"
    assert L["est_sonde"] is True
    assert isinstance(L["cmd"], str) and 0 < len(L["cmd"]) <= 80
    assert FAUX_JETON[:20] not in L["cmd"]
    assert FAUX_JETON[:20] not in json.dumps(L)


def test_commande_absente_donne_cmd_vide():
    spec = importlib.util.spec_from_file_location("hcg_nr_cmd", HOOK)
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    assert G._cmd_pour_journal("Read", {"file_path": "x"}) == ""
    assert len(G._cmd_pour_journal("Bash", {"command": "a" * 500})) <= 80
