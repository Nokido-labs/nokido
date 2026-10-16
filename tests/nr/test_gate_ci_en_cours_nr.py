"""NR -- aucune charge de l'agent pendant une CI de reference (regle owner du 29/09, recidive du 15/10 : trois
sessions pytest pendant la suite pure de bee38e2f7, un worker xdist ecrase). La regle est desormais EXECUTEE."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_ci_reference as ref  # noqa: E402
import hook_capability_gate as g  # noqa: E402

RUN = "mcp__laforge-sovereign-hub__run"
EN_COURS = {"pid": 1234, "sha": "bee38e2f73a2", "debut": 0}


def test_la_charge_est_muree_pendant_une_ci_vivante():
    etat = lambda: EN_COURS  # noqa: E731
    for entree in ({"action": "run_job", "script": "C:/tmp/x.py"},
                   {"action": "shell", "code": "python -m pytest tests/nr/test_a.py"},
                   {"action": "python", "code": "import subprocess; subprocess.run(['python', 'tools/ci_local.py'])"},
                   {"action": "trusted_script", "path": "tools/forge_x.py"}):
        bloque, msg = g.verdict_ci_en_cours(RUN, entree, etat=etat)
        assert bloque and "CI en cours" in msg and "bee38e2f7" in msg, entree


def test_le_leger_passe_meme_pendant_une_ci():
    etat = lambda: EN_COURS  # noqa: E731
    for entree in ({"action": "shell", "code": "findstr /N foo tools\\x.py"},
                   {"action": "job_status", "job_id": "job_x"},
                   {"action": "python", "code": "print(1)"}):
        assert g.verdict_ci_en_cours(RUN, entree, etat=etat) == (False, ""), entree
    assert g.verdict_ci_en_cours("mcp__laforge-sovereign-hub__read", {"action": "run_job"}, etat=etat) == (False, "")


def test_sans_ci_rien_n_est_mure():
    assert g.verdict_ci_en_cours(RUN, {"action": "run_job", "script": "x.py"}, etat=lambda: None) == (False, "")


def test_un_temoin_perime_ou_illisible_n_arrete_rien(tmp_path):
    import psutil
    vivant = tmp_path / "vivant.json"
    vivant.write_text(json.dumps({"pid": os.getpid(), "cree": psutil.Process().create_time(), "sha": "s", "debut": 0}))
    assert g.ci_en_cours(str(vivant))["pid"] == os.getpid()
    reutilise = tmp_path / "reutilise.json"
    reutilise.write_text(json.dumps({"pid": os.getpid(), "cree": 1.0, "sha": "s", "debut": 0}))
    assert g.ci_en_cours(str(reutilise)) is None                       # pid repris par un autre processus
    mort = tmp_path / "mort.json"
    mort.write_text(json.dumps({"pid": 2 ** 22 + 12345, "cree": 1.0, "sha": "s", "debut": 0}))
    assert g.ci_en_cours(str(mort)) is None
    casse = tmp_path / "casse.json"
    casse.write_text("{pas du json")
    assert g.ci_en_cours(str(casse)) is None
    assert g.ci_en_cours(str(tmp_path / "absent.json")) is None


def test_la_ci_pose_et_retire_son_temoin_mais_pas_un_test_simule(tmp_path, monkeypatch):
    t = tmp_path / "temoin.json"
    assert ref.poser_temoin("abc", chemin=t) and json.loads(t.read_text())["sha"] == "abc"
    ref.retirer_temoin(chemin=t)
    assert not t.exists()
    monkeypatch.setattr(ref, "TEMOIN_CI", tmp_path / "jamais.json")
    vu = []

    def faux(cmd, **k):
        vu.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    ref.main(["--sha", "abc"], executer=faux)
    assert vu and not (tmp_path / "jamais.json").exists() and not ref.TEMOIN_CI.exists()
