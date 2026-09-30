#!/usr/bin/env python3
"""
forge_gen_tls_cert.py — Génère un certificat TLS auto-signé local pour le hub.

But : fournir cert.pem + key.pem pour activer le TLS opt-in du hub
(tools/nokido_hub.py lit LAFORGE_HUB_TLS_CERT / LAFORGE_HUB_TLS_KEY).
Cert auto-signé pour 127.0.0.1 + localhost (SAN), valable 3650 jours.

Loopback mono-user : le TLS local coche la case compliance "chiffré même en
loopback" (in-transit). Self-signed => les clients hub doivent accepter le cert
(verify=False ou ajout au trust store). NE PAS activer le hub en https sans
avoir mis à jour les clients (Claude Desktop / Gemini / Cline / bridges qui
pointent http://127.0.0.1:8766), sinon ils perdent la connexion.

Usage
-----
  python tools/forge_gen_tls_cert.py                 # -> sandbox/tls/{cert,key}.pem
  python tools/forge_gen_tls_cert.py --out DIR --days 825

Dépend de `cryptography` (déjà présent dans l'env Nokido).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import ipaddress
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "sandbox" / "tls"


def gen_cert(out_dir: Path, days: int = 3650) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    out_dir.mkdir(parents=True, exist_ok=True)
    cert_path = out_dir / "cert.pem"
    key_path = out_dir / "key.pem"

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Nokido Sovereign Hub"),
    ])
    san = x509.SubjectAlternativeName([
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        x509.IPAddress(ipaddress.ip_address("::1")),
    ])
    # epoch fixe non-naïf pour ne pas dépendre d'une horloge interdite ici ;
    # validité large couvrant le passé proche pour éviter clock-skew.
    not_before = _dt.datetime(2025, 1, 1, tzinfo=_dt.timezone.utc)
    not_after = not_before + _dt.timedelta(days=max(days, 3650))

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Génère un cert TLS auto-signé local pour le hub.")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="Répertoire de sortie")
    p.add_argument("--days", type=int, default=3650, help="Validité en jours")
    args = p.parse_args(argv)

    cert_path, key_path = gen_cert(Path(args.out), args.days)
    print(f"[tls] cert : {cert_path}")
    print(f"[tls] key  : {key_path}")
    print()
    print("Pour activer le TLS du hub (après MAJ des clients en https !) :")
    print(f"  setx LAFORGE_HUB_TLS_CERT \"{cert_path}\"")
    print(f"  setx LAFORGE_HUB_TLS_KEY  \"{key_path}\"")
    print("  puis restart NokidoMCP via forge_supervisor_ctl.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
