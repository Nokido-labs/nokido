"""La passerelle GitHub est read-only PAR CONSTRUCTION, pas par convention.

CE QUE CES TESTS PROTEGENT. Le hub complet expose `run`, `governed_edit`,
`oracle_python_repl`, `manage_forge_lifecycle` des le ring 3 (mesure du 2026-09-13 :
30 outils visibles a ce ring). Exposer le hub a Internet reviendrait donc a exposer
un shell. La passerelle existe pour offrir une surface GitHub EN LECTURE a un client
externe SANS que le hub devienne routable, et sans qu'aucun nom d'outil recu du
client ne soit jamais interprete.

L'INVARIANT CENTRAL, et la raison d'etre du fichier : l'API publique est une
ENUMERATION FERMEE d'operations. Jamais `tool + args`. Un client ne peut pas nommer
une capacite : il choisit parmi cinq verbes, et rien d'autre n'existe. Une denylist
laisserait passer tout verbe futur par defaut -- c'est la doctrine du corps : on
classe par liste BLANCHE, jamais par liste noire.

ECRITS AVANT LE MODULE (methode du corps : NR rouge d'abord). Au premier passage ils
echouent a l'import, et c'est le comportement attendu.

Hermetiques : aucun reseau. L'appel GitHub est remplace par une sonde qui enregistre
ce qui lui est demande -- on verifie donc aussi, et surtout, ce que la passerelle
N'APPELLE PAS quand elle refuse.
"""

from __future__ import annotations

import importlib.util
import itertools
import pathlib
import re
import time

import pytest

MODULE = "forge_github_bridge"
CHEMIN = pathlib.Path(__file__).resolve().parents[2] / "tools" / (MODULE + ".py")


@pytest.fixture()
def pont():
    """Le module reel, charge PAR SON CHEMIN.

    Pas `import_module` : `tools/` n'est pas dans le sys.path des tests, et un
    import par nom pourrait de toute facon resoudre un homonyme d'un autre dossier
    (piege paye le 2026-09-06 : `app/Nokido.py` lu a la place de `tools/nokido.py`).
    On charge le fichier que le depot porte, celui-la et aucun autre.

    Un chargement neuf a chaque test remet aussi a zero l'etat de session du pont
    (jetons deja vus, compteurs de debit) : sans cela, le test de rejeu dependrait
    de l'ordre d'execution.
    """
    if not CHEMIN.exists():
        pytest.fail("%s introuvable -- la passerelle doit exister" % CHEMIN)
    spec = importlib.util.spec_from_file_location(MODULE, CHEMIN)
    if spec is None or spec.loader is None:
        pytest.fail("%s illisible par l'importeur" % CHEMIN)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        pytest.fail("%s ne s'importe pas : %s: %s" % (MODULE, type(exc).__name__, exc))
    return module


@pytest.fixture()
def sonde(pont, monkeypatch):
    """Remplace l'appel GitHub. Enregistre chemin et methode ; ne sort jamais."""
    vues = []

    def _faux(chemin, methode="GET"):
        vues.append((methode, chemin))
        return 200, {"full_name": "Nokido-labs/nokido", "private": True,
                     "default_branch": "alpha", "permissions": {"pull": True},
                     "commit": {"sha": "b" * 40}, "name": "alpha", "sha": "b" * 40,
                     "content": "", "encoding": "base64", "size": 0}

    monkeypatch.setattr(pont, "_appel_github", _faux)
    return vues


_COMPTEUR = itertools.count()


def _capacite(pont, **remplace):
    """Une capacite valide, sauf ce que le test remplace explicitement.

    L'identifiant d'usage vient d'un COMPTEUR, pas de l'horloge : dans une boucle
    serree, deux appels tombent dans la meme microseconde et l'anti-rejeu du pont
    refuserait le second -- un echec du harnais qu'on lirait comme un defaut du
    module. Meme famille que les N ecrivains qui repartent a la meme milliseconde.
    """
    charge = {"sub": "client-openai", "aud": pont.AUDIENCE, "scope": pont.SCOPE,
              "resource": "Nokido-labs/nokido", "exp": int(time.time()) + 300,
              "jti": "jti-%d" % next(_COMPTEUR)}
    charge.update(remplace)
    return pont.forger_capacite(charge)


