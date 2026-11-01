"""NR -- T2b : file persistante des permissions tranchees par l'owner. Aucun reseau."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_router as R  # noqa: E402

REQ = {"sessionId": "s1", "options": [{"optionId": "allow", "kind": "allow_once"},
                                      {"optionId": "deny", "kind": "reject_once"}]}


def _lancer(pol, params=REQ):
    box = {}
    t = threading.Thread(target=lambda: box.update(r=pol(params)))
    t.start()
    return t, box


def _attendre_fichier(d):
    for _ in range(100):
        fs = list(Path(d).glob("*.json"))
        if fs:
            return fs[0]
        time.sleep(0.05)
    raise AssertionError("aucune demande deposee")


def _decider_fichier(p, decision):
    j = json.loads(p.read_text(encoding="utf-8"))
    j["etat"] = "DECIDE"
    j["decision"] = decision
    sel = decision.get("optionId")
    j["jws"] = R.signer_hub({"pid": p.stem, "option": sel, "refuser": sel is None, "sub": "test"})
    R._ecrire_atomique(p, j)


def test_depot_puis_decision_valide(tmp_path):
    pol = R.politique_owner(tmp_path, delai_s=10)
    t, box = _lancer(pol)
    p = _attendre_fichier(tmp_path)
    j = json.loads(p.read_text(encoding="utf-8"))
    assert {"id", "session", "agent", "ts", "request", "options", "etat", "decision"} <= set(j)
    assert j["etat"] == "EN_ATTENTE" and j["request"] == REQ and p.stem == j["id"]
    _decider_fichier(p, {"outcome": "selected", "optionId": "allow"})
    t.join(5)
    assert box["r"] == {"outcome": "selected", "optionId": "allow"}


def test_option_hors_liste_cancelled(tmp_path):
    pol = R.politique_owner(tmp_path, delai_s=10)
    t, box = _lancer(pol)
    p = _attendre_fichier(tmp_path)
    _decider_fichier(p, {"outcome": "selected", "optionId": "pirate"})
    t.join(5)
    assert box["r"] == {"outcome": "cancelled"}


def test_delai_expire(tmp_path):
    pol = R.politique_owner(tmp_path, delai_s=1)
    t, box = _lancer(pol)
    t.join(8)
    assert box["r"] == {"outcome": "cancelled"}
    j = json.loads(next(Path(tmp_path).glob("*.json")).read_text(encoding="utf-8"))
    assert j["etat"] == "EXPIRE"


def test_cli_permissions_et_decider(tmp_path, capsys):
    pol = R.politique_owner(tmp_path, delai_s=10)
    t, box = _lancer(pol)
    p = _attendre_fichier(tmp_path)
    assert R.main(["--permissions", "--dossier", str(tmp_path)]) == 0
    liste = json.loads(capsys.readouterr().out)
    assert [x["id"] for x in liste] == [p.stem]
    assert R.main(["--decider", p.stem, "--option", "allow", "--dossier", str(tmp_path)]) == 0
    t.join(5)
    assert box["r"] == {"outcome": "selected", "optionId": "allow"}
    assert R.main(["--permissions", "--dossier", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == []


def test_cli_refuser(tmp_path):
    pol = R.politique_owner(tmp_path, delai_s=10)
    t, box = _lancer(pol)
    p = _attendre_fichier(tmp_path)
    assert R.main(["--decider", p.stem, "--refuser", "--dossier", str(tmp_path)]) == 0
    t.join(5)
    assert box["r"] == {"outcome": "cancelled"}


def test_cli_option_inconnue_refusee(tmp_path):
    pol = R.politique_owner(tmp_path, delai_s=2)
    t, box = _lancer(pol)
    p = _attendre_fichier(tmp_path)
    assert R.main(["--decider", p.stem, "--option", "pirate", "--dossier", str(tmp_path)]) != 0
    t.join(8)
    assert box["r"] == {"outcome": "cancelled"}


def test_routeur_timeout_client(tmp_path):
    r = R.ACPRouter(log_dir=tmp_path, route=lambda a: str(tmp_path), cmd_factory=lambda a: ["x"],
                    permission_policy=R.politique_owner(tmp_path, delai_s=300))
    assert r.permission_timeout >= 305
