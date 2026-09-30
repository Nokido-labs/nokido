"""NR — poser une ACE sur une cle TPM est un geste GOUVERNE, pas une commodite.

CAP V9, P4.1.y. L'ACL a ete lue et elle explique entierement le `NTE_PERM` :

    O:BA G:...-513 D:P (A;;FA;;;CO)(A;;FA;;;SY)(A;;FA;;;BA)

Trois ACE, toutes Full Access, et `LaForgeSbxOffline` dans aucune. La DACL est
PROTEGEE (`D:P`), donc aucun groupe parent ne peut donner l'acces.

LES INVARIANTS, ET C'EST EUX QU'ON TESTE -- JAMAIS UN SDDL
==========================================================
Un SDDL varie d'une machine a l'autre ; le figer ferait de ce NR une sonde sur
le POSTE. Ce qui est verrouille :

    * le droit est EXPLICITE -- aucun defaut sur une ACL ;
    * FA / GA / KA / WD sont REFUSES : un compte de service utilise le key
      container, il ne l'administre pas ;
    * l'ecriture exige le SDDL CAPTURE, et refuse s'il a change depuis --
      l'arbre est partage, une modification concurrente serait ecrasee ;
    * le defaut est le DRY-RUN : `appliquer=False` ne touche a rien ;
    * on AJOUTE une ACE, on n'en retire ni n'en elargit aucune ;
    * une ACE deja presente est un refus, pas un doublon silencieux ;
    * le compte est resolu par le SYSTEME (`LookupAccountNameW`), jamais par
      une chaine construite a la main.

AUCUNE ECRITURE N'EST FAITE PAR CE NR. Tous les cas passent par le dry-run ou
par un refus. La cle `laforge-agent-CLAUDE-sign` n'est ni modifiee ni ouverte
en ecriture.
"""
import importlib
import inspect

import pytest

TPM = "nokido_agent.app.forge_persona_tpm"
CLE = "laforge-agent-CLAUDE-sign"
# Ceux de `poser_ace_cle_tpm` (PLAN, APPLIQUE, REFUS) plus ceux que `descripteur_cle_tpm`
# rend quand il ne lit pas (ABSENTE, REFUSE, INDETERMINE), remontes tels quels.
# REFUSEE est le vocabulaire d'`etat_cle_tpm`, que le descripteur traduit en REFUSE :
# l'accepter ici laissait passer un etat impossible et rater celui du runner CI.
ETATS = {"PLAN", "APPLIQUE", "REFUS", "ABSENTE", "REFUSE", "INDETERMINE"}


@pytest.fixture(name="tpm")
def _fx_tpm():
    return importlib.import_module(TPM)


# ────────────────────────────── 1. le droit est explicite et borne

@pytest.mark.parametrize("droit", ["FA", "GA", "KA", "WD", "fa", "ga"])
def test_les_droits_d_ADMINISTRATION_sont_refuses(tpm, droit):
    """Un hub compromis avec FA pourrait effacer la cle ou se reecrire sa
    propre ACL. Le refus ne depend pas de la casse."""
    r = tpm.poser_ace_cle_tpm(CLE, "quelconque", droit, "peu importe")
    assert r["etat"] == "REFUS"
    assert r["applique"] is False
    assert droit.upper() in r["refus"]


def test_un_droit_VIDE_est_refuse_il_n_y_a_pas_de_defaut(tpm):
    """Une ACL sans masque explicite serait un geste qu'on n'a pas choisi."""
    for vide in ("", None, "   "):
        r = tpm.poser_ace_cle_tpm(CLE, "quelconque", vide, "peu importe")
        assert r["etat"] == "REFUS" and r["applique"] is False


# ────────────────────────────── 2. l'etat capture conditionne l'ecriture

def test_sans_SDDL_capture_aucune_ecriture(tpm):
    """Sans l'etat d'avant, on ne peut pas garantir qu'on n'ecrase pas une
    modification concurrente -- l'arbre est partage par plusieurs surfaces."""
    r = tpm.poser_ace_cle_tpm(CLE, "quelconque", "GR", "")
    assert r["etat"] == "REFUS"
    assert "capture" in r["refus"] or "attendu" in r["refus"]


