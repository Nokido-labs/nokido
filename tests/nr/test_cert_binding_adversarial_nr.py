"""NR adversarial — le certificat presente doit etre CELUI auquel le jeton est lie.

CAP V9, P1 : cert-binding / mTLS (RFC 8705). Meme methode que P0 (DPoP) et
resultat orthogonal : P0 prouvait la possession d'une CLE applicative, P1
prouve la possession d'un CERTIFICAT de transport.

MESURE AVANT D'ECRIRE
=====================
    forge_cert_binding   thumbprint · inspecter · verifier   PRESENT (10 425 o)
    trois etats          OK · KO · UNKNOWN
    appelant production  AUCUN -- seul forge_integrity porte le parametre
    champ de liaison     cnf["x5t#S256"]
    identite             SAN URI `urn:nokido:agent:` -- PAS le CN (RFC 9525)
    empreinte            base64url(sha256(DER)), jamais le PEM

`verifier()` est deja severe et le dit : « un seul KO ou UNKNOWN donne REFUSE »,
et UNKNOWN n'est tolere QUE sur les controles qu'on n'a pas demandes (revocation
sans liste, audience non exigee, en-tete absente). Ce NR ne l'affaiblit nulle
part -- il l'EPROUVE.

CE QU'IL ATTAQUE
================
1. Le binding lui-meme : presenter le certificat de B pour un jeton lie a A.
2. Le VOLET SYMETRIQUE, celui qui a mordu sur DPoP le meme jour : un jeton
   PORTEUR d'un `cnf.x5t#S256` peut-il passer quand AUCUN certificat n'est
   presente ? Si oui, le lien se contourne en ne le presentant pas.
3. L'en-tete declarative, que le module dit ne pouvoir que CONTREDIRE : peut-on
   obtenir l'identite d'un autre en la declarant ?
4. L'absence de certificat, dont le resultat doit etre MESURE et non suppose
   selon `exiger_mtls`.

AUCUN SECRET NI CERTIFICAT REEL : tout est genere dans le test.
"""
import datetime as _dt
import importlib

import pytest

CERTB = "nokido_agent.app.forge_cert_binding"
INTEGRITY = "nokido_agent.app.forge_integrity"

SECRET_DE_TEST = "secret-de-test-certbind-local-a-ce-fichier"
AGENT_A, AGENT_B = "NR_AGENT_CERT_A", "NR_AGENT_CERT_B"


def _fabriquer_cert(agent: str, *, client_auth: bool = True,
                    jours_validite: int = 30, avec_san: bool = True) -> bytes:
    """Certificat DER auto-signe portant l'identite dans son SAN URI."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    cb = importlib.import_module(CERTB)
    cle = ec.generate_private_key(ec.SECP256R1())
    nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, agent)])
    maintenant = _dt.datetime.now(_dt.timezone.utc)
    b = (x509.CertificateBuilder()
         .subject_name(nom).issuer_name(nom)
         .public_key(cle.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(maintenant - _dt.timedelta(days=1))
         .not_valid_after(maintenant + _dt.timedelta(days=jours_validite)))
    if avec_san:
        b = b.add_extension(x509.SubjectAlternativeName(
            [x509.UniformResourceIdentifier(cb.PREFIXE_SAN + agent)]), critical=False)
    if client_auth:
        b = b.add_extension(x509.ExtendedKeyUsage(
            [ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
    cert = b.sign(cle, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.DER)


@pytest.fixture()
def cb():
    return importlib.import_module(CERTB)


@pytest.fixture()
def integrity():
    return importlib.import_module(INTEGRITY)


@pytest.fixture()
def deux_certs(cb):
    """Garde-fou d'abord : deux certificats DOIVENT avoir deux empreintes.

    La lecon du meme jour sur `cle_locale()` -- un singleton pris pour un
    generateur -- a failli rendre verts des tests qui comparaient une cle a
    elle-meme. On ne recommence pas.
    """
    a, b = _fabriquer_cert(AGENT_A), _fabriquer_cert(AGENT_B)
    assert cb.thumbprint(a) != cb.thumbprint(b), (
        "deux certificats rendent la meme empreinte : le test ne prouverait rien"
    )
    return a, b


def _jeton_lie(integrity, cb, cert_der: bytes, agent: str):
    """Un jeton pour `agent`, lie a `cert_der` par cnf.x5t#S256."""
    import dataclasses

    mgr = integrity.IntegrityManager(SECRET_DE_TEST)
    brut = mgr.create_manifest(agent_id=agent, ring=integrity.IntegrityRing.DEV,
                               scopes={"fs": ["read"]}, duration_s=600)
    brut = brut if isinstance(brut, str) else getattr(brut, "raw", str(brut))
    charge = integrity.CapabilityToken.decode(brut, mgr._secret)
    charge = dataclasses.replace(charge, cnf={"x5t#S256": cb.thumbprint(cert_der)})
    return charge.encode(mgr._secret), mgr._secret


