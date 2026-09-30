"""NR -- un appel fournisseur qui ECHOUE laisse son issue dans l'audit, comme celui qui reussit.

MESURE 2026-09-25 (8 derniers Mo de logs/mcp_audit.log, canal CLOUD) : mistral 20 requetes / 0
reponse, deepseek 10/0, ollama 9/0, claude 4/0. `ask()` journalise la requete (`log_cloud_out`)
puis la reponse (`log_cloud_in`) sur le chemin NOMINAL seulement : ses branches `except
asyncio.TimeoutError` et `except Exception` rendaient `ok: False` sans rien ecrire. Des qu'on trace
les reponses (sidecar), n'en voir que les reussites fabriquerait un faux « 100 % sain » -- un
survivant n'est pas un echantillon.

Symetrie : une erreur levee AVANT l'emission (prompt systeme, contexte) n'est pas un echec du
FOURNISSEUR -- il n'a pas ete appele. Elle ne s'ecrit donc pas en issue fournisseur.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_agent_proxy as ap  # noqa: E402
from nokido_agent.app import forge_network_logger as nl  # noqa: E402


class _Fournisseur:
    model = "modele-test"
    display_name = "Fournisseur test"
    api_key_env = "CLE_TEST"

    def __init__(self, reponse=None, erreur=None):
        self.reponse, self.erreur = reponse, erreur

    def is_available(self):
        return True

    async def ask_tracked(self, **_k):
        if self.erreur is not None:
            raise self.erreur
        return self.reponse


@pytest.fixture
def journal(monkeypatch):
    appels = {"out": [], "in": []}
    monkeypatch.setattr(nl, "log_cloud_out", lambda *a, **k: appels["out"].append(a))
    monkeypatch.setattr(nl, "log_cloud_in", lambda *a, **k: appels["in"].append(a))
    monkeypatch.setattr(ap, "_emit", lambda *a, **k: None)
    return appels


def _ask(monkeypatch, fournisseur, **k):
    monkeypatch.setattr(ap, "get_provider", lambda name: fournisseur)
    return asyncio.run(ap.ask("fournisseur_test", "bonjour", rag_context=False, raw=True, **k))


def test_une_exception_du_fournisseur_s_ecrit_en_echec(monkeypatch, journal):
    r = _ask(monkeypatch, _Fournisseur(erreur=RuntimeError("quota epuise")))
    assert r["ok"] is False
    assert len(journal["out"]) == 1 and len(journal["in"]) == 1
    fournisseur, modele, agent, reponse = journal["in"][0][:4]
    assert (fournisseur, modele) == ("fournisseur_test", "modele-test")
    assert str(reponse).startswith("ERR") and "RuntimeError" in reponse


def test_un_timeout_du_fournisseur_s_ecrit_en_echec(monkeypatch, journal):
    r = _ask(monkeypatch, _Fournisseur(erreur=asyncio.TimeoutError()), timeout=7)
    assert r["ok"] is False
    assert len(journal["in"]) == 1
    reponse = journal["in"][0][3]
    assert str(reponse).startswith("ERR") and "timeout" in reponse.lower()


def test_une_erreur_avant_emission_n_accuse_pas_le_fournisseur(monkeypatch, journal):
    def _casse(*_a, **_k):
        raise ValueError("prompt systeme illisible")

    monkeypatch.setattr(ap, "_build_system_prompt", _casse)
    monkeypatch.setattr(ap, "get_provider", lambda name: _Fournisseur(reponse="jamais"))
    r = asyncio.run(ap.ask("fournisseur_test", "bonjour", rag_context=False, raw=False))
    assert r["ok"] is False
    assert journal["out"] == [] and journal["in"] == []


def test_la_reussite_reste_journalisee_une_seule_fois(monkeypatch, journal):
    r = _ask(monkeypatch, _Fournisseur(reponse="salut"))
    assert r["ok"] is True
    assert len(journal["out"]) == 1 and len(journal["in"]) == 1
    assert journal["in"][0][3] == "salut"
