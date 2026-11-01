"""NR -- parite ACP : on RELEVE ce que l'agent repond, on n'invente jamais une capacite.

Agent simule = faux processus stdio JSON-RPC. Absent / muet / illisible => statut + motif, jamais « false » suppose.
Aucun session/prompt n'est envoye (aucun cout modele).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_parite as P  # noqa: E402

FAUX = r'''
import json, sys
mode = sys.argv[1]
for line in sys.stdin:
    m = json.loads(line)
    meth = m.get("method")
    if meth == "session/prompt":
        open(sys.argv[2], "w").write("PROMPT")
    if mode == "muet":
        continue
    if mode == "garbage":
        print("pas du json", flush=True); sys.exit(0)
    if meth == "initialize":
        res = {"protocolVersion": 1,
               "agentCapabilities": {"loadSession": True,
                   "promptCapabilities": {"image": True, "audio": False, "embeddedContext": True},
                   "mcpCapabilities": {"http": True, "sse": False}},
               "authMethods": [{"id": "oauth", "name": "OAuth"}]}
        if mode == "partiel":
            res = {"protocolVersion": 1, "agentCapabilities": {"promptCapabilities": {"image": True}}}
    elif meth == "session/new":
        res = {"sessionId": "s1",
               "modes": {"currentModeId": "default", "availableModes": [{"id": "default"}]},
               "models": {"currentModelId": "m1", "availableModels": [{"modelId": "m1"}]}}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": res}), flush=True)
'''


def _cmd(tmp_path, mode):
    f = tmp_path / "faux.py"
    f.write_text(FAUX, encoding="utf-8")
    return [sys.executable, str(f), mode, str(tmp_path / "prompt.flag")]


def test_releve_complet(tmp_path):
    r = P.sonder("gemini", cmd=_cmd(tmp_path, "ok"), timeout=20)
    assert r["statut"] == "OK"
    assert r["protocolVersion"] == 1
    assert r["loadSession"] is True
    assert r["promptCapabilities"] == {"image": True, "audio": False, "embeddedContext": True}
    assert r["mcpCapabilities"] == {"http": True, "sse": False}
    assert r["authMethods"] == [{"id": "oauth", "name": "OAuth"}]
    assert r["sessionId"] == "s1"
    assert r["modes"]["currentModeId"] == "default"
    assert r["models"]["currentModelId"] == "m1"
    assert not (tmp_path / "prompt.flag").exists()  # aucun prompt envoye


def test_champ_non_repondu_reste_none_jamais_false(tmp_path):
    r = P.sonder("claude", cmd=_cmd(tmp_path, "partiel"), timeout=20)
    assert r["statut"] == "OK"
    assert r["promptCapabilities"] == {"image": True}  # audio/embeddedContext non inventes
    assert r["loadSession"] is None
    assert r["mcpCapabilities"] is None
    assert r["authMethods"] is None


def test_agent_introuvable_est_absent_avec_motif():
    r = P.sonder("codex", cmd=["binaire-inexistant-xyz-acp"], timeout=10)
    assert r["statut"] == "ABSENT" and r["motif"]
    assert r.get("loadSession") is None and r.get("promptCapabilities") is None
    # 28/10 : sous LaForgeSbxOffline, 4 CLI du profil owner « introuvables » -> le motif nomme le compte qui cherche
    import getpass
    assert getpass.getuser() in r["motif"] and r["compte"] == getpass.getuser()


def test_agent_muet_est_illisible(tmp_path):
    r = P.sonder("opencode", cmd=_cmd(tmp_path, "muet"), timeout=3)
    assert r["statut"] == "ILLISIBLE" and r["motif"]
    assert r.get("promptCapabilities") is None


def test_sortie_non_json_est_illisible(tmp_path):
    r = P.sonder("gemini", cmd=_cmd(tmp_path, "garbage"), timeout=10)
    assert r["statut"] == "ILLISIBLE" and r["motif"]


def test_agy_hors_acp_sans_tentative():
    r = P.sonder("agy")
    assert r["statut"] == "HORS_ACP" and "harness" in r["motif"]


def test_timeout_borne_a_60():
    assert P.borner_timeout(500) == 60
    assert P.borner_timeout(5) == 5


def test_docs_refuse_au_job_replie_sur_le_bac_a_sable(tmp_path):
    """Mesure reelle 28/10 (job_7cf2f9ed8268) : le compte du bac a sable ne peut pas creer docs/mesures
    (WinError 5) -> releve perdu, rc=1. Le releve doit atterrir dans sandbox/workspace, et le dire."""
    (tmp_path / "docs").write_text("bloque", encoding="utf-8")  # docs/mesures impossible a creer
    out = P.ecrire_mesure({"agents": []}, tmp_path, stamp="20261028")
    assert out == tmp_path / "sandbox" / "workspace" / "acp_parite_20261028.json"
    assert out.read_text(encoding="utf-8").startswith("{")


def test_docs_accessible_reste_la_destination(tmp_path):
    out = P.ecrire_mesure({"agents": []}, tmp_path, stamp="20261028")
    assert out == tmp_path / "docs" / "mesures" / "acp_parite_20261028.json"