# --------------------------------------------------- le chemin nominal

def test_le_bon_certificat_avec_son_jeton_est_ACCEPTE(cb, integrity, deux_certs):
    cert_a, _cert_b = deux_certs
    jeton, secret = _jeton_lie(integrity, cb, cert_a, AGENT_A)
    res = cb.verifier(cert_a, jeton, secret, revoques=set())
    assert res["decision"] == "ALLOW", res["raison"]
    assert res["agent"] == AGENT_A
    assert res["controles"]["token_lie_au_cert"] == "OK"
    assert res["controles"]["sub_egale_cert"] == "OK"


# --------------------------------------------------- l'attaque centrale

def test_le_certificat_de_B_pour_un_jeton_lie_a_A_est_REFUSE(cb, integrity, deux_certs):
    """LE test de P1. Le certificat de B est parfaitement VALIDE -- EKU client,
    dates bonnes, SAN present. Il n'est simplement pas CELUI du jeton.

    « un certificat valide » n'est pas « le certificat attendu ».
    """
    cert_a, cert_b = deux_certs
    jeton, secret = _jeton_lie(integrity, cb, cert_a, AGENT_A)
    res = cb.verifier(cert_b, jeton, secret, revoques=set())
    assert res["decision"] == "REFUSE"
    assert res["controles"].get("token_lie_au_cert") == "KO", res["controles"]
    assert res["raison"], "un refus doit nommer le maillon fautif"


def test_un_jeton_d_un_AUTRE_agent_que_le_certificat_est_REFUSE(cb, integrity, deux_certs):
    """Le certificat dit A, le jeton dit B, et le lien cryptographique est bon :
    seule la CONCORDANCE D'IDENTITE tranche."""
    cert_a, _b = deux_certs
    jeton, secret = _jeton_lie(integrity, cb, cert_a, AGENT_B)   # sub = B !
    res = cb.verifier(cert_a, jeton, secret, revoques=set())
    assert res["decision"] == "REFUSE"
    assert res["controles"]["sub_egale_cert"] == "KO"


# --------------------------------------------------- l'en-tete declarative

def test_l_entete_declarative_ne_peut_que_CONTREDIRE(cb, integrity, deux_certs):
    """Le module le dit dans son propre commentaire, ce NR le prouve : declarer
    une identite ne l'obtient pas. C'est l'invariant
    « en-tete != preuve d'identite != autorisation ».
    """
    cert_a, _b = deux_certs
    jeton, secret = _jeton_lie(integrity, cb, cert_a, AGENT_A)

    concordante = cb.verifier(cert_a, jeton, secret, agent_declare=AGENT_A,
                              revoques=set())
    assert concordante["decision"] == "ALLOW"

    menteuse = cb.verifier(cert_a, jeton, secret, agent_declare=AGENT_B,
                           revoques=set())
    assert menteuse["decision"] == "REFUSE", (
        "une en-tete qui CONTREDIT le certificat n'a pas fait echouer la "
        "verification : elle serait devenue une source d'autorite"
    )
    assert menteuse["controles"]["entete_coherente"] == "KO"


# --------------------------------------------------- l'absence, MESUREE

