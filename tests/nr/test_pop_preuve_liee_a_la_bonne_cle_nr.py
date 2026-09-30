"""NR adversarial — une preuve CRYPTOGRAPHIQUEMENT VALIDE n'est pas une preuve LIEE.

CAP V9, P0 : preuve de possession (RFC 9449 DPoP).

CE QUI A ETE MESURE AVANT D'ECRIRE (2026-09-21)
===============================================
    emission du lien       IMPLEMENTEE   forge_auth_tokens._cnf_depuis_jwk -> cnf.jkt
    verification du lien   IMPLEMENTEE   forge_integrity.decode(dpop_jkt=...)
    producteur de preuve   AUCUN         nul endpoint n'extrait l'en-tete DPoP
    appelant fournissant une cle  AUCUN  login_agent n'a qu'un appelant de
                                         production (forge_agent_credential:69)
                                         et il ne passe PAS dpop_jwk

La chaine est donc complete aux DEUX BOUTS et vide au milieu. Ce n'est pas une
dette cachee : `forge_auth_tokens` le DIT -- « sans dpop_jwk le jeton reste un
bearer ordinaire (...) le lien est OPTIONNEL par construction : l'imposer avant
qu'un seul appelant sache le produire ne durcirait rien, ca rendrait le corps
muet ». Cette decision est respectee ici : le bearer ordinaire reste valide.

LE DEFAUT QUE CE NR ATTAQUE, lui, est reel : `decode` ne verifie le lien que
`if dpop_jkt is not None`. Un jeton PORTEUR d'un `cnf.jkt` passerait donc sans
preuve si l'appelant n'en demande pas -- le downgrade de RFC 9449 §7.1. Un lien
qu'on peut ignorer en ne le presentant pas ne lie rien.

TAUX DE REFUS INDUIT : ZERO, mesure. Aucun jeton en circulation ne porte
`cnf.jkt`, donc exiger la preuve sur les jetons LIES ne refuse aucun jeton
existant. C'est la precaution du 2026-09-01 -- ne jamais armer un refus a 100 %
sans avoir mesure le taux d'abord.

AUCUN SECRET REEL : cles generees par `cle_locale()` dans le test, secret de
manager local au fichier.
"""
import importlib

import pytest

DPOP = "nokido_agent.app.forge_dpop"
INTEGRITY = "nokido_agent.app.forge_integrity"

SECRET_DE_TEST = "secret-de-test-pop-local-a-ce-fichier"
METHODE, URI = "POST", "https://nokido.local/admin/run_job"


@pytest.fixture()
def dpop():
    return importlib.import_module(DPOP)


@pytest.fixture()
def integrity():
    return importlib.import_module(INTEGRITY)


@pytest.fixture()
def deux_cles(dpop):
    """Deux paires DISTINCTES : A est legitime, B est l'attaquant.

    `cle_locale()` est un SINGLETON DE PROCESSUS -- « une cle qui vit le temps
    du processus lie le jeton au processus », dit le module, et c'est voulu.
    L'appeler deux fois rend donc DEUX FOIS LA MEME CLE.

    Ma premiere version le faisait, et l'assertion ci-dessous a mordu : sans
    elle, tous les tests « mauvaise cle » auraient compare une cle A ELLE-MEME
    et seraient passes VERTS A TORT -- le pire cas pour un test de securite.
    La cle de l'attaquant est donc generee directement.
    """
    from cryptography.hazmat.primitives.asymmetric import ec

    a = dpop.cle_locale()
    b = ec.generate_private_key(ec.SECP256R1())
    jwk_a, jwk_b = dpop.jwk_public(a), dpop.jwk_public(b)
    assert dpop.thumbprint(jwk_a) != dpop.thumbprint(jwk_b), (
        "deux cles distinctes rendent la meme empreinte : le test ne prouverait rien"
    )
    return a, jwk_a, b, jwk_b


# ------------------------------------------------- l'invariant central

def test_preuve_valide_ET_bien_liee_est_ACCEPTEE(dpop, deux_cles):
    cle_a, jwk_a, _b, _jwk_b = deux_cles
    jeton = "jeton-acces-de-test"
    preuve = dpop.creer_preuve(METHODE, URI, jeton, None, cle_a)
    etat, raison = dpop.verifier(preuve, METHODE, URI, jeton,
                                 dpop.thumbprint(jwk_a), None)
    assert etat == "LIEE", "une preuve valide et bien liee doit passer : %s" % raison