def _source(pont) -> str:
    return CHEMIN.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------- surface publique

def test_la_surface_publique_est_une_enumeration_fermee(pont):
    assert set(pont.OPERATIONS) == {"repo_info", "branch_head", "commit_info",
                                    "compare", "read_file"}, (
        "la surface publique a change : toute operation ajoutee doit etre un choix "
        "explicite, jamais un effet de bord")


def test_aucune_operation_n_est_mutante(pont):
    interdits = ("create", "update", "delete", "put", "post", "patch", "merge",
                 "dispatch", "write", "push")
    for nom in pont.OPERATIONS:
        assert not any(i in nom.lower() for i in interdits), \
            "%s ressemble a une mutation" % nom
    assert pont.METHODES_AUTORISEES == frozenset({"GET"}), (
        "la passerelle ne doit pouvoir emettre que des GET vers GitHub")


def test_un_nom_d_outil_recu_du_client_n_est_jamais_interprete(pont, sonde):
    for nom in ("run", "governed_edit", "oracle_python_repl", "ps_clm",
                "nokido_ensure_service", "update_file", "github", "__import__"):
        ok, _ = pont.traiter(nom, {"repo": "Nokido-labs/nokido"}, _capacite(pont))
        assert ok is False, "l'operation %r a ete acceptee" % nom
    assert sonde == [], "un refus a tout de meme appele GitHub : %r" % sonde


# ------------------------------------------------------------------ allowlist depot

def test_un_depot_hors_allowlist_est_refuse(pont, sonde):
    for depot in ("autre/projet", "Nokido-labs/autre", "nokido-labs/nokido-fork",
                  "../../etc", "Nokido-labs/nokido/../autre", "Nokido-labs/nokido "):
        ok, msg = pont.traiter("repo_info", {"repo": depot}, _capacite(pont))
        assert ok is False, "depot %r accepte" % depot
        assert "depot" in msg.lower() or "autoris" in msg.lower()
    assert sonde == [], "un depot refuse a tout de meme ete appele : %r" % sonde


def test_le_depot_autorise_passe(pont, sonde):
    ok, res = pont.traiter("branch_head",
                           {"repo": "Nokido-labs/nokido", "branch": "alpha"},
                           _capacite(pont))
    assert ok is True, "le depot autorise a ete refuse : %r" % (res,)
    assert res.get("sha") == "b" * 40
    assert len(sonde) == 1 and sonde[0][0] == "GET"


def test_une_branche_ou_un_chemin_ne_s_injectent_pas_dans_l_url(pont, sonde):
    """Un parametre du client ne doit pas pouvoir changer la RESSOURCE appelee."""
    for mauvais in ("../../../users/x", "alpha?a=b", "alpha#frag", "al pha",
                    "alpha/../../secrets"):
        ok, _ = pont.traiter("branch_head",
                             {"repo": "Nokido-labs/nokido", "branch": mauvais},
                             _capacite(pont))
        assert ok is False, "branche %r acceptee" % mauvais
    assert sonde == [], "un parametre refuse a tout de meme atteint GitHub : %r" % sonde


def test_read_file_refuse_un_chemin_qui_remonte(pont, sonde):
    for mauvais in ("../secrets.env", "/etc/passwd", "a/../../b", "..\\Nokido.env"):
        ok, _ = pont.traiter("read_file",
                             {"repo": "Nokido-labs/nokido", "path": mauvais,
                              "ref": "alpha"}, _capacite(pont))
        assert ok is False, "chemin %r accepte" % mauvais
    assert sonde == []


# ----------------------------------------------------------------------- capacite

def test_sans_capacite_rien_ne_passe(pont, sonde):
    for jeton in (None, "", "   ", "Bearer", "a.b", "a.b.c"):
        ok, _ = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)
        assert ok is False, "jeton %r accepte" % jeton
    assert sonde == []


