# -*- coding: utf-8 -*-
"""NR (31/10, choix owner « demande au regulateur ») : NREM3 ne redemarre plus rien elle-meme -- elle DEMANDE.

Mesure 31/10 : 11:21:49 et 11:51:49 REFUS 401 (POST superviseur sans jeton) ; apres 0d5ade792 (identite CIRCADIAN
par le hub), 12:51:49 [RBAC] DENY manage_forge_lifecycle ring 3 < 1. Choix owner : aucun privilege elargi. Le
circadien pose un bail forge_organ_demand (issuer CIRCADIAN) pour chaque organe de consolidation ; le regulateur du
hub (RESOURCE_MANAGER, qui detient deja l'acces superviseur) relance UNE fois par bail les services demandes, dans
le budget RAM (meme admission que les reprises), puis libere le bail. REQUESTED != ACHIEVED : le circadien rend
« REQUESTED », le regulateur journalise ce qu'il a honore.
"""
# pylint: disable=missing-function-docstring,protected-access,too-few-public-methods
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_circadian as fc  # noqa: E402
import forge_resource_manager as rm  # noqa: E402


@pytest.fixture()
def demandes(monkeypatch):
    """Base de demandes en memoire, branchee sur les deux noms d'import du module."""
    baux = {}

    def acquerir(organe, issuer, reason, duree_s=300.0, priority=50, ref=""):
        ident = "dem_%d" % (len(baux) + 1)
        baux[ident] = {"id": ident, "organe": organe, "issuer": issuer, "reason": reason, "libere": False}
        return ident

    def demandes_actives(organe):
        return [dict(b) for b in baux.values() if b["organe"] == organe and not b["libere"]]

    def liberer(ident):
        if ident in baux:
            baux[ident]["libere"] = True
        return True

    for nom in ("nokido_agent.app.forge_organ_demand", "forge_organ_demand"):
        try:
            mod = __import__(nom, fromlist=["acquerir"])
        except ImportError:
            continue
        monkeypatch.setattr(mod, "acquerir", acquerir)
        monkeypatch.setattr(mod, "demandes_actives", demandes_actives)
        monkeypatch.setattr(mod, "liberer", liberer)
    for nom in ("nokido_agent.app.forge_opsec", "forge_opsec"):
        try:
            mod = __import__(nom, fromlist=["is_human_locked"])
            monkeypatch.setattr(mod, "is_human_locked", lambda *a, **k: False)
        except ImportError:
            pass
    return baux


class _Rep:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


def test_le_circadien_demande_au_lieu_de_redemarrer(demandes, monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("aucun appel reseau : le circadien pose une demande")
    monkeypatch.setattr(urllib.request, "urlopen", interdit)
    r = fc._restart_service("NokidoHebbian")
    assert r["ok"] is True and r["etat"] == "REQUESTED" and r["demande"] in demandes
    assert demandes[r["demande"]]["issuer"] == "CIRCADIAN" and demandes[r["demande"]]["organe"] == "NokidoHebbian"


def test_le_regulateur_honore_une_fois_puis_libere(demandes, monkeypatch):
    urls = []

    def urlopen(req, timeout=None):
        urls.append(req.full_url)
        return _Rep()
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(rm, "_supervisor_auth_headers", lambda *a, **k: {})
    monkeypatch.setattr(rm, "_ram_totale_gb", lambda: 23.7)
    fc._restart_service("NokidoSkillCurator")
    fc._restart_service("NokidoHebbian")
    faits = rm._honorer_demandes_circadiennes(40.0, ["NokidoSkillCurator", "NokidoHebbian", "NokidoNightTrainer"])
    assert sorted(faits) == ["NokidoHebbian", "NokidoSkillCurator"]
    assert sorted(u.rsplit("/", 1)[-1] for u in urls) == ["NokidoHebbian", "NokidoSkillCurator"]
    assert all("/restart/" in u for u in urls)
    assert all(b["libere"] for b in demandes.values())
    assert rm._honorer_demandes_circadiennes(40.0, ["NokidoSkillCurator", "NokidoHebbian"]) == []  # une fois


def test_hors_budget_la_demande_attend(demandes, monkeypatch):
    urls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: urls.append(req.full_url) or _Rep())
    monkeypatch.setattr(rm, "_supervisor_auth_headers", lambda *a, **k: {})
    monkeypatch.setattr(rm, "_ram_totale_gb", lambda: 23.7)
    fc._restart_service("NokidoNightTrainer")
    assert rm._honorer_demandes_circadiennes(76.0, ["NokidoNightTrainer"]) == [] and urls == []
    assert not any(b["libere"] for b in demandes.values())  # le bail reste : prochain passage, RAM relue


def test_une_demande_d_un_autre_emetteur_n_est_pas_honoree_ici(demandes, monkeypatch):
    urls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: urls.append(req.full_url) or _Rep())
    monkeypatch.setattr(rm, "_supervisor_auth_headers", lambda *a, **k: {})
    monkeypatch.setattr(rm, "_ram_totale_gb", lambda: 23.7)
    import forge_organ_demand as od
    od.acquerir("NokidoHebbian", "AUTRE", "pas une consolidation")
    assert rm._honorer_demandes_circadiennes(40.0, ["NokidoHebbian"]) == [] and urls == []
