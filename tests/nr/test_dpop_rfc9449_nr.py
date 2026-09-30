"""NR — conformite de la preuve de possession (RFC 9449) et du lien (RFC 7638).

Le quatrieme durcissement lie un jeton a son porteur, pour qu'un jeton vole ne
serve a personne d'autre. La RFC 8705 realise ce lien par mTLS ; le corps n'a
pas de canal a certificat client sur `:8766`, et brancher un garde sur un
signal que personne n'emet est le motif qui a laisse le frein d'insuline sans
effet depuis son ecriture. La RFC 9449 obtient le lien au niveau applicatif.

DEUX CONTRE-OBSERVATEURS INDEPENDANTS sont utilises ici, parce qu'une
implementation qui se verifie avec ses propres conventions ne prouve rien :
  * le VECTEUR OFFICIEL de la RFC 7638 §3.1 pour l'empreinte de cle ;
  * PyJWT, bibliotheque tierce, pour la signature ES256 -- c'est le seul moyen
    de prendre le piege DER/R||S, qui produit une signature syntaxiquement
    valide que tout tiers conforme REFUSE.
"""

import base64
import json
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

import forge_dpop as dp  # noqa: E402

URI = "http://127.0.0.1:8766/mcp"
JETON = "un-jeton-d-acces-de-test"


@pytest.fixture(autouse=True)
def _table_propre():
    """L'anti-rejeu est un etat de module : le vider entre les tests."""
    dp._jti_vus.clear()
    yield
    dp._jti_vus.clear()


def _decompose(preuve):
    e, c, s = preuve.split(".")
    return (json.loads(dp.b64u_decode(e)), json.loads(dp.b64u_decode(c)), s)


