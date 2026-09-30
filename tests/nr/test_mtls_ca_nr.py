# -*- coding: utf-8 -*-
"""NR — autorite de certification CLIENTE du mTLS (RFC 8705, PKIX).

Ce que ce test garde, et pourquoi chaque point compte :

  1. un certificat client porte `clientAuth` et RIEN d'autre -- s'il portait aussi
     `serverAuth`, il pourrait authentifier un faux serveur Nokido ;
  2. un certificat client n'est PAS une autorite (`CA=False`) -- sinon il pourrait
     signer d'autres identites ;
  3. la CA est limitee a `path_length=0` : elle ne signe que des feuilles ;
  4. la signature est verifiee CRYPTOGRAPHIQUEMENT, pas seulement l'emetteur
     declare -- un champ `issuer` se recopie, une signature non ;
  5. emettre sans CA est REFUSE : on ne fabrique pas une identite orpheline ;
  6. `--init-ca` deux fois n'ECRASE PAS : perdre la cle de CA invaliderait tous
     les certificats deja emis.

Zero service externe : tout se passe dans tmp_path, aucune ecriture dans le depot.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

x509 = pytest.importorskip("cryptography.x509")
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

import forge_mtls_ca as ca  # noqa: E402


@pytest.fixture
def bac(monkeypatch, tmp_path):
    """Redirige TOUTE la PKI vers tmp_path : le depot n'est jamais touche."""
    monkeypatch.setattr(ca, "TLS", tmp_path)
    monkeypatch.setattr(ca, "CA_CERT", tmp_path / "clients_ca.pem")
    monkeypatch.setattr(ca, "CA_KEY", tmp_path / "clients_ca.key.pem")
    monkeypatch.setattr(ca, "CLIENTS", tmp_path / "clients")
    return tmp_path


def _cert(p: Path):
    return x509.load_pem_x509_certificate(p.read_bytes())


def test_emettre_sans_ca_est_refuse(bac):
    """Une identite ne doit pas pouvoir naitre sans autorite."""
    assert ca.issue("VIBE") == 2
    assert not (bac / "clients").exists()


def test_ca_est_limitee_aux_feuilles(bac):
    assert ca.init_ca() == 0
    c = _cert(bac / "clients_ca.pem")
    bc = c.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert bc.ca is True
    assert bc.path_length == 0, "la CA cliente ne doit pas pouvoir signer de sous-CA"
    ku = c.extensions.get_extension_for_class(x509.KeyUsage).value
    assert ku.key_cert_sign and ku.crl_sign
    assert not ku.digital_signature, "une CA ne signe pas des donnees applicatives"


def test_certificat_client_ne_peut_pas_authentifier_un_serveur(bac):
    """LE point central : sans cette garde, un cert client pourrait usurper le hub."""
    ca.init_ca()
    assert ca.issue("VIBE") == 0
    c = _cert(bac / "clients" / "vibe.pem")
    eku = c.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    noms = [o._name for o in eku]
    assert noms == ["clientAuth"], f"EKU trop permissif : {noms}"
    assert c.extensions.get_extension_for_class(
        x509.BasicConstraints).value.ca is False


def test_signature_verifiee_cryptographiquement(bac):
    """Un `issuer` se recopie ; une signature, non."""
    ca.init_ca()
    ca.issue("VIBE")
    autorite = _cert(bac / "clients_ca.pem")
    feuille = _cert(bac / "clients" / "vibe.pem")
    autorite.public_key().verify(
        feuille.signature, feuille.tbs_certificate_bytes,
        ec.ECDSA(feuille.signature_hash_algorithm))
    assert feuille.issuer == autorite.subject


def test_identite_agent_portee_par_le_certificat(bac):
    """L'identite doit vivre dans le certificat, pas dans un en-tete declaratif."""
    ca.init_ca()
    ca.issue("ANTIGRAVITY")
    c = _cert(bac / "clients" / "antigravity.pem")
    san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert [str(u.value) for u in san] == ["urn:nokido:agent:ANTIGRAVITY"]


def test_init_ca_deux_fois_n_ecrase_pas(bac):
    """Remplacer une CA invaliderait tous les certificats deja emis."""
    ca.init_ca()
    empreinte = (bac / "clients_ca.pem").read_bytes()
    assert ca.init_ca() == 0
    assert (bac / "clients_ca.pem").read_bytes() == empreinte


def test_issue_deux_fois_n_ecrase_pas(bac):
    ca.init_ca()
    ca.issue("VIBE")
    avant = (bac / "clients" / "vibe.pem").read_bytes()
    ca.issue("VIBE")
    assert (bac / "clients" / "vibe.pem").read_bytes() == avant
