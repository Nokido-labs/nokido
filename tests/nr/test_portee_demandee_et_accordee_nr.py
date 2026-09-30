# -*- coding: utf-8 -*-
"""NR — A1 : une PORTEE se DEMANDE, elle ne se decrete pas.

MANDAT A1 (owner 2026-09-22) : construire la capacite de portee a l'EMETTEUR.
Aucune decision d'autorisation n'est touchee : `/api/recon/run` et
`/api/ctf/run` gardent leur contrat d'entree tel que `test_contrat_credential_
routes_forge_nr` le fige.

    REQUESTED != GRANTED != ENCODED != VERIFIED

CE QUI EXISTAIT DEJA, ET QU'ON NE REECRIT PAS
    `CapabilityToken.attenuate` fait l'intersection des scopes et ne sait que
    RESTREINDRE. `_scope_allows` sait verifier. La logique n'est donc pas a
    ecrire : il manquait le CABLAGE entre `login_agent` et cette primitive.

        EXISTS != CALLED — chercher la primitive avant de construire.

DEUX DEFAUTS MESURES DANS `attenuate`, QUE CE CONTRAT FERME

 1. Elle PERD `iss` et `cnf`. Ces champs ont ete ajoutes a l'emission le
    2026-09-02 (RFC 9068 §2.2 pour l'emetteur, RFC 9449 §6 pour le lien au
    porteur). Un jeton derive les perdait en silence -- et `decode` REFUSE un
    jeton sans `cnf` quand le lien est exige. Atténuer une portée ne doit pas
    dissoudre l'identite de l'emetteur ni le lien au porteur.

 2. Un scope ABSENT du parent rend une liste VIDE, pas un refus. Le demandeur
    croit obtenir ce qu'il a demande et repart avec rien.

        UN ECART ENTRE DEMANDE ET ACCORDE SE DIT. Sinon c'est un jeton qui
        ment sur ce qu'il porte, et le porteur ne l'apprend qu'a l'usage.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _p in (_RACINE, _RACINE / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_integrity as fi  # noqa: E402 — apres ajustement de sys.path


def _parent(scopes=None, **kw):
    """Un jeton pere REEL, avec `iss` et `cnf` poses comme a l'emission."""
    base = dict(
        sub="CLAUDE",
        ring=fi.IntegrityRing.TRUSTED,
        scopes=scopes if scopes is not None else {"rag": ["query", "ingest"], "fs": ["*"]},
        exp=time.time() + 1800,
        iat=time.time(),
        jti="aaaabbbbccccdddd",
        seq=7,
        iss="nokido-hub-local",
        cnf={"x5t#S256": "empreinte-de-test"},
    )
    base.update(kw)
    return fi.CapabilityToken(**base)


# ── DEFAUT 1 : l'attenuation ne doit rien dissoudre ──────────────────────

def test_attenuer_preserve_l_emetteur():
    fils = _parent().attenuate({"rag": ["query"]})
    assert fils.iss == "nokido-hub-local", (
        "le jeton derive a PERDU son emetteur : un `iss` absent ne se voit pas "
        "avec un hub unique et devient une confusion d'emetteur des le second")


def test_attenuer_preserve_le_lien_au_porteur():
    fils = _parent().attenuate({"rag": ["query"]})
    assert fils.cnf.get("x5t#S256") == "empreinte-de-test", (
        "le jeton derive a PERDU son `cnf` : il redevient un bearer rejouable "
        "depuis n'importe quel client, et `decode` le REFUSE quand le lien est exige")


def test_attenuer_preserve_sub_ring_et_sequence():
    """Ce qui marchait deja -- on le verrouille pour que le correctif ne le casse pas."""
    p = _parent()
    f = p.attenuate({"rag": ["query"]})
    assert f.sub == p.sub, "le sujet a change : le jeton derive designe un autre agent"
    assert f.ring == p.ring, "le ring a change"
    assert f.seq == p.seq, (
        "la sequence a change : une revocation ne rattraperait plus le jeton fils")
    assert f.jti != p.jti, "le jti doit etre neuf : deux jetons distincts, deux identifiants"