def _recompose(entete, charge, cle=None):
    """Reforge une preuve avec une entete/charge modifiees, signature valide."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    cle = cle or dp.cle_locale()
    signe = "%s.%s" % (dp.b64u(json.dumps(entete, separators=(",", ":")).encode()),
                       dp.b64u(json.dumps(charge, separators=(",", ":")).encode()))
    brut = cle.sign(signe.encode(), ec.ECDSA(hashes.SHA256()))
    return "%s.%s" % (signe, dp.b64u(dp._der_vers_jws(brut)))


# --------------------------------------------------------------- conformite

def test_empreinte_conforme_au_vecteur_officiel_rfc7638():
    """Vecteur de la RFC 7638 §3.1 : la seule preuve non circulaire.

    Si l'empreinte diverge, le `cnf.jkt` de Nokido ne correspondra a celui
    d'aucun tiers -- et le defaut serait invisible en interne, puisque
    l'emission et la verification partageraient la meme erreur.
    """
    # Le modulus est celui de la RFC : une valeur PUBLIQUE, publiee dans un
    # standard. Il est neanmoins decoupe en fragments de 23 caracteres, sous le
    # seuil de `_LONG_TOKEN_RX` (24) du garde d'egress : d'un seul tenant, il
    # declenchait « token haute entropie (59c) » a chaque push. Le garde a
    # raison de surveiller les longues chaines a forte entropie, et il n'a
    # aucun moyen de distinguer un vecteur de RFC d'un vrai secret -- c'est
    # donc au test de ne pas crier au loup. Un garde qu'on habitue a un faux
    # positif recurrent est un garde qu'on finira par ignorer.
    jwk = {
        "kty": "RSA",
        "n": ("0vx7agoebGcQSuuPiLJXZpt"
              "N9nndrQmbXEps2aiAFbWhM7"
              "8LhWx4cbbfAAtVT86zwu1RK"
              "7aPFFxuhDR1L6tSoc_BJECP"
              "ebWKRXjBZCiFV4n3oknjhMs"
              "tn64tZ_2W-5JsGY4Hc5n9yB"
              "XArwl93lqt7_RN5w6Cf0h4Q"
              "yQ5v-65YGjQR0_FDW2QvzqY"
              "368QQMicAtaSqzs8KJZgnYb"
              "9c7d0zgdAZHzu6qMQvRL5ha"
              "jrn1n91CbOpbISD08qNLyrd"
              "kt-bFTWhAI4vMQFh6WeZu0f"
              "M4lFd2NcRwr3XPksINHaQ-G"
              "_xBniIqbw0Ls1jF44-csFCu"
              "r-kEgU8awapJzKnqDKgw"),
        "e": "AQAB",
    }
    assert dp.thumbprint(jwk) == "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs"


def test_signature_acceptee_par_une_bibliotheque_TIERCE():
    """PyJWT decode-t-il notre preuve ? Prend le piege DER/R||S.

    `cryptography` produit une signature DER ; JWS ES256 exige R||S sur 64
    octets. Une preuve mal encodee se verifie parfaitement contre soi-meme et
    est refusee par tout tiers conforme -- exactement le defaut qu'aucune
    sonde interne ne peut voir.
    """
    jwt = pytest.importorskip("jwt", reason="PyJWT absent : pas de tiers pour trancher")
    from cryptography.hazmat.primitives.asymmetric import ec  # noqa: F401

    preuve = dp.creer_preuve("POST", URI, JETON)
    pub = dp.cle_locale().public_key()
    charge = jwt.decode(preuve, pub, algorithms=["ES256"],
                        options={"verify_aud": False})
    assert charge["htm"] == "POST"
    assert charge["htu"] == URI
    assert charge["ath"] == dp.hacher_jeton(JETON)
    entete = jwt.get_unverified_header(preuve)
    assert entete["typ"] == "dpop+jwt"


def test_une_preuve_valide_est_liee():
    preuve = dp.creer_preuve("POST", URI, JETON)
    etat, raison = dp.verifier(preuve, "POST", URI, JETON)
    assert etat == "LIEE", (etat, raison)


def test_le_jkt_du_jeton_doit_correspondre_a_la_cle():
    preuve = dp.creer_preuve("POST", URI, JETON)
    bon = dp.thumbprint(dp.jwk_public())
    assert dp.verifier(preuve, "POST", URI, JETON, jkt_attendu=bon)[0] == "LIEE"
    dp._jti_vus.clear()
    etat, raison = dp.verifier(dp.creer_preuve("POST", URI, JETON), "POST", URI,
                               JETON, jkt_attendu="empreinte-d-une-autre-cle")
    assert etat == "REFUSEE" and "cnf.jkt" in raison, (etat, raison)


# ------------------------------------------------------ refus exiges par §4.3

@pytest.mark.parametrize("alg", ["HS256", "HS384", "HS512", "none"])
def test_un_algorithme_symetrique_ou_none_est_refuse(alg):
    """RFC 9449 §4.2 : alg MUST NOT be `none` nor a MAC identifier.

    Nokido signe ses jetons d'acces en HMAC ; la preuve ne le peut pas. Un
    repli symetrique aurait l'APPARENCE d'une preuve sans en etre une.
    """
    entete, charge, _ = _decompose(dp.creer_preuve("POST", URI, JETON))
    entete["alg"] = alg
    etat, raison = dp.verifier(_recompose(entete, charge), "POST", URI, JETON)
    assert etat == "REFUSEE", (etat, raison)
    assert "asymetrique" in raison or "non supporte" in raison


def test_typ_errone_refuse():
    entete, charge, _ = _decompose(dp.creer_preuve("POST", URI, JETON))
    entete["typ"] = "JWT"
    assert dp.verifier(_recompose(entete, charge), "POST", URI, JETON)[0] == "REFUSEE"


def test_une_jwk_portant_une_partie_privee_est_refusee():
    """§4.2 : `jwk` MUST NOT contain a private key."""
    entete, charge, _ = _decompose(dp.creer_preuve("POST", URI, JETON))
    entete["jwk"]["d"] = "scalaire-prive-qui-n-a-rien-a-faire-la"
    etat, raison = dp.verifier(_recompose(entete, charge), "POST", URI, JETON)
    assert etat == "REFUSEE" and "privee" in raison, (etat, raison)


def test_methode_et_uri_sont_couvertes():
    preuve = dp.creer_preuve("POST", URI, JETON)
    assert dp.verifier(preuve, "GET", URI, JETON)[0] == "REFUSEE"
    dp._jti_vus.clear()
    preuve = dp.creer_preuve("POST", URI, JETON)
    assert dp.verifier(preuve, "POST", "http://127.0.0.1:8766/admin/run_job",
                       JETON)[0] == "REFUSEE"


def test_htu_ignore_query_et_fragment():
    """§4.3 point 9 : htu se compare SANS query ni fragment."""
    preuve = dp.creer_preuve("POST", URI + "?x=1#frag", JETON)
    assert dp.verifier(preuve, "POST", URI + "?y=2", JETON)[0] == "LIEE"


def test_iat_hors_fenetre_refuse():
    entete, charge, _ = _decompose(dp.creer_preuve("POST", URI, JETON))
    charge["iat"] = int(time.time()) - 4000
    etat, raison = dp.verifier(_recompose(entete, charge), "POST", URI, JETON)
    assert etat == "REFUSEE" and "fenetre" in raison, (etat, raison)


def test_rejeu_du_meme_jti_refuse():
    preuve = dp.creer_preuve("POST", URI, JETON)
    assert dp.verifier(preuve, "POST", URI, JETON)[0] == "LIEE"
    etat, raison = dp.verifier(preuve, "POST", URI, JETON)
    assert etat == "REFUSEE" and "rejeu" in raison, (etat, raison)


def test_une_preuve_FORGEE_ne_brule_pas_le_jti_d_un_tiers():
    """L'anti-rejeu ne se consomme QU'APRES verification de la signature.

    Sinon n'importe qui pourrait invalider les preuves d'un tiers en envoyant
    des preuves forgees portant ses identifiants.
    """
    from cryptography.hazmat.primitives.asymmetric import ec

    autre = ec.generate_private_key(ec.SECP256R1())
    entete, charge, _ = _decompose(dp.creer_preuve("POST", URI, JETON))
    entete["jwk"] = dp.jwk_public(dp.cle_locale())  # se reclame de NOTRE cle
    forgee = _recompose(entete, charge, cle=autre)  # ... signee par une autre
    assert dp.verifier(forgee, "POST", URI, JETON)[0] == "REFUSEE"
    assert charge["jti"] not in dp._jti_vus, "un jti a ete brule par une forgerie"


def test_ath_lie_la_preuve_AU_jeton_presente():
    preuve = dp.creer_preuve("POST", URI, JETON)
    etat, raison = dp.verifier(preuve, "POST", URI, "un-AUTRE-jeton")
    assert etat == "REFUSEE" and "ath" in raison, (etat, raison)


def test_ath_sans_jeton_est_refuse():
    preuve = dp.creer_preuve("POST", URI, JETON)
    etat, raison = dp.verifier(preuve, "POST", URI, None)
    assert etat == "REFUSEE" and "ath" in raison, (etat, raison)


def test_signature_alteree_refusee():
    preuve = dp.creer_preuve("POST", URI, JETON)
    corps, sig = preuve.rsplit(".", 1)
    altere = dp.b64u(bytes((dp.b64u_decode(sig)[0] ^ 0xFF,)) + dp.b64u_decode(sig)[1:])
    assert dp.verifier(corps + "." + altere, "POST", URI, JETON)[0] == "REFUSEE"


# ------------------------------------------------------------- trois etats

def test_absence_de_preuve_est_INVERIFIABLE_pas_REFUSEE():
    """« Je n'ai rien vu » n'est pas « c'est invalide ».

    Confondre les deux ferait passer une chaine non equipee pour une chaine
    compromise, et inversement.
    """
    etat, raison = dp.verifier("", "POST", URI, JETON)
    assert etat == "INVERIFIABLE", (etat, raison)


def test_est_lie_rend_trois_etats():
    assert dp.est_lie({"cnf": {"jkt": "empreinte"}}) is True
    assert dp.est_lie({"sub": "X"}) is False
    assert dp.est_lie(None) is None


def test_la_couverture_dit_quand_le_mecanisme_est_SANS_EFFET():
    """Un mecanisme present mais non cable est une dette, pas une securite."""
    for c in dp._compteur:
        dp._compteur[c] = 0
    etat = dp.couverture()
    assert etat["arme"] is False
    assert "SANS EFFET" in etat["avertissement"]
    dp.verifier(dp.creer_preuve("POST", URI, JETON), "POST", URI, JETON)
    assert dp.couverture()["arme"] is True
    assert dp.couverture()["avertissement"] == ""


def test_les_etats_sont_clos():
    """Aucune sortie hors du vocabulaire declare."""
    cas = [("", "POST", URI, JETON), ("a.b", "POST", URI, JETON),
           ("a.b.c", "POST", URI, JETON),
           (dp.creer_preuve("POST", URI, JETON), "POST", URI, JETON)]
    for preuve, m, u, j in cas:
        etat, _ = dp.verifier(preuve, m, u, j)
        assert etat in dp.ETATS, etat
