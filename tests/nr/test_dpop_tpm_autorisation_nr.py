# -*- coding: utf-8 -*-
"""NR — preuve DPoP adossee au TPM : seul le porteur du credential PROPRE obtient la signature.

Chantier d'authentification, 24/09. PREUVE RUNTIME sur TPM REEL faite le meme jour
(C:/tmp/corrections/preuve_tpm_dpop.py, cle machine de CLAUDE) : 6/6 conformes — positif
LIEE ; maitre refuse avant signature ; cle logicielle aux memes champs REFUSEE ; rejeu,
autre URI REFUSES ; sans preuve INVERIFIABLE.

Ce NR rejoue la LOGIQUE en CI (pas de TPM en CI) : le module TPM est remplace par une cle
logicielle, mais l'autorisation (`_porteur_autorise`), la construction (`CleTpm`),
`creer_preuve_tpm` et `verifier` sont les VRAIS.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "app"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_dpop as d  # noqa: E402
from nokido_agent.app import forge_persona_tpm as tpm  # noqa: E402
from nokido_agent.app import forge_secrets as secrets_mod  # noqa: E402

URL = "http://127.0.0.1:8766/admin/run_job"
PROPRE, MAITRE = "p" * 64, "m" * 64


@pytest.fixture
def tpm_logiciel(monkeypatch):
    """Remplace le TPM par une cle logicielle (meme interface que le module reel)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    cle = ec.generate_private_key(ec.SECP256R1())

    def _signe(agent, donnees):
        r, s = decode_dss_signature(cle.sign(donnees, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")   # r||s comme NCryptSignHash

    monkeypatch.setattr(tpm, "sign_as", _signe)
    monkeypatch.setattr(tpm, "cle_publique_jwk_agent", lambda agent: (d.jwk_public(cle), ""))
    monkeypatch.setattr(secrets_mod, "get_secret",
                        lambda k: {"FORGE_TOKEN_CLAUDE": PROPRE, "FORGE_MCP_TOKEN": MAITRE}.get(k))
    return d.thumbprint(d.jwk_public(cle))


def test_porteur_du_credential_propre_obtient_une_preuve_liee(tpm_logiciel):
    p = d.creer_preuve_tpm("CLAUDE", "POST", URL, PROPRE)
    assert d.verifier(p, "POST", URL, PROPRE, jkt_attendu=tpm_logiciel)[0] == "LIEE"


def test_le_maitre_n_ouvre_pas_la_cle_d_un_organe(tpm_logiciel):
    with pytest.raises(PermissionError):
        d.CleTpm("CLAUDE", MAITRE)


def test_sans_credential_aucune_signature(tpm_logiciel, monkeypatch):
    appels = []
    monkeypatch.setattr(tpm, "sign_as", lambda *a: appels.append(a) or b"")
    with pytest.raises(PermissionError):
        d.creer_preuve_tpm("CLAUDE", "POST", URL, "")
    assert not appels, "sign_as a ete atteint sans autorisation prealable"


def test_une_autre_cle_ne_passe_pas_pour_la_cle_enregistree(tpm_logiciel):
    p = d.creer_preuve("POST", URL, PROPRE)   # cle logicielle DIFFERENTE, memes champs
    assert d.verifier(p, "POST", URL, PROPRE, jkt_attendu=tpm_logiciel)[0] == "REFUSEE"


def test_agent_non_enregistre_n_a_pas_d_empreinte():
    assert d.jkt_tpm_enregistre("AGENT_QUI_N_EXISTE_PAS_NR") is None