@pytest.mark.parametrize("champ,valeur", [
    ("aud", "hub"),                       # audience d'un autre destinataire
    ("aud", ""),                          # audience vide : refus, jamais "tout"
    ("scope", "github:write"),            # portee plus large que la sienne
    ("scope", "*"),                       # joker : refuse, jamais interprete
    ("resource", "autre/projet"),         # ressource hors de la capacite
    ("resource", "*"),                    # joker de ressource : refuse
])
def test_une_capacite_mal_cadree_est_refusee(pont, sonde, champ, valeur):
    ok, _ = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"},
                         _capacite(pont, **{champ: valeur}))
    assert ok is False, "capacite acceptee avec %s=%r" % (champ, valeur)
    assert sonde == []


def test_une_capacite_expiree_est_refusee(pont, sonde):
    ok, _ = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"},
                         _capacite(pont, exp=int(time.time()) - 1))
    assert ok is False
    assert sonde == []


def test_une_capacite_sans_expiration_est_refusee(pont, sonde):
    """Une capacite eternelle n'est pas une capacite attenuee."""
    charge = {"sub": "x", "aud": pont.AUDIENCE, "scope": pont.SCOPE,
              "resource": "Nokido-labs/nokido", "jti": "sans-exp"}
    ok, _ = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"},
                         pont.forger_capacite(charge))
    assert ok is False, "une capacite sans exp a ete acceptee"
    assert sonde == []


def test_une_signature_alteree_est_refusee(pont, sonde):
    jeton = _capacite(pont)
    altere = jeton[:-4] + ("0000" if not jeton.endswith("0000") else "1111")
    ok, _ = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, altere)
    assert ok is False, "une signature alteree a ete acceptee"
    assert sonde == []


def test_un_jeton_rejoue_est_refuse(pont, sonde):
    """Anti-rejeu : la meme capacite ne sert pas deux fois."""
    jeton = _capacite(pont)
    ok1, _ = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)
    ok2, _ = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)
    assert ok1 is True, "le premier usage aurait du passer"
    assert ok2 is False, "le second usage du meme jti a ete accepte"


# ------------------------------------------------- frontiere d'autorite du process

def test_le_pont_ne_lit_pas_le_coffre(pont):
    """Frontiere REELLE : `get_secret` donne acces a TOUT le coffre. Le pont ne
    connait qu'un secret, recu dans son environnement. Sinon la borne est decorative.

    LU PAR AST, PLUS PAR RECHERCHE DE TEXTE (2026-09-19). La version textuelle a
    mordu sur un COMMENTAIRE qui disait « aucun subprocess » — le mot etait dans
    la source, l'import n'y etait pas. C'est la onzieme fois ce mois-ci qu'un
    instrument s'accuse via son propre vocabulaire, et un garde qui crie a faux
    se fait desarmer. L'AST ne porte pas les commentaires, et il distingue un
    IMPORT d'une mention : c'est justement la propriete qu'on veut verifier.
    """
    import ast as _ast

    arbre = _ast.parse(_source(pont))
    importes = set()
    for n in _ast.walk(arbre):
        if isinstance(n, _ast.Import):
            for a in n.names:
                importes.add(a.name.split(".")[0])
                importes.add(a.name)
        elif isinstance(n, _ast.ImportFrom) and n.module:
            importes.add(n.module.split(".")[-1])
            importes.add(n.module)
    assert not any("forge_secrets" in m for m in importes), (
        "le pont importe forge_secrets : il pourrait lire MCP_DEV_SECRET et tous les "
        "FORGE_TOKEN_*. Le jeton GitHub doit venir de son environnement.")
    for interdit in ("forge_mcp_registry", "nokido_hub", "forge_videur",
                     "forge_auth_tokens", "subprocess"):
        assert not any(interdit in m for m in importes), (
            "le pont importe %s : il sortirait de son perimetre" % interdit)
    # `os.system` / `os.popen` : un APPEL, pas un import — on le cherche comme tel.
    dangereux = [
        _ast.unparse(n)[:60] for n in _ast.walk(arbre)
        if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
        and n.func.attr in {"system", "popen", "Popen", "spawn"}
    ]
    assert not dangereux, "le pont peut lancer un processus : %s" % dangereux