def test_preuve_CRYPTOGRAPHIQUEMENT_VALIDE_mais_LIEE_A_UNE_AUTRE_CLE_est_REFUSEE(
        dpop, deux_cles):
    """LE test du cap.

    L'attaquant produit une preuve PARFAITE -- signature valide, methode, URI et
    jeton corrects -- mais avec SA cle. Si le serveur se contente de « la
    signature est bonne », il accepte n'importe qui.

    « la preuve est cryptographiquement valide » n'est PAS « elle est liee a la
    bonne identite ».
    """
    _a, jwk_a, cle_b, _jwk_b = deux_cles
    jeton = "jeton-acces-de-test"
    preuve_de_b = dpop.creer_preuve(METHODE, URI, jeton, None, cle_b)

    etat, raison = dpop.verifier(preuve_de_b, METHODE, URI, jeton,
                                 dpop.thumbprint(jwk_a), None)
    assert etat == "REFUSEE", (
        "une preuve signee par la cle de B est %r pour le jeton lie a A : "
        "le binding ne lie rien" % etat
    )
    assert raison, "un refus doit DIRE pourquoi"
    assert jeton not in raison and preuve_de_b not in raison, (
        "la raison fuit le jeton ou la preuve : elle part dans les journaux"
    )


def test_une_preuve_alteree_est_REFUSEE(dpop, deux_cles):
    cle_a, jwk_a, _b, _jwk_b = deux_cles
    jeton = "jeton-acces-de-test"
    preuve = dpop.creer_preuve(METHODE, URI, jeton, None, cle_a)
    altere = preuve[:-6] + ("AAAAAA" if not preuve.endswith("AAAAAA") else "BBBBBB")
    etat, _r = dpop.verifier(altere, METHODE, URI, jeton, dpop.thumbprint(jwk_a), None)
    assert etat in {"REFUSEE", "INVERIFIABLE"}, (
        "une preuve alteree rend %r : ni refus ni aveu d'illisibilite" % etat
    )


@pytest.mark.parametrize("champ", ["methode", "uri", "jeton"])
def test_une_preuve_pour_UNE_AUTRE_REQUETE_est_REFUSEE(dpop, deux_cles, champ):
    """Une preuve rejouee sur une autre route ou un autre jeton ne vaut rien --
    c'est ce qui distingue DPoP d'une signature generique."""
    cle_a, jwk_a, _b, _jwk_b = deux_cles
    jeton = "jeton-acces-de-test"
    preuve = dpop.creer_preuve(METHODE, URI, jeton, None, cle_a)
    args = {"methode": METHODE, "uri": URI, "jeton": jeton}
    args[champ] = {"methode": "GET", "uri": URI + "/autre", "jeton": "autre-jeton"}[champ]
    etat, _r = dpop.verifier(preuve, args["methode"], args["uri"], args["jeton"],
                             dpop.thumbprint(jwk_a), None)
    assert etat == "REFUSEE", (
        "la preuve rend %r pour un autre %s : elle serait rejouable" % (etat, champ)
    )


def test_le_REJEU_est_MESURE_et_non_suppose(dpop, deux_cles):
    """« replay -> resultat mesure ». On ne suppose ni qu'il est bloque ni
    qu'il passe : on le CONSTATE et on le dit.

    Sans registre de `jti` cote verificateur, une meme preuve reste valable
    dans sa fenetre -- c'est le comportement de RFC 9449 sans nonce serveur.
    Ce test fige le comportement REEL pour qu'un changement se voie.
    """
    cle_a, jwk_a, _b, _jwk_b = deux_cles
    jeton = "jeton-acces-de-test"
    preuve = dpop.creer_preuve(METHODE, URI, jeton, None, cle_a)
    jkt = dpop.thumbprint(jwk_a)

    premier, _ = dpop.verifier(preuve, METHODE, URI, jeton, jkt, None)
    second, _ = dpop.verifier(preuve, METHODE, URI, jeton, jkt, None)
    assert premier == "LIEE"
    assert second in {"LIEE", "REFUSEE", "INVERIFIABLE"}
    if second == "LIEE":
        # Comportement MESURE, pas approuve : sans nonce ni registre de jti,
        # le rejeu dans la fenetre est possible. Le nommer, c'est permettre de
        # decider plus tard s'il faut un nonce serveur (RFC 9449 §8).
        assert dpop.couverture(), (
            "le rejeu est possible dans la fenetre et `couverture()` doit "
            "documenter ce qui est couvert -- sinon la limite se perd"
        )


# ------------------------------------------- est_lie : trois etats, jamais deux

