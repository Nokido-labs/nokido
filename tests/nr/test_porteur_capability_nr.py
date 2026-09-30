"""NR — le `via` distingue un jeton a bail d'un jeton inconnu.

Mesure fondatrice (2026-09-02, journal `sandbox/authz_shadow.jsonl`) : un
jeton a bail PARFAITEMENT VALIDE (HTTP 200, ring resolu identique a celui du
credential statique du meme organe) sortait `bearer_inconnu` -- le MEME mot
que le `bad_token` refuse 18 fois dans la meme fenetre. Cabler les organes
sur des jetons a bail aurait donc rendu leur trafic legitime indistinguable
d'un intrus : un durcissement qui DEGRADE la tracabilite qu'il sert.

Ce que ces tests ancrent, et qui ne doit pas se perdre :
  * la FORME seule ne vaut JAMAIS validation (un jeton forge est lisible) ;
  * l'ABSENCE de decodeur ne vaut JAMAIS refus (« je n'ai pas pu regarder »
    n'est pas « invalide ») ;
  * une comparaison qui casse n'ABSOUT pas le porteur.
"""

import base64
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

from forge_authz_shadow import (  # noqa: E402
    PORTEURS,
    classer_porteur,
    ressemble_a_capability,
)

MAITRE = "master-secret-de-test"
STATIQUE = "statique-organe-de-test"


def _forger(segments: int = 3, **champs) -> str:
    """Un jeton de la BONNE FORME dont la signature ne vaut rien.

    DEFAUT NAISSANT DE CE FICHIER, corrige le jour meme : la premiere version
    ne produisait que DEUX segments, et `ressemble_a_capability` n'acceptait
    donc qu'un point -- alors que les jetons REELS du corps en portent deux
    (`payload.hmac.signature_tpm`). Le classificateur rangeait un jeton a bail
    expire en `bearer_inconnu`, le mot meme du `bad_token` dont ce module
    existe pour le distinguer. Le test validait la convention de son auteur,
    pas la forme du corps. La forme reelle est donc le DEFAUT ici.
    """
    charge = {"sub": "STATE_ENCODER", "ring": 1, "exp": 9e9}
    charge.update(champs)
    tete = base64.urlsafe_b64encode(
        json.dumps(charge).encode()).decode().rstrip("=")
    jeton = tete + ".signature-qui-ne-prouve-rien"
    if segments == 3:
        jeton += ".signature-materielle"
    return jeton


def _entete(jeton: str) -> str:
    return "Bearer " + jeton


def _maitre(j):
    return j == MAITRE


def _statique(j):
    return j == STATIQUE


def test_jeton_a_bail_verifie_ne_se_lit_plus_inconnu():
    """Le defaut mesure : un jeton valide classe comme un bad_token."""
    via = classer_porteur(_entete(_forger()), est_maitre=_maitre,
                          est_statique=_statique, decoder=lambda j: object())
    assert via == "bearer_capability", via
    assert via != "bearer_inconnu"


def test_forme_seule_ne_vaut_pas_validation():
    """Un jeton FORGE est lisible : il ne doit jamais passer pour verifie."""
    forge = _forger(ring=0, sub="OWNER")
    assert ressemble_a_capability(forge) is True
    via = classer_porteur(_entete(forge), est_maitre=_maitre,
                          est_statique=_statique, decoder=lambda j: None)
    assert via == "bearer_capability_refuse", via


def test_sans_decodeur_un_jeton_de_bonne_forme_est_indecidable():
    """Absence d'instrument != verdict. Ni valide, ni refuse : illisible."""
    via = classer_porteur(_entete(_forger()), est_maitre=_maitre,
                          est_statique=_statique, decoder=None)
    assert via == "bearer_indecidable", via


def test_un_comparateur_qui_casse_n_absout_pas():
    def _explose(_j):
        raise RuntimeError("coffre injoignable")

    via = classer_porteur(_entete(_forger()), est_maitre=_explose,
                          est_statique=_statique, decoder=lambda j: object())
    assert via == "bearer_indecidable", via


def test_le_maitre_prime_et_reste_nomme():
    via = classer_porteur(_entete(MAITRE), est_maitre=_maitre,
                          est_statique=_statique, decoder=lambda j: object())
    assert via == "bearer_maitre", via


def test_statique_avant_toute_tentative_de_decodage():
    def _decodeur_interdit(_j):
        raise AssertionError("un statique n'a pas a etre decode")

    via = classer_porteur(_entete(STATIQUE), est_maitre=_maitre,
                          est_statique=_statique, decoder=_decodeur_interdit)
    assert via == "bearer_derive", via


def test_la_forme_REELLE_du_corps_est_reconnue():
    """Ancre la forme emise par `/api/login` : TROIS segments (signature TPM).

    Sans ce cas, un bail expire redevient indistinguable d'un `bad_token` --
    et le defaut serait invisible, puisque les autres tests fabriquent leur
    materiau.
    """
    reel = _forger(segments=3)
    assert reel.count(".") == 2, "la forme reelle porte deux points"
    assert ressemble_a_capability(reel) is True
    via = classer_porteur(_entete(reel), est_maitre=_maitre,
                          est_statique=_statique, decoder=lambda j: None)
    assert via == "bearer_capability_refuse", via
    assert via != "bearer_inconnu", "un bail expire se lit comme un bad_token"


def test_les_deux_formes_sont_acceptees():
    for n in (2, 3):
        assert ressemble_a_capability(_forger(segments=n)) is True, n


def test_chaine_quelconque_reste_inconnue():
    for mauvais in ("bad_token", "abc.def", "", "..", "a.b.c"):
        via = classer_porteur(_entete(mauvais), est_maitre=_maitre,
                              est_statique=_statique, decoder=lambda j: None)
        assert via in ("bearer_inconnu", "bearer_indecidable"), (mauvais, via)
        assert via != "bearer_capability", mauvais


def test_jamais_capability_sans_decodeur():
    """GARDE STRUCTUREL : aucune entree ne doit produire `bearer_capability`
    quand aucun decodeur n'est fourni -- sinon la forme suffirait a valider."""
    entrees = [_forger(), _forger(ring=0), "bad_token", "a.b", MAITRE + "x",
               base64.urlsafe_b64encode(b'{"sub":"X"}').decode() + ".z"]
    for e in entrees:
        via = classer_porteur(_entete(e), est_maitre=_maitre,
                              est_statique=_statique, decoder=None)
        assert via != "bearer_capability", (e, via)


def test_le_jeton_ne_ressort_jamais_dans_l_etiquette():
    """Regle owner : ne jamais journaliser un bearer. L'etiquette est close."""
    secret = _forger(sub="SECRET_A_NE_PAS_ECRIRE")
    for jeton in (secret, MAITRE, STATIQUE, "bad_token"):
        via = classer_porteur(_entete(jeton), est_maitre=_maitre,
                              est_statique=_statique, decoder=lambda j: None)
        assert via in PORTEURS or via == "", via
        assert jeton[:12] not in via


def test_entete_absent_ou_non_bearer_ne_produit_pas_d_etiquette():
    for e in ("", "Basic abc", "Token xyz", None):
        assert classer_porteur(e or "", decoder=lambda j: object()) == ""
