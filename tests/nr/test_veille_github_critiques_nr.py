# -*- coding: utf-8 -*-
"""NR — la veille recurrente suit les depots DUMPES, et re-recupere les CRITIQUES longtemps.

Mesures du 2026-09-23 :
  * le capteur `veille_github_head` (465 tirs / 465) ne suivait que 12 cibles sur 342 :
    il lisait le `nom_dump` BRUT du registre, alors que le dumper le DEDUIT
    (`charger_cibles`). llama.cpp, ollama, qdrant... dumpes le soir meme n'etaient pas
    suivis. Une cible dont un dump existe doit etre suivie.
  * l'intention `veille_gh.wanted` (TTL 24 h) avait 22 jours : le capteur voyait 4
    depots bouger et n'en re-recuperait aucun. Decision owner : « une duree de vie
    longue, limitee aux depots critiques ». `veille_gh_critiques.wanted` porte la LISTE
    et vit 180 jours ; hors de cette liste, l'intention courte reste la seule porte.
Exerce le vrai `pat_veille_github_head`, recuperation interceptee (aucun clone).
"""
import importlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
L = importlib.import_module("forge_autonomous_loops")


def test_une_cible_sans_nom_dump_brut_est_suivie_si_son_dump_existe(tmp_path):
    (tmp_path / "gitingest_veille_ggml_org_llama_cpp.txt").write_text("x", encoding="utf-8")
    doc = {"cibles": {
        "ggml_org_llama_cpp": {"target_id": "t1", "url": "https://github.com/ggml-org/llama.cpp"},
        "jamais_dumpe": {"target_id": "t2", "url": "https://github.com/a/b"},
        "historique": {"target_id": "t3", "url": "https://github.com/c/d", "nom_dump": "hist"},
    }}
    suivies, sans = L._gh_cibles_suivies(doc, docs=tmp_path)
    noms = sorted(c["nom_dump"] for c in suivies)
    assert noms == ["ggml_org_llama_cpp", "hist"], noms
    assert sans == 1


def _monter(monkeypatch, tmp_path, critiques, age_s=0):
    monkeypatch.setattr(L, "_GH_INTENTION", tmp_path / "absente.wanted")
    f = tmp_path / "veille_gh_critiques.wanted"
    if critiques is not None:
        f.write_text(json.dumps({"cibles": critiques}), encoding="utf-8")
        t = time.time() - age_s
        os.utime(f, (t, t))
    monkeypatch.setattr(L, "_GH_INTENTION_CRITIQUES", f)
    monkeypatch.setattr(L, "_GH_ETAT", tmp_path / "etat.json")
    appels = []
    monkeypatch.setattr(L, "_gh_recuperer",
                        lambda cible, sha, docs, appel=None: appels.append(cible["nom_dump"])
                        or {"etat": "SKIPPED", "raison": "test"})
    return appels


def _cibles():
    return [{"target_id": "t1", "repo": "ggml-org/llama.cpp", "url": "u1", "nom_dump": "llama"},
            {"target_id": "t2", "repo": "x/y", "url": "u2", "nom_dump": "autre"}]


def _jouer(tmp_path):
    return L.pat_veille_github_head(cibles=_cibles(), tete=lambda url: ("b" * 40, "ok"),
                                    sha_local=lambda p: "a" * 40, docs=tmp_path)


def test_sans_intention_globale_seuls_les_critiques_sont_recuperes(monkeypatch, tmp_path):
    appels = _monter(monkeypatch, tmp_path, critiques=["llama"])
    _jouer(tmp_path)
    assert appels == ["llama"], appels


def test_intention_critique_vit_180_jours(monkeypatch, tmp_path):
    appels = _monter(monkeypatch, tmp_path, critiques=["llama"], age_s=100 * 86400)
    _jouer(tmp_path)
    assert appels == ["llama"], "une intention critique de 100 j doit rester valide"


def test_intention_critique_perimee_au_dela(monkeypatch, tmp_path):
    appels = _monter(monkeypatch, tmp_path, critiques=["llama"], age_s=200 * 86400)
    _jouer(tmp_path)
    assert appels == []


def test_sans_aucune_intention_rien_n_est_recupere(monkeypatch, tmp_path):
    appels = _monter(monkeypatch, tmp_path, critiques=None)
    r = _jouer(tmp_path)
    assert appels == [] and r["UPDATED"] == 2
