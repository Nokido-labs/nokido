"""NR — l'axe TPM de l'observation, et surtout ce qu'il REFUSE de conclure.

CAP V9, P4.3.3. L'observateur `forge_authz_shadow` tournait deja -- 2501 traces
reelles, 0 illisible, 7 modes d'authentification distingues, 157 porteurs de
capability sur `/mcp`. Il ne portait AUCUN axe TPM : la dimension n'etait pas
mesurable, ce qui n'est pas la meme chose qu'un taux de zero.

L'INVARIANT CENTRAL, ET C'EST UN REFUS
======================================
    UN TROISIEME SEGMENT N'EST PAS UNE PREUVE.

C'est un INDICE STRUCTUREL. `encode(tpm_sign=True)` en ajoute un quand la
signature a ete obtenue -- mais l'observateur ne possede pas la cle publique,
ne verifie rien, et un jeton forge en porte un aussi. Conclure `EMIS_AVEC_TPM`
d'une FORME fabriquerait un taux de couverture a partir de rien : exactement
le faux calme que la campagne traque.

`EMIS_AVEC_TPM` n'est donc JAMAIS rendu par l'observation seule. Il le sera par
la verification a la cle publique (P4.3.4), pas avant.

L'ASYMETRIE EST VOULUE : l'ABSENCE de troisieme segment, elle, est
STRUCTURELLEMENT certaine -- il n'existe aucun emplacement ou une preuve
pourrait se trouver. Deux segments donnent donc `EMIS_SANS_TPM`, et c'est une
mesure, pas une deduction.

CE QUE CE NR NE TOUCHE PAS : `require_tpm`, le TPM, l'ACL de la cle de persona,
les emetteurs, et le comportement d'autorisation. Aucune decision ne change.
"""
import base64
import importlib
import json

import pytest

AS = "nokido_agent.app.forge_authz_shadow"


@pytest.fixture(name="shadow")
def _fx_shadow():
    return importlib.import_module(AS)


def _jeton(segments: int, sub: str = "CLAUDE", charge_utile=None) -> str:
    """Fabrique une FORME de capability. Rien de valide, rien de signe."""
    payload = charge_utile if charge_utile is not None else {"sub": sub, "ring": 1}
    brut = base64.urlsafe_b64encode(
        json.dumps(payload).encode("utf-8")).rstrip(b"=").decode("ascii")
    morceaux = [brut, "hmac" + "0" * 20]
    if segments == 3:
        morceaux.append("c2lnbmF0dXJlLXRwbS1mYWJyaXF1ZWU")
    return ".".join(morceaux[:segments])


# ══════════════════════════ 1. LES DEUX ADVERSARIAUX DU MANDAT

def test_un_capability_a_DEUX_segments_n_est_PAS_classe_TPM(shadow):
    """Adversarial n.1 : l'absence de preuve ne doit pas devenir une preuve."""
    etat, raison = shadow.etat_tpm_observable(_jeton(2))
    assert etat == shadow.EMIS_SANS_TPM
    assert etat != shadow.EMIS_AVEC_TPM
    assert "aucun emplacement" in raison


@pytest.mark.parametrize("troisieme", [
    "c2lnbmF0dXJlLXRwbS1mYWJyaXF1ZWU",   # base64 plausible, signature inventee
    "!!!pas-du-base64!!!",               # malforme
    "",                                  # vide
    "A",                                 # tronque
])
def test_un_TROISIEME_segment_non_verifie_n_est_PAS_EMIS_AVEC_TPM(shadow,
                                                                  troisieme):
    """Adversarial n.2 : le coeur du mandat.

    Un troisieme segment, valide d'apparence ou malforme, ne doit JAMAIS etre
    compte comme une preuve emise. L'observateur n'a pas verifie -- il le dit.
    """
    jeton = _jeton(2) + "." + troisieme
    etat, raison = shadow.etat_tpm_observable(jeton)
    assert etat != shadow.EMIS_AVEC_TPM, (
        "un troisieme segment %r a ete compte comme une preuve : le taux de "
        "couverture serait fabrique a partir d'une FORME" % troisieme[:20]
    )
    assert etat == shadow.TPM_NON_MESURABLE
    assert "NON verifiee" in raison or "non verifiee" in raison.lower()


