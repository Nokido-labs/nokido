"""NR -- jeton court injecte par le superviseur (decision owner 2026-09-28), etape A :
le RENOUVELLEMENT d'un jeton court.

Un service lance par le superviseur recevra un jeton COURT (30 min) au lieu d'heriter du
jeton maitre. Il doit pouvoir le prolonger sans jamais tenir de secret statique : il presente
son jeton courant, le hub en emet un neuf. Mesure du jour : aucun renouvellement n'existait
(`attenuate` ne prolonge jamais, et c'est voulu).

Contrats :
  1. un jeton valide se renouvelle : meme `sub`, ring, portee, `iss`, `aud`, `cnf` ; `jti`
     neuf ; `seq` avance ; bail neuf ;
  2. un jeton EXPIRE, REVOQUE ou forge ne se renouvelle pas ;
  3. aucun renouvellement pour un ring <= DEV (l'owner ne passe jamais par le lanceur) ;
  4. un renouvellement n'ELEVE jamais : si le registre a promu l'identite, le jeton garde son
     ring ; s'il l'a retrogradee, le jeton neuf suit la retrogradation et sa portee se reduit ;
  5. `verify` refuse toujours un jeton revoque (la revocation vit desormais en UN endroit) ;
  6. la route est un ECHANGE DE JETON RFC 8693 §2 : corps form-urlencoded, `grant_type`
     token-exchange, `subject_token` + `subject_token_type` access_token ; reponse RFC 8693
     §2.2.1 (`access_token`, `issued_token_type`, `token_type`, `expires_in`) avec
     `Cache-Control: no-store` (RFC 6749 §5.1) ; erreurs RFC 6749 §5.2 (400 `invalid_request`,
     `unsupported_grant_type`, `invalid_grant`, `invalid_scope`) et RFC 8693 §2.2.2
     (`invalid_target`) ; la boucle locale seule est une politique locale (403).
"""
from __future__ import annotations

import importlib
import time
from urllib.parse import urlencode

import pytest

AT = "nokido_agent.app.forge_auth_tokens"
FI = "nokido_agent.app.forge_integrity"
PHRASE_DE_TEST = "phrase-de-test-renouvellement-0123456789abcdef"
IDENT = "AGENT_NR_RENOUV"
IDENT_OUVERT = "id-ouvert-de-test"


@pytest.fixture
def banc(monkeypatch):
    at = importlib.import_module(AT)
    fi = importlib.import_module(FI)
    mgr = fi.IntegrityManager(PHRASE_DE_TEST)
    registre = {IDENT: fi.IntegrityRing.COLLAB}
    monkeypatch.setattr(at, "get_manager", lambda: mgr)
    monkeypatch.setattr(at, "_ring_de", lambda r: registre[r.upper()])

    def emettre():
        return at.login_agent(IDENT, secret_id=IDENT_OUVERT, agent_tokens={IDENT: IDENT_OUVERT})

    return at, fi, mgr, registre, emettre


def _lire(fi, mgr, jeton):
    return fi.CapabilityToken.decode(jeton, mgr._secret)


def test_un_jeton_valide_se_renouvele_a_l_identique_avec_un_bail_neuf(banc):
    at, fi, mgr, _registre, emettre = banc
    ancien = _lire(fi, mgr, emettre())
    neuf = _lire(fi, mgr, at.renouveler(ancien.encode(mgr._secret)))
    memes = (neuf.sub, neuf.ring, neuf.scopes, neuf.iss, neuf.aud, neuf.cnf) == (
        ancien.sub, ancien.ring, ancien.scopes, ancien.iss, ancien.aud, ancien.cnf)
    ok = (memes, neuf.jti != ancien.jti, neuf.seq > ancien.seq, neuf.exp >= ancien.exp,
          neuf.exp - time.time() > 1700)
    assert ok == (True, True, True, True, True)


def test_un_jeton_expire_ne_se_renouvelle_pas(banc, monkeypatch):
    at, fi, _mgr, _registre, emettre = banc
    jeton = emettre()
    plus_tard = time.time() + 3600
    monkeypatch.setattr(fi.time, "time", lambda: plus_tard)
    with pytest.raises(ValueError):
        at.renouveler(jeton)


def test_un_jeton_revoque_ne_se_renouvelle_pas_et_verify_le_refuse(banc):
    at, fi, mgr, _registre, emettre = banc
    jeton = emettre()
    mgr.revoke(IDENT)
    with pytest.raises(ValueError):
        at.renouveler(jeton)
    ok, _raison = mgr.verify("rag", "read", jeton)
    assert ok is False


def test_un_jeton_forge_ne_se_renouvelle_pas(banc):
    at, *_ = banc
    with pytest.raises(ValueError):
        at.renouveler("pas.un.jeton")
    autre = importlib.import_module(FI).IntegrityManager("une-autre-phrase-de-test-0123456789")
    faux = importlib.import_module(FI).CapabilityToken(
        sub=IDENT, ring=importlib.import_module(FI).IntegrityRing.COLLAB, scopes={},
        exp=time.time() + 600, iat=time.time(), jti="x", seq=1)
    with pytest.raises(ValueError):
        at.renouveler(faux.encode(autre._secret))