# --- L'EXCEPTION ACCORDEE AU SOCLE EST BORNEE, et ces tests SONT sa borne -------
#
# La regle d'or du depot dit : un secret vient du COFFRE, jamais de l'environnement
# -- « la seule couche qu'aucune rotation ne met a jour ». Le pont y deroge, et deux
# gates l'ont signale (cliquet `secrets hors coffre`, `golden-rules`). La derogation
# est ACCORDEE et GELEE au socle pour ce module, parce que l'inverse serait pire :
# lire le coffre, c'est pouvoir lire TOUS les secrets de la machine, et ce processus
# est destine a etre joignable depuis l'exterieur.
#
# Une derogation sans borne est un cheque en blanc. Les tests ci-dessous SONT la
# borne : deux variables nommees, pas une de plus, et aucune autre porte vers un
# secret. Si quelqu'un elargit la lecture d'environnement ici, ils echouent -- le
# socle, lui, ne le verrait pas (il gele un COMPTE par fichier, pas des noms).

_SECRETS_TOLERES = {"NOKIDO_BRIDGE_GITHUB_TOKEN", "NOKIDO_BRIDGE_CAPABILITY_KEY"}
_REGLAGES_TOLERES = {"NOKIDO_BRIDGE_ALLOWED_IPS", "NOKIDO_BRIDGE_TRUSTED_PROXIES",
                     "NOKIDO_BRIDGE_IP_FILTER", "NOKIDO_BRIDGE_REVOKED"}


def _variables_lues(source: str) -> set:
    """Tout nom d'environnement litteral atteint par le module.

    On collecte a l'AST `os.environ.get("X")`, `os.environ["X"]`, et les litteraux
    passes au lecteur interne -- sans quoi une lecture indirecte echapperait au
    controle en passant par une fonction.
    """
    import ast as _ast
    noms = set()
    arbre = _ast.parse(source)
    for n in _ast.walk(arbre):
        if isinstance(n, _ast.Call):
            f = n.func
            nom = f.attr if isinstance(f, _ast.Attribute) else getattr(f, "id", "")
            interessant = nom in ("get", "_liste_env") or nom.endswith("_liste_env")
            if interessant:
                for a in n.args:
                    if isinstance(a, _ast.Constant) and isinstance(a.value, str) \
                            and a.value.isupper() and "_" in a.value:
                        noms.add(a.value)
        elif isinstance(n, _ast.Subscript):
            v, s = n.value, n.slice
            if isinstance(v, _ast.Attribute) and v.attr == "environ" \
                    and isinstance(s, _ast.Constant) and isinstance(s.value, str):
                noms.add(s.value)
    return noms


def test_l_exception_ne_couvre_que_deux_variables_NOMMEES(pont):
    lues = _variables_lues(_source(pont))
    inattendues = lues - _SECRETS_TOLERES - _REGLAGES_TOLERES
    assert not inattendues, (
        "le pont lit des variables d'environnement hors de l'exception accordee : "
        "%s. L'exception vaut pour %s et rien d'autre."
        % (sorted(inattendues), sorted(_SECRETS_TOLERES)))
    assert _SECRETS_TOLERES <= lues, (
        "une des deux variables de l'exception n'est plus lue (%s) : si le besoin a "
        "disparu, RETIRER l'entree du socle plutot que la laisser dormir"
        % sorted(_SECRETS_TOLERES - lues))


def test_aucune_autre_porte_vers_un_secret(pont):
    """Ni le coffre, ni les jetons d'agent, ni un secret d'une autre couche."""
    src = _source(pont)
    for interdit in ("FORGE_TOKEN_", "FORGE_MCP_TOKEN", "MCP_DEV_SECRET",
                     "LAFORGE_ADMIN_TOKEN", "LAFORGE_SUPERVISOR_TOKEN",
                     "ANTHROPIC_API_KEY", "machine_vault", "Nokido.env"):
        assert interdit not in src, (
            "le pont reference %r : l'exception ne couvre QUE ses deux variables "
            "propres, pas une autre source de secret" % interdit)


