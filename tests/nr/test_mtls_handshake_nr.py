"""Non-regression : le handshake mTLS EXIGE et VERIFIE le certificat client.

Ce test est HERMETIQUE : il fabrique sa propre CA, son certificat serveur et ses
certificats clients dans `tmp_path`. Il ne lit JAMAIS `sandbox/tls/` -- un test qui
dependrait du materiel reel de la machine passerait au vert sur un poste sans mTLS,
et se lirait comme une garantie. Ici, si le mecanisme casse, le test rougit partout.

Ce qui est verifie -- et l'essentiel est dans les REFUS :

  - un certificat signe par la CA attendue est ACCEPTE, et son SAN est LISIBLE ;
  - aucun certificat            -> refus PENDANT le handshake ;
  - certificat d'une autre CA   -> refus PENDANT le handshake ;
  - certificat sans sa cle      -> impossible a presenter (preuve de possession) ;
  - l'incoherence entre SAN et `X-Agent-Name` est DETECTABLE.

Un succes seul ne prouverait rien : c'est la combinaison qui fait la preuve
(RFC 8705 place l'authentification du client pendant le handshake, jamais dans un
code HTTP applicatif).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

crypto = pytest.importorskip(
    "cryptography",
    reason="cryptography absent : les certificats ne peuvent pas etre fabriques ; "
           "l'essai n'est pas MENE, ce qui n'est pas la meme chose qu'un refus",
)

import forge_mtls_probe as probe  # noqa: E402


# --------------------------------------------------------------------------- #
# Materiel de test, fabrique a la volee
# --------------------------------------------------------------------------- #

def _ca(nom: str):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    cle = ec.generate_private_key(ec.SECP256R1())
    sujet = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nom)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(sujet).issuer_name(sujet)
            .public_key(cle.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(cle, hashes.SHA256()))
    return cle, cert


def _feuille(ca_cle, ca_cert, nom: str, *, serveur: bool):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    cle = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    if serveur:
        import ipaddress
        # Une IP nue n'est pas un GeneralName : elle doit etre enveloppee.
        san = x509.SubjectAlternativeName(
            [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))])
        eku = x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH])
    else:
        san = x509.SubjectAlternativeName(
            [x509.UniformResourceIdentifier("urn:nokido:agent:%s" % nom)])
        eku = x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH])
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nom)]))
            .issuer_name(ca_cert.subject)
            .public_key(cle.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(hours=1))
            .add_extension(san, critical=False)
            .add_extension(eku, critical=False)
            .sign(ca_cle, hashes.SHA256()))
    return cle, cert


def _ecrire(dossier: Path, base: str, cle, cert) -> tuple[Path, Path]:
    from cryptography.hazmat.primitives import serialization

    p_cert = dossier / ("%s.pem" % base)
    p_cle = dossier / ("%s.key.pem" % base)
    p_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    p_cle.write_bytes(cle.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()))
    return p_cert, p_cle


@pytest.fixture()
def bac(tmp_path):
    """CA legitime, CA etrangere, cert serveur, cert client -- tout en tmp_path."""
    ca_cle, ca_cert = _ca("CA Nokido (test)")
    from cryptography.hazmat.primitives import serialization
    p_ca = tmp_path / "ca.pem"
    p_ca.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    s_cle, s_cert = _feuille(ca_cle, ca_cert, "127.0.0.1", serveur=True)
    p_srv = _ecrire(tmp_path, "serveur", s_cle, s_cert)

    c_cle, c_cert = _feuille(ca_cle, ca_cert, "VIBE", serveur=False)
    p_cli = _ecrire(tmp_path, "vibe", c_cle, c_cert)

    e_cle, e_cert = _ca("CA Etrangere (test)")
    p_pir = _feuille(e_cle, e_cert, "VIBE", serveur=False)
    p_pirate = _ecrire(tmp_path, "pirate", *p_pir)

    journal = []
    srv = probe._serveur(0, journal, srv_cert=p_srv[0], srv_key=p_srv[1], ca=p_ca)
    port = srv.server_address[1]
    try:
        yield {"port": port, "ca": p_ca, "srv": p_srv, "client": p_cli,
               "pirate": p_pirate, "journal": journal}
    finally:
        srv.shutdown()
        srv.server_close()


# --------------------------------------------------------------------------- #

def _conclusif(*a, **k):
    """Un essai qui REFUSE de trancher sur un ILLISIBLE.

    Mesure du 2026-09-19 : en suite complete (10 823 tests, ~18 min), deux essais
    sont sortis en `TimeoutError` -- donc `ILLISIBLE`, l'etat que la sonde reserve
    a « je n'ai pas pu regarder ». Les memes passent 24/24 en isolation, et le
    serveur est un `ThreadingHTTPServer` : ce n'est pas une file d'attente, c'est
    une borne depassee sous charge.

    Un ILLISIBLE n'est NI un PASS NI un REFUSED. Le ranger du cote des echecs
    FABRIQUE une panne -- la constitution semantique du depot l'interdit
    (UNKNOWN != NO) -- et le ranger du cote des succes en masquerait une.

    Ce skip ne peut pas masquer une regression du contrat mTLS : un vrai refus
    sort en `REFUSED` (SSLError, ou reset cote Windows), jamais en ILLISIBLE.

    On retente UNE fois -- un handshake en loopback est deterministe, l'expiration
    ne l'est pas -- puis on skippe en DISANT le motif et la borne.
    """
    v, d = probe._essai(*a, **k)
    if v != "ILLISIBLE":
        return v, d
    v, d = probe._essai(*a, **k)
    if v != "ILLISIBLE":
        return v, d
    pytest.skip("essai non conclusif 2 fois (borne client %g s, reglable par "
                "LAFORGE_MTLS_TIMEOUT_S) : %s" % (probe.TIMEOUT_CLIENT_S, d))


def test_un_certificat_de_la_bonne_ca_est_accepte(bac):
    v, d = _conclusif(bac["port"], bac["client"][0], bac["client"][1],
                      ancre_serveur=bac["ca"])
    assert v == "PASS", d
    assert "urn:nokido:agent:VIBE" in d


def test_le_serveur_recoit_reellement_le_certificat(bac):
    """Le succes cote client ne suffit pas : le SERVEUR doit avoir vu le certificat."""
    _conclusif(bac["port"], bac["client"][0], bac["client"][1], ancre_serveur=bac["ca"])
    vus = [e for e in bac["journal"] if e.get("evenement") == "connexion"]
    assert vus, "aucune connexion enregistree cote serveur"
    assert vus[-1]["san"] == "urn:nokido:agent:VIBE"


def test_sans_certificat_le_handshake_est_refuse(bac):
    """LE test qui prouve : sans certificat, la connexion ne doit pas s'etablir."""
    v, d = _conclusif(bac["port"], None, None, ancre_serveur=bac["ca"])
    assert v == "REFUSED", "une connexion SANS certificat a ete acceptee : %s" % d


