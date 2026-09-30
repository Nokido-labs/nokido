"""NR — ABSENTE, REFUSEE et UTILISABLE sont trois etats, pas deux.

CAP V9, P4.1. Mesure du 2026-09-21, faite en appelant `NCryptOpenKey` a la main
parce que le corps ne savait pas la rendre :

    provider TPM                                   rc=0x00000000  OK
    magasin MACHINE      laforge-agent-*-sign      rc=0x80090016  NTE_BAD_KEYSET
    magasin UTILISATEUR  laforge-agent-*-sign      rc=0x80090011  NTE_NOT_FOUND

Windows distingue donc « la cle n'existe pas » de « acces refuse ». Le wrapper,
lui, jetait l'information :

    if nc.NCryptOpenKey(...) == 0: return hkey
    if not create: return None          # <- le code d'erreur disparait ici

`_etat_cle` ne pouvait par consequent rendre qu'un `INDISPONIBLE` qui melange
les deux -- et l'outil le DISAIT (« INDISPONIBLE ne veut pas dire ABSENTE »),
faute de pouvoir faire mieux. C'est `UNKNOWN != NO` perdu a la frontiere de
l'API, et ca coute dans les deux sens : envoyer reparer des droits quand la
cle n'existe pas, ou envoyer provisionner une cle qui existe deja.

CE QUE CE NR VERROUILLE
=======================
    NTE_BAD_KEYSET != NTE_PERM
    NTE_NOT_FOUND  != NTE_PERM
    UTILISABLE != ABSENTE != REFUSEE != INDETERMINE

La classification est une fonction PURE : elle se teste sans TPM, sans droits,
sur une machine qui n'en a pas. Le test d'integration, lui, s'adapte a ce que
la machine porte reellement et ne juge jamais la MACHINE -- un NR qui exige un
TPM provisionne serait une sonde sur le poste, pas sur le code.
"""
import importlib

import pytest

TPM = "nokido_agent.app.forge_persona_tpm"


@pytest.fixture(name="tpm")
def _fx_tpm():
    return importlib.import_module(TPM)


# ─────────────────────────────────────────── 1. la classification est PURE

@pytest.mark.parametrize("code,attendu", [
    (0x00000000, "UTILISABLE"),
    (0x80090016, "ABSENTE"),      # NTE_BAD_KEYSET — mesure du magasin MACHINE
    (0x80090011, "ABSENTE"),      # NTE_NOT_FOUND  — mesure du magasin UTILISATEUR
    (0x80090010, "REFUSEE"),      # NTE_PERM
    (0x80090029, "INDETERMINE"),  # NTE_NOT_SUPPORTED : ni absence ni refus
    (0x80090008, "INDETERMINE"),  # NTE_BAD_ALGID
])
def test_chaque_code_a_son_etat(tpm, code, attendu):
    assert tpm.classer_code_ncrypt(code) == attendu


def test_ABSENTE_et_REFUSEE_ne_se_confondent_JAMAIS(tpm):
    """Le coeur de l'invariant, dit en une ligne exécutable.

    Les confondre envoie reparer des droits quand il faut provisionner, ou
    provisionner quand il faut ouvrir un acces.
    """
    assert tpm.classer_code_ncrypt(0x80090016) != tpm.classer_code_ncrypt(0x80090010)
    assert tpm.classer_code_ncrypt(0x80090011) != tpm.classer_code_ncrypt(0x80090010)


def test_un_code_INCONNU_ne_tombe_pas_du_cote_sain(tpm):
    """Liste BLANCHE : un code qu'on n'a pas prevu est INDETERMINE, jamais
    UTILISABLE ni ABSENTE. Une liste noire laisserait toute valeur inattendue
    tomber du cote rassurant."""
    for inconnu in (0xDEADBEEF, 0x00000001, 0x80090099):
        assert tpm.classer_code_ncrypt(inconnu) == "INDETERMINE"


# ─────────────────────────────────────────── 2. la sonde rend l'etat ET le code

def test_la_sonde_rend_un_ETAT_et_le_CODE_qui_le_fonde(tpm):
    """Un verdict sans son code n'est pas verifiable : on ne peut ni le
    contester, ni le rejouer. La sonde rend les deux."""
    etat, code = tpm.etat_cle_tpm("laforge-agent-CLAUDE-sign")
    assert etat in {"UTILISABLE", "ABSENTE", "REFUSEE", "INDETERMINE"}
    assert isinstance(code, int)
    assert tpm.classer_code_ncrypt(code) == etat, (
        "l'etat rendu ne decoule pas du code rendu : l'un des deux ment"
    )


def test_la_sonde_n_ouvre_PAS_le_magasin_par_defaut_sans_le_dire(tpm):
    """Le magasin depend de `FORGE_TPM_MACHINE`. Une sonde qui ne dit pas OU
    elle a cherche rend un « ABSENTE » qui ne veut rien dire : la cle peut
    exister dans l'autre magasin."""
    import inspect
    src = inspect.getsource(tpm.etat_cle_tpm)
    assert "machine" in src.lower(), (
        "la sonde ne distingue pas les deux magasins : son verdict est "
        "ambigu par construction"
    )


def test_la_sonde_ne_CREE_jamais_de_cle(tpm):
    """Sonder n'est pas provisionner. La creation exige l'elevation et reste
    un geste operateur -- une sonde qui creerait en passant transformerait une
    mesure en modification."""
    import inspect
    src = inspect.getsource(tpm.etat_cle_tpm)
    for interdit in ("NCryptCreatePersistedKey", "NCryptFinalizeKey", "create=True"):
        assert interdit not in src, (
            "la sonde touche a la creation (%r) : elle doit se borner a "
            "ouvrir et refermer" % interdit
        )


# ─────────────────────────────────────────── 3. le chemin reel de l'outil

def test_l_outil_d_etat_consomme_la_distinction(tpm):
    """`_etat_cle` doit cesser de rendre un `INDISPONIBLE` fourre-tout : la
    distinction existe desormais en amont, il faut qu'elle arrive jusqu'au
    rapport que lit l'operateur."""
    outil = importlib.import_module("nokido_agent.tools.forge_tpm_agent_keys")
    import inspect
    src = inspect.getsource(outil._etat_cle)
    assert "etat_cle_tpm" in src, (
        "l'outil n'utilise pas la sonde : il continue de fusionner ABSENTE et "
        "REFUSEE en INDISPONIBLE, et l'operateur ne peut pas savoir quoi faire"
    )
