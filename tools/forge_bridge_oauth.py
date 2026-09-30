"""forge_bridge_oauth.py - autorite OAuth locale, adossee a l'habilitation existante.

__FORGE_COLOR__ = "membrane/autorisation-oauth"

CE QUE CE FICHIER EST. Un serveur d'autorisation OAuth 2.1 minimal, pour que le
relais officiel puisse presenter notre serveur MCP comme une RESSOURCE PROTEGEE et
laisser le client mener le flot. Mesure du 2026-09-14 contre le relais : il recupere
`/.well-known/oauth-protected-resource`, interroge le serveur d'autorisation, puis
REECRIT le defi `WWW-Authenticate` vers son propre ingress et publie les points de
decouverte a sa place (`OAuth discovery URLs published`). Il n'y a donc aucun port a
ouvrir : les points OAuth sont tunnelises comme le reste.

CE QU'IL N'EST PAS -- et c'est le point qui compte. Ce n'est PAS une seconde
autorite. Le jeton d'acces qu'il delivre EST une habilitation du pont, signee par la
meme clef, et relue a chaque requete par `forge_github_bridge._lire_capacite` -- la
fonction qui verifie deja `aud`, `scope`, `resource`, `exp`, `jti` et la revocation.
Rien n'est reimplemente ici :

    jeton OAuth  ==  habilitation du pont          <- meme objet, meme signature
    verification ==  _lire_capacite()              <- meme fonction, meme verdict

Appeler une fonction au nom souligne depuis un autre module est un couplage
delibere, et le bon choix : la seule alternative serait de recopier ses controles,
c'est-a-dire de fabriquer la seconde implementation qu'on veut eviter. Un NR verifie
qu'aucun `hmac`, aucune liste de depots et aucune comparaison d'audience n'apparait
dans ce fichier.

POURQUOI UN CONSENTEMENT, ET PAS UN OCTROI AUTOMATIQUE. Un serveur d'autorisation
qui accorde un jeton a quiconque le demande ne protege rien : le rempart
redeviendrait le tunnel seul, c'est-a-dire l'etat que l'on cherche precisement a
quitter. Le flot passe donc par une page de consentement qui reclame un CODE
D'APPARIEMENT connu du seul operateur. Ce n'est pas un second mecanisme
d'autorisation -- c'est l'etape de consentement que tout OAuth comporte, et elle ne
delivre rien d'autre qu'une habilitation ordinaire.

CE QUE CETTE COUCHE NE FAIT PAS. Elle n'authentifie pas une PERSONNE : elle atteste
que le demandeur connait le code d'appariement. Pour un service personnel dont
l'acces est deja borne a cinq lectures sur un depot, c'est la garantie visee, et il
vaut mieux l'ecrire que la laisser croire plus forte qu'elle n'est.
"""

from __future__ import annotations

__FORGE_COLOR__ = "membrane/autorisation-oauth"

import importlib.util
import json
import logging
import os
import pathlib
import re
import secrets
import time

_LOG = logging.getLogger("Nokido.BridgeOAuth")

_DEFAUT_PONT = pathlib.Path(__file__).resolve().parent / "forge_github_bridge.py"


def _chemin_pont() -> pathlib.Path:
    """La passerelle dont ce processus delivre les habilitations.

    UNE autorite, PARAMETREE PAR PASSERELLE (2026-09-28, connecteur des pairs cloud) : par
    defaut le pont GitHub, inchange -- le connecteur ChatGPT ne bouge pas. Une autre passerelle
    SEULEMENT si elle vit dans `tools/` et s'appelle `forge_passerelle_*.py` : laisser
    l'environnement designer n'importe quel fichier reviendrait a lui laisser choisir qui signe
    les habilitations. NR : tests/nr/test_oauth_par_passerelle_nr.py.
    """
    brut = (os.environ.get("NOKIDO_OAUTH_PASSERELLE") or "").strip()
    if not brut:
        return _DEFAUT_PONT
    chemin = pathlib.Path(brut)
    if not chemin.is_absolute():
        chemin = _DEFAUT_PONT.parent / chemin
    chemin = chemin.resolve()
    if chemin.parent != _DEFAUT_PONT.parent or not re.fullmatch(r"forge_passerelle_[a-z0-9_]+\.py", chemin.name):
        raise SystemExit("passerelle OAuth refusee : %s (seul tools/forge_passerelle_*.py)" % brut)
    return chemin


