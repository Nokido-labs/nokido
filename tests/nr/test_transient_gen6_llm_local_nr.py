"""NR — GEN-6 : le chemin LLM LOCAL, et son etat reel mesure.

GEN-6 est la premiere generation autorisee a viser un LLM. Elle ne l'est pas a
en inventer un : l'etat du corps se mesure AVANT l'appel, et il decide.

MESURE DU 2026-09-17, faite avant toute ligne de ce chemin :

    llama-server :8091   port FERME
    ollama       :11434  port OUVERT, /api/tags rend 200 avec des modeles,
                         mais une GENERATION reelle rend HTTP 503 en 0,3 s
    embedder     :8099   port ferme
    LM Studio    :1234   port ferme

`/api/tags` MENT -- piege deja paye le 2026-09-07 (« 16 modeles listes, aucun
runner »), et confirme une seconde fois ici. Les trois etats de la constitution
sont donc distincts et mesures : TRANSPORT (le port repond) n'est pas APPLICATIF
(l'API repond) qui n'est pas CAPACITE (un modele genere).

CONSEQUENCE : aucun LLM local n'est disponible. `PROVIDER_UNAVAILABLE` est le
resultat CORRECT, et ces tests interdisent les deux facons de le maquiller --
basculer vers le cloud, ou transformer l'indisponibilite du fournisseur en echec
de la tache. Ce sont deux choses differentes, et `forge_swarm_evidence` porte
deja cette distinction.
"""
from __future__ import annotations

import os
import sys

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : reseau localhost sans serveur simule (:8091)
#   (l.66)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (RACINE, os.path.join(RACINE, "app"), os.path.join(RACINE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

executor = pytest.importorskip("forge_transient_executor")
proto = pytest.importorskip("forge_m2m_protocol")
gate = pytest.importorskip("forge_tool_gate")
ev = pytest.importorskip("forge_swarm_evidence")


def _transient_llm(prompt="dis OK", call_id="toolu_L1"):
    t = proto.normaliser_transient({
        "hook_event_name": "TRANSIENT", "transport": "interne",
        "session_id": "sess-gen6", "tool_use_id": call_id,
        "tool_name": "llm.local",
        "tool_input": {"prompt": prompt},
    })
    assert t is not None
    return t


# ── LA CAPACITE EXISTE, ET ELLE EST LOCALE ─────────────────────────────────

def test_la_capacite_llm_local_est_reconnue():
    assert executor.capacite_de(_transient_llm()) == "llm.local"


def test_le_backend_est_SONDE_avant_tout_appel():
    """EXISTE n'est pas DISPONIBLE, et DISPONIBLE n'est pas REPOND.

    La sonde doit rendre les trois separement, pour qu'un port ouvert ne se lise
    jamais comme une capacite.
    """
    etat = executor.etat_llm_local()
    assert set(("port_ouvert", "genere", "detail")) <= set(etat)
    assert isinstance(etat["port_ouvert"], bool)
    assert etat["genere"] in (True, False, None), (
        "`genere` doit valoir True, False, ou None quand la question n'a pas pu "
        "etre posee -- jamais un booleen par defaut")


# ── INDISPONIBLE N'EST PAS ECHEC ───────────────────────────────────────────

def test_backend_indisponible_rend_PROVIDER_UNAVAILABLE(monkeypatch):
    monkeypatch.setattr(executor, "etat_llm_local",
                        lambda: {"port_ouvert": False, "genere": False,
                                 "detail": "port ferme"})
    t = _transient_llm(call_id="toolu_L2")
    res = executor.executer(t, gate.admettre_transient(t))
    assert res["status"] == "PROVIDER_UNAVAILABLE", res
    assert res.get("result") is None, "aucun resultat ne peut etre invente"


def test_un_fournisseur_indisponible_n_est_PAS_une_tache_echouee(monkeypatch):
    """Distinction portee par la couche a preuves, et qu'on ne doit pas perdre.

    Un echec de TRANSPORT ne dit RIEN de la tache : conclure a l'echec ferait
    accuser une tache qui n'a jamais ete tentee.
    """
    monkeypatch.setattr(executor, "etat_llm_local",
                        lambda: {"port_ouvert": True, "genere": False,
                                 "detail": "HTTP 503"})
    t = _transient_llm(call_id="toolu_L3")
    res = executor.executer(t, gate.admettre_transient(t))
    verdict = executor.verifier(res)
    assert verdict["etat"] == ev.UNKNOWN, (
        "indisponibilite du fournisseur -> UNKNOWN, jamais REJECTED : %r" % verdict)
    assert "disponible" in (verdict.get("motif") or "").lower() or \
           "fournisseur" in (verdict.get("motif") or "").lower()


def test_aucune_bascule_cloud_quand_le_local_manque(monkeypatch):
    """Le premier chemin reste SOUVERAIN. Pas d'OpenRouter, pas de Gemini."""
    vus = []
    import urllib.request
    vrai = urllib.request.urlopen

    def _piste(req, *a, **k):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "127.0.0.1" not in url and "localhost" not in url:
            vus.append(url)
        return vrai(req, *a, **k)

    monkeypatch.setattr(urllib.request, "urlopen", _piste)
    monkeypatch.setattr(executor, "etat_llm_local",
                        lambda: {"port_ouvert": False, "genere": False,
                                 "detail": "port ferme"})
    t = _transient_llm(call_id="toolu_L4")
    executor.executer(t, gate.admettre_transient(t))
    assert vus == [], "une adresse NON locale a ete contactee : %r" % vus


# ── L'ETAT REEL DU CORPS, TEL QU'IL EST ────────────────────────────────────

def test_l_etat_reel_est_rapporte_sans_etre_maquille():
    """Ce test ne suppose PAS un backend disponible : il verifie la coherence.

    Si un LLM local est un jour disponible, il passera aussi -- c'est justement
    ce qu'on veut d'un test d'etat.
    """
    etat = executor.etat_llm_local()
    t = _transient_llm(call_id="toolu_L5")
    res = executor.executer(t, gate.admettre_transient(t))
    if etat.get("genere") is True:
        assert res["status"] == "COMPLETED", res
        assert res["result"], "un backend qui genere doit produire un resultat"
    else:
        assert res["status"] == "PROVIDER_UNAVAILABLE", (
            "le backend ne genere pas (%s) : le statut doit le DIRE"
            % etat.get("detail"))
