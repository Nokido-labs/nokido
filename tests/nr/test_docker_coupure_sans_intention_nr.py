# -*- coding: utf-8 -*-
"""NR (owner 3/11 « la liberation de Docker doit etre plus rapide, deja dit, si le corps ne porte plus d'intention
vers lui ; ici une annulation, donc coupure »).

Mesure 3/11 : 4 veilles annulees par ChainExecutor._arreter_chaine ; deux avaient une etape EN COURS, donc pas de
verdict terminal, donc pas de relache ; puis release_claim appliquait 180 s de grace meme a 0 intention -> Docker
(3,7 Go) restait tenu, la RAM a refuse trois jobs. Contrat : (a) fin/annulation de CHAINE sans autre reclamation ni
intention en attente = coupure SANS grace ; (b) une intention en attente garde la grace ; (c) la recherche
PONCTUELLE garde sa grace (recherches qui s'enchainent) ; (d) l'annulation relache sans attendre l'etape en cours.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import nokido_agent.tools.forge_docker_keeper as K  # noqa: E402
import nokido_agent.app.forge_watch_agent as W  # noqa: E402
from nokido_agent.app.forge_chain_executor import ChainExecutor  # noqa: E402


def _keeper(monkeypatch, tmp_path, intentions):
    monkeypatch.setattr(K, "WANT_FLAG", tmp_path / "docker.wanted")
    monkeypatch.setattr(K, "_release_at_path", lambda: tmp_path / "docker.release_at")
    arrets = []
    monkeypatch.setattr(K, "_release_docker", lambda: arrets.append(1) or {"stopped": ["x"]})
    monkeypatch.setattr(K, "_audit", lambda *a, **k: None)
    monkeypatch.delenv("LAFORGE_DOCKER_GRACE_S", raising=False)   # grace PAR DEFAUT (180 s) : c'est elle qu'on court-circuite
    monkeypatch.setattr(K, "palier_courant", lambda: "CALME")
    monkeypatch.setattr(K, "intentions_docker_en_attente", lambda *a, **k: intentions)
    return arrets


def test_fin_de_chaine_sans_intention_coupe_sans_grace(monkeypatch, tmp_path):
    arrets = _keeper(monkeypatch, tmp_path, 0)
    K.claim_docker("wj_a")
    r = W._relacher_docker("wj_a")
    assert r["released"] is True and arrets == [1], r


def test_intention_en_attente_garde_la_grace(monkeypatch, tmp_path):
    arrets = _keeper(monkeypatch, tmp_path, 2)
    K.claim_docker("wj_a")
    r = W._relacher_docker("wj_a")
    assert r["released"] is True and arrets == [], r


def test_recherche_ponctuelle_garde_sa_grace(monkeypatch, tmp_path):
    arrets = _keeper(monkeypatch, tmp_path, 0)
    K.claim_docker("searxng_ponctuel")
    r = K.release_claim("searxng_ponctuel")
    assert r["released"] is True and arrets == [], r


def test_annulation_relache_sans_attendre_l_etape_en_cours(monkeypatch, tmp_path):
    arrets = _keeper(monkeypatch, tmp_path, 0)
    K.claim_docker("wj_c")
    ex = ChainExecutor(str(tmp_path / "chaines.db"))
    ex._arreter_chaine("wj_c", "annulation owner")
    assert arrets == [1] and not K.WANT_FLAG.exists()
