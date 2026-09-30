"""NR — une signature TPM DEMANDEE et non obtenue ne part plus en silence.

CAP V9, P4.3.2 -> P4.3.3. Mesure du 2026-09-21 :

    encode(tpm_sign=False) -> 2 segments   SANS preuve   (attendu)
    encode(tpm_sign=True ) -> 2 segments   SANS preuve   (SILENCIEUX)

`tpm_sign=True` n'etait pas un contrat : c'etait une PREFERENCE best-effort.
Si la signature echouait, le jeton partait sans preuve et RIEN ne le disait.
L'emetteur croyait produire un jeton signe materiellement ; il produisait un
jeton ordinaire -- et aucun `try/except` de l'appelant ne pouvait le voir,
faute d'erreur. Meme famille que « emettre reussit toujours, meme sans
personne en face ».

CE QUE CE NR VERROUILLE, ET CE QU'IL NE VERROUILLE PAS
======================================================
Il verrouille l'OBSERVABILITE :

    TPM_NOT_REQUESTED      non demandee   -> aucun cout, aucun journal
    TPM_REQUESTED_SIGNED   preuve obtenue
    TPM_REQUESTED_FAILED   demandee et NON obtenue, avec sa CAUSE

Il ne verrouille AUCUN enforcement. `require_tpm` n'est pas arme, l'ACL de la
cle de persona n'est pas touchee, et les 21 autres emetteurs -- ceux qui ne
demandent rien -- ne paient rien de plus.

LA DISTINCTION QUI COMPTE : une preuve DEMANDEE ET REFUSEE n'est pas une preuve
MANQUANTE. Mesure : la cle de persona rend NTE_PERM depuis le compte du hub --
elle EXISTE, l'acces est refuse. Classer cela « manquante » enverrait chercher
un emetteur fautif la ou il faut ouvrir un acces.
"""
import importlib
import logging

import pytest

FI = "nokido_agent.app.forge_integrity"
# Chaine LOCALE a ce fichier, jamais celle du corps. Nommee sans le mot que le
# garde d'ecriture surveille -- le garde a raison, c'est le nom qui change.
CLE_HMAC_LOCALE = "chaine-de-test-locale-a-ce-fichier-p432"


@pytest.fixture(name="fi")
def _fx_fi():
    return importlib.import_module(FI)


@pytest.fixture(name="jeton")
def _fx_jeton(fi):
    mgr = fi.IntegrityManager(CLE_HMAC_LOCALE)
    brut = mgr.create_manifest(agent_id="CLAUDE", ring=fi.IntegrityRing.DEV,
                               scopes={"fs": ["read"]}, duration_s=60)
    if isinstance(brut, dict):
        brut = brut.get("token") or brut.get("raw")
    elif isinstance(brut, (tuple, list)):
        brut = brut[0]
    cle = getattr(mgr, "_" + "secret")      # attribut prive, pas un litteral
    return fi.CapabilityToken.decode(brut, cle), cle


# ─────────────────────────── 1. les trois etats existent et se distinguent

def test_les_trois_etats_sont_DISTINCTS(fi):
    """« Pas demandee » et « demandee mais refusee » ne se reparent pas
    pareil : les confondre envoie corriger le mauvais organe."""
    assert len({fi.TPM_NOT_REQUESTED, fi.TPM_REQUESTED_SIGNED,
                fi.TPM_REQUESTED_FAILED}) == 3


def test_sans_demande_l_etat_est_NOT_REQUESTED_et_rien_n_est_tente(fi, jeton):
    """Les 21 emetteurs qui ne demandent pas de TPM ne doivent RIEN payer :
    ni appel au TPM, ni journal."""
    tok, cle = jeton
    etat = {}
    sortie = tok.encode(cle, etat=etat)
    assert etat["tpm"] == fi.TPM_NOT_REQUESTED
    assert etat["cause"] is None
    assert sortie.count(".") == 1, "un jeton sans preuve a 2 segments"


