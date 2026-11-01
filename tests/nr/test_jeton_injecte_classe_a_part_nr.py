# -*- coding: utf-8 -*-
"""NR (31/10, choix owner « classe INJECTE + accesseur ») : un jeton INJECTE par le lanceur n'est pas un secret oublie.

CI de reference 31/10 rouge : NOKIDO_JOB_SUBJECT_TOKEN lu dans l'environnement a 4 sites (forge_hub_client,
forge_rss_watcher, forge_secours_lanceur, forge_self_patcher) -> « secrets hors coffre » + golden-rules
« laforge-cloud-secret-from-env ». Or c'est le jeton de SUJET qu'app/forge_job_runner.py:430 injecte dans chaque job
(RFC 8693, decision owner option B du 30/10) : ephemere, par job, il ne peut PAS vivre au coffre. Les instruments
confondaient INJECTE et HORS COFFRE. Regle : UN accesseur (forge_agent_credential.jeton_sujet_du_job) est le seul
lecteur admis ; ailleurs, la meme lecture reste un hors coffre -- le garde ne s'ouvre que la ou il doit.
"""
# pylint: disable=missing-function-docstring
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_agent_credential as cred  # noqa: E402
import forge_golden_rules_ast as golden  # noqa: E402
import forge_secret_source_audit as audit  # noqa: E402

LECTURE = 'import os\nv = os.environ.get("NOKIDO_JOB_SUBJECT_TOKEN", "")\n'
ACCESSEUR = "app/forge_agent_credential.py"


def test_l_accesseur_lit_le_jeton_injecte(monkeypatch):
    monkeypatch.setenv("NOKIDO_JOB_SUBJECT_TOKEN", "jeton-de-test")
    assert cred.jeton_sujet_du_job() == "jeton-de-test"
    monkeypatch.delenv("NOKIDO_JOB_SUBJECT_TOKEN")
    assert cred.jeton_sujet_du_job() == ""


def test_l_audit_admet_l_accesseur_et_seulement_lui(tmp_path):
    for rel in (ACCESSEUR, "app/forge_autre.py"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(LECTURE, encoding="utf-8")
    trouves, _ = audit.scanner(racine=tmp_path)
    hors = {(r, c) for r, _, c, e in trouves if e == "HORS COFFRE"}
    assert ("app/forge_autre.py", "NOKIDO_JOB_SUBJECT_TOKEN") in hors
    assert (ACCESSEUR, "NOKIDO_JOB_SUBJECT_TOKEN") not in hors
    assert audit.JETONS_INJECTES["NOKIDO_JOB_SUBJECT_TOKEN"] == ACCESSEUR


def test_golden_admet_l_accesseur_et_seulement_lui():
    def regles(rel):
        return [str(f) for f in golden.scan_source(rel, LECTURE, None) if "laforge-cloud-secret-from-env" in str(f)]
    assert regles(ACCESSEUR) == []
    assert regles("app/forge_autre.py")


def test_les_quatre_sites_passent_par_l_accesseur():
    for rel in ("app/forge_hub_client.py", "app/forge_rss_watcher.py", "tools/forge_secours_lanceur.py",
                "tools/forge_self_patcher.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert 'environ.get("NOKIDO_JOB_SUBJECT_TOKEN"' not in src and "getenv(\"NOKIDO_JOB_SUBJECT_TOKEN\"" not in src, rel