def test_un_SDDL_qui_ne_correspond_PLUS_bloque_l_ecriture(tpm):
    """Le garde anti-ecrasement. On presente un SDDL volontairement faux : le
    refus doit tomber AVANT toute tentative d'ecriture."""
    r = tpm.poser_ace_cle_tpm(CLE, "quelconque", "GR",
                              "O:BAD:P(A;;GR;;;S-1-0-0)", appliquer=True)
    assert r["applique"] is False
    assert r["etat"] in ETATS
    # Sur une machine sans la cle, le refus vient du descripteur illisible ;
    # avec la cle, il vient du SDDL divergent. Les deux sont des refus, et
    # aucun n'ecrit -- c'est la propriete, pas le motif, qui est verrouillee.


@pytest.mark.parametrize("etat_lu", ["REFUSE", "ABSENTE", "INDETERMINE"])
def test_un_descripteur_illisible_remonte_un_etat_du_vocabulaire(tpm, monkeypatch, etat_lu):
    """CI GitHub du 2026-09-26 (run 36215947412) : sur le runner, la cle EXISTE
    mais son compte ne peut pas l'ouvrir -> `descripteur_cle_tpm` rend REFUSE,
    que `poser_ace_cle_tpm` remonte tel quel -- et REFUSE manquait a ETATS. En
    local la cle etait ABSENTE et le test passait : son verdict dependait du
    POSTE. Ce test fixe l'etat lu, il juge le CODE partout pareil."""
    monkeypatch.setattr(tpm, "descripteur_cle_tpm", lambda *_a, **_k: {
        "etat": etat_lu, "code": 5, "sddl": None, "proprietaire": None})
    r = tpm.poser_ace_cle_tpm(CLE, "quelconque", "GR",
                              "O:BAD:P(A;;GR;;;S-1-0-0)", appliquer=True)
    assert r["applique"] is False
    assert r["etat"] == etat_lu
    assert r["etat"] in ETATS


# ────────────────────────────── 3. le defaut ne touche a rien

def test_le_defaut_est_le_DRY_RUN(tpm):
    """`appliquer` doit valoir False par defaut : un geste de securite ne
    s'execute pas parce qu'on a oublie un drapeau."""
    sig = inspect.signature(tpm.poser_ace_cle_tpm)
    assert sig.parameters["appliquer"].default is False


def test_l_ecriture_n_est_atteignable_que_sous_appliquer(tpm):
    """`NCryptSetProperty` ne doit pas pouvoir etre atteint sans passer par la
    garde. On verifie que l'appel est SOUS le `if not appliquer: return`."""
    src = inspect.getsource(tpm.poser_ace_cle_tpm)
    i_garde = src.find("if not appliquer")
    i_ecriture = src.find("NCryptSetProperty")
    assert i_garde != -1 and i_ecriture != -1
    assert i_garde < i_ecriture, (
        "l'ecriture precede la garde du dry-run : elle serait atteignable sans "
        "confirmation"
    )


# ────────────────────────────── 4. on ajoute, on ne retire jamais

def test_le_plan_CONSERVE_toutes_les_ACE_existantes(tpm):
    """Invariant central : le SDDL calcule doit CONTENIR l'ancien. Retirer ou
    elargir une ACE existante serait une modification qu'on n'a pas demandee.

    Le test s'adapte a la machine : si la cle n'est pas lisible ici, il exige
    un refus propre plutot que de juger le POSTE.
    """
    # Magasin MACHINE explicite : c'est la que vit la cle d'agent. Sans ce
    # parametre le test interrogeait le magasin UTILISATEUR et se declarait
    # skip en permanence -- une couverture qui n'existait que sur le papier.
    lu = tpm.descripteur_cle_tpm(CLE, machine=True)
    if lu["etat"] != "LISIBLE":
        r = tpm.poser_ace_cle_tpm(CLE, "quelconque", "GR", "x")
        assert r["applique"] is False and r["etat"] in ETATS
        pytest.skip("cle non lisible depuis ce compte (%s) : refus verifie, "
                    "l'invariant de conservation se teste la ou elle l'est"
                    % lu["etat"])
    r = tpm.poser_ace_cle_tpm(CLE, "SYSTEM", "GR", lu["sddl"], machine=True)
    if r["etat"] == "PLAN":
        for ace in ("(A;;FA;;;CO)", "(A;;FA;;;SY)", "(A;;FA;;;BA)"):
            if ace in r["avant"]:
                assert ace in r["apres"], "l'ACE %s a disparu du plan" % ace
        assert r["apres"].startswith(r["avant"][:10])