def test_aucun_renouvellement_pour_un_ring_owner(banc):
    at, fi, _mgr, registre, emettre = banc
    registre[IDENT] = fi.IntegrityRing.DEV
    jeton = emettre()
    with pytest.raises(ValueError):
        at.renouveler(jeton)


def test_un_renouvellement_n_eleve_jamais_et_suit_une_retrogradation(banc):
    at, fi, mgr, registre, emettre = banc
    registre[IDENT] = fi.IntegrityRing.TRUSTED
    jeton = emettre()
    registre[IDENT] = fi.IntegrityRing.SYSTEM                  # promu depuis
    garde = _lire(fi, mgr, at.renouveler(jeton))
    assert garde.ring == fi.IntegrityRing.TRUSTED
    registre[IDENT] = fi.IntegrityRing.UNTRUSTED               # retrograde depuis
    suit = _lire(fi, mgr, at.renouveler(jeton))
    assert suit.ring == fi.IntegrityRing.UNTRUSTED
    for portee, actions in suit.scopes.items():
        assert set(actions) <= set(garde.scopes.get(portee, []))


FORM = "application/x-www-form-urlencoded"
ECHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCES = "urn:ietf:params:oauth:token-type:access_token"


def _demande(jeton, **extra):
    champs = {"grant_type": ECHANGE, "subject_token": jeton, "subject_token_type": ACCES}
    champs.update(extra)
    return urlencode({k: v for k, v in champs.items() if v is not None}).encode()


def test_la_route_est_un_echange_de_jeton_rfc8693(banc):
    at, fi, mgr, _registre, emettre = banc
    statut, corps, entetes = at.traiter_renouvellement("127.0.0.1", FORM, _demande(emettre()))
    ok = (statut == 200, _lire(fi, mgr, corps["access_token"]).sub == IDENT,
          corps.get("issued_token_type") == ACCES, corps.get("token_type") == "Bearer",
          corps.get("expires_in") == 1800, entetes.get("Cache-Control") == "no-store")
    assert ok == (True, True, True, True, True, True)


def test_la_route_repond_les_erreurs_rfc6749_et_rfc8693(banc):
    at, _fi, mgr, _registre, emettre = banc
    jeton = emettre()
    cas = {
        "hors boucle locale": (("localhost", FORM, _demande(jeton)), 403, "access_denied"),
        "pas en formulaire": (("127.0.0.1", "application/json", b"{}"), 400, "invalid_request"),
        "grant_type absent": (("127.0.0.1", FORM, _demande(jeton, grant_type=None)), 400, "invalid_request"),
        "autre grant": (("127.0.0.1", FORM, _demande(jeton, grant_type="client_credentials")),
                        400, "unsupported_grant_type"),
        "autre type": (("127.0.0.1", FORM, _demande(jeton, subject_token_type="urn:x")), 400, "invalid_request"),
        "delegation": (("127.0.0.1", FORM, _demande(jeton, actor_token="x", actor_token_type=ACCES)),
                       400, "invalid_request"),
        "audience": (("127.0.0.1", FORM, _demande(jeton, audience="ailleurs")), 400, "invalid_target"),
        "portee": (("127.0.0.1", FORM, _demande(jeton, scope="rag:read")), 400, "invalid_scope"),
        "parametre repete": (("127.0.0.1", FORM, _demande(jeton) + b"&grant_type=" + ECHANGE.encode()),
                             400, "invalid_request"),
    }
    for nom, (args, statut_attendu, code) in cas.items():
        statut, corps, _e = at.traiter_renouvellement(*args)
        assert (nom, statut, corps.get("error")) == (nom, statut_attendu, code)
        assert jeton not in str(corps), nom
    mgr.revoke(IDENT)
    statut, corps, _e = at.traiter_renouvellement("127.0.0.1", FORM, _demande(jeton))
    assert (statut, corps.get("error")) == (400, "invalid_grant")


def test_un_jeton_lie_dpop_ne_se_renouvelle_pas_comme_un_porteur(banc):
    """RFC 9449 : un jeton lie (`cnf.jkt`) sans preuve de possession n'est ni renouvele ni
    reemis sous `token_type` Bearer -- ce point ne verifie pas encore de preuve DPoP."""
    from cryptography.hazmat.primitives.asymmetric import ec
    import base64

    at, _fi, _mgr, _registre, _emettre = banc
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()

    def b64u(n):
        return base64.urlsafe_b64encode(n.to_bytes(32, "big")).rstrip(b"=").decode()

    jwk = {"kty": "EC", "crv": "P-256", "x": b64u(pub.x), "y": b64u(pub.y)}
    lie = at.login_agent(IDENT, secret_id=IDENT_OUVERT, agent_tokens={IDENT: IDENT_OUVERT}, dpop_jwk=jwk)
    statut, corps, _e = at.traiter_renouvellement("127.0.0.1", FORM, _demande(lie))
    assert (statut, corps.get("error")) == (400, "invalid_grant")
