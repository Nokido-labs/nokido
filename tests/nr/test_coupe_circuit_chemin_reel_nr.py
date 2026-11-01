# -*- coding: utf-8 -*-
"""NR -- cliquet du coupe-circuit OpenCode sur le CHEMIN REEL (_delegate_to_opencode), sorties d'instance factices.

24/10 : taches reaffectees en < 1 min (GPTOSS -> GLM, NEMOTRON -> GLM), GLM « service temporarily overloaded ».
Attendu : panne fournisseur (429 / overloaded) ET boucle sans progres -> instance en REPOS, motif NOMME, rouverte a l'echeance.
Cause de la reaffectation rapide (mesure, pas un bug) : _motif_reaffectation_apres -> _panne_cli rend un motif des la
PREMIERE panne et _reaffecter part aussitot ; le seuil de 2 ne gouverne que le repos."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as T  # noqa: E402

pytestmark = pytest.mark.timeout(60)


class Doublure:
    sorties: list = []

    def __init__(self, cmd=None, cwd=None, on_log=None, agent="gemini", env=None):
        pass

    def start(self):
        return None

    def initialize(self):
        return {}

    def session_new(self):
        return "sid"

    def request(self, method, params, timeout=30):
        return {}

    def prompt(self, sid, text, timeout=30):
        s = Doublure.sorties[0] if len(Doublure.sorties) == 1 else Doublure.sorties.pop(0)
        if isinstance(s, Exception):
            raise s
        return {"text": s}

    def close(self):
        return None


def _prepare(tmp_path, monkeypatch):
    f = tmp_path / "instances.json"
    f.write_text(json.dumps({"OPENCODE_GLM": {"modele": "zai/glm-4.7-flash", "worktree": "opencode_glm"}}), encoding="utf-8")
    monkeypatch.setenv("LAFORGE_OPENCODE_INSTANCES_FILE", str(f))
    monkeypatch.setenv("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE", str(tmp_path / "cc.json"))
    monkeypatch.setenv("LAFORGE_OPENCODE_REPOS_S", "1800")
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_GLM_WORKDIR", str(wt))
    monkeypatch.setattr(T, "ACPClient", Doublure)
    monkeypatch.setattr(T, "_etat_git", lambda w: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "")
    monkeypatch.setattr(T, "_preserver_livraison", lambda *a, **k: "")
    monkeypatch.setattr(T, "_juger_livraison",
                        lambda ok, detail, w, avant, autorises=None, desc=None: (ok, "commits produits : 1", None))
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda i: "jeton")
    monkeypatch.setattr(T, "_lire_cle_fournisseur", lambda n: "cle")
    monkeypatch.setattr(T, "_battement_delegation", lambda a, t: __import__("contextlib").nullcontext())
    monkeypatch.setattr(T, "_reaffecter", lambda *a, **k: None)
    monkeypatch.setattr(T, "_clore_delegation", lambda *a, **k: None)
    monkeypatch.setattr(T, "OPENCODE_MAX_TOURS", 6)


def _deleguer(n):
    T._delegate_to_opencode({"id": f"job_cc_{n}", "agent": "OPENCODE_GLM",
                             "description": "Consigne de test assez longue pour etre extraite."}, "jx")


@pytest.mark.parametrize("sortie", [
    RuntimeError("session/prompt -> {'code': -32603, 'message': 'service may be temporarily overloaded'}"),
    RuntimeError("Client error '429 Too Many Requests'"),
])
def test_panne_fournisseur_coupe_nomme_et_rouvre(tmp_path, monkeypatch, sortie):
    _prepare(tmp_path, monkeypatch)
    Doublure.sorties = [sortie]
    _deleguer(1)
    assert not T.executeur_en_repos("OPENCODE_GLM")
    _deleguer(2)
    motif = T.executeur_en_repos("OPENCODE_GLM")
    assert motif and "REPOS" in motif and "fournisseur" in motif.lower()
    assert T.executeur_en_repos("OPENCODE_GLM", maintenant=time.time() + 1801) is None


def test_boucle_sans_progres_coupe_nomme_et_rouvre(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    Doublure.sorties = ["je continue le travail"]  # meme sortie a chaque tour, jamais d'intention finale
    _deleguer(1)
    _deleguer(2)
    motif = T.executeur_en_repos("OPENCODE_GLM")
    assert motif and "BOUCLE SANS PROGRES" in motif, motif
    assert T.executeur_en_repos("OPENCODE_GLM", maintenant=time.time() + 1801) is None


def test_boucle_s_arrete_au_premier_tour_sans_progres(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    vus = []
    orig = Doublure.prompt

    def prompt(self, sid, text, timeout=30):
        vus.append(text)
        return orig(self, sid, text, timeout)

    monkeypatch.setattr(Doublure, "prompt", prompt)
    Doublure.sorties = ["je continue le travail"]
    _deleguer(1)
    assert len(vus) == 2, len(vus)  # 1 tour + 1 relance identique -> coupe, pas 6 tours
