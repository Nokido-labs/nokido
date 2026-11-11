"""NR 3/11 — ring d'un client OAuth choisi par l'owner AU TRAY et inscrit au registre des identites.

Decision owner 3/11 (« ring choisi au tray + inscrit au registre ») : un client public se re-inscrit a chaque
re-authentification (Claude Code : nouveau client_id), donc un ring declare a la main par client_id ne tient pas. Le
ring se decide au consentement ; la decision est INSCRITE au registre (autorite unique, aucun ring lu du jeton seul).
Bornes : identite OAUTH_* seulement, ring 1..3 (jamais 0), motif trace dans l'entree + audit, ecriture atomique.
"""
import json

import pytest

from nokido_agent.app import forge_ring_admin as A


@pytest.fixture
def registre(tmp_path, monkeypatch):
    p = tmp_path / "agent_identities.json"
    p.write_text(json.dumps({"agents": {"CLAUDE": {"ring": 1}}}), encoding="utf-8")
    monkeypatch.setattr(A, "_STORE", p)
    audits = []
    monkeypatch.setattr(A, "_audit", lambda m: audits.append(m))
    return p, audits


def test_inscrit_le_client_au_ring_choisi(registre):
    p, audits = registre
    r = A.inscrire_client_oauth("OAUTH_nkc_abc", 1, "consentement tray 3/11")
    assert r["ok"] is True
    e = json.loads(p.read_text(encoding="utf-8"))["agents"]["OAUTH_NKC_ABC"]
    assert e["ring"] == 1 and e["kind"] == "oauth_client" and "consentement tray" in e["_note"]
    assert any("OAUTH_NKC_ABC" in a and "1" in a for a in audits)
    assert json.loads(p.read_text(encoding="utf-8"))["agents"]["CLAUDE"]["ring"] == 1     # rien d'autre touche


def test_mise_a_jour_idempotente(registre):
    p, _ = registre
    A.inscrire_client_oauth("OAUTH_nkc_abc", 1, "a")
    A.inscrire_client_oauth("OAUTH_nkc_abc", 3, "b")
    assert json.loads(p.read_text(encoding="utf-8"))["agents"]["OAUTH_NKC_ABC"]["ring"] == 3


@pytest.mark.parametrize("identite,ring", [("CLAUDE", 1), ("HUB", 3), ("OAUTH_x", 0), ("OAUTH_x", 4), ("OAUTH_x", "1x"),
                                           ("", 1)])
def test_bornes(registre, identite, ring):
    p, _ = registre
    avant = p.read_text(encoding="utf-8")
    assert A.inscrire_client_oauth(identite, ring, "x")["ok"] is False
    assert p.read_text(encoding="utf-8") == avant