def test_une_ACE_DEJA_presente_est_un_refus_pas_un_doublon(tpm):
    """Empiler deux fois la meme ACE rendrait l'ACL illisible et masquerait
    une erreur d'operateur."""
    src = inspect.getsource(tpm.poser_ace_cle_tpm)
    assert "DEJA presente" in src or "deja presente" in src.lower()


# ────────────────────────────── 5. le compte vient du systeme

def test_le_compte_est_resolu_par_le_SYSTEME(tpm):
    """Un SID construit a la main pourrait viser un principal inexistant ou,
    pire, un autre. On demande a Windows."""
    src = inspect.getsource(tpm.poser_ace_cle_tpm)
    assert "LookupAccountNameW" in src
    r = tpm.poser_ace_cle_tpm(CLE, "COMPTE_QUI_N_EXISTE_PAS_2026", "GR", "x")
    assert r["applique"] is False


# ────────────────────────────── 6. REQUESTED != ACHIEVED

def test_le_resultat_est_RELU_et_compare_pas_seulement_planifie(tpm):
    """La faute mesuree le 2026-09-21, sur le chemin reel.

    Le PLAN conservait les trois ACE. Le RESULTAT non : Windows a normalise la
    DACL a l'application -- `(A;;FA;;;CO)` a disparu et `D:P` est devenu
    `D:PAI`, sans que rien ne le demande. Le NR d'alors verifiait le PLAN, donc
    il n'a rien vu.

    Comparer ce qu'on a demande ne dit RIEN de ce qui s'est produit. L'ecriture
    doit relire et DIRE ce qui a bouge.
    """
    src = inspect.getsource(tpm.poser_ace_cle_tpm)
    assert "aces_perdues" in src, (
        "l'ecriture ne compare pas l'ACL relue a celle d'avant : une ACE "
        "supprimee par la normalisation passerait inapercue"
    )
    i_ecriture = src.find("NCryptSetProperty")
    i_relecture = src.find("descripteur_cle_tpm(nom, machine=machine)",
                           i_ecriture)
    assert i_ecriture != -1 and i_relecture > i_ecriture, (
        "l'ACL n'est pas RELUE apres l'ecriture : le resultat rapporte serait "
        "le plan, pas l'etat reel"
    )


def test_le_plan_ne_pretend_PAS_savoir_ce_qu_il_n_a_pas_mesure(tpm):
    """En dry-run, `normalise` doit valoir None -- ni True ni False. Rien n'a
    ete ecrit, donc rien n'a pu etre observe : affirmer « pas de perte »
    serait une conclusion tiree d'une mesure qui n'a pas eu lieu."""
    r = tpm.poser_ace_cle_tpm(CLE, "quelconque", "GR", "x")
    if r["etat"] == "PLAN":
        assert r["normalise"] is None
        assert r["aces_perdues"] == []


def test_l_outil_AVERTIT_quand_la_DACL_a_ete_normalisee():
    """Un ecart silencieux entre demande et resultat laisserait croire que
    l'ACL est celle qu'on voulait."""
    outil = importlib.import_module("nokido_agent.tools.forge_tpm_agent_keys")
    src = inspect.getsource(outil.main)
    assert "aces_perdues" in src and "NORMALISE" in src.upper(), (
        "l'operateur n'est pas averti d'une DACL normalisee"
    )


def test_aucune_partie_privee_ne_transite(tpm):
    """Poser une ACL ne touche pas au materiel de cle."""
    import ast
    import textwrap
    arbre = ast.parse(textwrap.dedent(inspect.getsource(tpm.poser_ace_cle_tpm)))
    appels = {n.func.attr for n in ast.walk(arbre)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "NCryptExportKey" not in appels
    assert "NCryptDeleteKey" not in appels