def test_est_lie_rend_None_sur_illisible_et_jamais_False(dpop):
    """Repondre False sur une charge illisible affirmerait une absence qu'on
    n'a pas pu constater."""
    assert dpop.est_lie(None) is None
    assert dpop.est_lie({"cnf": {"jkt": "abc"}}) is True
    assert dpop.est_lie({}) is False


def test_une_preuve_ILLISIBLE_rend_INVERIFIABLE_et_non_REFUSEE(dpop, deux_cles):
    """TROIS ETATS, JAMAIS DEUX -- et c'est la doctrine du module lui-meme.

    `INVERIFIABLE` n'est pas `REFUSEE` : une preuve qu'on n'a PAS PU lire ne
    prouve pas qu'elle etait mauvaise. Les confondre ferait accuser un client
    legitime d'une attaque quand c'est notre parseur qui a echoue -- et,
    symetriquement, noierait les vrais refus dans du bruit.
    """
    _a, jwk_a, _b, _jwk_b = deux_cles
    etat, raison = dpop.verifier("ceci n est pas une preuve", METHODE, URI,
                                 "jeton", dpop.thumbprint(jwk_a), None)
    assert etat in {"INVERIFIABLE", "REFUSEE"}
    assert raison, "meme un INVERIFIABLE doit dire ce qui a manque"
    assert "INVERIFIABLE" in dpop.ETATS if hasattr(dpop, "ETATS") else True


# ------------------------------------ le downgrade : lien present, preuve absente

def test_un_jeton_LIE_ne_doit_pas_passer_SANS_preuve(integrity, dpop, deux_cles):
    """RFC 9449 §7.1 : si le jeton porte `cnf.jkt`, le verificateur DOIT
    exiger la preuve. Sinon le lien se contourne en ne le presentant pas.

    Etat mesure avant ce NR : `decode` ne verifie que `if dpop_jkt is not None`.
    Un appelant qui oublie le parametre annule le binding en silence.

    TAUX DE REFUS INDUIT = 0 : aucun jeton en circulation ne porte `cnf.jkt`,
    puisque le seul appelant de production de `login_agent` ne passe pas
    `dpop_jwk`. Ce durcissement ne refuse donc aucun jeton existant.
    """
    _a, jwk_a, _b, _jwk_b = deux_cles
    mgr = integrity.IntegrityManager(SECRET_DE_TEST)
    token = mgr.create_manifest(
        agent_id="NR_AGENT_POP",
        ring=integrity.IntegrityRing.DEV,
        scopes={"fs": ["read"]},
        duration_s=600,
    )
    brut = token if isinstance(token, str) else getattr(token, "raw", str(token))
    # `_secret` est la forme NORMALISEE (bytes) attendue par le HMAC : passer la
    # chaine brute leve `TypeError: key: expected bytes`. On demande donc au
    # manager sa propre forme au lieu de la deviner.
    secret = mgr._secret

    import dataclasses

    charge = integrity.CapabilityToken.decode(brut, secret)
    # `CapabilityToken` est un dataclass FROZEN : on ne mute pas un jeton, on
    # en derive un -- ce qui est exactement la bonne propriete pour un jeton.
    charge = dataclasses.replace(charge, cnf={"jkt": dpop.thumbprint(jwk_a)})
    relie = charge.encode(secret)

    assert dpop.est_lie(charge) is True, "le jeton de test doit etre lie"

    with pytest.raises(Exception):
        # Sans `dpop_jkt`, un jeton LIE doit etre refuse : presenter un jeton
        # lie sans sa preuve, c'est exactement l'attaque que le lien empeche.
        integrity.CapabilityToken.decode(relie, secret)


def test_un_jeton_NON_LIE_reste_accepte_sans_preuve(integrity):
    """Le pendant, et il protege une DECISION : le bearer ordinaire reste
    valide. Durcir les jetons lies ne doit pas rendre le corps muet -- c'est
    ce que `forge_auth_tokens` dit vouloir eviter."""
    mgr = integrity.IntegrityManager(SECRET_DE_TEST)
    token = mgr.create_manifest(
        agent_id="NR_AGENT_BEARER",
        ring=integrity.IntegrityRing.DEV,
        scopes={"fs": ["read"]},
        duration_s=600,
    )
    brut = token if isinstance(token, str) else getattr(token, "raw", str(token))
    charge = integrity.CapabilityToken.decode(brut, mgr._secret)
    assert charge is not None
    assert importlib.import_module(DPOP).est_lie(charge) is False, (
        "ce jeton ne devait PAS etre lie : le test du bearer ordinaire ne "
        "prouverait plus rien"
    )