def test_la_clef_de_signature_ne_peut_PAS_venir_du_coffre(pont):
    """Pourquoi la seconde variable est dans l'exception, et pas une negligence.

    La clef d'habilitation SIGNE et VERIFIE les jetons presentes au pont. La lire au
    coffre supposerait d'ouvrir le coffre au processus -- ce que les tests voisins
    interdisent. Elle doit donc arriver par l'environnement, comme le jeton GitHub.
    Sans clef, le pont tire une clef ALEATOIRE de processus : fail-closed, aucun
    jeton exterieur ne passe. C'est verifie ici, faute de quoi « pas de clef »
    pourrait un jour devenir « pas de verification ».
    """
    import os as _os
    ancienne = _os.environ.pop("NOKIDO_BRIDGE_CAPABILITY_KEY", None)
    try:
        jeton_etranger = "ZmFicmlxdWU.c2lnbmF0dXJl"
        ok, motif = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"},
                                 jeton_etranger)
        assert ok is False, "un jeton forge ailleurs a ete accepte sans clef declaree"
        assert "sceau" in motif.lower() or "habilitation" in motif.lower(), motif
    finally:
        if ancienne is not None:
            _os.environ["NOKIDO_BRIDGE_CAPABILITY_KEY"] = ancienne


def test_le_pont_n_ecoute_pas_le_monde_par_defaut(pont):
    """L'exposition est une DECISION, pas un defaut. Le port s'ouvre sur loopback ;
    l'ouvrir ailleurs doit etre un geste explicite de l'operateur."""
    assert pont.HOTE_PAR_DEFAUT == "127.0.0.1", (
        "defaut d'ecoute = %r : un bind sur 0.0.0.0 par defaut expose la passerelle "
        "des le premier lancement" % pont.HOTE_PAR_DEFAUT)


def test_aucun_secret_ne_peut_etre_journalise(pont):
    """Un journal qui recopie l'en-tete d'autorisation publie la capacite."""
    src = _source(pont)
    for motif in (r"print\([^)]*jeton", r"log[^)]*\(\s*[^)]*capacite",
                  r"print\([^)]*token", r"%s.*Authorization"):
        assert not re.search(motif, src, re.I), \
            "le pont journalise potentiellement un secret (motif %r)" % motif


# ------------------------------------------------------------ filtre d'adresse

def test_par_defaut_seule_la_machine_elle_meme_peut_appeler(pont, monkeypatch):
    monkeypatch.delenv("NOKIDO_BRIDGE_ALLOWED_IPS", raising=False)
    assert pont.adresse_admise("127.0.0.1") is True
    for etranger in ("8.8.8.8", "localhost", "localhost", ""):
        assert pont.adresse_admise(etranger) is False, \
            "%r admis alors qu'aucune liste n'a ete declaree" % etranger


def test_seules_les_adresses_declarees_passent(pont, monkeypatch):
    monkeypatch.setenv("NOKIDO_BRIDGE_ALLOWED_IPS", "203.0.113.7")
    assert pont.adresse_admise("203.0.113.7") is True
    for etranger in ("203.0.113.8", "127.0.0.1", "203.0.113.70"):
        assert pont.adresse_admise(etranger) is False, "%r admis" % etranger


def test_un_entete_transmis_ne_vaut_RIEN_sans_relais_de_confiance(pont, monkeypatch):
    """X-Forwarded-For est fabricable par quiconque parle au port : le lire sans
    relais declare laisserait l'appelant CHOISIR son adresse."""
    monkeypatch.setenv("NOKIDO_BRIDGE_ALLOWED_IPS", "203.0.113.7")
    monkeypatch.delenv("NOKIDO_BRIDGE_TRUSTED_PROXIES", raising=False)
    assert pont.adresse_admise("8.8.8.8", "203.0.113.7") is False, (
        "un appelant non autorise s'est fait passer pour une adresse admise en "
        "posant lui-meme l'en-tete transmis")
    assert pont.adresse_appelante("8.8.8.8", "203.0.113.7") == "8.8.8.8"


