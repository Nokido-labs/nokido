#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_mtls_ca.py — autorite de certification CLIENTE pour le mTLS Nokido.

__FORGE_COLOR__ = "immunitaire/identite-cryptographique-des-agents"

POURQUOI UNE CA SEPAREE DE CELLE DU SERVEUR
    Un certificat CLIENT ne doit jamais pouvoir servir de certificat SERVEUR, ni
    l'inverse. Deux autorites distinctes rendent la confusion impossible par
    construction, plutot que par convention :

        Nokido MCP Client CA   ->  cert-VIBE, cert-ANTIGRAVITY, ...   EKU clientAuth
        cert serveur du hub    ->  forge_gen_tls_cert.py              EKU serverAuth

CE QUE CELA APPORTE, ET CE QUE CELA N'APPORTE PAS
    Un bearer prouve la POSSESSION d'un secret ; il est rejouable par quiconque
    l'obtient. Un certificat client prouve en plus la detention d'une CLE PRIVEE
    (RFC 8705). C'est la brique qui permettra de rattacher la contribution d'un
    agent a une identite verifiable, et non a un simple en-tete declaratif.

    En revanche la cle privee vit ici dans un FICHIER : elle est copiable. Le
    niveau superieur (cle non exportable scellee dans le TPM) est mesure comme
    NON DISPONIBLE aujourd'hui -- `forge_persona_tpm` detient bien une cle ECDSA
    P-256 dans le TPM, mais il n'expose AUCUN export de cle publique, et la pile
    TLS de Python (OpenSSL) ne sait pas signer un handshake via le Platform
    Crypto Provider (CNG). Passer au TPM demandera ces deux ponts ; le present
    module est concu pour que seule la GENERATION change alors.

CONTRAT DE PRUDENCE
    - N'ECRASE JAMAIS une CA ou un certificat existant sans `--force` : perdre une
      cle de CA invalide tous les certificats emis.
    - Les cles privees vont dans `sandbox/tls/` (hors git). Le certificat PUBLIC de
      la CA peut, lui, etre distribue.
    - Rien n'est active ici : `forge_tls_caddy.py --mtls` est ce qui EXIGE le
      certificat, et il refuse de s'armer si cette CA n'existe pas.

Usage :
    forge_mtls_ca.py --init-ca
    forge_mtls_ca.py --issue VIBE
    forge_mtls_ca.py --verify
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from pathlib import Path

__FORGE_COLOR__ = "immunitaire/identite-cryptographique-des-agents"

ROOT = Path(__file__).resolve().parent.parent
TLS = ROOT / "sandbox" / "tls"
CA_CERT = TLS / "clients_ca.pem"          # lu par forge_tls_caddy --mtls
CA_KEY = TLS / "clients_ca.key.pem"       # NE QUITTE JAMAIS la machine
CLIENTS = TLS / "clients"

_JOURS_CA = 3650
_JOURS_CLIENT = 397   # <= 398 j, plafond usuel des navigateurs/CA publiques


def _log(m: str) -> None:
    print(f"[mtls-ca] {m}", flush=True)


def _crypto():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
        return x509, hashes, serialization, ec, NameOID, ExtendedKeyUsageOID
    except Exception as e:  # noqa: BLE001
        _log(f"ERREUR: `cryptography` indisponible ({type(e).__name__}: {e}).")
        raise SystemExit(2)