def test_une_autre_ca_est_refusee(bac):
    """Un certificat bien forme mais signe ailleurs ne doit pas passer."""
    v, d = _conclusif(bac["port"], bac["pirate"][0], bac["pirate"][1],
                      ancre_serveur=bac["ca"])
    assert v == "REFUSED", "un certificat d'une CA etrangere a ete accepte : %s" % d


def test_un_certificat_sans_sa_cle_ne_peut_pas_etre_presente(bac):
    """Preuve de possession (RFC 8705).

    L'echec survient au CHARGEMENT de la paire, donc AVANT le handshake : on ne peut
    pas presenter un certificat dont on n'a pas la cle privee. C'est structurel, et
    il faut le dire ainsi plutot que de le presenter comme une alerte TLS.
    """
    v, d = _conclusif(bac["port"], bac["client"][0], bac["pirate"][1],
                      ancre_serveur=bac["ca"])
    assert v == "REFUSED", d
    assert "chargement" in d or "MISMATCH" in d.upper()


def test_l_incoherence_entre_le_san_et_l_entete_est_detectable(bac):
    """mTLS n'apporte quelque chose que si l'identite du certificat est COMPARABLE
    a l'identite applicative. Ce test prouve la DISPONIBILITE du signal ; il ne
    prouve pas qu'un consommateur la refuse -- c'est un autre chainon."""
    v, _ = _conclusif(bac["port"], bac["client"][0], bac["client"][1],
                      entete="CLAUDE", ancre_serveur=bac["ca"])
    assert v == "PASS"
    vus = [e for e in bac["journal"] if e.get("evenement") == "connexion"]
    assert vus[-1]["san"] == "urn:nokido:agent:VIBE"
    assert vus[-1]["entete"] == "CLAUDE"
    assert vus[-1]["san"].rsplit(":", 1)[-1] != vus[-1]["entete"]


def test_un_certificat_absent_ne_rend_pas_une_identite(bac):
    """Trois etats : un pair sans certificat rend "" , jamais un nom par defaut."""
    assert probe._san_uri(None) == ""
    assert probe._san_uri({}) == ""
    assert probe._san_uri({"subjectAltName": (("DNS", "exemple"),)}) == ""
