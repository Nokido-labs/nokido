"""NR — avant la CI complete, les rouges du dernier run GitHub doivent etre couverts (26/09).

Decision owner : GitHub ne juge un sha qu'une fois publie ; un test dont le verdict depend du
poste (test_tpm_acl_gouvernee_nr, 26/09) passe en local et rougit la-bas. L'apercu du push
relit donc le dernier run GitHub TERMINE de la branche. Contrat :
  - run vert -> VERT ; chaque FAILED touche par un commit du sha certifie -> COUVERT ;
  - un FAILED sans commit, ou un job rouge sans test nomme -> A_VERIFIER (jamais NON :
    le correctif peut vivre dans le code teste) ;
  - jeton absent, API muette, aucun run termine -> ILLISIBLE, jamais vert ;
  - le dernier run TERMINE fait foi, un run en cours plus recent est signale ;
  - l'apercu du push l'imprime et ne bloque rien, meme si la sonde casse.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import forge_ci_check as cc  # noqa: E402  (import strict)
import forge_push_sovereign as fps  # noqa: E402

LIGNE_TPM = ("FAILED tests/nr/test_tpm_acl_gouvernee_nr.py::test_le_plan_CONSERVE_toutes_les_ACE_existantes"
             " - AssertionError: assert 'REFUSE' in {...}")


def _run(conclusion, status="completed", created="2026-09-26T03:48:42Z", rid="36215947412"):
    return {"status": status, "conclusion": conclusion, "head": "45311820", "created": created,
            "url": "https://github.com/o/r/actions/runs/%s" % rid, "name": "CI"}


@pytest.fixture(autouse=True)
def une_seule_instance(monkeypatch):
    """L'apercu du push importe `forge_ci_check` a l'appel : un autre test qui recharge le
    module dans sys.modules lui ferait voir une AUTRE instance que celle qu'on double
    (mesure : appel reseau reel, WinError 10013). On epingle la notre."""
    monkeypatch.setitem(sys.modules, "forge_ci_check", cc)


@pytest.fixture
def api(monkeypatch):
    etat = {"check": {"ok": True, "runs": [], "vus_toutes_branches": 0}, "journal": {"ok": True, "jobs": []}}
    monkeypatch.setattr(cc, "check", lambda repo, branch, limit=5: etat["check"])
    monkeypatch.setattr(cc, "journal_echecs", lambda repo, run_id, garde=40: etat["journal"])
    return etat


def _couvre(commits_par_fichier):
    return lambda base, sha, f: commits_par_fichier.get(f, [])


def test_extraction_des_failed_sans_doublon():
    lignes = [LIGNE_TPM, LIGNE_TPM, "E   AssertionError", "FAILED tests/test_a.py::test_b[param-1] - x"]
    assert cc.tests_rouges(lignes) == [
        ("tests/nr/test_tpm_acl_gouvernee_nr.py", "test_le_plan_CONSERVE_toutes_les_ACE_existantes"),
        ("tests/test_a.py", "test_b[param-1]")]


def test_run_vert(api):
    api["check"]["runs"] = [_run("success")]
    assert cc.couverture_des_rouges("o/r", "alpha", "abc", _couvre({}))["etat"] == cc.ROUGES_VERT


def test_rouge_touche_par_un_commit_est_couvert(api):
    api["check"]["runs"] = [_run("failure")]
    api["journal"]["jobs"] = [{"job": "pytest-pur", "conclusion": "failure", "lignes": [LIGNE_TPM]}]
    r = cc.couverture_des_rouges("o/r", "alpha", "abc", _couvre(
        {"tests/nr/test_tpm_acl_gouvernee_nr.py": ["584532375 fix(tpm): liste blanche"]}))
    assert r["etat"] == cc.ROUGES_COUVERT and r["run"] == "36215947412"
    assert r["rouges"][0]["commits"] == ["584532375 fix(tpm): liste blanche"]


def test_rouge_sans_commit_est_a_verifier_pas_non(api):
    api["check"]["runs"] = [_run("failure")]
    api["journal"]["jobs"] = [{"job": "pytest-pur", "conclusion": "failure", "lignes": [LIGNE_TPM]}]
    assert cc.couverture_des_rouges("o/r", "alpha", "abc", _couvre({}))["etat"] == cc.ROUGES_A_VERIFIER


def test_job_rouge_sans_test_nomme_est_a_verifier(api):
    api["check"]["runs"] = [_run("failure")]
    api["journal"]["jobs"] = [{"job": "gates", "conclusion": "failure", "lignes": ["1 gate(s) bloquant(s)"]}]
    r = cc.couverture_des_rouges("o/r", "alpha", "abc", _couvre({}))
    assert r["etat"] == cc.ROUGES_A_VERIFIER and r["jobs_sans_test"][0]["job"] == "gates"


@pytest.mark.parametrize("check, journal", [
    ({"ok": False, "error": "GITHUB_TOKEN introuvable (coffre DPAPI)"}, None),
    ({"ok": True, "runs": [], "vus_toutes_branches": 7}, None),
    ({"ok": True, "runs": [_run("failure")]}, {"ok": False, "error": "HTTPError: 403"}),
])
def test_ce_qui_ne_se_lit_pas_est_illisible_jamais_vert(api, check, journal):
    api["check"] = check
    if journal:
        api["journal"] = journal
    r = cc.couverture_des_rouges("o/r", "alpha", "abc", _couvre({}))
    assert r["etat"] == cc.ROUGES_ILLISIBLE and r["raison"]


def test_le_dernier_run_termine_fait_foi_et_l_en_cours_est_signale(api):
    api["check"]["runs"] = [_run(None, status="in_progress", created="2026-09-26T05:00:00Z", rid="2"),
                            _run("success", rid="1")]
    r = cc.couverture_des_rouges("o/r", "alpha", "abc", _couvre({}))
    assert r["etat"] == cc.ROUGES_VERT and r["run"] == "1" and r["en_cours_plus_recents"] == 1


# ── chemin reel : l'apercu du push ─────────────────────────────────────────────────

class _Git:
    def __init__(self, url):
        self.url = url

    def __call__(self, *a, **kw):
        class R:
            stdout = self.url if a[:2] == ("remote", "get-url") else "584532375 fix(tpm)\n"
            returncode = 0
        return R()


def test_l_apercu_du_push_imprime_les_rouges(api, monkeypatch, capsys):
    api["check"]["runs"] = [_run("failure")]
    api["journal"]["jobs"] = [{"job": "pytest-pur", "conclusion": "failure", "lignes": [LIGNE_TPM]}]
    monkeypatch.setattr(fps, "git", _Git("https://github.com/Nokido-labs/nokido.git"))
    fps._ci_github_rouges("alpha", "abc")
    sortie = capsys.readouterr().out
    assert "-> COUVERT" in sortie and "ROUGE tests/nr/test_tpm_acl_gouvernee_nr.py::" in sortie
    assert "correctif candidat : 584532375" in sortie


def test_l_apercu_ne_casse_jamais_le_push(monkeypatch, capsys):
    def boum(*a, **kw):
        raise RuntimeError("api muette")

    monkeypatch.setattr(cc, "couverture_des_rouges", boum)
    monkeypatch.setattr(fps, "git", _Git("https://github.com/Nokido-labs/nokido.git"))
    fps._ci_github_rouges("alpha", "abc")
    assert "ILLISIBLE : RuntimeError: api muette" in capsys.readouterr().out


def test_le_dry_run_appelle_l_apercu():
    src = (RACINE / "tools" / "forge_push_sovereign.py").read_text(encoding="utf-8")
    assert "if not args.push:\n        _ci_github_rouges(br, spec.split(\":\")[0])" in src.replace("\r\n", "\n")