def test_l_entete_transmis_compte_derriere_un_relais_declare(pont, monkeypatch):
    monkeypatch.setenv("NOKIDO_BRIDGE_ALLOWED_IPS", "203.0.113.7")
    monkeypatch.setenv("NOKIDO_BRIDGE_TRUSTED_PROXIES", "localhost")
    assert pont.adresse_appelante("localhost", "203.0.113.7, localhost") == "203.0.113.7"
    assert pont.adresse_admise("localhost", "203.0.113.7") is True
    assert pont.adresse_admise("localhost", "8.8.8.8") is False, (
        "le relais est de confiance, mais l'adresse qu'il transmet reste soumise "
        "a la liste blanche")


def test_une_adresse_mal_formee_ne_passe_jamais(pont, monkeypatch):
    monkeypatch.setenv("NOKIDO_BRIDGE_ALLOWED_IPS", "203.0.113.7")
    for tordue in ("203.0.113.7 ; rm -rf", "'; DROP", "203.0.113.7/24", None):
        assert pont.adresse_admise(tordue if tordue is not None else "") is False


# ----------------------------------------------- mode de rejeu et revocation

def test_par_defaut_une_habilitation_ne_sert_qu_une_fois(pont, sonde):
    """Le defaut reste le plus strict : ne pas ecrire `replay` = usage unique."""
    jeton = _capacite(pont)
    assert pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)[0] is True
    assert pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)[0] is False


def test_une_cle_durable_est_POSSIBLE_mais_doit_etre_declaree(pont, sonde):
    """Une Action externe presente une cle STATIQUE : sans ce mode, la passerelle
    serait inutilisable pour l'usage qui l'a fait naitre. Le mode est ecrit DANS
    l'habilitation -- donc decide a l'emission, jamais deduit du trafic."""
    jeton = _capacite(pont, replay="multi", jti="cle-action-durable")
    for essai in range(3):
        ok, res = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)
        assert ok is True, "usage %d refuse : %r" % (essai + 1, res)


def test_un_mode_de_rejeu_invente_est_refuse(pont, sonde):
    for mode in ("always", "none", "*", "", 1, None):
        ok, _ = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"},
                             _capacite(pont, replay=mode))
        assert ok is False, "mode de rejeu %r accepte" % (mode,)
    assert sonde == []


def test_une_cle_durable_sans_expiration_reste_refusee(pont, sonde):
    """Le mode durable ne dispense de RIEN d'autre : sans expiration, la cle serait
    eternelle et la revocation son unique frein."""
    charge = {"sub": "x", "aud": pont.AUDIENCE, "scope": pont.SCOPE,
              "resource": "Nokido-labs/nokido", "jti": "durable-sans-exp",
              "replay": "multi"}
    ok, _ = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"},
                         pont.forger_capacite(charge))
    assert ok is False
    assert sonde == []


def test_une_habilitation_revoquee_ne_passe_plus(pont, sonde, monkeypatch):
    """Si la cle d'une Action fuit, on la coupe sans redeployer la passerelle."""
    jeton = _capacite(pont, replay="multi", jti="cle-compromise")
    assert pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)[0] is True
    monkeypatch.setenv("NOKIDO_BRIDGE_REVOKED", "autre-cle,cle-compromise")
    ok, msg = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)
    assert ok is False and "revoqu" in msg.lower(), msg


# --------------- une habilitation durable REEVALUE tout, a chaque requete

def _durable(pont, **remplace):
    """Habilitation de type cle statique : le jti l'IDENTIFIE, il ne la consomme pas."""
    champs = {"jti": "cle-durable"}
    champs.update(remplace)          # le test peut nommer son propre identifiant
    return _capacite(pont, replay="multi", **champs)


