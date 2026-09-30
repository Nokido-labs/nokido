"""NR — un jeton peut etre LIE a la cle de son porteur (RFC 9449 §6).

Sans lien, un bearer vole est rejouable depuis n'importe quel client : il
prouve la connaissance d'un secret, jamais l'identite du porteur. Le champ
`cnf` existait deja pour la voie mTLS (`x5t#S256`, RFC 8705) mais cette voie
suppose un canal a certificat client, que le corps n'a pas sur le loopback --
un garde branche sur un signal que personne n'emet. La voie DPoP obtient le
meme lien au niveau applicatif.

HERMETIQUE PAR CONSTRUCTION : secret de test injecte, jamais le coffre ni
`get_manager()`. Une suite qui passe en local et tombe en CI parce qu'elle
lit l'environnement a deja ete payee (2026-08-26, 8 echecs).
"""

import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

import forge_auth_tokens as fat  # noqa: E402
import forge_dpop as dp  # noqa: E402
from forge_integrity import CapabilityToken, IntegrityRing  # noqa: E402

SECRET = b"secret-de-test-hermetique-pas-le-coffre"


@pytest.fixture
def jwk():
    return dp.jwk_public()


def _jeton(cnf=None) -> str:
    t = CapabilityToken(
        sub="ORGANE_TEST",
        ring=IntegrityRing(3),
        scopes={},
        exp=time.time() + 600,
        iat=time.time(),
        jti="jti-de-test",
        cnf=cnf or {},
    )
    return t.encode(SECRET)


def test_cnf_depuis_jwk_pose_l_empreinte_rfc7638(jwk):
    cnf = fat._cnf_depuis_jwk(jwk)
    assert cnf == {"jkt": dp.thumbprint(jwk)}


def test_sans_cle_presentee_aucun_lien_n_est_invente():
    assert fat._cnf_depuis_jwk(None) == {}
    assert fat._cnf_depuis_jwk({}) == {}


def test_une_empreinte_incalculable_remonte_au_lieu_de_valoir_zero_lien():
    """Un jeton qu'on CROIT lie et qui ne l'est pas est pire qu'un jeton
    ouvertement non lie : l'erreur doit remonter, pas produire un {} muet."""
    with pytest.raises(Exception):
        fat._cnf_depuis_jwk({"kty": "KTY-INCONNU", "x": "a"})


def test_le_bon_porteur_est_accepte(jwk):
    brut = _jeton({"jkt": dp.thumbprint(jwk)})
    t = CapabilityToken.decode(brut, SECRET, dpop_jkt=dp.thumbprint(jwk))
    assert t.sub == "ORGANE_TEST"


def test_un_autre_porteur_est_refuse(jwk):
    brut = _jeton({"jkt": dp.thumbprint(jwk)})
    with pytest.raises(ValueError, match="AUTRE cle"):
        CapabilityToken.decode(brut, SECRET, dpop_jkt="empreinte-d-une-autre-cle")


def test_un_jeton_NON_LIE_est_refuse_des_qu_un_lien_est_exige(jwk):
    """Une absence de lien ne vaut JAMAIS une correspondance."""
    with pytest.raises(ValueError, match="non lie"):
        CapabilityToken.decode(_jeton(), SECRET, dpop_jkt=dp.thumbprint(jwk))


def test_un_jeton_non_lie_reste_accepte_quand_aucun_lien_n_est_exige():
    """Retrocompatibilite VOULUE : imposer le lien avant qu'un appelant sache
    le produire rendrait le corps muet au lieu de le durcir."""
    assert CapabilityToken.decode(_jeton(), SECRET).sub == "ORGANE_TEST"


def test_les_deux_voies_de_lien_coexistent_sans_se_confondre(jwk):
    """`x5t#S256` (mTLS) et `jkt` (DPoP) sont deux canaux distincts.

    Un jeton lie a une CLE ne doit pas passer pour lie a un CERTIFICAT : les
    confondre ferait accepter une preuve d'un canal comme preuve de l'autre.
    """
    brut = _jeton({"jkt": dp.thumbprint(jwk)})
    with pytest.raises(ValueError, match="x5t#S256"):
        CapabilityToken.decode(brut, SECRET, cert_thumbprint="empreinte-cert")


def test_le_refus_dit_LAQUELLE_des_deux_formes_manquait(jwk):
    """« non lie » et « lie a autre chose » n'appellent pas le meme remede."""
    try:
        CapabilityToken.decode(_jeton(), SECRET, dpop_jkt=dp.thumbprint(jwk))
    except ValueError as e:
        assert "reemettre" in str(e)
    try:
        CapabilityToken.decode(_jeton({"jkt": "x"}), SECRET,
                               dpop_jkt=dp.thumbprint(jwk))
    except ValueError as e:
        assert "AUTRE cle" in str(e)


def test_bout_en_bout_preuve_et_jeton_se_repondent(jwk):
    """Le jeton porte l'empreinte, la preuve porte la cle : les deux se
    verifient l'un par l'autre, ce qui est tout l'objet du lien."""
    uri = "http://127.0.0.1:8766/mcp"
    brut = _jeton({"jkt": dp.thumbprint(jwk)})
    preuve = dp.creer_preuve("POST", uri, brut)
    etat, raison = dp.verifier(preuve, "POST", uri, brut,
                               jkt_attendu=dp.thumbprint(jwk))
    assert etat == "LIEE", (etat, raison)
    CapabilityToken.decode(brut, SECRET, dpop_jkt=dp.thumbprint(jwk))
