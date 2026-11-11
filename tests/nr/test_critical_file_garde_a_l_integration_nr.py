"""NR RED -- choix owner du 8/11 (decision_garde_critique_a_l_integration_2026-11-08).

1. Le garde CRITICAL_FILE bloque a l'ENTREE DANS ALPHA, plus au commit du worktree de tache :
   tools/forge_merge_gate.py
     reconcilier(sha, fichiers_nommes, apply=False, agent="?", sujet="", tests=None, root=None, allow_critical=False)
     reconcilier_sauvegarde(..., root=None, allow_critical=False)
     merger(agent, tests=None, apply=False, allow_critical=False)
   - dry-run : r["critiques"] liste les fichiers critiques a integrer ;
   - apply sans allow_critical et fichier critique : r["decision"] commence par "CRITICAL_FILE REFUSE",
     r["applique"] False, alpha INTACT (aucun checkout, aucun commit) ;
   - apply avec allow_critical=True : integre, r["derogation_critique"] True, une ligne JSON tracee dans
     <root>/sandbox/git_gate_derogations.jsonl (meme journal que les derogations du gate) ;
   - une seule fonction de garde `_garde_critique_integration` appelee par les trois points d'entree ;
   - CLI : drapeau --allow-critical.
2. Un livrable dont le commit est REFUSE (toute cause) ne se reaffecte PLUS : il se preserve et remonte a
   l'emetteur (`_motif_reaffectation_apres` -> None quand l'effet porte [COMMIT REFUSE] et des fichiers non commites).
3. Le stderr du refus est NOMME dans l'EFFET juge. Mesure du 8/11 : la note du committer le porte deja
   (`commit executeur REFUSE rc=... : <stderr>`), mais `_juger_livraison` (l.3332) la remplace par un libelle
   fixe -> cause ILLISIBLE lors de job_010be69e. Contrat : `_motif_refus_commit(detail) -> str | None` extrait le
   motif (<= 300 car.) de la note `[executeur]`, et `_juger_livraison` l'ajoute apres `[COMMIT REFUSE] ... : `.
Depots jetables ; aucun acces au RAG.
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import forge_merge_gate as M  # noqa: E402
import forge_task_executor as T  # noqa: E402

CRIT = "app/forge_rbac.py"


def _git(wt, *args):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(wt), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


def _depot_alpha(tmp_path):
    """Depot jetable sur alpha + un commit de tache (branche tache) touchant un fichier critique."""
    d = tmp_path / "depot"
    d.mkdir()
    _git(d, "init", "-q", "-b", "alpha")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    _git(d, "config", "core.hooksPath", str(tmp_path / "nohooks"))
    (d / "base.txt").write_text("base\n", encoding="utf-8")
    _git(d, "add", "base.txt")
    assert _git(d, "commit", "-q", "-m", "base").returncode == 0
    _git(d, "checkout", "-q", "-b", "tache")
    (d / "app").mkdir()
    (d / CRIT).write_text("X = 1\n", encoding="utf-8")
    _git(d, "add", CRIT)
    assert _git(d, "commit", "-q", "-m", "feat: critique").returncode == 0
    sha = _git(d, "rev-parse", "HEAD").stdout.strip()
    _git(d, "checkout", "-q", "alpha")
    return d, sha


def test_dry_run_nomme_les_critiques(tmp_path):
    d, sha = _depot_alpha(tmp_path)
    r = M.reconcilier(sha, [CRIT], apply=False, root=d)
    assert r.get("critiques") == [CRIT], r


def test_apply_sans_derogation_refuse_et_alpha_intact(tmp_path):
    d, sha = _depot_alpha(tmp_path)
    head0 = _git(d, "rev-parse", "alpha").stdout.strip()
    r = M.reconcilier(sha, [CRIT], apply=True, root=d)
    assert str(r.get("decision", "")).startswith("CRITICAL_FILE REFUSE"), r
    assert r.get("applique") is False
    assert _git(d, "rev-parse", "alpha").stdout.strip() == head0
    assert not (d / CRIT).exists(), "le fichier critique a ete extrait dans alpha malgre le refus"


def test_apply_avec_derogation_integre_et_trace(tmp_path):
    d, sha = _depot_alpha(tmp_path)
    r = M.reconcilier(sha, [CRIT], apply=True, root=d, allow_critical=True)
    assert r.get("decision") == "INTEGRE", r
    assert r.get("derogation_critique") is True
    journal = d / "sandbox" / "git_gate_derogations.jsonl"
    assert journal.is_file(), "derogation d'integration non tracee"
    lignes = [json.loads(l) for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(CRIT in json.dumps(l) for l in lignes), lignes


def test_garde_unique_appelee_par_les_trois_entrees():
    assert hasattr(M, "_garde_critique_integration")
    for fn in (M.reconcilier, M.reconcilier_sauvegarde, M.merger):
        assert "allow_critical" in inspect.signature(fn).parameters, fn.__name__
        assert "_garde_critique_integration" in inspect.getsource(fn), fn.__name__
    assert "--allow-critical" in inspect.getsource(M.main)
    assert '"--tests"' in inspect.getsource(M.main), "relecture 8/11 : --tests supprime par le rendu GPTOSS"


def test_garde_indisponible_fail_closed(tmp_path, monkeypatch):
    import builtins
    vrai = builtins.__import__

    def sans_garde(nom, *a, **k):
        fromlist = (a[2] if len(a) > 2 else k.get("fromlist")) or ()
        if "forge_critical_gate" in nom or "forge_critical_gate" in fromlist:
            raise ImportError("garde indisponible (NR)")
        return vrai(nom, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sans_garde)
    assert M._garde_critique_integration(["m.py"], False, tmp_path) == ["m.py"]


def test_dry_run_avec_derogation_ne_trace_rien(tmp_path):
    d, sha = _depot_alpha(tmp_path)
    M.reconcilier(sha, [CRIT], apply=False, root=d, allow_critical=True)
    assert not (d / "sandbox" / "git_gate_derogations.jsonl").exists(), "derogation tracee sans usage"


EFFET_010BE69E = ("commits produits : 0 (e53a8bff1..e53a8bff1) ; fichiers non commites : 1 ; [COMMIT REFUSE] "
                  "commit de l'executeur refuse par le depot, travail laisse non livre")


def test_commit_refuse_ne_se_reaffecte_pas():
    assert T._motif_reaffectation_apres(False, EFFET_010BE69E, '{"intent":"OK_DONE"}') is None


def test_echec_sans_livraison_se_reaffecte_toujours():
    """Garde : sans fichier ni commit, la reaffectation existante reste."""
    effet = "commits produits : 0 (a..a) ; fichiers non commites : 0"
    assert T._motif_reaffectation_apres(False, effet, "rien fait") is not None


def test_motif_du_refus_survit_au_jugement():
    detail = ('{"intent":"OK_DONE"}\n' + T._MARQUE_NOTE_EXECUTEUR
              + "commit executeur REFUSE rc=1 : BOOM-gate-7f3a refus mesure")
    m = T._motif_refus_commit(detail)
    assert m and "BOOM-gate-7f3a" in m and len(m) <= 300, m
    assert T._motif_refus_commit('{"intent":"OK_DONE"}') is None
    assert "_motif_refus_commit" in inspect.getsource(T._juger_livraison)


def test_stderr_du_refus_nomme_dans_la_note(tmp_path):
    """Garde (vert le 8/11) : la note du committer porte le stderr du hook."""
    wt = tmp_path / "wt"
    wt.mkdir()
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\necho 'BOOM-gate-7f3a refus mesure' >&2\nexit 1\n", encoding="utf-8")
    _git(wt, "init", "-q")
    _git(wt, "config", "user.email", "t@t")
    _git(wt, "config", "user.name", "t")
    _git(wt, "config", "core.hooksPath", str(hooks))
    (wt / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    note = T._committer_deux_temps(str(wt), ["git", "-c", "safe.directory=*", "-C", str(wt)],
                                   [], ["m.py"], "feat: f", "corps", "X")
    assert T._RE_COMMIT_REFUSE.search(note), note
    assert "BOOM-gate-7f3a" in note, "le stderr du refus n'est pas nomme : cause ILLISIBLE"