def test_une_habilitation_durable_sert_plusieurs_fois(pont, sonde):
    jeton = _durable(pont)
    for essai in range(3):
        ok, res = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)
        assert ok is True, "usage %d refuse : %r" % (essai + 1, res)
    assert len(sonde) == 3, "les trois usages n'ont pas atteint GitHub : %r" % sonde


@pytest.mark.parametrize("champ,valeur,attendu", [
    ("aud", "hub", "audience"),
    ("scope", "github:write", "portee"),
    ("resource", "autre/projet", "ressource"),
])
def test_un_defaut_de_cadrage_refuse_meme_en_durable(pont, sonde, champ, valeur,
                                                     attendu):
    """Le mode durable ne dispense d'AUCUN autre garde."""
    ok, msg = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"},
                           _durable(pont, **{champ: valeur}))
    assert ok is False, "durable accepte avec %s=%r" % (champ, valeur)
    assert attendu in msg.lower(), "motif inattendu : %r" % msg
    assert sonde == []


def test_une_habilitation_durable_expiree_est_refusee_des_le_premier_appel(pont, sonde):
    ok, msg = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"},
                           _durable(pont, exp=int(time.time()) - 1))
    assert ok is False and "expir" in msg.lower(), msg
    assert sonde == []


def test_AUCUN_verdict_n_est_mis_en_cache_apres_un_premier_succes(pont, sonde,
                                                                  monkeypatch):
    """LE risque propre au mode durable : qu'un garde valide une fois puis laisse
    passer. Chaque garde est donc casse APRES un usage reussi, un par un, et doit
    refuser immediatement -- le passe ne fait jamais autorite sur le present."""
    jeton = _durable(pont)
    assert pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)[0] is True
    appels_apres_succes = len(sonde)

    # 1. revocation : effet immediat, sans redemarrage
    monkeypatch.setenv("NOKIDO_BRIDGE_REVOKED", "cle-durable")
    ok, msg = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)
    assert ok is False and "revoqu" in msg.lower(), "revocation sans effet : %r" % msg
    monkeypatch.delenv("NOKIDO_BRIDGE_REVOKED", raising=False)

    # 2. le depot demande doit rester celui de l'habilitation, a chaque appel
    ok, _ = pont.traiter("repo_info", {"repo": "autre/projet"}, jeton)
    assert ok is False, "un depot etranger est passe apres un usage reussi"

    # 3. l'expiration est relue, pas retenue du premier controle
    fige = time.time() + 10_000
    monkeypatch.setattr(pont.time, "time", lambda: fige)
    ok, msg = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)
    assert ok is False and "expir" in msg.lower(), \
        "l'expiration n'est pas reevaluee : %r" % msg

    assert len(sonde) == appels_apres_succes, (
        "un refus posterieur au premier succes a tout de meme appele GitHub : %r"
        % sonde)


def test_le_jti_sert_a_REVOQUER_meme_ce_qui_n_a_jamais_servi(pont, sonde):
    """Le jti identifie l'habilitation : on doit pouvoir la couper avant tout usage."""
    import os as _os
    jeton = _durable(pont, jti="jamais-utilisee")
    _os.environ["NOKIDO_BRIDGE_REVOKED"] = "jamais-utilisee"
    try:
        ok, msg = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, jeton)
    finally:
        _os.environ.pop("NOKIDO_BRIDGE_REVOKED", None)
    assert ok is False and "revoqu" in msg.lower(), msg
    assert sonde == []


# ------------------------------- le filtre d'adresse n'est PAS l'autorite

def test_couper_le_filtre_d_adresse_n_ouvre_rien(pont, sonde, monkeypatch):
    """L'adresse de sortie d'un service d'inference n'est pas stable : on doit
    pouvoir couper ce filtre. Mais le couper ne doit RIEN ouvrir -- l'habilitation
    reste seule autorite."""
    monkeypatch.setenv("NOKIDO_BRIDGE_IP_FILTER", "off")
    assert pont.adresse_admise("203.0.113.99") is True, \
        "filtre coupe : l'adresse ne doit plus etre un critere"
    ok, _ = pont.traiter("repo_info", {"repo": "Nokido-labs/nokido"}, None)
    assert ok is False, "filtre coupe et habilitation absente : ca a PASSE"
    ok, _ = pont.traiter("repo_info", {"repo": "autre/projet"}, _capacite(pont))
    assert ok is False, "filtre coupe : le depot n'est plus verifie"
    assert sonde == []


