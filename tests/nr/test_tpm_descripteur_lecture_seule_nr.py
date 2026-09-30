"""NR — lire une ACL de cle TPM ne doit ni la modifier, ni confondre REFUSE et ABSENTE.

CAP V9, P4.1.x. Mandat owner du 2026-09-21 : capturer l'etat INITIAL du
descripteur AVANT toute ecriture d'ACL -- modifier d'abord effacerait la preuve
qui explique le `NTE_PERM`.

L'ETAT MESURE QUI JUSTIFIE CETTE LECTURE
========================================
Meme cle, meme provider, meme magasin, seul le COMPTE change :

    admin   laforge-agent-CLAUDE-sign   UTILISABLE  signe et verifie (64 o)
    hub     laforge-agent-CLAUDE-sign   REFUSEE     rc=0x80090010 NTE_PERM

La chaine TPM fonctionne. Ce qui bloque est la frontiere d'acces au key
container, et c'est elle qu'on va lire.

CE QUE CE NR TESTE, ET CE QU'IL NE TESTE PAS
============================================
Il teste LA MESURE, pas un SDDL particulier. Une machine n'a pas la meme ACL
qu'une autre, et un NR qui figerait une chaine precise serait une sonde sur le
POSTE, pas sur le code. Ce qui est verrouille :

    LISIBLE != REFUSE != ABSENTE != INDETERMINE

et surtout : un refus d'acces ne doit JAMAIS ressortir en « clé absente ».
C'est la confusion que P4.1 vient de fermer sur `OpenKey` ; elle se rejouerait
ici si la lecture du descripteur ne la tenait pas.

AUCUNE ECRITURE. Les tests verifient aussi, dans la SOURCE, qu'aucun chemin
d'ecriture d'ACL ni d'export de cle n'existe -- une lecture qui pourrait
ecrire n'est pas une lecture.
"""
import importlib
import inspect

import pytest

TPM = "nokido_agent.app.forge_persona_tpm"
OUTIL = "nokido_agent.tools.forge_tpm_agent_keys"
ETATS = {"LISIBLE", "REFUSE", "ABSENTE", "INDETERMINE"}


@pytest.fixture(name="tpm")
def _fx_tpm():
    return importlib.import_module(TPM)


# ────────────────────────────────── 1. la lecture NE PEUT PAS ecrire

INTERDITS = ("NCryptSetProperty", "NCryptCreatePersistedKey",
             "NCryptFinalizeKey", "NCryptDeleteKey", "NCryptExportKey")


def _apis_appelees(source: str) -> set:
    """Noms d'API REELLEMENT appelees, par AST.

    SURTOUT PAS une recherche textuelle : le docstring de la fonction CITE
    `NCryptExportKey` pour dire qu'il n'est jamais appele, et un `in src` le
    detecte. C'est la quatrieme fois de la journee qu'un instrument a moi lit
    son propre vocabulaire (compteur `_API_KEYS`, garde d'egress, note de bas
    de page du rapport TPM). Un test textuel sur du code interdit d'expliquer
    ce qu'on ne fait pas.
    """
    import ast
    import textwrap
    arbre = ast.parse(textwrap.dedent(source))
    vus = set()
    for node in ast.walk(arbre):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                vus.add(f.attr)
            elif isinstance(f, ast.Name):
                vus.add(f.id)
    return vus


def test_la_lecture_ne_contient_aucun_chemin_d_ecriture(tpm):
    """Une lecture qui pourrait ecrire n'est pas une lecture. Verifie sur les
    APPELS, pas sur le texte."""
    appels = _apis_appelees(inspect.getsource(tpm.descripteur_cle_tpm))
    for interdit in INTERDITS:
        assert interdit not in appels, (
            "la lecture du descripteur APPELLE %r : ce n'est plus une mesure, "
            "c'est une modification" % interdit
        )