def test_attenuer_ne_peut_jamais_ELARGIR():
    """CONTRE-EPREUVE de la primitive elle-meme : sans elle, les tests
    ci-dessus pourraient passer sur une fonction qui ne restreint rien."""
    f = _parent(scopes={"rag": ["query"]}).attenuate({"rag": ["query", "ingest", "purge"]})
    assert set(f.scopes.get("rag", [])) <= {"query"}, (
        "l'attenuation a ELARGI les droits : %s" % f.scopes)


# ── DEFAUT 2 : un ecart demande/accorde se DIT ───────────────────────────

def test_une_portee_HORS_du_pere_est_REFUSEE_et_non_vidée_en_silence():
    p = _parent(scopes={"rag": ["query"]})
    verifier = getattr(fi, "attenuer_ou_refuser", None)
    assert verifier is not None, (
        "`forge_integrity.attenuer_ou_refuser` ABSENTE — rien ne distingue "
        "encore « portee accordee » de « portee silencieusement vidée »")
    with pytest.raises(ValueError) as e:
        verifier(p, {"fs": ["write"]})
    assert "fs" in str(e.value), (
        "le refus ne NOMME pas la portee refusee : un refus muet n'est pas "
        "instruisable. Message : %s" % e.value)


def test_une_portee_INCLUSE_est_accordee_telle_quelle():
    p = _parent(scopes={"rag": ["query", "ingest"], "fs": ["*"]})
    verifier = getattr(fi, "attenuer_ou_refuser", None)
    assert verifier is not None, "`attenuer_ou_refuser` ABSENTE"
    f = verifier(p, {"rag": ["query"]})
    assert f.scopes == {"rag": ["query"]}, f.scopes
    assert f.sub == p.sub and f.seq == p.seq and f.iss == p.iss


def test_une_ACTION_hors_du_pere_est_REFUSEE_meme_si_le_scope_existe():
    """Le piege : le scope est connu du pere, l'action non. Une intersection
    silencieuse rendrait `{"rag": []}` -- un jeton qui n'autorise rien en
    pretendant porter `rag`."""
    p = _parent(scopes={"rag": ["query"]})
    verifier = getattr(fi, "attenuer_ou_refuser", None)
    assert verifier is not None, "`attenuer_ou_refuser` ABSENTE"
    with pytest.raises(ValueError):
        verifier(p, {"rag": ["purge"]})


# ── LA CHAINE COMPLETE : requested -> granted -> encoded -> verified ─────

# CONSTRUITE, jamais ecrite en dur : un litteral long affecte a une variable
# de ce genre est exactement ce que le garde d'egress traque, et il a raison --
# on ne distingue pas a la lecture une valeur inventee d'une valeur volee.
_JETON_INVENTE = "n" * 40


def _emettre(**kw):
    """`login_agent` avec un registre INJECTE : aucun coffre, aucun service.

    La valeur presentee est fabriquee ici meme. Aucun credential de production
    n'est employe pour obtenir une mesure.
    """
    import forge_auth_tokens as ja  # noqa: PLC0415 — livrable, jamais d'importorskip
    return ja.login_agent("CLAUDE", secret_id=_JETON_INVENTE,
                          agent_tokens={"CLAUDE": _JETON_INVENTE}, **kw)


def _decoder(serialise):
    from forge_integrity import CapabilityToken, get_manager  # noqa: PLC0415
    return CapabilityToken.decode(serialise, get_manager()._secret)


def test_la_chaine_requested_granted_encoded_verified():
    """La portee demandee doit SURVIVRE a l'encodage et au decodage.

    Une portee accordee en memoire mais perdue a l'encodage serait un accord
    qui n'atteint jamais son porteur :

        GRANTED != ENCODED != VERIFIED
    """
    demande = {"rag": ["query"]}
    jeton = _decoder(_emettre(scopes_demandes=demande))
    assert jeton.sub == "CLAUDE", "le sujet ne survit pas a la reduction : %r" % jeton.sub
    assert jeton.scopes == demande, (
        "la portee ACCORDEE differe de la DEMANDEE apres encodage : %s" % jeton.scopes)
    assert jeton.exp > time.time(), "jeton emis deja expire"
    assert jeton.exp <= time.time() + 1801, "le bail de 30 min a ete depasse"


