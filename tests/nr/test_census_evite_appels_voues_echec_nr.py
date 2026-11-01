"""NR -- forge_free_tier_census evite les appels voues a l'echec (S1 + S2).

Verifie :
  - should_skip(fournisseur) vrai -> zero appel, etat SAUTE
  - 429 Retry-After <= 30s (ex: 2s) -> un seul nouvel essai (retry)
  - 429 Retry-After > 30s (ex: 3600s) -> echeance enregistree au census et fournisseur saute pour la suite
  - 402 Payment Required -> SANS_SOLDE, aucun nouvel essai
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_free_tier_census as C
import forge_provider_quota as Q


def _creer_http_error(url: str, code: int, msg: str, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, msg, headers or {}, io.BytesIO(b"erreur test"))


def test_should_skip_vrai_zero_appel(monkeypatch, tmp_path):
    """should_skip vrai -> zero appel ; etat SAUTE avec motif."""
    from nokido_agent.app import forge_secrets as s
    monkeypatch.setattr(s, "get_secret", lambda k: "cle-test")

    appels_completer = []
    def faux_completer(*a, **k):
        appels_completer.append(a)
        return {"choices": [{"message": {"content": "ok"}}]}, {}

    monkeypatch.setattr(C, "_completer", faux_completer)
    monkeypatch.setattr(C, "_lire_catalogue", lambda base, cle: (200, [{"id": "m1"}], {}, ""))
    monkeypatch.setattr(Q, "should_skip", lambda provider, threshold=1.0: provider == "groq")

    sortie = C.cibler([("groq", "m1")])
    assert len(sortie) == 1
    r = sortie[0]
    assert r["etat"] == "SAUTE"
    assert "quota fournisseur epuise" in r["motif"] or "should_skip" in r["motif"]
    assert len(appels_completer) == 0


def test_429_retry_after_2_un_seul_nouvel_essai(monkeypatch):
    """429 Retry-After 2 -> un seul nouvel essai (2 appels au total), reussite finale."""
    appels = []
    delais_sleep = []
    monkeypatch.setattr(C.time, "sleep", lambda s: delais_sleep.append(s))

    def faux_completer(base, cle, modele, outils, max_tokens=None):
        appels.append(len(appels) + 1)
        if len(appels) == 1:
            raise _creer_http_error("http://test/chat/completions", 429, "Too Many Requests", {"Retry-After": "2"})
        return {"choices": [{"message": {"content": "pong"}}]}, {}

    monkeypatch.setattr(C, "_completer", faux_completer)

    res = C.sonder("http://test", "cle", "modele-test", outils=False, fournisseur="test_prov")
    assert len(appels) == 2  # 1 initial + 1 retry
    assert delais_sleep == [2.0]
    assert res["joignable"] is True


def test_429_retry_after_3600_echeance_enregistree_et_fournisseur_saute(monkeypatch, tmp_path):
    """429 Retry-After 3600 -> echeance enregistree et fournisseur saute pour le reste du census."""
    census_file = tmp_path / "free_tier_census.json"
    # cas reel : le census existe deja (consigner_quota_epuise ECRIT DANS un census, il n'en cree pas)
    census_file.write_text(json.dumps({"verdicts": {}}), encoding="utf-8")
    monkeypatch.setattr(C, "SORTIE", census_file)
    from nokido_agent.app import forge_secrets as s
    monkeypatch.setattr(s, "get_secret", lambda k: "cle-test")
    monkeypatch.setattr(C, "PAUSE_S", 0)

    appels_completer = []
    def faux_completer(base, cle, modele, outils, max_tokens=None):
        appels_completer.append(modele)
        raise _creer_http_error("http://test/chat/completions", 429, "Too Many Requests", {"Retry-After": "3600"})

    monkeypatch.setattr(C, "_completer", faux_completer)
    monkeypatch.setattr(C, "_lire_catalogue", lambda base, cle: (200, [{"id": "m1"}, {"id": "m2"}], {}, ""))

    sortie = C.cibler([("groq", "m1"), ("groq", "m2")])
    assert len(sortie) == 2
    # Premier appel a tente et a recu 429 > 30s
    assert sortie[0]["etat"] in ("QUOTA_EPUISE", "SAUTE") or "HTTP 429" in sortie[0].get("motif", "")
    # Deuxieme modele saute directement
    assert sortie[1]["etat"] == "SAUTE"
    # m1 a ete appele, m2 n'a PAS ete appele
    assert appels_completer == ["m1"]

    # Verifier que l'echeance a ete enregistree dans le census
    assert census_file.exists()
    doc = json.loads(census_file.read_text(encoding="utf-8"))
    verdicts = doc.get("verdicts", {})
    assert "groq:m1" in verdicts
    assert verdicts["groq:m1"].get("quota_epuise_jusqu_a") is not None


def test_402_sans_solde_aucun_nouvel_essai(monkeypatch):
    """402 = SANS_SOLDE, aucun nouvel essai."""
    appels = []
    delais_sleep = []
    monkeypatch.setattr(C.time, "sleep", lambda s: delais_sleep.append(s))

    def faux_completer(base, cle, modele, outils, max_tokens=None):
        appels.append(len(appels) + 1)
        raise _creer_http_error("http://test/chat/completions", 402, "Payment Required")

    monkeypatch.setattr(C, "_completer", faux_completer)

    res = C.sonder("http://test", "cle", "modele-test", outils=False, fournisseur="test_prov")
    assert len(appels) == 1  # Un seul appel, zero retry
    assert len(delais_sleep) == 0
    assert res["joignable"] is False
    assert res.get("etat") == "SANS_SOLDE"
