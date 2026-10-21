# -*- coding: utf-8 -*-
"""NR — l'effort de raisonnement de Codex suit la TAILLE de la tache (owner 17/10 : « si tu utilises les cli sur des
modeles plus faibles ils depenseront moins vite leur quota, selon la complexite »).

Mesure 17/10 : Codex Free (GPT-6-Luna, reasoning medium par defaut) a perdu >= 9 % de son quota MENSUEL sur une seule
reponse exploratoire. Le harness lancait `codex exec` sans `-c model_reasoning_effort`, donc toujours au defaut.
Contrat : taille S -> low, M -> medium, L -> high ; taille INCONNUE -> aucun reglage (UNKNOWN n'est pas S, le defaut
de la config owner reste) ; le prompt `-` reste le DERNIER argument.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as T  # noqa: E402


def _effort(args):
    for i, a in enumerate(args[:-1]):
        if a == "-c" and args[i + 1].startswith("model_reasoning_effort="):
            return args[i + 1].split("=", 1)[1].strip('"')
    return None


def test_la_taille_se_lit_dans_la_consigne():
    assert T._taille_tache("LOT de 3 demandes owner A FAIRE (taille S) -- charge compacte") == "S"
    assert T._taille_tache("[A FAIRE taille M ; critere : ...]") == "M"
    assert T._taille_tache("taille: L") == "L"
    assert T._taille_tache("Consigne sans indication de grandeur") is None
    assert T._taille_tache("une detaille S n'est pas une taille") is None


def test_l_effort_suit_la_taille_et_l_inconnu_garde_le_defaut(tmp_path):
    assert _effort(T._args_codex(tmp_path, "S")) == "low"
    assert _effort(T._args_codex(tmp_path, "M")) == "medium"
    assert _effort(T._args_codex(tmp_path, "L")) == "high"
    assert _effort(T._args_codex(tmp_path, None)) is None
    assert _effort(T._args_codex(tmp_path)) is None
    for taille in ("S", "M", "L", None):
        args = T._args_codex(tmp_path, taille)
        assert args[0] == "exec" and args[-1] == "-", args


def test_la_delegation_codex_ecrit_l_effort_de_la_taille_dans_le_job(tmp_path, monkeypatch):
    jobs = tmp_path / "harness_jobs"
    jobs.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    monkeypatch.delenv("LAFORGE_CODEX_EXEC_ARGS", raising=False)
    monkeypatch.setattr(T, "_HARNESS_JOBS", jobs)
    monkeypatch.setattr(T, "_workdir_codex", lambda: wt)
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_consommer_quota_codex", lambda: 1)
    monkeypatch.setattr(T, "_attendre_harness", lambda job, delai, task_id=None: {"ok": False, "error": "doublure"})
    monkeypatch.setattr(T, "_juger_livraison",
                        lambda ok, detail, wt_, avant, autorises=None: (False, "commits produits : 0", None))
    monkeypatch.setattr(T, "_clore_delegation", lambda task_id, token, ok, detail, intent=None: None)
    T._delegate_to_codex({"id": "job_codex_taille_01",
                          "description": "LOT de 1 demande owner A FAIRE (taille S) : consigne de test assez longue."},
                         "JETON_EXECUTEUR")
    ecrits = list(jobs.glob("*.json"))
    assert len(ecrits) == 1, ecrits
    args = json.loads(ecrits[0].read_text(encoding="utf-8"))["args"]
    assert _effort(args) == "low", args
