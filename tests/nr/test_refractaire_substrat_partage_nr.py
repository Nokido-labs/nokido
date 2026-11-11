# -*- coding: utf-8 -*-
"""NR (owner 3/11, debat 2 tour 2) : la periode refractaire de l'effecteur de substrat est PARTAGEE entre processus.

relacher_substrat_sans_intention est appelee depuis le HUB (refus d'admission) et vit aussi dans le KEEPER : avec un
refractaire en memoire (_STATE), chacun pouvait couper Docker coup sur coup. Livraison OPENCODE_GLM (395d83b16) reprise
seulement dans l'idee : elle persistait `now`, que les appelants passent en horloge MONOTONE (propre a chaque processus,
incomparable entre processus), ecrivait le vrai sandbox/ dans son NR et mentait (« pas relache ») si l'ecriture echouait
APRES l'arret. Ici : horloge MURALE, fichier temporaire, verite sur le relachement.
"""
import json
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_docker_keeper as K  # noqa: E402


@pytest.fixture
def keeper(monkeypatch, tmp_path):
    relaches = []
    monkeypatch.setattr(K, "_FICHIER_SUBSTRAT", tmp_path / "docker.substrat_release.json")
    monkeypatch.setattr(K, "_STATE", {k: v for k, v in K._STATE.items() if k != "last_release_ts"})
    monkeypatch.setattr(K, "RELEASE_ENABLED", True)
    monkeypatch.setattr(K, "_RELEASE_REFRACTORY_S", 600.0)
    monkeypatch.setattr(K, "_docker_wanted", lambda: False)
    monkeypatch.setattr(K, "_docker_procs_present", lambda: True)
    monkeypatch.setattr(K, "_release_docker", lambda: relaches.append(1) or {"engine": "stop demande (rc=0)"})
    monkeypatch.setattr(K, "_audit", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_resource_manager",
                        types.SimpleNamespace(get_active_intents=lambda: {"chains_active": 0}))
    return relaches


def test_un_autre_processus_voit_le_refractaire(keeper, monkeypatch):
    assert K.relacher_substrat_sans_intention(5.0)["relache"] is True          # horloge monotone du « hub » : 5 s
    d = json.loads(K._FICHIER_SUBSTRAT.read_text(encoding="utf-8"))
    assert abs(d["ts"] - time.time()) < 60                                      # horloge MURALE persistee
    monkeypatch.setattr(K, "_STATE", {})                                        # « keeper » : autre processus
    r = K.relacher_substrat_sans_intention(987654.0)                           # sa propre horloge monotone
    assert r["relache"] is False and "refractaire" in r["motif"] and keeper == [1]


def test_refractaire_ecoule_on_peut_relacher(keeper):
    K._FICHIER_SUBSTRAT.write_text(json.dumps({"ts": time.time() - 3600}), encoding="utf-8")
    assert K.relacher_substrat_sans_intention(1.0)["relache"] is True and keeper == [1]


def test_registre_illisible_on_ne_coupe_pas(keeper):
    K._FICHIER_SUBSTRAT.write_text("{casse", encoding="utf-8")
    r = K.relacher_substrat_sans_intention(1.0)
    assert r["relache"] is False and "illisible" in r["motif"] and keeper == []


def test_ecriture_ratee_apres_l_arret_ne_ment_pas(keeper, monkeypatch):
    def _casse(*a, **k):
        raise OSError("disque")
    monkeypatch.setattr(K.os, "replace", _casse)
    r = K.relacher_substrat_sans_intention(1.0)
    assert r["relache"] is True and keeper == [1] and "non persiste" in r["motif"]
