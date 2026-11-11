# -*- coding: utf-8 -*-
"""NR owner 4/11 (« capacite basique du corps : sans intention, Docker doit s'arreter seul, immediatement » ; « pense
comme un corps : signal nerveux = action / reaction »). 17:58:26 le keeper tente la relache -> « engine intact
(conteneurs tiers presents) » (conteneur anonyme du concours, loving_hypatia) ; le conteneur s'arrete a 18:09, mais la
tentative SANS EFFET avait arme le refractaire de 1800 s -> Docker allume sans intention jusqu'a 18:28 ; et la relache
lancee depuis le compte des jobs ne peut pas arreter un Docker Desktop de session owner (6 x « NON ARRETE »).
Remede : un SIGNAL de relache (docker.relache_demandee) depose par l'organe qui constate ; le keeper (effecteur qui en a
les droits) REAGIT a son battement suivant, refractaire ignore ; signal maintenu tant qu'un tiers bloque, eteint des
que l'arret est fait. Sans signal, le refractaire reste (pas de martelage)."""
import importlib
import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "tools")]
K = importlib.import_module("forge_docker_keeper")
INTACT = {"stopped": [], "engine": "intact (conteneurs tiers presents)", "foreign_laisses": ["loving_hypatia"]}
ARRETE = {"stopped": [], "engine": "stop demande (rc=0)", "engine_verdict": "ARRETE (docker desktop stop)"}


def _armer(monkeypatch, tmp_path, retours):
    appels = []
    monkeypatch.setattr(K, "RELEASE_ENABLED", True)
    monkeypatch.setattr(K, "_docker_wanted", lambda *a, **k: False)
    monkeypatch.setattr(K, "_release_at_path", lambda: tmp_path / "absent.release_at")
    monkeypatch.setattr(K, "WANT_FLAG", tmp_path / "docker.wanted")
    monkeypatch.setattr(K, "_audit", lambda *a, **k: None)
    monkeypatch.setattr(K, "_retient_docker", lambda intents: False)
    faux = types.ModuleType("forge_resource_manager")
    faux.get_active_intents = lambda: []
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_resource_manager", faux)

    def _release():
        appels.append(1)
        return retours[min(len(appels), len(retours)) - 1]
    monkeypatch.setattr(K, "_release_docker", _release)
    monkeypatch.setitem(K._STATE, "last_release_ts", 0.0)
    return appels


def test_tiers_bloquant_arme_le_signal_et_le_keeper_reagit_des_qu_il_part(monkeypatch, tmp_path):
    appels = _armer(monkeypatch, tmp_path, [INTACT, ARRETE])
    t = 100000.0
    assert K._maybe_release(t) is not None and len(appels) == 1
    assert K._signal_relache_path().exists(), "relache bloquee par un tiers : le reflexe reste ARME"
    assert K._maybe_release(t + 30) is not None, "battement suivant : reaction, refractaire ignore"
    assert len(appels) == 2
    assert not K._signal_relache_path().exists(), "arret fait : le signal s'eteint"


def test_signal_depose_par_un_autre_organe_declenche_la_reaction(monkeypatch, tmp_path):
    appels = _armer(monkeypatch, tmp_path, [ARRETE])
    monkeypatch.setitem(K._STATE, "last_release_ts", 100000.0 - 10)   # en plein refractaire
    K._signaler_relache("job_CONCOURS")
    assert K._maybe_release(100000.0) is not None and len(appels) == 1
    assert not K._signal_relache_path().exists()


def test_sans_signal_une_relache_effective_garde_son_refractaire(monkeypatch, tmp_path):
    appels = _armer(monkeypatch, tmp_path, [ARRETE])
    t = 100000.0
    assert K._maybe_release(t) is not None
    assert K._maybe_release(t + 300) is None, "pas de signal : pas de martelage"
    assert len(appels) == 1


def test_la_derniere_reclamation_relachee_depose_le_signal(monkeypatch, tmp_path):
    _armer(monkeypatch, tmp_path, [{"stopped": [], "engine_verdict": "NON ARRETE : le daemon repond encore"}])
    monkeypatch.setattr(K, "_lire_claims", lambda: ["job_CONCOURS"])
    monkeypatch.setattr(K, "_ecrire_claims", lambda c: None)
    monkeypatch.setattr(K, "palier_courant", lambda: 0)
    monkeypatch.setattr(K, "intentions_docker_en_attente", lambda *a, **k: 0)
    K.release_claim("job_CONCOURS", immediat=True)
    assert K._signal_relache_path().exists(), "le compte des jobs n'a pas pu arreter : il SIGNALE au keeper"
