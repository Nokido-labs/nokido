"""NR 19/10 -- l'arene darwinienne observe les integrations REELLES (reconciliation), pas seulement merger().

Mesure 19/10 ~22 h : sandbox/arene_promotion_observe.jsonl est ABSENT -- l'arene (312aa797c, observation) n'est
branchee que sur merger() (fusion d'une branche wip/<agent>), chemin inutilise ; toutes les integrations du jour
passent par reconcilier (--commit / --sauvegarde) et l'arene n'en a vu AUCUNE. Le reste « constater un vrai merge
journalise » (bb:decision_owner_hamilton_arene_vibe_capture_20261016) ne pouvait donc jamais se constater.
Contrat : une integration reussie (INTEGRE) journalise l'avis de l'arene sur ses seuls .py (mode observation,
origine = la tache ou le sha) ; arene illisible -> verdict INCONNU, l'integration reste INTEGRE ; echec d'integration
-> aucun avis journalise.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("forge_merge_gate_arene_nr", ROOT / "tools" / "forge_merge_gate.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(m)
    return m


def _faux_git(commit_rc=0):
    def faux(args, cwd=None):
        if "--name-only" in args:
            return 0, "app/a.py\ndocs/n.md", ""
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return 0, "alpha", ""
        if args[:3] == ["diff", "--cached", "--quiet"]:
            return 1, "", ""
        if args[:2] == ["cat-file", "-e"]:
            return 0, "", ""
        if args and args[0] == "show" and ":" in args[-1]:
            return 0, "x = 1\n", ""
        if args and args[0] == "commit":
            return commit_rc, "", "" if commit_rc == 0 else "refus"
        return 0, "", ""
    return faux


def _journal(f):
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []


def test_une_integration_reussie_est_observee_par_l_arene(tmp_path, monkeypatch):
    m = _module()
    monkeypatch.setattr(m, "_git", _faux_git())
    monkeypatch.setattr(m, "JOURNAL_ARENE", tmp_path / "arene.jsonl")
    r = m.reconcilier("abc1234", ["app/a.py", "docs/n.md"], apply=True, agent="OPENCODE_X")
    assert r["decision"] == "INTEGRE", r
    lignes = _journal(tmp_path / "arene.jsonl")
    assert len(lignes) == 1 and lignes[0]["mode"] == "observation"
    assert [f["fichier"] for f in lignes[0]["fichiers"]] == ["app/a.py"], lignes
    assert "abc1234" in json.dumps(lignes[0])


def test_arene_illisible_n_empeche_pas_l_integration(tmp_path, monkeypatch):
    m = _module()
    monkeypatch.setattr(m, "_git", _faux_git())
    monkeypatch.setattr(m, "JOURNAL_ARENE", tmp_path / "arene.jsonl")
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_darwinian_arena", None)
    r = m.reconcilier("abc1234", ["app/a.py"], apply=True)
    assert r["decision"] == "INTEGRE"
    assert _journal(tmp_path / "arene.jsonl")[0]["fichiers"][0]["verdict"] == "INCONNU"


def test_un_echec_d_integration_n_est_pas_observe(tmp_path, monkeypatch):
    m = _module()
    monkeypatch.setattr(m, "_git", _faux_git(commit_rc=1))
    monkeypatch.setattr(m, "JOURNAL_ARENE", tmp_path / "arene.jsonl")
    m.reconcilier("abc1234", ["app/a.py"], apply=True)
    assert _journal(tmp_path / "arene.jsonl") == []
