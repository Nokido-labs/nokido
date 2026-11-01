"""NR -- une delegation LIVREE ne doit JAMAIS etre rendue FAILURE : le verdict se LIT sur l'ARTEFACT.

Mesures du 2026-10-22 (bb:architecture_rules/bug_juge_failure_avec_livraison_20261022) :
- job_0cd422a1 (OPENCODE_GPTOSS) : l'effet observe disait « commits produits : 1 (500cbdf91..93826cfb7) ; fichiers non
  commites : 0 » -- un commit LIVRE sur la branche de l'executeur -- et le verdict rendu etait FAILURE : le garde de
  CONTENU ([TESTS TOUCHES]) a ete lu comme un echec de LIVRAISON.
- job_af6dbf75 / job_818ec8d8 (AGY) : le travail etait JUSTE mais NON COMMITTE (« commits produits : 0 ; fichiers non
  commites : 1 ») -> FAILURE, et le travail a disparu au recalage suivant du worktree, sans aucune sauvegarde.
- job_d7d57967 : « commits produits : 0 (872be9980..872be9980) ; fichiers non commites : 2 » rendu FAILURE (« [NON LIVRE]
  aucun commit propre, 2 fichier(s) non committe(s) ») alors que 2 fichiers venaient d'etre ecrits.

Ce qui est garde, ici :
(a) un commit livre sur la branche de l'executeur => jamais FAILURE (le CONTENU peut etre refuse : PARTIEL) ;
(b) des fichiers modifies non committes => LIVRE_NON_COMMITTE, les fichiers sont NOMMES, et le travail est PRESERVE
    (commit ou COPIE dans sandbox/sauvegardes_executeurs) ;
(c) ni commit ni diff => FAILURE, comme avant ;
(d) une COPIE avant toute synchronisation de worktree : la synchro ne peut plus effacer un travail non sauvegarde.

Le juge EXISTANT (`_juger_livraison`) et le mecanisme EXISTANT de preservation (`_preserver_livraison`,
`_sauvegarder_travail`) portent le contrat : aucun second juge, aucun second mecanisme.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

EFFET_COMMIT = "[effet observe] commits produits : 1 (500cbdf91..93826cfb7) ; fichiers non commites : 0"
EFFET_SALE = "[effet observe] commits produits : 0 (500cbdf91..500cbdf91) ; fichiers non commites : 2"
EFFET_RIEN = "[effet observe] commits produits : 0 (500cbdf91..500cbdf91) ; fichiers non commites : 0"


class _rien:
    """Contexte vide : le battement de delegation n'a rien a ecrire dans un test."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Verrou:
    """Faux verrou de workdir : un test n'ouvre pas la base des verrous."""

    def acquerir(self, *a, **k):
        return True

    def liberer(self, *a, **k):
        return None


class _Conn:
    """Fausse connexion : `_clore_delegation` n'a besoin que de close()."""

    def close(self):
        pass


