"""forge_github_bridge_mcp.py - transport MCP (stdio) des cinq operations GitHub.

__FORGE_COLOR__ = "membrane/transport-mcp"

CE QUE CE FICHIER EST, ET SURTOUT CE QU'IL N'EST PAS.
C'est un ADAPTATEUR. Il traduit un appel MCP en appel a la passerelle, et rend la
reponse. Il ne verifie rien, n'autorise rien, ne connait aucun depot et n'appelle
jamais GitHub. Toute l'autorite vit dans `forge_github_bridge.traiter()`, et elle
doit y rester :

    outil MCP  ->  PONT.traiter()                            <- l'unique porte
    outil MCP  ->  verification locale  ->  PONT.traiter()   <- JAMAIS

Une seconde implementation de l'autorisation diverge toujours de la premiere, et
c'est la plus permissive des deux qui fait loi. Les NR de ce module verifient cette
absence : ni signature, ni liste de depots, ni appel sortant ici.

DEUX TRANSPORTS, UNE SEULE AUTORITE. Le relais officiel sait porter un serveur MCP
de deux facons, et le choix change ce que l'appelant PEUT presenter :

    stdio  le relais lance ce processus et parle sur son entree et sa sortie
           standard. Aucun port, aucune URL, aucun socket -- mais AUCUN EN-TETE non
           plus : l'appelant ne peut rien presenter, et l'habilitation ne peut etre
           que la BORNE DU PROCESSUS, posee par l'operateur au lancement.
    http   le relais atteint ce serveur en MCP Streamable HTTP sur le loopback, et
           il TRANSMET l'en-tete `Authorization` du client. Ce n'est pas une lecture
           de documentation : mesure du 2026-09-14 contre le relais lui-meme, trois
           requetes relayees portant toutes le `Bearer` emis par le client, la ou
           les huit requetes de mise en route du relais n'en portaient aucune.

En HTTP l'habilitation redevient donc ce qu'elle doit etre : un jeton porte par
l'APPELANT, verifie a chaque appel. Et la borne du processus n'y est PAS un repli --
sinon un appel HTTP sans en-tete emprunterait l'habilitation de l'operateur, ce qui
reviendrait a n'authentifier personne tout en paraissant authentifier. L'absence
d'en-tete est un refus.

Ce que l'habilitation contraint ne change pas d'un iota selon le transport : depot,
portee, expiration et revocation restent verifies A CHAQUE APPEL par `traiter()`, et
par elle seule. Sans habilitation, rien ne passe -- fail-closed, verifie par un NR.

DEUX DETAILS DU TRANSPORT HTTP QUI NE SONT PAS DES REGLAGES DE CONFORT.
`stateless_http` est VRAI parce que la mesure l'impose : les requetes relayees ne
portent aucun `Mcp-Session-Id` -- le relais ouvre puis FERME sa propre session avant
de relayer quoi que ce soit. Un serveur a session les refuserait toutes. Et
l'adresse d'ecoute est ecrite en dur sur le loopback, sans option pour en changer :
un serveur qui peut s'ouvrir sur l'exterieur finit par s'y ouvrir.

Lancement (par le relais, jamais a la main en production) :
    NOKIDO_BRIDGE_GITHUB_TOKEN=...    jeton GitHub, lecture seule
    NOKIDO_BRIDGE_CAPABILITY_KEY=...  clef de signature des habilitations
    NOKIDO_BRIDGE_HABILITATION=...    la borne de CE processus
    LAFORGE_PYTHON tools/forge_github_bridge_mcp.py
"""

from __future__ import annotations

__FORGE_COLOR__ = "membrane/transport-mcp"

import importlib.util
import logging
import os
import pathlib
import sys

_LOG = logging.getLogger("Nokido.GithubBridgeMCP")

_CHEMIN_PONT = pathlib.Path(__file__).resolve().parent / "forge_github_bridge.py"

# L'adresse d'ecoute n'est PAS une option -- cf. l'en-tete du fichier.
HOTE = "127.0.0.1"
CHEMIN_HTTP = "/mcp"
PORT_HTTP_PAR_DEFAUT = 8791


