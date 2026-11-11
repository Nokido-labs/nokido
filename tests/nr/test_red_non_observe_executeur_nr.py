"""NR : TDD exige + tests DEJA VERTS sur le commit RED -> PARTIEL (RED_NON_OBSERVE)."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import forge_task_executor as fte  # noqa: E402


def _git(d, *a):
    subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t"] + list(a),
                   check=True, capture_output=True)


def _depot(tmp_path, msg):
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("1")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    avant = fte._etat_git(str(tmp_path))
    (tmp_path / "b.py").write_text("x=1")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "feat: x", "-m", msg)
    return avant


def test_tdd_et_deja_verts_donne_partiel(tmp_path):
    avant = _depot(tmp_path, "ALERTE : tests DEJA VERTS sur le commit RED seul")
    ok, effet, _ = fte._juger_livraison(True, '{"intent":"OK_DONE","pointer_ref":"x"}', str(tmp_path), avant,
                                        desc="TACHE TDD : test d'abord")
    assert not ok and "RED_NON_OBSERVE" in effet
    assert fte._statut_livraison(ok, effet) == "PARTIEL"
    assert fte.verdict_automatique(ok, effet, "", None) is None


def test_tdd_et_rouges_inchange(tmp_path):
    avant = _depot(tmp_path, "preuve RED : tests ROUGES sur le commit RED seul")
    assert fte._red_non_observe("TDD", str(tmp_path), avant) is None


def test_sans_tdd_inchange(tmp_path):
    avant = _depot(tmp_path, "ALERTE : tests DEJA VERTS sur le commit RED seul")
    assert fte._red_non_observe("tache simple", str(tmp_path), avant) is None


def test_indetermine_inchange(tmp_path):
    avant = _depot(tmp_path, "preuve RED INDETERMINEE (x)")
    assert fte._red_non_observe("TDD", str(tmp_path), avant) is None


def test_commit_refuse_par_l_executeur_n_est_jamais_un_succes():
    # 30/10 : job_db32d872 (MISTRAL) a REMPLACE 4 traductions par « ERR: extract requiert text + idea_id » ; le garde
    # a refuse le commit (reecriture destructrice) mais la tache est sortie SUCCESS -- la note etait dans le detail.
    # 7/11 : le detail suit le format REEL des delegations (`detail\n[executeur] <note>`, _delegate_to_vibe/codex/agy/
    # claude/opencode depuis le 16/10) ; depuis 7aa64ee12 une note SANS cette frontiere est de la prose d'agent et ne
    # juge plus (un marqueur cite ne vaut pas verdict). Le contrat reste : refus executeur -> jamais SUCCESS.
    detail = ("[effet observe] commits produits : 0 (a..a) ; fichiers non commites : 4 | ERR: extract requiert text "
              "+ idea_id\n[executeur] commit executeur REFUSE : "
              "reecriture destructrice de docs/i18n/README.fr.md (plus de la moitie des lignes retirees)")
    assert fte._statut_livraison(True, detail) == "NEEDS_HUMAN"
    assert fte._statut_livraison(True, detail.replace("REFUSE : reecriture destructrice", "REFUSE par le scorecard")) \
        == "NEEDS_HUMAN"
    # prose vide (« sortie vide ») : la note reste celle de l'executeur
    assert fte._statut_livraison(True, "[effet observe] commits produits : 0 (a..a) ; fichiers non commites : 4 | "
                                       "\n[executeur] commit executeur REFUSE rc=1 : hook") == "NEEDS_HUMAN"
    assert fte._statut_livraison(True, "[effet observe] commits produits : 1 (a..b)") == "SUCCESS"


def test_commit_refuse_cloture_reelle_emet_needs_human(monkeypatch):
    emis = []
    monkeypatch.setattr(fte, "_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(fte, "_mark_done", lambda *a, **k: None)
    monkeypatch.setattr(fte, "_noter_cause_echec", lambda *a, **k: None)
    monkeypatch.setattr(fte, "_hub_call", lambda tool, args, token, timeout=30: emis.append(args) or {})
    effet = "[effet observe] commits produits : 0 (a..a) ; fichiers non commites : 4"
    prose = "ERR: extract requiert text + idea_id"
    fte._clore_delegation("t_refus", "x", True, "%s | %s\n[executeur] %s" % (
        effet, prose, "commit executeur REFUSE : reecriture destructrice de a.md"))
    assert emis and '"status_code": "NEEDS_HUMAN"' in emis[0]["result"]


def test_consigne_claude_rappelle_l_ordre():
    assert "VOIR ROUGE" in fte._CONSIGNE_GIT_CLAUDE
