"""NR -- recette Codex du 28/10 (session codex-1-8710352) : le modele par defaut de codex-acp (gpt-5.5) est
REFUSE pour un compte ChatGPT (400 model_not_found), alors que le CLI Codex de l'owner tourne sur le modele de
~/.codex/config.toml (gpt-6-luna). Le routeur choisit le modele prefere de l'agent, SEULEMENT s'il est annonce
par session/new (jamais deviner) ; sinon il le journalise. Faux agent stdio, aucun vrai CLI.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_router as R  # noqa: E402

FAUX = r'''
import json, sys
rec, modeles = sys.argv[1], json.loads(sys.argv[2])
for line in sys.stdin:
    m = json.loads(line)
    meth = m.get("method")
    if meth == "initialize":
        res = {"protocolVersion": 1, "agentCapabilities": {}}
    elif meth == "session/new":
        res = {"sessionId": "s1", "modes": {"availableModes": []},
               "models": {"availableModels": [{"modelId": x} for x in modeles]}}
    elif meth in ("session/set_model", "session/set_mode"):
        open(rec, "a").write(json.dumps({"method": meth, "params": m.get("params")}) + "\n")
        res = {}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": res}), flush=True)
'''


def _routeur(tmp_path, modeles):
    f = tmp_path / "faux.py"
    f.write_text(FAUX, encoding="utf-8")
    rec = tmp_path / "rec.txt"
    wt = tmp_path / "wt"
    wt.mkdir(exist_ok=True)
    r = R.ACPRouter(log_dir=tmp_path / "logs", route=lambda a: str(wt),
                    cmd_factory=lambda a: [sys.executable, str(f), str(rec), json.dumps(modeles)])
    return r, rec


def _set_model(rec):
    lignes = [json.loads(l) for l in rec.read_text().splitlines()] if rec.exists() else []
    return [l["params"]["modelId"] for l in lignes if l["method"] == "session/set_model"]


def _journal(tmp_path, sid):
    return [json.loads(l) for l in (tmp_path / "logs" / f"{sid}.jsonl").read_text(encoding="utf-8").splitlines()]


def test_modele_prefere_annonce_avec_niveau_applique(tmp_path):
    r, rec = _routeur(tmp_path, ["gpt-5.5[low]", "gpt-6-luna[low]", "gpt-6-luna[medium]"])
    sid = r.ouvrir("codex", modele="gpt-6-luna")
    try:
        assert _set_model(rec) == ["gpt-6-luna[medium]"]
        assert any(l["kind"] == "modele_applique" for l in _journal(tmp_path, sid))
    finally:
        r.fermer(sid)


def test_modele_non_annonce_jamais_devine(tmp_path):
    r, rec = _routeur(tmp_path, ["gpt-5.5[low]", "gpt-5.4[medium]"])
    sid = r.ouvrir("codex", modele="gpt-6-luna")
    try:
        assert _set_model(rec) == []
        evt = [l for l in _journal(tmp_path, sid) if l["kind"] == "modele_inchange"]
        assert len(evt) == 1 and "gpt-6-luna" in json.dumps(evt[0]["payload"])
    finally:
        r.fermer(sid)


def test_codex_prefere_le_modele_du_config_toml(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('model = "gpt-6-luna"\n[mcp_servers.x]\ncommand = "y"\n', encoding="utf-8")
    monkeypatch.setenv("LAFORGE_CODEX_CONFIG", str(cfg))
    assert R._modele_prefere("codex") == "gpt-6-luna"
    assert R._modele_prefere("claude") is None


def test_config_absent_aucun_modele_impose(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_CODEX_CONFIG", str(tmp_path / "absent.toml"))
    assert R._modele_prefere("codex") is None