def _charger_pont():
    """La passerelle, chargee PAR SON CHEMIN.

    Pas un import par nom : `tools/` n'est pas toujours dans le chemin de recherche
    du processus que le relais demarre, et un import par nom pourrait resoudre un
    homonyme d'un autre dossier. On charge le fichier voisin, celui-la et aucun
    autre.
    """
    if not _CHEMIN_PONT.exists():
        raise SystemExit("passerelle introuvable : %s" % _CHEMIN_PONT)
    spec = importlib.util.spec_from_file_location("forge_github_bridge", _CHEMIN_PONT)
    if spec is None or spec.loader is None:
        raise SystemExit("passerelle illisible : %s" % _CHEMIN_PONT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PONT = _charger_pont()


def outils_exposes() -> tuple:
    """La surface MCP EST celle de la passerelle -- elle n'en est pas une copie.

    Deriver la liste plutot que la recopier interdit qu'un outil soit annonce sans
    etre execute, ou execute sans etre annonce.
    """
    return tuple(PONT.OPERATIONS)


def habilitation_du_processus() -> str:
    """La borne de CE processus, posee par l'operateur au lancement.

    En stdio l'appelant ne presente aucun en-tete : sans cette variable, il n'y
    aurait aucune borne du tout. On rend une chaine vide plutot que None pour que
    l'appel suivant echoue par le chemin normal de refus, jamais par une exception.
    """
    return (os.environ.get("NOKIDO_BRIDGE_HABILITATION") or "").strip()


def habilitation_appelant_exigee() -> bool:
    """L'appelant doit presenter SA propre habilitation. EXIGE PAR DEFAUT.

    POURQUOI CE N'EST PAS OPTIONNEL. En passant de HTTP a stdio, l'en-tete
    d'autorisation disparait : l'appelant ne presente plus rien, et c'est le relais
    qui l'authentifie. Cela DELEGUE entierement l'authentification au transport --
    quiconque atteint le tunnel pourrait appeler les cinq outils. Une confiance
    unique n'est pas une defense en profondeur, et un serveur qui ne demande rien
    n'authentifie personne.

    Le defaut est donc l'EXIGENCE : sans habilitation valide presentee a l'appel,
    rien ne passe. C'est la doctrine du corps -- n'est autorise que ce qui est
    PROUVE autorise, et une valeur absente est un refus, jamais un laissez-passer.

    La desactivation existe pour un diagnostic local, et c'est un geste EXPLICITE :
    il faut ecrire `0`. Ni l'absence de variable, ni une valeur inattendue, ni une
    chaine vide ne desarment ce controle -- une faute de frappe ne doit pas ouvrir
    une porte.
    """
    return (os.environ.get("NOKIDO_BRIDGE_EXIGER_HABILITATION", "1") or "1").strip() != "0"


def appeler(operation: str, args: dict, habilitation_appelant: str = "",
            repli_processus: bool = True) -> tuple:
    """Traduit un appel MCP. Rend (succes, resultat|motif). N'ajoute aucun controle.

    Le seul geste propre a l'adaptateur est de refuser un nom d'operation hors de
    la surface AVANT de deranger la passerelle -- pour qu'un nom invente n'atteigne
    jamais la couche d'autorisation, et que les NR puissent le verifier.

    L'habilitation retenue est celle de l'APPELANT quand il en presente une. A
    defaut, et SEULEMENT si le transport l'autorise, celle du processus. C'est tout
    le role de `repli_processus` : en stdio l'appelant ne peut rien presenter, donc
    la borne de l'operateur est la seule habilitation possible ; en HTTP il le peut,
    et lui preter celle de l'operateur reviendrait a n'authentifier personne. Un
    seul parametre, parce que c'est une seule question : le transport donne-t-il la
    parole a l'appelant ?

    Dans les deux cas la verification est la meme -- `PONT.traiter()`. Il n'y a
    toujours qu'une implementation de l'autorisation.
    """
    if not isinstance(operation, str) or operation not in outils_exposes():
        return False, "operation inconnue"
    presentee = (habilitation_appelant or "").strip()
    if habilitation_appelant_exigee() and not presentee:
        return False, ("habilitation de l'appelant EXIGEE : ce serveur ne se "
                       "contente pas de l'authentification du transport")
    borne = presentee
    if not borne and repli_processus:
        borne = habilitation_du_processus()
    if not borne:
        return False, ("aucune habilitation : ni presentee par l'appelant, ni posee "
                       "dans l'environnement du processus -- le transport refuse tout")
    return PONT.traiter(operation, args if isinstance(args, dict) else {}, borne)


def entete_autorisation_courante():
    """L'en-tete `Authorization` de la requete HTTP en cours, s'il y en a une.

    TROIS ETATS, JAMAIS DEUX, et c'est tout l'interet de cette fonction :

        None  le transport n'a pas d'en-tetes du tout (stdio) ;
        ""    transport HTTP, en-tete absent ou illisible ;
        "..." transport HTTP, en-tete present.

    Confondre les deux premiers ferait retomber un appel HTTP non authentifie sur la
    borne du processus -- c'est-a-dire ouvrir la porte en croyant la fermer. Ce
    qu'on n'a pas pu lire et ce qui n'a pas lieu d'exister ne sont pas la meme
    chose.

    La requete est lue dans la variable de contexte du SDK plutot que recue en
    parametre d'outil : un parametre apparaitrait dans le schema annonce au client,
    qui pourrait alors le renseigner lui-meme -- et une habilitation qu'on peut
    poser dans le corps de l'appel n'est plus portee par le transport.
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
    except Exception:  # noqa: BLE001 - SDK absent : on est forcement hors HTTP
        return None
    contexte = request_ctx.get(None)
    requete = getattr(contexte, "request", None) if contexte is not None else None
    if requete is None:
        return None
    entetes = getattr(requete, "headers", None)
    if entetes is None:
        return ""
    try:
        return entetes.get("authorization") or ""
    except Exception:  # noqa: BLE001
        return ""


def habilitation_de_l_entete(entete: str) -> str:
    """Extrait l'habilitation d'un en-tete `Authorization`. `Bearer` SEUL.

    Un schema inconnu ne rend pas une habilitation approximative : il rend une
    chaine vide, et l'appel echoue ensuite par le chemin normal de refus. On ne
    devine pas ce qu'un client a voulu dire -- accepter `Basic`, ou un jeton nu,
    parce que « c'est probablement ca » fabriquerait une seconde grammaire
    d'authentification a cote de la premiere.
    """
    valeur = (entete or "").strip()
    if not valeur:
        return ""
    morceaux = valeur.split(None, 1)
    if len(morceaux) != 2 or morceaux[0].lower() != "bearer":
        return ""
    return morceaux[1].strip()


def oauth_actif() -> bool:
    """L'autorisation OAuth est-elle posee sur le transport http ? PAR DEFAUT OUI.

    Meme grammaire d'interrupteur que l'exigence d'habilitation : seule la valeur
    `0`, ecrite exactement, desarme. Une faute de frappe laisse le controle ARME --
    liste blanche, jamais liste noire, appliquee a un interrupteur.

    Sans objet en stdio : il n'y a ni en-tete, ni point de decouverte a publier.
    """
    return (os.environ.get("NOKIDO_BRIDGE_OAUTH", "1") or "1").strip() != "0"


def _charger_oauth():
    """L'autorite OAuth, chargee PAR SON CHEMIN, comme la passerelle."""
    import importlib.util as _u

    chemin = pathlib.Path(__file__).resolve().parent / "forge_bridge_oauth.py"
    if not chemin.exists():
        raise SystemExit("autorite OAuth introuvable : %s" % chemin)
    spec = _u.spec_from_file_location("forge_bridge_oauth", chemin)
    module = _u.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def construire_serveur(transport: str = "stdio", port: int = 0, oauth=None):
    """Serveur MCP : un outil par operation, chacun delegant a `appeler`.

    Les reglages du transport HTTP sont poses ICI et nulle part ailleurs : hote en
    dur sur le loopback, `stateless_http` parce que le relais ne renvoie pas de
    `Mcp-Session-Id` sur les requetes qu'il relaie, `json_response` parce qu'une
    reponse unique n'a pas besoin d'un flux d'evenements.

    CE QUE L'AUTORISATION OAUTH AJOUTE, ET CE QU'ELLE NE CHANGE PAS. Elle pose
    devant les outils une verification du porteur, et publie les points de
    decouverte que le relais tunnelise. Elle ne remplace RIEN : le jeton qu'elle
    valide EST une habilitation du pont, et `traiter()` la revalide a chaque appel
    metier. Deux lectures du meme verdict par la meme fonction, pas deux autorites.
    """
    from mcp.server.fastmcp import FastMCP

    reglages = {}
    autorite = None
    module_oauth = None
    if transport == "http":
        numero = int(port or PORT_HTTP_PAR_DEFAUT)
        reglages = {"host": HOTE,
                    "port": numero,
                    "streamable_http_path": CHEMIN_HTTP,
                    "stateless_http": True,
                    "json_response": True}
        if oauth_actif() if oauth is None else bool(oauth):
            module_oauth = _charger_oauth()
            autorite = module_oauth.AutoriteLocale()
            reglages["auth_server_provider"] = autorite
            # Deux bases, deux publics : les metadonnees OAuth sont lues par
            # l'appelant DISTANT (elles doivent porter l'URL du tunnel), la page
            # de consentement s'ouvre dans le navigateur de l'OPERATEUR (elle
            # reste en loopback, et le tunnel ne la relaierait pas de toute
            # facon -- chemin non standard, mesure du 2026-09-14).
            reglages["auth"] = module_oauth.reglages(
                base_publique(numero), CHEMIN_HTTP,
                "http://%s:%d" % (HOTE, numero))
    serveur = FastMCP("nokido-github-readonly", **reglages)

    def _enregistrer(nom: str):
        description = ("Lecture seule GitHub (%s) sur le depot autorise. "
                       "Aucune ecriture n'existe." % nom)

        async def _outil(repo: str, branch: str = "", sha: str = "",
                         base: str = "", head: str = "", path: str = "",
                         ref: str = "") -> dict:
            args = {"repo": repo}
            for cle, valeur in (("branch", branch), ("sha", sha), ("base", base),
                                ("head", head), ("path", path), ("ref", ref)):
                if valeur:
                    args[cle] = valeur
            entete = entete_autorisation_courante()
            if entete is None:
                # Transport sans en-tetes : la borne du processus est la seule
                # habilitation que l'appelant PUISSE avoir.
                ok, res = appeler(nom, args)
            else:
                # Transport HTTP : l'habilitation vient de l'appelant, et d'elle
                # seule. Aucun repli -- un appel sans en-tete doit echouer, pas
                # emprunter l'habilitation de l'operateur.
                ok, res = appeler(nom, args, habilitation_de_l_entete(entete),
                                  repli_processus=False)
            if not ok:
                _LOG.info("[mcp] refus sur %s : %s", nom, res)
                return {"ok": False, "error": res}
            return {"ok": True, "data": res}

        _outil.__name__ = nom
        _outil.__doc__ = description
        serveur.tool(name=nom, description=description)(_outil)

    for nom in outils_exposes():
        _enregistrer(nom)
    if autorite is not None and module_oauth is not None:
        module_oauth.poser_consentement(serveur, autorite)
        # On garde LE module charge, pas un second exemplaire : deux chargements
        # du meme fichier donnent deux objets distincts, avec deux etats -- dont
        # deux `BASE_PUBLIQUE` qui divergeraient en silence.
        serveur._nokido_oauth = module_oauth
    return serveur


def base_publique(port: int) -> str:
    """L'URL par laquelle on ATTEINT ce serveur — pas celle ou il ecoute.

    DEFAUT PAYE le 2026-09-14. Les metadonnees OAuth (RFC 8414 / RFC 9728) etaient
    construites en dur sur l'adresse d'ECOUTE :

        module_oauth.reglages("http://%s:%d" % (HOTE, numero), ...)

    Or ce serveur est atteint A TRAVERS un tunnel : l'appelant decouvrait donc un
    `token_endpoint` en loopback, qu'il ne peut pas joindre. Le flux allait jusqu'a
    la redirection -- `/authorize`, consentement accorde, code emis -- puis
    s'arretait sans un seul appel a `/token`, et l'utilisateur lisait « Un probleme
    est survenu lors de la connexion », message qui ne nomme ni le maillon ni la
    cause.

    ANNONCER N'EST PAS ECOUTER. Cette fonction ne touche QUE ce qui est annonce :
    `HOTE` reste le loopback, et c'est ce qui rend le montage acceptable -- rien
    n'ecoute vers l'exterieur, le relais long-polle en sortant.

    Sans declaration, le comportement d'origine est conserve : un usage local ne
    change pas. Une valeur vide vaut une absence -- annoncer une base vide
    produirait des URL relatives et une decouverte qui echoue sans le dire.
    """
    declaree = (os.environ.get("NOKIDO_BRIDGE_PUBLIC_URL") or "").strip()
    if declaree:
        return declaree.rstrip("/")
    return "http://%s:%d" % (HOTE, port)


def transport_choisi(argv=None) -> tuple:
    """Le transport et le port, depuis la ligne de commande puis l'environnement.

    Le defaut reste `stdio` : changer le transport d'un service en place est un
    geste d'operateur, jamais l'effet de bord d'une mise a jour. L'hote, lui, n'est
    pas un choix -- il n'apparait dans aucune option.
    """
    import argparse

    analyseur = argparse.ArgumentParser(
        description="Transport MCP des cinq operations GitHub en lecture seule.")
    analyseur.add_argument("--transport", choices=("stdio", "http"),
                           default=(os.environ.get("NOKIDO_BRIDGE_TRANSPORT")
                                    or "stdio").strip().lower(),
                           help="stdio (defaut), ou http sur le loopback")
    analyseur.add_argument("--port", type=int,
                           default=int(os.environ.get("NOKIDO_BRIDGE_HTTP_PORT")
                                       or PORT_HTTP_PAR_DEFAUT),
                           help="port d'ecoute du transport http, sur 127.0.0.1")
    connus, _ = analyseur.parse_known_args(argv)
    return connus.transport, connus.port


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    transport, port = transport_choisi(argv)
    if habilitation_appelant_exigee():
        _LOG.info("[mcp] habilitation de l'appelant EXIGEE (defaut) : "
                  "l'authentification du transport ne suffit pas")
    else:
        _LOG.warning("[mcp] habilitation de l'appelant DESARMEE par "
                     "NOKIDO_BRIDGE_EXIGER_HABILITATION=0 : le transport authentifie "
                     "SEUL. A n'utiliser qu'en diagnostic local.")
    if transport == "http":
        _LOG.info("[mcp] transport http sur %s:%d%s -- l'habilitation vient de "
                  "l'en-tete Authorization de l'appelant, jamais de "
                  "l'environnement", HOTE, port, CHEMIN_HTTP)
        if oauth_actif():
            _LOG.info("[mcp] autorisation OAuth ACTIVE : points de decouverte "
                      "publies, consentement exige avant toute delivrance")
        else:
            _LOG.warning("[mcp] autorisation OAuth DESARMEE par "
                         "NOKIDO_BRIDGE_OAUTH=0 : le porteur n'est plus verifie "
                         "qu'a l'appel metier. A n'utiliser qu'en diagnostic local.")
        serveur = construire_serveur("http", port)
        module_oauth = getattr(serveur, "_nokido_oauth", None)
        if module_oauth is None:
            serveur.run(transport="streamable-http")
            return 0
        # L'application est montee ICI plutot que par `run()`, parce qu'il faut y
        # poser un complement de decouverte AVANT son demarrage : le SDK annonce
        # des methodes d'authentification du client qui ne comprennent pas le
        # client public, alors qu'il l'accepte. Un client consciencieux renonce
        # sur l'annonce sans jamais essayer.
        import uvicorn

        application = serveur.streamable_http_app()
        module_oauth.poser_complements(application)
        uvicorn.run(application, host=HOTE, port=int(port or PORT_HTTP_PAR_DEFAUT),
                    log_level="info")
        return 0
    if not habilitation_appelant_exigee() and not habilitation_du_processus():
        _LOG.warning("[mcp] NOKIDO_BRIDGE_HABILITATION absente : le transport "
                     "demarre mais refusera tout appel (fail-closed)")
    construire_serveur("stdio").run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
