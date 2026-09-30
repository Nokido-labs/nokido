"""NR -- la veille ne perd plus une alerte dont l'ingestion a echoue (C_06b, owner 24/09).

Mesure : depuis le 19/09, 34/34 releases vues ressortaient a « 0 chunk » et etaient marquees VUES
quand meme -> jamais retentees. `_ingest` rendait 0 pour toute reponse non reconnue, sans la
journaliser (« inconnu » lu comme « rien »). Et un refus HTTP du hub declenchait le repli
d'ECRITURE DIRECTE -- un ecrivain de plus sur la base RAG, qui contournait l'autorisation.
Contrat :
  - verdict explicite (INSERE / REJETE / ERREUR / INCONNU) selon le protocole du hub ;
  - « 0 inseres » n'est PAS un succes (doublon ou echec : indistinguables) ;
  - seul INSERE marque « vu » ; tout autre verdict est dit et reste rejouable ;
  - refus HTTP = REJETE, JAMAIS de repli d'ecriture directe.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_rss_watcher as rw  # noqa: E402


def test_verdict_suit_le_protocole_du_hub():
    assert rw._verdict_reponse("ingest OK: 3 chunks -> 2 inseres domain=x")[:2] == (rw.INSERE, 2)
    assert rw._verdict_reponse("ingest OK: 3 chunks -> 0 inseres domain=x")[0] == rw.INCONNU
    assert rw._verdict_reponse("ingest: 0 chunks (texte trop court ou vide)")[0] == rw.REJETE
    assert rw._verdict_reponse("ingest error: boom")[0] == rw.ERREUR
    assert rw._verdict_reponse("")[0] == rw.INCONNU
    assert rw._verdict_reponse("reponse jamais vue")[0] == rw.INCONNU


def test_gate_denied_observe_en_production_est_un_rejet_rejouable():
    """Forme REELLE relevee le 24/09 22:35 par le chemin nominal du producteur (sans sonde)."""
    v = rw._verdict_reponse("GATE_DENIED: ring:ring 4 <= requis 3")
    assert v[0] == rw.REJETE and "ring 4" in v[2]
    etat = {"seen": []}
    assert rw._marquer_si_succes(etat, "gh:o/r:v1", v) is False and etat["seen"] == [], "rejete = rejouable"


def test_seul_insere_marque_vu():
    etat = {"seen": []}
    for statut in (rw.REJETE, rw.ERREUR, rw.INCONNU):
        assert rw._marquer_si_succes(etat, "u", (statut, 0, "x")) is False
    assert etat["seen"] == []
    assert rw._marquer_si_succes(etat, "u", (rw.INSERE, 2, "ok")) is True and etat["seen"] == ["u"]


@pytest.fixture()
def veille(monkeypatch):
    etat = {"seen": []}
    monkeypatch.setattr(rw, "GITHUB_REPOS", ["o/r"])
    for nom in ("PYPI_PACKAGES", "ARXIV_QUERIES", "WATCH_QUERIES_RYZENAI", "WATCH_URLS"):
        monkeypatch.setattr(rw, nom, [])
    monkeypatch.setattr(rw, "fetch_github_release", lambda repo: {
        "version": "v1", "body": "breaking change", "title": "t",
        "url": "https://github.com/o/r/releases/tag/v1", "age_days": 0})
    monkeypatch.setattr(rw, "_load_state", lambda: etat)
    monkeypatch.setattr(rw, "_save_state", lambda s: None)
    monkeypatch.setattr(rw.time, "sleep", lambda s: None)
    return etat, monkeypatch


def test_chemin_reel_une_ingestion_non_prouvee_reste_rejouable(veille):
    etat, mp = veille
    mp.setattr(rw, "_ingest", lambda **k: (rw.INCONNU, 0, "reponse non reconnue"))
    rw.run_watch(since_days=7)
    assert "gh:o/r:v1" not in etat["seen"], "release perdue : marquee vue sans ingestion prouvee"
    mp.setattr(rw, "_ingest", lambda **k: (rw.INSERE, 2, "ok"))
    rw.run_watch(since_days=7)
    assert "gh:o/r:v1" in etat["seen"], "la release retentee et inseree doit enfin etre marquee"


@pytest.fixture()
def hub_double(monkeypatch):
    import nokido_agent.app.forge_agent_credential as cred
    import nokido_agent.app.forge_ingest_pipeline as pipe

    monkeypatch.setattr(cred, "jeton_pour", lambda *a, **k: "jeton-de-test")
    ecritures = []
    monkeypatch.setattr(pipe, "store_chunks", lambda chunks: ecritures.append(chunks) or 1)
    return monkeypatch, ecritures


def test_refus_http_rejete_sans_repli_d_ecriture(hub_double):
    mp, ecritures = hub_double

    def _refus(req, timeout=0):
        raise urllib.error.HTTPError("http://hub/mcp", 401, "Unauthorized", None, None)

    mp.setattr(urllib.request, "urlopen", _refus)
    v = rw._ingest(text="t", source="s", domain="watch_alerts", role="release:x", author="o/r", summary="s")
    assert v[0] == rw.REJETE and "401" in v[2]
    assert ecritures == [], "un refus du hub ne doit JAMAIS declencher une ecriture directe"


def test_erreur_json_rpc_est_une_erreur(hub_double):
    mp, _ = hub_double
    mp.setattr(urllib.request, "urlopen",
               lambda req, timeout=0: io.BytesIO(json.dumps({"error": {"code": -1, "message": "refus"}}).encode()))
    assert rw._ingest(text="t", source="s", domain="d", role="r", author="a", summary="s")[0] == rw.ERREUR