@pytest.mark.parametrize("exiger", [True, False])
def test_l_absence_de_certificat_a_un_resultat_MESURE(cb, integrity, deux_certs, exiger):
    """« Ne transforme surtout pas une absence en vulnerabilite par hypothese. »

    On MESURE les deux politiques au lieu d'en supposer une. Resultat constate :
    meme sans exigence de mTLS, l'absence de certificat REFUSE -- avec une raison
    differente, « identite NON ETABLIE » plutot que « aucun certificat presente ».
    Le refus est le meme, la CAUSE est distincte, et c'est ce qui compte pour
    savoir quoi reparer.
    """
    cert_a, _b = deux_certs
    jeton, secret = _jeton_lie(integrity, cb, cert_a, AGENT_A)
    res = cb.verifier(None, jeton, secret, exiger_mtls=exiger, revoques=set())
    assert res["decision"] == "REFUSE"
    assert res["controles"]["cert_present"] == ("KO" if exiger else "UNKNOWN")
    assert res["raison"]


# --------------------------------------------------- qualite du certificat

def test_un_certificat_SANS_EKU_client_est_REFUSE(cb, integrity):
    """« Absence d'EKU = usage non restreint. C'est permissif, donc on le REFUSE
    plutot que de l'accepter en silence » -- un certificat SERVEUR ne doit pas
    servir de certificat CLIENT."""
    cert = _fabriquer_cert(AGENT_A, client_auth=False)
    jeton, secret = _jeton_lie(integrity, cb, cert, AGENT_A)
    res = cb.verifier(cert, jeton, secret, revoques=set())
    assert res["decision"] == "REFUSE"
    assert res["controles"]["cert_eku_clientauth"] == "KO"


def test_un_certificat_SANS_SAN_ne_porte_aucune_identite(cb, integrity):
    """L'identite vit dans le SAN URI, pas dans le CN (RFC 9525)."""
    cert = _fabriquer_cert(AGENT_A, avec_san=False)
    jeton, secret = _jeton_lie(integrity, cb, cert, AGENT_A)
    res = cb.verifier(cert, jeton, secret, revoques=set())
    assert res["decision"] == "REFUSE"
    assert res["controles"]["cert_san_agent"] == "KO"
    assert res["agent"] == "", "un CN ne doit JAMAIS servir d'identite"


def test_un_certificat_revoque_est_REFUSE(cb, integrity, deux_certs):
    cert_a, _b = deux_certs
    jeton, secret = _jeton_lie(integrity, cb, cert_a, AGENT_A)
    res = cb.verifier(cert_a, jeton, secret, revoques={cb.thumbprint(cert_a)})
    assert res["decision"] == "REFUSE"
    assert res["controles"]["cert_non_revoque"] == "KO"


def test_sans_liste_de_revocation_on_DIT_qu_on_ne_sait_pas(cb, integrity, deux_certs):
    """« On ne transforme pas ce silence en non-revoque. » UNKNOWN est tolere
    ici PARCE QU'ON N'A PAS DEMANDE le controle -- et il reste VISIBLE."""
    cert_a, _b = deux_certs
    jeton, secret = _jeton_lie(integrity, cb, cert_a, AGENT_A)
    res = cb.verifier(cert_a, jeton, secret, revoques=None)
    assert res["controles"]["cert_non_revoque"] == "UNKNOWN"
    assert res["decision"] == "ALLOW", (
        "un controle NON DEMANDE ne doit pas bloquer, mais il doit se VOIR"
    )


# ------------------------------------- le volet symetrique (meme piege que DPoP)

def test_un_jeton_LIE_A_UN_CERT_ne_doit_pas_passer_SANS_certificat(
        cb, integrity, deux_certs):
    """Le piege qui a mordu sur DPoP le meme jour, verifie ici sur RFC 8705.

    `decode` ne compare le lien que `if cert_thumbprint is not None`. Un jeton
    PORTEUR d'un `cnf.x5t#S256` presente sur un canal SANS certificat serait
    donc accepte : le lien se contourne EN NE LE PRESENTANT PAS.

    TAUX DE REFUS INDUIT : ZERO -- aucun appelant de production n'emet de jeton
    portant `x5t#S256`, comme pour `jkt`.
    """
    cert_a, _b = deux_certs
    jeton, secret = _jeton_lie(integrity, cb, cert_a, AGENT_A)
    with pytest.raises(Exception):
        integrity.CapabilityToken.decode(jeton, secret)
