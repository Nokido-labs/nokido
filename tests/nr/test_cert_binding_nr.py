"""Non-regression : le certificat, le token et l'identite declaree doivent CONCORDER.

Le handshake mTLS prouve la possession d'une cle privee. Il ne prouve pas que ce
certificat est celui de l'agent VIBE de Nokido. Ces tests portent sur le chainon qui
etablit ce lien -- et l'essentiel, une fois de plus, tient dans les REFUS.

Hermetique : CA, certificats et tokens sont fabriques en memoire. Aucun materiel de
la machine n'est lu, sinon le test passerait au vert la ou rien n'est configure.

NOTE DE PORTEE, a ne pas perdre : ces tests valident la couche de DECISION. Ils ne
prouvent pas qu'un appel HTTP reel la traverse -- ce branchement est une dette
distincte, et la confondre avec celle-ci rendrait le systeme faussement sur.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
for sous in ("app", "tools"):
    if str(ROOT / sous) not in sys.path:
        sys.path.insert(0, str(ROOT / sous))

pytest.importorskip(
    "cryptography",
    reason="cryptography absent : les certificats ne peuvent pas etre fabriques ; "
           "l'essai n'est pas MENE, ce qui n'est pas un refus",
)

import forge_cert_binding as cb  # noqa: E402
from forge_integrity import CapabilityToken, IntegrityRing  # noqa: E402

SECRET = b"secret-de-test-hermetique-32-octets!"
AUDIENCE = "https://mcp.nokido.local/"


def _ca(nom="CA Nokido (test)"):
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


def _client(ca_cle, ca_cert, agent, *, eku_client=True, valide=True) -> bytes:
    """Rend le DER d'un certificat client. `eku_client` / `valide` servent aux refus."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    cle = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    if valide:
        debut, fin = now - dt.timedelta(minutes=5), now + dt.timedelta(hours=1)
    else:  # deja expire
        debut, fin = now - dt.timedelta(days=2), now - dt.timedelta(days=1)
    usage = ExtendedKeyUsageOID.CLIENT_AUTH if eku_client else ExtendedKeyUsageOID.SERVER_AUTH
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, agent)]))
            .issuer_name(ca_cert.subject)
            .public_key(cle.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(debut).not_valid_after(fin)
            .add_extension(x509.SubjectAlternativeName(
                [x509.UniformResourceIdentifier("urn:nokido:agent:%s" % agent)]),
                critical=False)
            .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
            .sign(ca_cle, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.DER)


def _token(sub, *, empreinte=None, aud=AUDIENCE) -> str:
    import time
    tok = CapabilityToken(
        sub=sub, ring=IntegrityRing.DEV, scopes={"rag": ["query"]},
        exp=time.time() + 600, iat=time.time(), jti="jti-%s" % sub,
        aud=aud, cnf={"x5t#S256": empreinte} if empreinte else {})
    return tok.encode(SECRET)


@pytest.fixture()
def bac():
    ca_cle, ca_cert = _ca()
    vibe = _client(ca_cle, ca_cert, "VIBE")
    mammouth = _client(ca_cle, ca_cert, "MAMMOUTH")
    return {"ca": (ca_cle, ca_cert), "VIBE": vibe, "MAMMOUTH": mammouth}


# --------------------------------------------------------------------------- #
# L'empreinte
# --------------------------------------------------------------------------- #

def test_l_empreinte_porte_sur_le_der_et_est_stable(bac):
    e1 = cb.thumbprint(bac["VIBE"])
    e2 = cb.thumbprint(bac["VIBE"])
    assert e1 == e2 and len(e1) == 43, e1          # SHA-256 base64url sans padding
    assert "=" not in e1, "le remplissage doit etre retire (RFC 8705 §3.1)"
    assert e1 != cb.thumbprint(bac["MAMMOUTH"])


def test_une_empreinte_sur_rien_leve(bac):
    with pytest.raises(ValueError):
        cb.thumbprint(b"")


# --------------------------------------------------------------------------- #
# Le cas nominal
# --------------------------------------------------------------------------- #

def test_cert_vibe_token_vibe_audience_correcte_donne_allow(bac):
    emp = cb.thumbprint(bac["VIBE"])
    r = cb.verifier(bac["VIBE"], _token("VIBE", empreinte=emp), SECRET,
                    audience=AUDIENCE, agent_declare="VIBE")
    assert r["decision"] == "ALLOW", r
    assert r["agent"] == "VIBE"


# --------------------------------------------------------------------------- #
# Les refus -- ce sont eux qui prouvent
# --------------------------------------------------------------------------- #

def test_cert_vibe_avec_token_claude_est_refuse(bac):
    """Le token parle d'un autre agent que le certificat."""
    emp = cb.thumbprint(bac["VIBE"])
    r = cb.verifier(bac["VIBE"], _token("CLAUDE", empreinte=emp), SECRET,
                    audience=AUDIENCE)
    assert r["decision"] == "REFUSE"
    assert r["controles"]["sub_egale_cert"] == "KO"


def test_token_sans_cnf_est_refuse(bac):
    """Un bearer non lie est rejouable depuis n'importe quel client."""
    r = cb.verifier(bac["VIBE"], _token("VIBE", empreinte=None), SECRET,
                    audience=AUDIENCE)
    assert r["decision"] == "REFUSE"
    assert r["controles"]["token_lie_au_cert"] == "KO"
    assert "possession" in r["raison"]


def test_token_lie_a_un_autre_certificat_est_refuse(bac):
    """MAMMOUTH presente son cert avec un token lie au cert de VIBE."""
    emp_vibe = cb.thumbprint(bac["VIBE"])
    r = cb.verifier(bac["MAMMOUTH"], _token("MAMMOUTH", empreinte=emp_vibe), SECRET,
                    audience=AUDIENCE)
    assert r["decision"] == "REFUSE"
    assert r["controles"]["token_lie_au_cert"] == "KO"


def test_mauvaise_audience_est_refusee(bac):
    """RFC 8707 : un token emis pour une autre ressource ne vaut pas ici."""
    emp = cb.thumbprint(bac["VIBE"])
    r = cb.verifier(bac["VIBE"], _token("VIBE", empreinte=emp, aud="https://autre/"),
                    SECRET, audience=AUDIENCE)
    assert r["decision"] == "REFUSE"
    assert r["controles"]["token_audience"] == "KO"


def test_entete_declarative_ne_peut_que_contredire(bac):
    """cert VIBE + X-Agent-Name=CLAUDE : l'identite reste VIBE, et c'est REFUSE."""
    emp = cb.thumbprint(bac["VIBE"])
    r = cb.verifier(bac["VIBE"], _token("VIBE", empreinte=emp), SECRET,
                    audience=AUDIENCE, agent_declare="CLAUDE")
    assert r["decision"] == "REFUSE"
    assert r["agent"] == "VIBE", "l'identite retenue doit venir du certificat"
    assert r["controles"]["entete_coherente"] == "KO"


def test_aucun_certificat_est_refuse(bac):
    r = cb.verifier(None, _token("VIBE"), SECRET, audience=AUDIENCE)
    assert r["decision"] == "REFUSE"
    assert r["controles"]["cert_present"] == "KO"


def test_certificat_valide_mais_sans_token_est_refuse(bac):
    """Le transport est authentifie ; l'appelant ne l'est pas."""
    r = cb.verifier(bac["VIBE"], None, SECRET, audience=AUDIENCE)
    assert r["decision"] == "REFUSE"
    assert r["controles"]["token_present"] == "KO"


def test_certificat_expire_est_refuse(bac):
    ca_cle, ca_cert = bac["ca"]
    perime = _client(ca_cle, ca_cert, "VIBE", valide=False)
    r = cb.verifier(perime, _token("VIBE", empreinte=cb.thumbprint(perime)), SECRET,
                    audience=AUDIENCE)
    assert r["decision"] == "REFUSE"
    assert r["controles"]["cert_validite"] == "KO"


def test_certificat_sans_clientauth_est_refuse(bac):
    """Un certificat SERVEUR ne doit pas pouvoir servir d'identite cliente."""
    ca_cle, ca_cert = bac["ca"]
    serveur = _client(ca_cle, ca_cert, "VIBE", eku_client=False)
    r = cb.verifier(serveur, _token("VIBE", empreinte=cb.thumbprint(serveur)), SECRET,
                    audience=AUDIENCE)
    assert r["decision"] == "REFUSE"
    assert r["controles"]["cert_eku_clientauth"] == "KO"


def test_certificat_revoque_est_refuse(bac):
    emp = cb.thumbprint(bac["VIBE"])
    r = cb.verifier(bac["VIBE"], _token("VIBE", empreinte=emp), SECRET,
                    audience=AUDIENCE, revoques={emp})
    assert r["decision"] == "REFUSE"
    assert r["controles"]["cert_non_revoque"] == "KO"


# --------------------------------------------------------------------------- #
# Trois etats : ne pas savoir n'est pas autoriser
# --------------------------------------------------------------------------- #

def test_sans_liste_de_revocation_l_etat_est_inconnu_pas_ok(bac):
    """On ne transforme pas l'absence de liste en « certificat non revoque »."""
    emp = cb.thumbprint(bac["VIBE"])
    r = cb.verifier(bac["VIBE"], _token("VIBE", empreinte=emp), SECRET,
                    audience=AUDIENCE)
    assert r["controles"]["cert_non_revoque"] == "UNKNOWN"
    assert r["decision"] == "ALLOW", "un UNKNOWN tolere ne doit pas bloquer le nominal"


def test_un_certificat_illisible_ne_passe_pas(bac):
    r = cb.verifier(b"ceci n'est pas un certificat", _token("VIBE"), SECRET,
                    audience=AUDIENCE)
    assert r["decision"] == "REFUSE"


def test_le_module_ne_pretend_pas_valider_la_chaine(bac):
    """Garde-fou de LECTURE : la docstring doit dire que la CA est verifiee par le
    handshake, pas ici. Sans cette mention, un lecteur croirait `verifier()`
    suffisant sur un certificat quelconque."""
    assert "ne valide PAS la chaine" in cb.__doc__