def _module(monkeypatch, effet=None, contenu=None):
    """L'executeur charge par SON CHEMIN (pas d'import de package) : le NR mesure le fichier du depot."""
    spec = importlib.util.spec_from_file_location("juge_failure_avec_livraison_nr",
                                                  RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if effet is not None:
        monkeypatch.setattr(m, "_effet_observe", lambda workdir, avant: effet)
    monkeypatch.setattr(m, "_contenu_livre", lambda workdir, avant, autorises=None: contenu)
    return m


def _statut_clore(m, monkeypatch, ok, detail, intent=None):
    """Le status_code du compte rendu M2M -- ce que l'emetteur voit de la delegation."""
    capture = {}

    def _hub(tool, args, token=None, timeout=None):
        capture.update(args)
        return {}

    monkeypatch.setattr(m, "_db", lambda: _Conn())
    monkeypatch.setattr(m, "_mark_done", lambda *a, **k: None)
    monkeypatch.setattr(m, "_hub_call", _hub)
    m._clore_delegation("job_nr", "tok", ok, detail, intent)
    return json.loads(capture["result"])


def test_un_commit_livre_ne_renderait_pas_failure(monkeypatch, tmp_path):
    """(a) job_0cd422a1 : le travail est sur la branche, le CONTENU est refuse -> PARTIEL, jamais FAILURE."""
    m = _module(monkeypatch, EFFET_COMMIT, contenu="[TESTS TOUCHES] tests/nr/test_x.py")
    ok, effet, rendu = m._juger_livraison(True, "travail livre", str(tmp_path), ("500cbdf91", 0))
    assert ok is False, effet          # le CONTENU refuse reste un echec de CONTENU
    r = _statut_clore(m, monkeypatch, ok, effet, rendu)
    assert r["status_code"] != "FAILURE", r


def test_un_travail_non_commite_est_livre_non_commite_et_nomme(monkeypatch, tmp_path):
    """(b) job_af6dbf75 / job_d7d57967 : des fichiers ecrits, non committes -> LIVRE_NON_COMMITTE, et NOMMES."""
    m = _module(monkeypatch, EFFET_SALE)
    monkeypatch.setattr(m, "_chemins_status", lambda wt: frozenset({"app/x.py", "app/y.py"}))
    ok, effet, rendu = m._juger_livraison(True, "travail fait", str(tmp_path), ("500cbdf91", 0))
    r = _statut_clore(m, monkeypatch, ok, effet, rendu)
    assert r["status_code"] == "LIVRE_NON_COMMITTE", r
    assert "app/x.py" in effet and "app/y.py" in effet, effet


def test_rien_du_tout_reste_un_failure(monkeypatch, tmp_path):
    """(c) ni commit ni diff ni artefact pointe : FAILURE, comme avant le correctif."""
    m = _module(monkeypatch, EFFET_RIEN)
    monkeypatch.setattr(m, "_chemins_status", lambda wt: frozenset())
    ok, effet, rendu = m._juger_livraison(True, "rien", str(tmp_path), ("500cbdf91", 0))
    assert ok is False, effet
    r = _statut_clore(m, monkeypatch, ok, effet, rendu)
    assert r["status_code"] == "FAILURE", r


def test_le_travail_d_une_session_agy_echouee_est_preserve(monkeypatch, tmp_path):
    """(b) job_af6dbf75 / job_818ec8d8 : session AGY en echec, 2 fichiers ecrits, jamais committes, disparus au
    recalage. L'executeur doit les.committer ou les COPIER -- jamais les perdre derriere un FAILURE."""
    m = _module(monkeypatch, EFFET_SALE)
    wt = tmp_path / "wt"
    (wt / "app").mkdir(parents=True)
    (wt / "app" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (wt / "app" / "y.py").write_text("y = 2\n", encoding="utf-8")
    monkeypatch.setattr(m, "_SAUVEGARDES", tmp_path / "sauvegardes")
    monkeypatch.setattr(m, "_workdir_agy", lambda: str(wt))
    monkeypatch.setattr(m, "_etat_git", lambda wd: ("500cbdf91", 0))
    monkeypatch.setattr(m, "_chemins_status", lambda wd: frozenset({"app/x.py", "app/y.py"}))
    monkeypatch.setattr(m, "_committer_pour_agent", lambda *a, **k: None)   # rien n'est committable
    monkeypatch.setattr(m, "_reaffecter", lambda *a, **k: False)
    monkeypatch.setattr(m, "_clore_delegation", lambda *a, **k: None)
    monkeypatch.setattr(m, "_battement_delegation", lambda *a, **k: _rien())
    monkeypatch.setenv("LAFORGE_AGY_BIN", sys.executable)
    try:    # le verrou de workdir ouvre une base : un test ne l'ouvre pas
        import nokido_agent.app.forge_lock_manager as _lmmod
        monkeypatch.setattr(_lmmod, "get_lock_manager", lambda: _Verrou())
    except Exception:  # noqa: BLE001 - pas de pont nokido_agent : l'executeur journalise et continue
        pass

    class _Res:
        stdout = '{"status": "SUCCESS"}'      # AGY : SUCCESS SANS reponse -> echec qui nomme le refus
        stderr = ""
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Res())

    m._delegate_to_agy({"id": "job_agy_nr", "description": "ecris app/x.py et app/y.py"}, "tok")
    copies = list((tmp_path / "sauvegardes").rglob("x.py"))
    assert copies, "le travail de la session AGY en echec n'a pas ete preserve"


def test_une_synchronisation_de_worktree_ne_peut_pas_effacer_un_travail_non_sauvegarde(monkeypatch, tmp_path):
    """(d) job_d7d57967 : 2 fichiers ecrits par AGY, jamais committes, DISPARUS au recalage du worktree. La
    sauvegarde se fait AVANT la synchronisation : apres, c'est trop tard."""
    m = _module(monkeypatch)
    wt = tmp_path / "wt"
    (wt / "app").mkdir(parents=True)
    (wt / "app" / "x.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(m, "_SAUVEGARDES", tmp_path / "sauvegardes")
    monkeypatch.setattr(m, "_chemins_status", lambda wd: frozenset({"app/x.py"}))
    monkeypatch.setattr(m, "_worktree_de", lambda nom: wt, raising=False)
    vu = {}

    def _sync(nom):
        vu["copies"] = [str(p) for p in (tmp_path / "sauvegardes").rglob("x.py")]
        return {"agent": nom, "rebased": True}

    faux = types.ModuleType("forge_worktree")
    faux.sync = _sync
    monkeypatch.setitem(sys.modules, "forge_worktree", faux)

    m._preparer_worktree("ANTIGRAVITY")
    assert vu.get("copies"), "le travail n'etait pas sauvegarde AVANT la synchronisation du worktree"