def test_EMIS_AVEC_TPM_n_est_JAMAIS_rendu_par_l_observation(shadow):
    """Verrou global : aucune entree, quelle qu'elle soit, ne doit produire
    cet etat tant que la verification par cle publique n'existe pas."""
    entrees = [_jeton(2), _jeton(3), "", "pas-un-jeton", "a.b", "a.b.c.d",
               _jeton(3, sub="AUTRE"), _jeton(2, charge_utile={"pas_sub": 1})]
    for e in entrees:
        etat, _ = shadow.etat_tpm_observable(e)
        assert etat != shadow.EMIS_AVEC_TPM, "entree %r a produit EMIS_AVEC_TPM" % e[:24]


# ══════════════════════════ 2. NON_MESURABLE n'est pas une absence

def test_ce_qui_n_est_PAS_un_capability_est_NON_MESURABLE(shadow):
    """Un porteur d'une autre nature n'est pas « sans TPM » : la question ne
    se pose pas pour lui. Le ranger en EMIS_SANS_TPM gonflerait le
    denominateur d'un taux qui ne le concerne pas."""
    for e in ("", "abc", "Bearer xyz", "a.b.c.d.e"):
        etat, raison = shadow.etat_tpm_observable(e)
        assert etat == shadow.TPM_NON_MESURABLE
        assert raison


def test_les_CINQ_etats_sont_distincts(shadow):
    assert len({shadow.EMIS_AVEC_TPM, shadow.EMIS_SANS_TPM,
                shadow.TPM_DEMANDE_REFUSEE, shadow.TPM_NON_DEMANDE,
                shadow.TPM_NON_MESURABLE}) == 5


# ══════════════════════════ 3. la trace porte l'etiquette, JAMAIS le jeton

def test_la_trace_ne_recoit_PAS_le_jeton(shadow):
    """Contrat du module, et il ne bouge pas : « un journal d'autorisation qui
    recopie les jetons transforme une trace en magasin de secrets ». L'axe TPM
    passe donc par une ETIQUETTE calculee en amont."""
    import inspect
    params = list(inspect.signature(shadow.trace_de).parameters)
    for interdit in ("jeton", "token", "bearer", "entete", "header"):
        assert interdit not in params, (
            "`trace_de` recoit %r : la trace redeviendrait un magasin de "
            "secrets" % interdit
        )
    assert "etat_tpm" in params


def test_le_defaut_est_NON_MESURABLE_pas_SANS_TPM(shadow):
    """Un appelant qui ne renseigne pas l'axe n'a pas mesure une absence : il
    n'a rien mesure. Le defaut doit le dire."""
    t = shadow.trace_de("/mcp", "POST", 1, "CLAUDE", "bearer_capability",
                        {"pid": None})
    assert t["etat_tpm"] == shadow.TPM_NON_MESURABLE
    assert t["raison_tpm"], "le defaut ne dit pas POURQUOI il ne sait pas"


def test_l_etiquette_fournie_est_CONSERVEE(shadow):
    t = shadow.trace_de("/mcp", "POST", 1, "CLAUDE", "bearer_capability",
                        {"pid": 42}, etat_tpm=shadow.EMIS_SANS_TPM,
                        raison_tpm="deux segments")
    assert t["etat_tpm"] == shadow.EMIS_SANS_TPM
    assert t["raison_tpm"] == "deux segments"


def test_aucun_champ_de_trace_ne_porte_un_materiau_d_authentification(shadow):
    """Le filtre `_INTERDITS` du module doit continuer de mordre, et l'ajout
    de l'axe TPM ne doit pas avoir introduit de champ suspect."""
    t = shadow.trace_de("/mcp", "POST", 1, "CLAUDE", "bearer_capability",
                        {"pid": 1}, etat_tpm=shadow.EMIS_SANS_TPM)
    for cle in t:
        assert not any(x in cle.lower()
                       for x in ("bearer", "jwt", "cookie", "authorization"))


# ══════════════════════════ 4. l'agregat distingue « pas mesure » de « mesure »

def test_la_matrice_separe_SANS_AXE_de_NON_MESURABLE(shadow):
    """Les 2501 traces anterieures a ce champ ne sont pas « non mesurables » :
    l'instrument ne regardait pas encore. Les fondre ensemble effacerait la
    date a laquelle la mesure a commence."""
    import inspect
    src = inspect.getsource(shadow.matrice)
    assert "sans_axe_tpm" in src
    m = shadow.matrice(limite=3000)
    assert "tpm" in m and "sans_axe_tpm" in m
    assert isinstance(m["tpm"], dict)
    # Le denominateur reste explicite, comme pour le reste de la matrice.
    assert m["lues"] >= m["sans_axe_tpm"]
