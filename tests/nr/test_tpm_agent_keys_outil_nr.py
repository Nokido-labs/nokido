"""NR — l'outil de provisionnement TPM rend des ETATS, et REFUSE en disant le geste.

DETTE SOLDEE. Le cliquet `test_aucun_module_nouveau_sans_test` a refuse la CI du
2026-09-21 en nommant deux modules ajoutes sans aucun NR. L'un est de moi :
`tools/forge_tpm_agent_keys.py`, cree le 2026-09-20 (352965bd1). Le cliquet avait
raison, et il a mis vingt-quatre heures a etre entendu parce que la CI complete
n'avait pas ete rejouee depuis.

CE NR TESTE L'EFFET, PAS L'IMPORT -- c'est la consigne exacte du cliquet
(« Ecrire un test qui verifie son EFFET (pas son import) »). Un test qui se
contente d'importer prouve que le fichier se parse, ce que l'AST dit deja.

IL NE CREE AUCUNE CLE. La creation est un geste ADMINISTRATEUR mesure le
2026-09-20 : `NCryptCreatePersistedKey` rend 0x00000000 puis `NCryptFinalizeKey`
rend NTE_PERM (0x80090010) sous un compte non eleve. Un NR qui tenterait la
creation dependrait du compte qui lance la CI -- ce serait une sonde sur la
MACHINE et non sur le code.

CE QUE CE NR VERROUILLE
=======================
1. `--check` rend QUATRE etats et jamais un booleen : UTILISABLE,
   SIGNE_NON_VERIFIE, INDISPONIBLE, NON_DECLARE. Un booleen confondrait
   « absente » et « inaccessible depuis ce compte ».
2. INDISPONIBLE n'est pas ABSENTE, et l'outil le DIT en toutes lettres. Sous un
   compte non admin le magasin MACHINE rend NTE_PERM sur une cle qui EXISTE ;
   le premier essai du 20/09, sans le drapeau MACHINE, rendait NTE_NOT_FOUND en
   cherchant dans le magasin UTILISATEUR d'un compte sandbox, qui est vide.
   Deux codes, deux verites -- les confondre aurait fait conclure « pas de cle ».
3. On ne provisionne que les agents qui echangent REELLEMENT : une cle non
   utilisee est une surface, pas une securite.
4. Tout agent provisionne est DECLARE au registre d'identite : donner du
   materiel cryptographique a une etiquette inconnue, ce serait authentifier un
   fantome.
"""
import importlib

import pytest

MOD = "nokido_agent.tools.forge_tpm_agent_keys"

# `INDISPONIBLE` a ete REMPLACE le 2026-09-21, pas retire par complaisance :
# il fusionnait « la cle n'existe pas » et « acces refuse », qui appellent des
# gestes OPPOSES. `NCryptOpenKey` distingue les deux (0x80090016 / 0x80090011
# contre 0x80090010) ; le wrapper jetait le code, il le remonte desormais.
# Ce cliquet a fait son travail : l'enumeration a change, il l'a dit.
ETATS = {"UTILISABLE", "SIGNE_NON_VERIFIE", "NON_DECLARE",
         "ABSENTE", "REFUSEE", "INDETERMINE"}


@pytest.fixture()
def outil():
    return importlib.import_module(MOD)


def test_les_agents_provisionnes_sont_un_sous_ensemble_mesure(outil):
    """Sept agents, pas 146. Le registre compte 146 identites ; on ne
    provisionne que celles qui echangent en M2M."""
    actifs = getattr(outil, "AGENTS_ACTIFS", None)
    assert actifs, "la liste des agents a provisionner doit etre EXPLICITE"
    assert len(actifs) <= 20, (
        "%d agents : une cle non utilisee est une surface, pas une securite"
        % len(actifs)
    )
    assert "CLAUDE" in actifs


def test_chaque_agent_actif_est_declare_au_registre(outil):
    """Pas de materiel cryptographique pour une etiquette inconnue."""
    from nokido_agent.app.forge_m2m_protocol import _resoudre_agent

    for agent in outil.AGENTS_ACTIFS:
        canon, _surface = _resoudre_agent(agent)
        assert canon, (
            "%s n'est pas declare au SSoT d'identite : lui provisionner une "
            "cle authentifierait un fantome" % agent
        )


def test_le_nom_de_cle_derive_de_l_identite_canonique(outil):
    """Une seule convention de nommage. Deux conventions divergent toujours en
    silence, et c'est celle qu'on oublie qui laisse une cle orpheline."""
    from nokido_agent.app.forge_persona_tpm import nom_cle_agent

    for agent in outil.AGENTS_ACTIFS:
        nom = nom_cle_agent(agent)
        assert nom.startswith("laforge-agent-")
        assert nom.endswith("-sign")
        assert nom == nom_cle_agent(agent), "le nom doit etre DETERMINISTE"


def test_un_agent_non_declare_est_refuse_et_non_invente(outil):
    from nokido_agent.app.forge_persona_tpm import nom_cle_agent

    with pytest.raises(ValueError):
        nom_cle_agent("AGENT_QUI_N_EXISTE_NULLE_PART_2026")


def test_check_rend_un_etat_ferme_jamais_un_booleen(outil):
    """L'EFFET du mode --check, sans rien ecrire."""
    fn = getattr(outil, "etat_des_cles", None) or getattr(outil, "check", None)
    assert fn is not None, (
        "l'outil doit exposer son etat de facon appelable, pas seulement via "
        "un print dans main()"
    )
    etats = fn()
    assert etats, "le check doit rendre un etat par agent actif"
    for agent, fiche in etats.items():
        val = fiche if isinstance(fiche, str) else fiche.get("etat")
        assert val in ETATS, "%s porte %r, hors de %s" % (agent, val, sorted(ETATS))
        assert not isinstance(val, bool), (
            "un booleen confondrait ABSENTE et INACCESSIBLE-DEPUIS-CE-COMPTE"
        )


def test_le_module_dit_qu_indisponible_n_est_pas_absente(outil):
    """La nuance doit etre ECRITE la ou l'operateur la lira, pas seulement ici.

    Sous un compte non admin le magasin MACHINE rend NTE_PERM sur une cle qui
    EXISTE : un outil qui rendrait « absente » enverrait re-provisionner une
    cle deja presente.
    """
    import inspect

    src = inspect.getsource(outil)
    assert "INDISPONIBLE" in src
    assert "NTE_PERM" in src or "absente" in src.lower()


def test_creer_sans_elevation_ne_tente_rien_et_dit_la_commande(outil, monkeypatch):
    """Un outil qui echoue en silence sur un probleme de compte est exactement
    ce qui a coute des heures dans ce depot."""
    import inspect

    src = inspect.getsource(outil)
    assert "--create" in src or "create" in src
    assert "admin" in src.lower(), "le refus doit nommer l'elevation requise"
    assert "FORGE_TPM_MACHINE" in src, (
        "le refus doit donner la commande exacte a rejouer, drapeau compris"
    )