def test_aucune_partie_privee_ne_transite(tpm):
    """Le SDDL est une liste de controle d'acces, pas du materiel de cle.
    `NCryptExportKey` ne doit etre appele nulle part dans le module -- le citer
    dans un commentaire pour dire qu'on ne l'appelle pas reste permis."""
    # 2026-09-26 : la preuve DPoP (10611225c) a ajoute AU MODULE un export de la cle PUBLIQUE (JWK du jeton).
    # Le contrat vise la LECTURE DU DESCRIPTEUR -- c'est elle que son docstring engage, c'est elle qu'on juge.
    # Et sur tout le module, un export ne peut viser que le blob PUBLIC : la privee ne quitte jamais le TPM.
    assert "NCryptExportKey" not in _apis_appelees(inspect.getsource(tpm.descripteur_cle_tpm))
    import ast
    arbre = ast.parse(inspect.getsource(tpm))
    exports = [n for n in ast.walk(arbre) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", getattr(n.func, "id", None)) == "NCryptExportKey"]
    for n in exports:
        assert (len(n.args) >= 3 and isinstance(n.args[2], ast.Name)
                and n.args[2].id == "_ECCPUBLICBLOB"), ast.unparse(n)
    assert tpm._ECCPUBLICBLOB == "ECCPUBLICBLOB"


# ────────────────────────────────── 2. quatre etats, et REFUSE n'est pas ABSENTE

def test_la_lecture_rend_un_etat_de_l_ensemble_ferme(tpm):
    nom = tpm.nom_cle_agent("CLAUDE")
    d = tpm.descripteur_cle_tpm(nom)
    assert set(d) >= {"etat", "code", "sddl", "proprietaire"}
    assert d["etat"] in ETATS, "etat %r hors de %s" % (d["etat"], sorted(ETATS))


def test_une_cle_INEXISTANTE_rend_ABSENTE_et_pas_REFUSE(tpm):
    """Le pire melange possible : envoyer ouvrir un acces sur une cle qui
    n'existe pas, ou provisionner une cle qui existe deja."""
    d = tpm.descripteur_cle_tpm("laforge-cle-qui-n-existe-nulle-part-2026")
    assert d["etat"] in {"ABSENTE", "INDETERMINE"}, (
        "une cle inexistante rend %r : si c'est REFUSE, la confusion que P4.1 "
        "a fermee vient de se rouvrir ici" % d["etat"]
    )
    assert d["sddl"] is None


def test_un_etat_non_LISIBLE_ne_fabrique_pas_de_SDDL(tpm):
    """Pas de descripteur invente quand on n'a pas pu lire : un `sddl` non nul
    sur un etat REFUSE ferait croire a une mesure qui n'a pas eu lieu."""
    d = tpm.descripteur_cle_tpm("laforge-cle-qui-n-existe-nulle-part-2026")
    if d["etat"] != "LISIBLE":
        assert d["sddl"] is None and d["proprietaire"] is None


def test_le_verdict_porte_son_CODE(tpm):
    """Un etat sans le code qui le fonde ne se conteste pas et ne se rejoue
    pas -- meme exigence que pour `etat_cle_tpm`."""
    d = tpm.descripteur_cle_tpm(tpm.nom_cle_agent("CLAUDE"))
    assert isinstance(d["code"], int)


# ────────────────────────────────── 3. le mode CLI, et ce qu'il dit a l'operateur

def test_le_mode_acl_existe_et_est_annonce_en_lecture_seule():
    outil = importlib.import_module(OUTIL)
    src = inspect.getsource(outil.main)
    assert '"--acl"' in src or "'--acl'" in src, "le mode de lecture n'existe pas"
    assert "LECTURE SEULE" in src, (
        "le mode ne dit pas a l'operateur qu'il ne modifie rien : il le "
        "laissera croire qu'une ACL a ete posee"
    )


def test_un_refus_de_lecture_nomme_le_geste():
    """« Je n'ai pas pu lire » sans dire quoi faire oblige a re-chercher.

    Le refus doit porter TROIS informations : les deux causes distinctes, le
    magasin interroge, et le compte a utiliser. On teste ces PROPRIETES, pas
    une formulation -- la version precedente de ce test figeait la phrase
    « n'existe pas dans ce magasin » et a rougi des qu'on l'a AMELIOREE en
    « DANS LE MAGASIN INTERROGE ». Un test qui verrouille des mots interdit de
    les corriger, et c'est la cinquieme fois de la campagne.
    """
    outil = importlib.import_module(OUTIL)
    src = inspect.getsource(outil.main)
    assert "REFUSE" in src and "ABSENTE" in src, (
        "le refus ne distingue pas les deux causes"
    )
    assert "FORGE_TPM_MACHINE" in src and "MAGASIN" in src.upper(), (
        "le refus ne dit pas QUEL magasin a ete interroge : un ABSENTE qui "
        "tait le magasin ne dit rien sur l'existence reelle de la cle"
    )
    assert "compte" in src.lower(), "le refus ne nomme pas le compte a utiliser"


def test_les_SID_sont_RESOLUS_ou_l_echec_est_DIT():
    """Une ACL illisible par un humain n'informe personne. Mais un nom INVENTE
    serait pire : la resolution echoue en le disant, elle ne devine pas."""
    outil = importlib.import_module(OUTIL)
    src = inspect.getsource(outil._nom_du_sid)
    assert "LookupAccountSidW" in src
    for aveu in ("SID non convertible", "SID inconnu de cette machine",
                 "resolution impossible"):
        assert aveu in src, "l'echec de resolution %r n'est pas dit" % aveu
