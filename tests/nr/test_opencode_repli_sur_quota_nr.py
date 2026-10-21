# -*- coding: utf-8 -*-
"""NR — quota gratuit epuise -> repli sur le modele par defaut, dans la MEME delegation (owner 17/10 ~22 h 30 : « ok a et
utilisez le quota b par jour quand dispo avant bascule »).

Mesure 17/10 job_be9a6847 : NEMOTRON (openrouter :free) -> « Rate limit exceeded: free-models-per-day » apres 1-2 taches,
0 commit. Contrat : une instance qui declare `repli_modele` relance UNE fois la tache avec ce modele quand l'erreur est un
quota ; le detail DIT le repli ; sans `repli_modele`, ou pour une erreur qui n'est pas un quota, aucun repli.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as T  # noqa: E402

QUOTA = "session/prompt -> {'code': -32603, 'message': 'Internal error: Rate limit exceeded: free-models-per-day'}"


class Doublure:
    vus = []

    def __init__(self, cmd=None, cwd=None, on_log=None, agent="gemini", env=None):
        self.modele = json.loads((env or {}).get("OPENCODE_CONFIG_CONTENT", "{}")).get("model")

    def start(self):
        return None

    def initialize(self):
        return {}

    def session_new(self):
        return "sid"

    def request(self, method, params, timeout=30):
        return {}

    def prompt(self, sid, text, timeout=30):
        Doublure.vus.append(self.modele)
        if self.modele and self.modele.startswith("openrouter/") and Doublure.erreur:
            raise RuntimeError(Doublure.erreur)
        return {"text": 'fait {"intent":"OK_DONE","pointer_ref":"x"}'}

    def close(self):
        return None


def _deleguer(tmp_path, monkeypatch, repli=True, erreur=QUOTA):
    table = {"OPENCODE_NEMOTRON": {"modele": "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
                                   "worktree": "opencode_nemotron"}}
    if repli:
        table["OPENCODE_NEMOTRON"]["repli_modele"] = ""
    f = tmp_path / "instances.json"
    f.write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setenv("LAFORGE_OPENCODE_INSTANCES_FILE", str(f))
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_NEMOTRON_WORKDIR", str(wt))
    Doublure.vus, Doublure.erreur = [], erreur
    monkeypatch.setattr(T, "ACPClient", Doublure)
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "commit ok")
    monkeypatch.setattr(T, "_juger_livraison", lambda ok, detail, wt_, avant, autorises=None: (ok, "commits produits : 1", None))
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda i: "jeton_coffre")
    monkeypatch.setattr(T, "_lire_cle_fournisseur", lambda nom: "cle_fabriquee")
    monkeypatch.setattr(T, "_battement_delegation", lambda agent, tid: __import__("contextlib").nullcontext())
    clos = []
    monkeypatch.setattr(T, "_clore_delegation", lambda task_id, token, ok, detail, intent=None: clos.append((ok, detail)))
    T._delegate_to_opencode({"id": "job_repli_01", "agent": "OPENCODE_NEMOTRON",
                             "description": "Consigne de test assez longue pour etre extraite."}, "jx")
    return clos


def test_quota_epuise_bascule_une_fois_sur_le_repli_et_le_dit(tmp_path, monkeypatch):
    clos = _deleguer(tmp_path, monkeypatch)
    assert Doublure.vus == ["openrouter/nvidia/nemotron-3-super-120b-a12b:free", None], Doublure.vus
    assert len(clos) == 1 and clos[0][0] is True, clos
    assert "repli" in clos[0][1].lower() and "quota" in clos[0][1].lower(), clos[0][1]


def test_sans_repli_declare_le_quota_reste_un_echec_dit(tmp_path, monkeypatch):
    clos = _deleguer(tmp_path, monkeypatch, repli=False)
    assert Doublure.vus == ["openrouter/nvidia/nemotron-3-super-120b-a12b:free"], Doublure.vus
    assert len(clos) == 1 and clos[0][0] is False


class DelaiDepasse(TimeoutError):
    pass


def test_un_delai_acp_depasse_bascule_aussi_sur_le_repli(tmp_path, monkeypatch):
    """Mesure 17/10 : groq gpt-oss (x2) et zai glm-4.7-flash (x2) -> « timeout en attente id=4 », 0 commit, alors que le
    modele par defaut d'OpenCode livre la meme tache. Owner 17/10 ~22 h 50 : « ok » au repli etendu au delai."""
    erreurs = iter([DelaiDepasse("timeout en attente id=4")])

    def prompt(self, sid, text, timeout=30):
        Doublure.vus.append(self.modele)
        if self.modele and self.modele.startswith("openrouter/"):
            raise next(erreurs)
        return {"text": 'fait {"intent":"OK_DONE","pointer_ref":"x"}'}

    monkeypatch.setattr(Doublure, "prompt", prompt)
    clos = _deleguer(tmp_path, monkeypatch, erreur=None)
    assert Doublure.vus == ["openrouter/nvidia/nemotron-3-super-120b-a12b:free", None], Doublure.vus
    assert len(clos) == 1 and clos[0][0] is True, clos


def test_une_erreur_qui_n_est_pas_un_quota_ne_bascule_pas(tmp_path, monkeypatch):
    clos = _deleguer(tmp_path, monkeypatch, erreur="session/prompt -> timeout reseau")
    assert Doublure.vus == ["openrouter/nvidia/nemotron-3-super-120b-a12b:free"], Doublure.vus
    assert len(clos) == 1 and clos[0][0] is False