_CHEMIN_PONT = _chemin_pont()

# Duree de vie d'un jeton d'acces. Courte par principe, renouvelable par le flot.
DUREE_JETON_S = int(os.environ.get("NOKIDO_BRIDGE_OAUTH_DUREE_S") or 3600)
DUREE_CODE_S = 300
# Le renouvellement dure plus longtemps que le jeton -- c'est tout son objet : il
# permet a l'acces de rester COURT sans redemander un consentement chaque heure.
DUREE_RENOUVELLEMENT_S = int(
    os.environ.get("NOKIDO_BRIDGE_OAUTH_DUREE_SUITE_S") or 30 * 86400)
PORTEE = "github:read"


def _charger_pont():
    """La passerelle, chargee PAR SON CHEMIN -- jamais par nom.

    `tools/` n'est pas toujours dans le chemin de recherche du processus que le
    relais demarre, et un import par nom pourrait resoudre un homonyme.
    """
    if not _CHEMIN_PONT.exists():
        raise SystemExit("passerelle introuvable : %s" % _CHEMIN_PONT)
    spec = importlib.util.spec_from_file_location(_CHEMIN_PONT.stem, _CHEMIN_PONT)
    if spec is None or spec.loader is None:
        raise SystemExit("passerelle illisible : %s" % _CHEMIN_PONT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PONT = _charger_pont()


def depot_unique() -> str:
    """Le depot pour lequel les habilitations sont emises.

    Il vient de la liste blanche du pont, jamais d'une constante locale : deux
    listes finiraient par diverger, et c'est la plus permissive qui ferait loi.
    """
    depots = sorted(PONT.DEPOTS_AUTORISES)
    if len(depots) != 1:
        raise SystemExit("liste de depots inattendue : %s" % depots)
    return depots[0]


FLOTS = ("authorization_code", "refresh_token")


def fichier_des_clients():
    """Ou vivent les clients inscrits dynamiquement -- si on veut qu'ils vivent.

    POURQUOI LA PERSISTANCE N'EST PAS UN CONFORT. Un client inscrit GARDE son
    identifiant. Si le serveur l'oublie a son redemarrage, l'appelant continue de
    presenter un identifiant que plus personne ne connait et recoit un refus de
    client inconnu -- une panne qui ne ressemble a rien, et qu'on ne rattache pas
    spontanement a un redemarrage survenu des heures plus tot. C'est le genre de
    defaut qui se paie en enquete, pas en correction.

    Le chemin est EXIGE explicitement : sans lui, aucune persistance, et le
    serveur le DIT au demarrage. Un defaut silencieux qui ecrirait dans un
    repertoire devine serait pire que pas de persistance du tout.
    """
    chemin = (os.environ.get("NOKIDO_BRIDGE_OAUTH_CLIENTS") or "").strip()
    return pathlib.Path(chemin) if chemin else None


def client_preenregistre():
    """Le client pose par l'operateur, pour un appelant qui ne sait pas s'inscrire.

    POURQUOI CE CHEMIN EXISTE. L'inscription dynamique suppose que le client sache
    la faire. Des connecteurs demandent au contraire qu'on leur remette un
    identifiant et un secret etablis d'avance, et refusent tout autre mode. Sans ce
    chemin il faudrait leur fermer la porte -- ou desarmer le consentement pour
    qu'ils passent, ce qui serait bien pire.

    Les valeurs viennent de l'ENVIRONNEMENT, comme le jeton GitHub du pont. C'est
    la meme frontiere d'autorite, et elle est deliberee : le processus qui LANCE le
    serveur lit le coffre ; le serveur, lui, ne connait que son environnement et ne
    peut donc pas en extraire autre chose.

    Les trois valeurs sont exigees ENSEMBLE. Un identifiant sans secret, ou sans
    redirection declaree, donnerait un client a moitie defini : l'un ouvrirait sans
    authentifier, l'autre laisserait la redirection libre. On rend None -- et
    l'inscription dynamique reste alors le seul chemin.
    """
    from mcp.shared.auth import OAuthClientInformationFull

    identifiant = (os.environ.get("NOKIDO_BRIDGE_OAUTH_CLIENT_ID") or "").strip()
    motdepasse = (os.environ.get("NOKIDO_BRIDGE_OAUTH_CLIENT_SECRET") or "").strip()
    redirections = [x.strip() for x in
                    (os.environ.get("NOKIDO_BRIDGE_OAUTH_REDIRECT") or "").split(",")
                    if x.strip()]
    if not identifiant or not motdepasse or not redirections:
        return None
    donnees = {"client_id": identifiant,
               "redirect_uris": redirections,
               "scope": PONT.SCOPE,
               "response_types": ["code"]}
    donnees["client_secret"] = motdepasse
    donnees["grant_types"] = list(FLOTS)
    donnees["token_endpoint_auth_method"] = "client_secret_post"
    return OAuthClientInformationFull(**donnees)


def code_d_appariement() -> str:
    """Le secret que l'operateur presente a la page de consentement.

    Absent = aucune delivrance possible. C'est un fail-closed voulu : un serveur
    d'autorisation sans consentement accorderait a quiconque atteint le tunnel.
    """
    return (os.environ.get("NOKIDO_BRIDGE_OAUTH_APPARIEMENT") or "").strip()


def revoquer(jti: str) -> None:
    """Revoque une habilitation, DANS LE REGISTRE EXISTANT.

    Le pont lit `NOKIDO_BRIDGE_REVOKED` a CHAQUE lecture de capacite : ajouter un
    identifiant ici suffit, et le verdict change des l'appel suivant. Pas de second
    registre, pas de cache a invalider -- ce qui rend la revocation observable par
    un test, et non pas seulement declaree.
    """
    jti = (jti or "").strip()
    if not jti:
        return
    actuels = [x.strip() for x in
               (os.environ.get("NOKIDO_BRIDGE_REVOKED") or "").split(",") if x.strip()]
    if jti not in actuels:
        actuels.append(jti)
    os.environ["NOKIDO_BRIDGE_REVOKED"] = ",".join(actuels)


# --------------------------------------------------------------- verification

def verifier(jeton: str):
    """Rend (charge, None) ou (None, motif) -- en DELEGUANT au pont, toujours.

    Aucun verdict n'est mis en cache : `_lire_capacite` relit l'expiration et la
    liste des revoquees a chaque appel. C'est ce qui permet qu'une revocation
    prenne effet entre deux requetes d'une meme session.
    """
    return PONT._lire_capacite(jeton)


class VerificateurHabilitation:
    """`TokenVerifier` du SDK. Il ne verifie rien lui-meme : il traduit."""

    async def verify_token(self, token: str):
        from mcp.server.auth.provider import AccessToken

        charge, motif = verifier(token)
        if charge is None:
            _LOG.info("[oauth] jeton refuse : %s", motif)
            return None
        return AccessToken(
            token=token,
            client_id=str(charge.get("sub") or "inconnu"),
            scopes=[str(charge.get("scope") or "")],
            expires_at=int(charge.get("exp") or 0),
            subject=str(charge.get("sub") or ""),
            claims={"jti": charge.get("jti"),
                    "resource": charge.get("resource"),
                    "replay": charge.get("replay")},
        )


# ------------------------------------------------------- serveur d'autorisation

def _empreinte(jeton: str) -> str:
    """sha256 d'un moyen de renouvellement : la SEULE forme ecrite sur disque (2026-09-29).
    32 octets aleatoires ne se retrouvent pas depuis leur empreinte : le fichier ne donne rien
    a qui le lit, et le jeton presente se verifie en le hachant."""
    import hashlib
    return hashlib.sha256(str(jeton or "").encode("utf-8")).hexdigest()


def fichier_des_renouvellements():
    """A cote du registre des clients (meme compte, memes droits) ; None = pas de persistance."""
    clients = fichier_des_clients()
    return clients.with_name(clients.stem + ".renouvellements.json") if clients else None


class AutoriteLocale:
    """`OAuthAuthorizationServerProvider` du SDK, adosse a l'habilitation du pont.

    Les codes d'autorisation vivent EN MEMOIRE : cinq minutes, un seul usage. Les clients
    inscrits sont persistes (fichier_des_clients), et depuis le 2026-09-29 les moyens de
    renouvellement aussi, par leur SEULE empreinte : mesure du jour, une relance du serveur
    des pairs effacait les renouvellements en memoire et forcait claude.ai et ChatGPT a se
    reautoriser a chaque redemarrage (decision owner : les garder). Rotation inchangee.
    """

    def __init__(self):
        self._clients = {}
        self._codes = {}
        self._demandes = {}
        self._renouvellements = {}
        self._relire()
        self._relire_renouvellements()
        pose = client_preenregistre()
        if pose is not None:
            self._clients[pose.client_id] = pose
            _LOG.info("[oauth] client pre-enregistre charge : %s", pose.client_id)
        else:
            _LOG.info("[oauth] aucun client pre-enregistre : seule l'inscription "
                      "dynamique est ouverte")

    # -- persistance des inscrits ----------------------------------------
    def _relire(self) -> None:
        """Recharge les clients inscrits lors des vies precedentes du processus."""
        from mcp.shared.auth import OAuthClientInformationFull

        chemin = fichier_des_clients()
        if chemin is None:
            _LOG.warning("[oauth] NOKIDO_BRIDGE_OAUTH_CLIENTS absente : les clients "
                         "inscrits dynamiquement seront OUBLIES au redemarrage")
            return
        if not chemin.exists():
            _LOG.info("[oauth] aucun client inscrit anterieurement (%s)", chemin)
            return
        try:
            brut = json.loads(chemin.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            # Un registre illisible se DIT : l'avaler ferait repartir de zero en
            # silence, et l'appelant recevrait un refus incomprehensible.
            _LOG.error("[oauth] registre des clients ILLISIBLE (%s: %s) -- les "
                       "inscriptions anterieures sont perdues",
                       type(exc).__name__, exc)
            return
        charges = 0
        for donnees in (brut if isinstance(brut, list) else []):
            try:
                client = OAuthClientInformationFull(**donnees)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("[oauth] un client enregistre est illisible : %s", exc)
                continue
            self._clients[client.client_id] = client
            charges += 1
        _LOG.info("[oauth] %d client(s) inscrit(s) recharge(s) depuis %s",
                  charges, chemin)

    def _ecrire(self) -> None:
        """Ecrit le registre. Une ecriture qui echoue se DIT, jamais ne s'avale."""
        chemin = fichier_des_clients()
        if chemin is None:
            return
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            provisoire = chemin.with_suffix(chemin.suffix + ".tmp")
            provisoire.write_text(
                json.dumps([json.loads(c.model_dump_json(exclude_none=True))
                            for c in self._clients.values()],
                           indent=2, ensure_ascii=False), encoding="utf-8")
            provisoire.replace(chemin)
        except Exception as exc:  # noqa: BLE001
            _LOG.error("[oauth] le registre des clients n'a PAS pu etre ecrit "
                       "(%s: %s) : l'inscription vaudra jusqu'au prochain "
                       "redemarrage, pas au-dela", type(exc).__name__, exc)

    # -- persistance des renouvellements (EMPREINTES seulement) ---------------
    def _relire_renouvellements(self) -> None:
        """Recharge les renouvellements non echus ; le jeton lui-meme n'a jamais ete ecrit."""
        from mcp.server.auth.provider import RefreshToken

        chemin = fichier_des_renouvellements()
        if chemin is None or not chemin.exists():
            return
        try:
            brut = json.loads(chemin.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            _LOG.error("[oauth] registre des renouvellements ILLISIBLE (%s) -- les clients "
                       "devront se reautoriser", type(exc).__name__)
            return
        maintenant = time.time()
        for empreinte, d in (brut.items() if isinstance(brut, dict) else []):
            try:
                if d.get("expires_at") and d["expires_at"] <= maintenant:
                    continue
                self._renouvellements[empreinte] = RefreshToken(
                    token="", client_id=d["client_id"], scopes=list(d.get("scopes") or []),
                    expires_at=d.get("expires_at"))
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("[oauth] un renouvellement enregistre est illisible : %s", type(exc).__name__)
        _LOG.info("[oauth] %d renouvellement(s) recharge(s) depuis %s (empreintes seulement)",
                  len(self._renouvellements), chemin)

    def _ecrire_renouvellements(self) -> None:
        """Ecrit les empreintes non echues. Un echec se DIT : l'acces vaudra jusqu'au redemarrage."""
        chemin = fichier_des_renouvellements()
        if chemin is None:
            return
        try:
            maintenant = time.time()
            donnees = {e: {"client_id": r.client_id, "scopes": list(r.scopes or []), "expires_at": r.expires_at}
                       for e, r in self._renouvellements.items()
                       if not (r.expires_at and r.expires_at <= maintenant)}
            chemin.parent.mkdir(parents=True, exist_ok=True)
            provisoire = chemin.with_suffix(chemin.suffix + ".tmp")
            provisoire.write_text(json.dumps(donnees, indent=1), encoding="utf-8")
            provisoire.replace(chemin)
        except Exception as exc:  # noqa: BLE001
            _LOG.error("[oauth] renouvellements NON ecrits (%s: %s) : ils ne survivront pas au "
                       "redemarrage", type(exc).__name__, exc)

    # -- clients ----------------------------------------------------------
    async def get_client(self, client_id: str):
        return self._clients.get(client_id)

    async def register_client(self, client_info) -> None:
        self._clients[client_info.client_id] = client_info
        _LOG.info("[oauth] client enregistre : %s (redirections : %s)",
                  client_info.client_id,
                  [str(u) for u in (client_info.redirect_uris or [])])
        self._ecrire()

    # -- autorisation -----------------------------------------------------
    async def authorize(self, client, params) -> str:
        """Rend l'URL de NOTRE page de consentement, pas celle du client.

        Le SDK attend une URL de redirection ; rien ne l'oblige a pointer tout de
        suite vers le client. On l'envoie d'abord demander le consentement, et la
        redirection finale n'aura lieu que si le code d'appariement est juste.
        """
        identifiant = secrets.token_urlsafe(16)
        self._demandes[identifiant] = {
            "client_id": client.client_id,
            "params": params,
            "expire": time.time() + DUREE_CODE_S,
        }
        # BASE_CONSENTEMENT, pas BASE_PUBLIQUE : cette page s'ouvre dans le
        # navigateur de l'operateur, sur la machine qui heberge le serveur. Le
        # tunnel ne la relaierait pas (chemin non standard).
        return "%s/consentement?demande=%s" % (BASE_CONSENTEMENT[0].rstrip("/"),
                                               identifiant)

    def demande(self, identifiant: str):
        """La demande en cours, si elle existe encore."""
        d = self._demandes.get(identifiant)
        if not d:
            return None
        if d["expire"] <= time.time():
            self._demandes.pop(identifiant, None)
            return None
        return d

    def accorder(self, identifiant: str) -> str:
        """Le consentement est donne : on cree le code d'autorisation.

        Rend l'URL de retour vers le client, avec le code et l'etat. Le SDK
        verifiera ensuite PKCE au moment de l'echange.
        """
        from mcp.server.auth.provider import AuthorizationCode

        d = self._demandes.pop(identifiant, None)
        if not d:
            return ""
        params = d["params"]
        code = secrets.token_urlsafe(24)
        self._codes[code] = AuthorizationCode(
            code=code,
            scopes=list(params.scopes or [PONT.SCOPE]),
            expires_at=time.time() + DUREE_CODE_S,
            client_id=d["client_id"],
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        retour = str(params.redirect_uri)
        colle = "&" if "?" in retour else "?"
        morceaux = "code=%s" % code
        if params.state:
            morceaux += "&state=%s" % params.state
        return retour + colle + morceaux

    async def load_authorization_code(self, client, authorization_code: str):
        code = self._codes.get(authorization_code)
        if code is None or code.client_id != client.client_id:
            return None
        if code.expires_at <= time.time():
            self._codes.pop(authorization_code, None)
            return None
        return code

    # -- delivrance -------------------------------------------------------
    def _delivrer(self, sujet: str, portees):
        """Forge une habilitation du pont, et son moyen de renouvellement.

        `replay` vaut `multi` -- ce n'est pas un relachement, c'est la seule valeur
        coherente avec OAuth : un jeton d'acces est fait pour servir plusieurs fois
        pendant sa duree de vie. En `single`, la verification du transport
        consommerait l'identifiant d'usage et l'appel metier suivant serait refuse.
        Expiration et revocation restent les freins, comme le pont le documente.

        POURQUOI UN RENOUVELLEMENT EXISTE. Sans lui, l'acces cesserait a chaque
        expiration et il faudrait redonner son consentement -- toutes les heures.
        Un dispositif qu'on doit reveiller sans cesse finit par etre desarme : on
        allongerait la duree du jeton jusqu'a ce qu'elle ne protege plus rien. Le
        renouvellement est donc ce qui permet a l'acces d'etre COURT.

        Il est garde par son EMPREINTE, en memoire et sur disque (2026-09-29) : il survit
        au redemarrage du serveur, sans que le fichier contienne de quoi le rejouer. Ce
        n'est pas un registre d'habilitations -- il ne porte aucun droit par lui-meme et
        ne peut rien ouvrir : il sert seulement a redemander une habilitation au meme sujet.
        """
        from mcp.server.auth.provider import RefreshToken
        from mcp.shared.auth import OAuthToken

        jti = "oauth-%s" % secrets.token_urlsafe(12)
        jeton = PONT.forger_capacite({
            "sub": sujet,
            "aud": PONT.AUDIENCE,
            "scope": PONT.SCOPE,
            "resource": depot_unique(),
            "exp": int(time.time()) + DUREE_JETON_S,
            "jti": jti,
            "replay": "multi",
        })
        suite = secrets.token_urlsafe(32)
        self._renouvellements[_empreinte(suite)] = RefreshToken(
            token=suite,
            client_id=sujet,
            scopes=list(portees or [PONT.SCOPE]),
            expires_at=int(time.time()) + DUREE_RENOUVELLEMENT_S,
        )
        self._ecrire_renouvellements()
        _LOG.info("[oauth] habilitation delivree a %s (jti %s)", sujet, jti)
        rendu = {"token_type": "Bearer", "expires_in": DUREE_JETON_S,
                 "scope": PONT.SCOPE}
        rendu["access_token"] = jeton
        rendu["refresh_token"] = suite
        return OAuthToken(**rendu)

    async def exchange_authorization_code(self, client, authorization_code):
        """Le code est consomme -- une fois, et une seule."""
        self._codes.pop(authorization_code.code, None)
        return self._delivrer(client.client_id,
                              list(authorization_code.scopes or [PONT.SCOPE]))

    async def load_refresh_token(self, client, refresh_token: str):
        suite = self._renouvellements.get(_empreinte(refresh_token))
        if suite is None or suite.client_id != client.client_id:
            return None
        if suite.expires_at and suite.expires_at <= time.time():
            self._renouvellements.pop(_empreinte(refresh_token), None)
            self._ecrire_renouvellements()
            return None
        # recharge depuis le disque, l'objet ne porte pas le jeton : on rend celui PRESENTE
        return suite.model_copy(update={"token": refresh_token})

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        """Renouvelle EN TOURNANT : l'ancien moyen est retire, un neuf est emis.

        OAuth 2.1 l'exige pour un client public, et la raison tient en une phrase :
        sans rotation, un renouvellement qui fuit reste utilisable aussi longtemps
        que le legitime, et rien ne distingue les deux. Avec rotation, le second
        usage echoue -- la fuite devient visible au lieu d'etre silencieuse.
        """
        self._renouvellements.pop(_empreinte(getattr(refresh_token, "token", "")), None)
        return self._delivrer(client.client_id,
                              list(scopes or refresh_token.scopes or [PONT.SCOPE]))

    async def load_access_token(self, token: str):
        return await VerificateurHabilitation().verify_token(token)

    async def revoke_token(self, token) -> None:
        """Revoque par le registre du pont -- le seul qui existe."""
        claims = getattr(token, "claims", None) or {}
        revoquer(str(claims.get("jti") or ""))


# L'adresse publique sous laquelle ce serveur est vu. Le relais la REECRIT vers son
# ingress ; en local elle vaut l'adresse de boucle. Une liste d'un element pour que
# le serveur puisse la poser au demarrage sans variable globale mutable dispersee.
BASE_PUBLIQUE = ["http://127.0.0.1:8791"]
# Base des pages servies A L'OPERATEUR, dans SON navigateur, sur CETTE machine.
#
# POURQUOI ELLE EST DISTINCTE DE `BASE_PUBLIQUE` (mesure 2026-09-14). Le tunnel
# du plan de controle ne route QUE les chemins standards -- `/authorize`,
# `/token`, `/register`, `/.well-known/...`. `/consentement` est un chemin propre
# a Nokido : annonce derriere le tunnel, il rend
#
#     Invalid URL (GET /v1/tunnel/tunnel_<id>/consentement)
#
# et la connexion echoue plus tot qu'avant. Les deux bases repondent donc a deux
# questions differentes : « par ou l'APPELANT DISTANT me joint-il ? » (metadonnees
# OAuth) et « par ou l'OPERATEUR voit-il cette page ? » (consentement). Les
# confondre casse l'une ou l'autre, et le message d'erreur ne dit jamais laquelle.
BASE_CONSENTEMENT = ["http://127.0.0.1:8791"]


def reglages(base: str, chemin_mcp: str = "/mcp", base_consentement: str = ""):
    """`AuthSettings` du SDK, avec l'enregistrement dynamique et la revocation.

    L'enregistrement dynamique est ACTIF parce que le client du relais s'inscrit
    lui-meme : sans cela il faudrait lui poser un identifiant a la main, et la
    decouverte tunnelisee n'aurait plus d'objet.

    La revocation est ACTIVE parce qu'une revocation qu'on ne peut pas DEMANDER
    n'est pas une revocation : elle resterait un champ que personne n'ecrit. Le
    point de revocation passe par le registre du pont, et le verdict change des
    l'appel suivant -- ce qui rend la coupure observable par un test, et non pas
    seulement affirmee.
    """
    from mcp.server.auth.settings import (AuthSettings, ClientRegistrationOptions,
                                          RevocationOptions)

    BASE_PUBLIQUE[0] = base.rstrip("/")
    # Sans base de consentement explicite, on retombe sur la base publique : c'est
    # le cas d'un serveur joint directement, ou les deux coincident.
    BASE_CONSENTEMENT[0] = (base_consentement or base).rstrip("/")
    return AuthSettings(
        issuer_url=BASE_PUBLIQUE[0],
        resource_server_url=BASE_PUBLIQUE[0] + chemin_mcp,
        required_scopes=[PONT.SCOPE],
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[PONT.SCOPE],
            default_scopes=[PONT.SCOPE],
        ),
        revocation_options=RevocationOptions(enabled=True),
    )


PAGE = """<!doctype html><meta charset="utf-8"><title>Consentement</title>
<style>body{font-family:system-ui;margin:3rem auto;max-width:34rem;line-height:1.5}
input{font-size:1rem;padding:.4rem;width:20rem}button{font-size:1rem;padding:.4rem 1rem}
.p{color:#555}</style>
<h1>Autoriser l'acces en lecture</h1>
<p class="p">Un client demande a lire <b>%s</b> en lecture seule, par les cinq
operations de la passerelle. Aucune ecriture n'existe.</p>
<form method="post">
<input type="hidden" name="demande" value="%s">
<p><label>Code d'appariement<br><input name="code" type="password" autofocus></label></p>
<p><button type="submit">Autoriser</button></p>
</form>"""


CHEMIN_AS = "/.well-known/oauth-authorization-server"
CHEMIN_PRMD = "/.well-known/oauth-protected-resource"


def poser_complements(app) -> None:
    """Complete deux documents de decouverte que le SDK publie incomplets.

    DEUX ECARTS MESURES le 2026-09-14 contre le serveur de demonstration livre
    avec le relais, qui fait foi puisqu'il decrit « les metadonnees que
    tunnel-client attend » :

    1. `token_endpoint_auth_methods_supported` n'annonce pas `none`. La liste est
       ECRITE EN DUR dans le SDK, aucune option ne la change. Or un client qui
       s'inscrit dynamiquement le fait en client PUBLIC, sans secret, protege par
       PKCE -- et notre serveur l'ACCEPTE (verifie : inscription en `none`
       acceptee, HTTP 201). Il refusait donc en annonce ce qu'il autorisait en
       fait, et un client consciencieux renoncait avant d'essayer. On ne change
       aucun comportement ici : on cesse de mentir sur celui qu'on a.

    2. Le document de ressource protegee n'est servi qu'au chemin de l'endpoint
       MCP. La specification demande au client d'essayer AUSSI la racine, et le
       serveur de demonstration la sert. On la sert donc.

    Le complement se fait en sortie, sur le document du SDK : on ne le reecrit pas,
    on y ajoute ce qui manque. Si sa forme change demain, ce qui reste passe tel
    quel plutot que d'etre remplace par une copie figee.
    """
    import json as _j

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    async def completer(requete, suite):
        reponse = await suite(requete)
        # `scope["path"]` plutot que `url.path` (construite avec l'en-tete Host,
        # CVE-2026-48710) — ici ce n'est pas une decision d'acces, mais la regle
        # reste la meme partout pour qu'aucun site ne la reintroduise par copie.
        if requete.scope.get("path", "").rstrip("/") != CHEMIN_AS.rstrip("/"):
            return reponse
        corps = b""
        async for morceau in reponse.body_iterator:
            corps += morceau
        try:
            document = _j.loads(corps)
            methodes = list(document.get("token_endpoint_auth_methods_supported")
                            or [])
            if "none" not in methodes:
                document["token_endpoint_auth_methods_supported"] = \
                    ["none"] + methodes
                corps = _j.dumps(document).encode()
        except Exception as exc:  # noqa: BLE001
            # On rend le document INTACT plutot qu'une version devinee : un
            # document d'autorisation approximatif est pire qu'un document brut.
            _LOG.warning("[oauth] complement impossible (%s) -- document rendu "
                         "tel quel", type(exc).__name__)
        return Response(corps, status_code=reponse.status_code,
                        media_type="application/json")

    app.add_middleware(BaseHTTPMiddleware, dispatch=completer)


def poser_consentement(serveur, autorite: AutoriteLocale) -> None:
    """Ajoute les deux routes de consentement au serveur MCP.

    Elles vivent sur le meme serveur que le reste : le relais ne tunnelise qu'une
    origine, et un second listener serait une seconde surface a proteger.
    """
    from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

    @serveur.custom_route(CHEMIN_PRMD, methods=["GET"])
    async def _ressource_a_la_racine(request):  # noqa: ANN001
        """La meme declaration, au chemin racine que la specification impose
        d'essayer. Le SDK ne sert que le chemin de l'endpoint ; un client qui
        commence par la racine y recevait un 404 et abandonnait la decouverte."""
        base = BASE_PUBLIQUE[0].rstrip("/")
        return JSONResponse({
            "resource": base + "/mcp",
            "authorization_servers": [base + "/"],
            "scopes_supported": [PONT.SCOPE],
            "bearer_methods_supported": ["header"],
        })

    @serveur.custom_route("/consentement", methods=["GET"])
    async def _formulaire(request):  # noqa: ANN001
        identifiant = request.query_params.get("demande", "")
        if not autorite.demande(identifiant):
            return HTMLResponse("<h1>Demande inconnue ou expiree</h1>", status_code=404)
        return HTMLResponse(PAGE % (depot_unique(), identifiant))

    @serveur.custom_route("/consentement", methods=["POST"])
    async def _valider(request):  # noqa: ANN001
        import hmac as _h

        formulaire = await request.form()
        identifiant = str(formulaire.get("demande", ""))
        propose = str(formulaire.get("code", ""))
        attendu = code_d_appariement()
        if not autorite.demande(identifiant):
            return HTMLResponse("<h1>Demande inconnue ou expiree</h1>", status_code=404)
        if not attendu or not _h.compare_digest(propose, attendu):
            _LOG.warning("[oauth] consentement refuse : code d'appariement errone")
            return HTMLResponse("<h1>Code errone</h1>", status_code=403)
        retour = autorite.accorder(identifiant)
        if not retour:
            return HTMLResponse("<h1>Demande expiree</h1>", status_code=404)
        return RedirectResponse(retour, status_code=302)