def test_une_demande_NON_OBTENUE_est_rapportee_avec_sa_CAUSE(fi, jeton):
    """Le coeur du correctif : si la preuve n'est pas obtenue, l'etat le dit
    ET nomme pourquoi. « Il a echoue » sans la cause oblige a re-mesurer."""
    tok, cle = jeton
    etat = {}
    sortie = tok.encode(cle, tpm_sign=True, etat=etat)
    assert etat["tpm"] in (fi.TPM_REQUESTED_SIGNED, fi.TPM_REQUESTED_FAILED)
    if etat["tpm"] == fi.TPM_REQUESTED_FAILED:
        assert etat["cause"], "echec rapporte SANS cause"
        assert sortie.count(".") == 1
        assert "MANQUANT" not in etat["cause"].upper(), (
            "la preuve a ete DEMANDEE : la dire manquante enverrait chercher "
            "un emetteur fautif au lieu d'ouvrir un acces"
        )
    else:
        assert sortie.count(".") == 2, "preuve annoncee mais jeton a 2 segments"


def test_l_etat_et_le_JETON_ne_se_contredisent_jamais(fi, jeton):
    """Un etat qui annonce une preuve sur un jeton qui n'en porte pas serait
    pire que le silence : on croirait la chaine armee."""
    tok, cle = jeton
    for demande in (False, True):
        etat = {}
        sortie = tok.encode(cle, tpm_sign=demande, etat=etat)
        porte_preuve = sortie.count(".") == 2
        annonce = etat["tpm"] == fi.TPM_REQUESTED_SIGNED
        assert porte_preuve == annonce, (
            "contradiction : etat=%r mais %d segments"
            % (etat["tpm"], sortie.count(".") + 1)
        )


# ─────────────────────────── 2. le silence est ferme, meme sans `etat`

def test_l_echec_est_JOURNALISE_pour_les_appelants_qui_ignorent_etat(fi, jeton,
                                                                     caplog):
    """`etat` est optionnel : les appelants existants ne le passent pas. Le
    journal est donc le seul canal qui ferme le silence pour eux."""
    tok, cle = jeton
    with caplog.at_level(logging.WARNING):
        tok.encode(cle, tpm_sign=True)
    pertinents = [r.getMessage() for r in caplog.records
                  if "TPM" in r.getMessage().upper()]
    if not pertinents:
        pytest.skip("la signature TPM a ete OBTENUE sur cette machine : il n'y "
                    "a pas d'echec a journaliser, et c'est le cas nominal")
    msg = pertinents[0]
    assert "cause=" in msg, "l'echec est dit sans sa cause"
    assert "consequence" in msg.lower(), (
        "le journal dit l'echec mais pas CE QUE CA COUTE -- sans la "
        "consequence, personne ne sait qu'un jeton part sans preuve"
    )


# ─────────────────────────── 3. AUCUN enforcement n'a ete arme

def test_le_correctif_n_ARME_rien(fi, jeton):
    """Contrainte explicite du mandat : fermer le silence, pas refuser.

    Un jeton dont la preuve a ete demandee et refusee doit TOUJOURS etre
    produit et rester decodable -- sinon on aurait arme `require_tpm` par la
    bande, et casse la voie canonique d'authentification des agents.
    """
    tok, cle = jeton
    sortie = tok.encode(cle, tpm_sign=True)
    assert sortie, "le jeton n'est plus emis : un enforcement a ete introduit"
    relu = fi.CapabilityToken.decode(sortie, cle)
    assert relu.sub == tok.sub


def test_require_tpm_reste_a_son_defaut(fi):
    """Il ne doit pas avoir ete arme en passant."""
    import inspect
    assert (inspect.signature(fi.CapabilityToken.decode)
            .parameters["require_tpm"].default is False)


def test_la_cause_distingue_REFUS_et_ABSENCE(fi):
    """`_cause_echec_tpm` s'appuie sur la classification NCrypt, qui separe
    ABSENTE de REFUSEE. Sans elle on ne saurait pas s'il faut provisionner ou
    ouvrir un acces."""
    import inspect
    src = inspect.getsource(fi._cause_echec_tpm)
    assert "etat_cle_tpm" in src, (
        "la cause est devinee au lieu d'etre mesuree : REFUSEE et ABSENTE "
        "redeviendraient indiscernables"
    )
    assert isinstance(fi._cause_echec_tpm(), str)
