"""NR -- revue d'integration T2b (CLAUDE 28/10) : la file de permissions se defend seule.

1. decider(pid) construisait dossier / f"{pid}.json" sans valider pid : traversee de chemin (« ../x »).
   Le front T3 filtre, mais la fonction est aussi appelee par la CLI.
2. La demande deposee portait `request` EN CLAIR alors que le journal de session est caviarde :
   une commande d'outil avec un secret restait lisible dans sandbox/acp_permissions/.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_router as R  # noqa: E402


@pytest.mark.parametrize("pid", ["../x", "..\\x", "a/b", "", "ABC", "0" * 31, "0" * 32 + ".json"])
def test_decider_refuse_un_identifiant_qui_n_est_pas_un_uuid_hex(tmp_path, pid):
    dehors = tmp_path / "x.json"
    dehors.write_text(json.dumps({"etat": "EN_ATTENTE", "options": [{"optionId": "allow"}]}), encoding="utf-8")
    dossier = tmp_path / "perm"
    dossier.mkdir()
    with pytest.raises(ValueError):
        R.decider(pid, option="allow", dossier=dossier)
    assert json.loads(dehors.read_text(encoding="utf-8"))["etat"] == "EN_ATTENTE"  # rien d'ecrit hors du dossier


def test_demande_deposee_passe_par_le_redacteur(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_caviarder", lambda obj: json.loads(json.dumps(obj).replace("JETON_FICTIF", "[MASQUE]")))
    pol = R.politique_owner(dossier=tmp_path, delai_s=0.5)
    req = {"sessionId": "s1", "toolCall": {"rawInput": {"command": "curl -H JETON_FICTIF"}},
           "options": [{"optionId": "allow", "kind": "allow_once"}]}
    box = {}
    t = threading.Thread(target=lambda: box.update(r=pol(req)))
    t.start()
    fichier = None
    for _ in range(100):
        fs = list(tmp_path.glob("*.json"))
        if fs:
            fichier = fs[0]
            break
        time.sleep(0.02)
    assert fichier is not None
    texte = fichier.read_text(encoding="utf-8")
    assert "JETON_FICTIF" not in texte and "[MASQUE]" in texte
    # les options restent exploitables : l'owner peut toujours choisir
    assert json.loads(texte)["options"][0]["optionId"] == "allow"
    t.join(5)
    assert box["r"] == {"outcome": "cancelled"}  # expiration -> fail-closed