def _ecrire_prive(chemin: Path, data: bytes) -> None:
    """Ecrit une cle privee en restreignant l'acces des la creation."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def init_ca(force: bool = False) -> int:
    x509, hashes, serialization, ec, NameOID, _ = _crypto()
    if CA_CERT.exists() and not force:
        _log(f"CA deja presente ({CA_CERT}). --force pour la REMPLACER "
             "— cela invaliderait tous les certificats deja emis.")
        return 0
    TLS.mkdir(parents=True, exist_ok=True)
    cle = ec.generate_private_key(ec.SECP256R1())
    sujet = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Nokido MCP Client CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Nokido"),
    ])
    maintenant = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(sujet)
        .issuer_name(sujet)
        .public_key(cle.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(maintenant - _dt.timedelta(minutes=5))
        .not_valid_after(maintenant + _dt.timedelta(days=_JOURS_CA))
        # pathlen=0 : cette CA ne signe que des FEUILLES, jamais une sous-CA.
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(digital_signature=False, content_commitment=False,
                          key_encipherment=False, data_encipherment=False,
                          key_agreement=False, key_cert_sign=True, crl_sign=True,
                          encipher_only=False, decipher_only=False),
            critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(cle.public_key()),
                       critical=False)
        .sign(cle, hashes.SHA256())
    )
    _ecrire_prive(CA_KEY, cle.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    CA_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _log(f"CA creee : {CA_CERT}")
    _log(f"cle CA   : {CA_KEY} (0600 — ne JAMAIS la distribuer)")
    return 0


def issue(agent: str, force: bool = False) -> int:
    x509, hashes, serialization, ec, NameOID, EKU = _crypto()
    agent = agent.upper().strip()
    if not agent.isalnum() and "_" not in agent:
        _log(f"nom d'agent invalide : {agent!r}")
        return 2
    if not (CA_CERT.exists() and CA_KEY.exists()):
        _log("CA absente. Lancer --init-ca d'abord.")
        return 2
    dest_cert = CLIENTS / f"{agent.lower()}.pem"
    dest_key = CLIENTS / f"{agent.lower()}.key.pem"
    if dest_cert.exists() and not force:
        _log(f"certificat deja present pour {agent} ({dest_cert}). --force pour le remplacer.")
        return 0

    ca_cert = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
    ca_key = serialization.load_pem_private_key(CA_KEY.read_bytes(), password=None)
    cle = ec.generate_private_key(ec.SECP256R1())
    maintenant = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, agent),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Nokido"),
        ]))
        .issuer_name(ca_cert.subject)
        .public_key(cle.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(maintenant - _dt.timedelta(minutes=5))
        .not_valid_after(maintenant + _dt.timedelta(days=_JOURS_CLIENT))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        # EKU clientAuth SEUL : ce certificat ne peut PAS authentifier un serveur.
        .add_extension(x509.ExtendedKeyUsage([EKU.CLIENT_AUTH]), critical=True)
        .add_extension(
            x509.KeyUsage(digital_signature=True, content_commitment=False,
                          key_encipherment=False, data_encipherment=False,
                          key_agreement=False, key_cert_sign=False, crl_sign=False,
                          encipher_only=False, decipher_only=False),
            critical=True)
        # L'identite d'agent est PORTEE par le certificat, pas par un en-tete.
        .add_extension(x509.SubjectAlternativeName([
            x509.UniformResourceIdentifier(f"urn:nokido:agent:{agent}")]),
            critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(cle.public_key()),
                       critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _ecrire_prive(dest_key, cle.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    dest_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _log(f"{agent} : cert={dest_cert}")
    _log(f"{agent} : cle ={dest_key} (0600)")
    _log(f"{agent} : SAN=urn:nokido:agent:{agent} EKU=clientAuth expire dans {_JOURS_CLIENT} j")
    return 0


def verify() -> int:
    """Etat SEUL. Trois etats par objet : PRESENT / ABSENT / ILLISIBLE."""
    x509, _, _, _, _, _ = _crypto()
    def _lire(p: Path):
        if not p.exists():
            return None, "ABSENT"
        try:
            return x509.load_pem_x509_certificate(p.read_bytes()), "PRESENT"
        except Exception as e:  # noqa: BLE001
            return None, f"ILLISIBLE({type(e).__name__})"

    ca, etat = _lire(CA_CERT)
    _log(f"CA cliente   {etat:22} {CA_CERT}")
    if ca is not None:
        _log(f"             sujet={ca.subject.rfc4514_string()} expire={ca.not_valid_after_utc:%Y-%m-%d}")
    _log(f"cle CA       {'PRESENTE' if CA_KEY.exists() else 'ABSENTE'}")
    if not CLIENTS.exists():
        _log("certificats clients : AUCUN (repertoire absent)")
        return 0
    n = 0
    for p in sorted(CLIENTS.glob("*.pem")):
        if p.name.endswith(".key.pem"):
            continue
        c, e = _lire(p)
        n += 1
        if c is None:
            _log(f"  {p.stem:14} {e}")
            continue
        try:
            eku = [o._name for o in c.extensions.get_extension_for_class(
                x509.ExtendedKeyUsage).value]
        except Exception:  # noqa: BLE001
            eku = ["(aucun EKU — certificat trop permissif)"]
        _log(f"  {p.stem:14} expire={c.not_valid_after_utc:%Y-%m-%d} EKU={eku}")
    if n == 0:
        _log("certificats clients : AUCUN emis")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--init-ca", action="store_true", help="Cree la CA cliente")
    g.add_argument("--issue", metavar="AGENT", help="Emet un certificat client")
    g.add_argument("--verify", action="store_true", help="Etat seul, aucune ecriture")
    p.add_argument("--force", action="store_true",
                   help="Remplace un objet existant (DESTRUCTIF : une CA remplacee "
                        "invalide tous les certificats deja emis)")
    a = p.parse_args(argv)
    if a.init_ca:
        return init_ca(force=a.force)
    if a.issue:
        return issue(a.issue, force=a.force)
    return verify()


if __name__ == "__main__":
    sys.exit(main())