def test_le_filtre_d_adresse_ne_se_coupe_pas_tout_seul(pont, monkeypatch):
    monkeypatch.delenv("NOKIDO_BRIDGE_IP_FILTER", raising=False)
    assert pont.filtre_adresse_actif() is True
    for valeur in ("", "on", "oui", "1", "OFF_", "false"):
        monkeypatch.setenv("NOKIDO_BRIDGE_IP_FILTER", valeur)
        assert pont.filtre_adresse_actif() is True, \
            "%r a desarme le filtre alors que seul 'off' le doit" % valeur
    monkeypatch.setenv("NOKIDO_BRIDGE_IP_FILTER", "off")
    assert pont.filtre_adresse_actif() is False


# ------------------------------------------------------------- schema OpenAPI

def test_le_schema_decrit_EXACTEMENT_ce_qui_est_execute(pont):
    """Un schema qui diverge de la table de routage ment au client -- et un client
    qui declare une operation inexistante recevra 404 sans comprendre pourquoi."""
    schema = pont.schema_openapi("https://exemple.test")
    routes = {c[len("/v1/"):] for c in schema["paths"] if c.startswith("/v1/")}
    assert routes == set(pont.OPERATIONS), (
        "le schema annonce %r alors que la passerelle execute %r"
        % (sorted(routes), sorted(pont.OPERATIONS)))
    for chemin, corps in schema["paths"].items():
        assert set(corps) == {"post"}, "%s expose autre chose qu'un POST" % chemin


def test_le_schema_n_annonce_aucune_ecriture(pont):
    schema = pont.schema_openapi()
    verbes = {v for corps in schema["paths"].values() for v in corps}
    assert verbes <= {"post"}, "le schema expose %r" % sorted(verbes)
    texte = str(schema).lower()
    for interdit in ("delete", "update_file", "create_file", "dispatch", "merge"):
        assert interdit not in texte, "le schema mentionne %r" % interdit


def test_le_schema_ne_divulgue_ni_secret_ni_adresse_interne(pont):
    schema = str(pont.schema_openapi("https://exemple.test"))
    for fuite in ("127.0.0.1", "localhost", "8766", "NOKIDO_BRIDGE_GITHUB_TOKEN",
                  "FORGE_TOKEN", "ghp_", "github_pat_"):
        assert fuite not in schema, "le schema divulgue %r" % fuite


def test_le_fichier_du_pont_n_est_pas_tronque(pont):
    """Garde de LIVRAISON, paye le 2026-09-13 : une ecriture gouvernee a rendu
    `ok` et « relecture disque identique » sur un fichier coupe au milieu d'un
    `return`. Le fichier restait IMPORTABLE (le fragment etait une expression
    valide), donc le defaut ne sortait qu'a l'usage. On verifie donc la presence
    des symboles de fin, pas seulement que l'import passe."""
    src = _source(pont)
    for symbole in ("def traiter(", "def construire_app(", "def main(",
                    'if __name__ == "__main__":'):
        assert symbole in src, "%r absent : fichier vraisemblablement tronque" % symbole
    assert src.rstrip().endswith("raise SystemExit(main())"), \
        "le fichier ne se termine pas par son point d'entree"
    for nom in pont.OPERATIONS:
        assert hasattr(pont, "_op_" + nom), "handler _op_%s absent" % nom


def test_le_pont_declare_son_organe(pont):
    """Regle du corps : un module neuf porte sa declaration, sinon il sort non classe.
    Le census ne lit que les 12 000 premiers caracteres, regex ancree en debut de ligne."""
    assert re.search(r"^__FORGE_COLOR__\s*=", _source(pont)[:12000], re.M), \
        "declaration d'organe absente de la fenetre lue par le census"