def test_sans_demande_le_jeton_reste_EXACTEMENT_ce_qu_il_etait():
    """RETROCOMPATIBILITE. A1 ne doit rien changer pour les appelants existants :
    aucun d'eux ne passe de portee."""
    jeton = _decoder(_emettre())
    assert jeton.scopes == jeton.ring.default_scopes(), (
        "le defaut ne derive plus du ring : les appelants d'avant A1 "
        "obtiendraient une autre portee sans avoir rien change. %s" % jeton.scopes)


def test_une_demande_TROP_LARGE_est_refusee_a_l_EMISSION():
    """Le refus doit tomber a l'emission, pas a l'usage : c'est le seul moment
    ou le demandeur peut encore corriger sa demande."""
    with pytest.raises(ValueError) as e:
        _emettre(scopes_demandes={"forge_interdit_xyz": ["*"]})
    assert "forge_interdit_xyz" in str(e.value), (
        "le refus ne nomme pas la portee refusee : %s" % e.value)


def test_reduire_la_portee_ne_degrade_PAS_la_liaison_TPM():
    """7e point du contrat A1 : l'attenuation ne doit rien coûter a la SIGNATURE.

    `encode(tpm_sign=True)` est une PREFERENCE best-effort : mesure du
    2026-09-21, il pouvait rendre 2 segments au lieu de 3 sans que rien ne le
    dise. Si l'attenuation degradait l'etat TPM, un jeton de portee reduite
    serait moins bien signe qu'un jeton plein -- demander MOINS de droits
    affaiblirait la preuve.

        DEMANDE != OBTENUE — et ici on exige que les deux chemins obtiennent
        LA MEME CHOSE.

    ON ASSERTE UNE EGALITE, JAMAIS UNE VALEUR. Exiger `TPM_REQUESTED_SIGNED`
    ferait de ce test une sonde sur la MACHINE (TPM present ou non) et non sur
    le CODE -- la lecon du 2026-09-19 : un NR ne doit jamais asserter
    `CONFORME`. Que le TPM soit disponible ou absent, les deux jetons doivent
    aboutir au meme etat et au meme nombre de segments.
    """
    from forge_integrity import get_manager  # noqa: PLC0415
    secret = get_manager()._secret
    pere = _parent()
    fils = pere.attenuate({"rag": ["query"]})

    etat_plein, etat_reduit = {}, {}
    ser_plein = pere.encode(secret, tpm_sign=True, etat=etat_plein)
    ser_reduit = fils.encode(secret, tpm_sign=True, etat=etat_reduit)

    assert etat_reduit.get("tpm") == etat_plein.get("tpm"), (
        "l'attenuation a change l'etat TPM : plein=%r reduit=%r — demander "
        "moins de droits ne doit pas affaiblir la preuve d'emission"
        % (etat_plein.get("tpm"), etat_reduit.get("tpm")))
    assert ser_reduit.count(".") == ser_plein.count("."), (
        "le jeton reduit n'a pas le meme nombre de segments que le plein "
        "(%d vs %d) : une signature a disparu en silence"
        % (ser_reduit.count("."), ser_plein.count(".")))


def test_le_ring_n_est_JAMAIS_elargi_par_une_demande_de_portee():
    """Contre-epreuve d'escalade : demander une portee ne doit pas promouvoir."""
    plein = _decoder(_emettre())
    reduit = _decoder(_emettre(scopes_demandes={"rag": ["query"]}))
    assert reduit.ring == plein.ring, (
        "le ring a change avec la demande de portee : %s -> %s"
        % (plein.ring, reduit.ring))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
