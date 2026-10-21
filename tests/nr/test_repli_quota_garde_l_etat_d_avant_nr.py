"""NR -- le repli apres quota epuise garde l'etat du worktree d'AVANT le premier tour.

Enquete AGY job_198d901b (docs/audit/sauvegarde_executeur_rates_20261019.md), verifiee sur piece : sur quota epuise,
_delegate_to_opencode se rappelle (l.2696) et RECALCULE _sales_avant (l.2591) APRES que le premier tour a ecrit ses
fichiers -- la preservation les prend pour des restes d'autres taches et les exclut (job_171ef456, Nemotron, 22:12 :
« 1 fichier non committe », aucune sauvegarde).
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


class _ClientQuota:
    prompts = 0

    def __init__(self, *_a, **_k):
        pass

    def start(self):
        pass

    def initialize(self):
        pass

    def session_new(self):
        return "sid"

    def prompt(self, _sid, _text, timeout=None):
        type(self).prompts += 1
        if type(self).prompts == 1:
            raise RuntimeError("429 quota exceeded (rate limit)")
        return {"text": '{"intent":"OK_DONE","pointer_ref":"docs/x.md"}'}

    def close(self):
        pass


def test_le_repli_preserve_avec_l_etat_d_avant_le_premier_tour(tmp_path, monkeypatch):
    _ClientQuota.prompts = 0
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_NEMOTRON_WORKDIR", str(wt))
    monkeypatch.setattr(T, "ACPClient", _ClientQuota)
    monkeypatch.setattr(T, "_instances_opencode", lambda: {
        "OPENCODE_NEMOTRON": {"modele": "openrouter/nvidia/nemotron", "repli_modele": "opencode/repli"}})
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: "jeton_" + inst)
    monkeypatch.setattr(T, "_env_cle_fournisseur", lambda _m: "")
    monkeypatch.setattr(T, "_battement_delegation", lambda *_a, **_k: contextlib.nullcontext())
    monkeypatch.setattr(T, "_etat_git", lambda _wt: None)
    etats = iter([frozenset(), frozenset({"app/ecrit_par_le_tour_1.py"})])
    monkeypatch.setattr(T, "_chemins_status", lambda _wt: next(etats, frozenset({"app/ecrit_par_le_tour_1.py"})))
    vus = {}

    def _preserver(ok, wt_, task_id, detail, inst, sales):
        vus["sales"] = sales
        return ""

    monkeypatch.setattr(T, "_preserver_livraison", _preserver)
    monkeypatch.setattr(T, "_juger_livraison",
                        lambda ok, detail, wt_, avant, autorises=None: (True, "commits produits : 1", "OK_DONE"))
    monkeypatch.setattr(T, "_consigner_verdict_auto", lambda *_a, **_k: None)
    monkeypatch.setattr(T, "_motif_reaffectation_apres", lambda *_a, **_k: None)
    monkeypatch.setattr(T, "_clore_delegation", lambda *a, **k: vus.setdefault("clos", a))

    T._delegate_to_opencode({"id": "job_repli_nr", "agent": "OPENCODE_NEMOTRON", "description": "x"}, "tok")

    assert _ClientQuota.prompts == 2, "le repli n'a pas ete tente"
    assert vus.get("sales") == frozenset(), vus.get("sales")
