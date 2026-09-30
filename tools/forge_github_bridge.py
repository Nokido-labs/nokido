"""forge_github_bridge.py - passerelle GitHub EN LECTURE pour un client externe.

__FORGE_COLOR__ = "membrane/passerelle-lecture"

POURQUOI CE PROCESSUS EXISTE, ET POURQUOI IL EST SEPARE.
Le hub MCP expose `run`, `governed_edit`, `oracle_python_repl` et le cycle de vie
des modules des le ring 3 -- mesure du 2026-09-13 : 30 outils visibles a ce ring.
Le rendre routable depuis Internet reviendrait donc a publier un shell. Cette
passerelle offre la surface GitHub voulue SANS que le hub cesse d'ecouter en
loopback. Elle ne l'appelle jamais et ne l'importe jamais.

CE QUI LA REND READ-ONLY PAR CONSTRUCTION, et non par convention :

  1. l'API publique est une ENUMERATION FERMEE de cinq verbes. Un client ne peut
     pas NOMMER une capacite : il n'y a pas de route `outil + arguments`. Le nom
     recu n'est jamais resolu, jamais concatene, jamais importe -- il sert de clef
     dans un dictionnaire fige, et tout le reste tombe dans le refus.
  2. la seule methode HTTP que ce module sait emettre vers GitHub est GET. Aucune
     fonction d'ecriture n'existe : il n'y a rien a desactiver, donc rien a
     reactiver par megarde.
  3. depots ET adresses appelantes sont des listes BLANCHES. Une liste noire
     laisserait passer tout depot -- ou toute adresse -- futur par defaut ; la
     doctrine du corps est qu'on n'autorise que ce qui est PROUVE autorise.
  4. chaque parametre venant du client est valide contre une forme stricte AVANT
     de toucher une URL. Une branche, une reference et un chemin ne peuvent pas
     changer la ressource appelee.

FRONTIERE D'AUTORITE -- le point qui compte vraiment.
Ce module ne lit PAS le coffre. Lire le coffre, c'est pouvoir lire TOUS les
secrets de la machine ; une passerelle exposee ne doit connaitre que le sien. Le
jeton GitHub arrive donc par l'environnement du processus, pose au demarrage par
l'operateur ou le superviseur. La borne n'est pas decorative : elle est physique.

Et l'absence de jeton se DIT. Un appel non authentifie sur un depot prive rend 404,
pas 403 : « mal forme » et « acces refuse » portent alors le meme code. Ce piege a
coute des heures le 2026-09-13, sur un handler qui partait anonyme en silence. Ici,
l'anonymat est nomme dans la reponse.

FILTRE D'ADRESSE. L'ecoute par defaut est le loopback, et seules les adresses
declarees peuvent appeler. `X-Forwarded-For` n'est lu QUE si le pair direct est un
relais declare de confiance : sinon n'importe qui le fabrique, et le filtre ne
filtre plus rien. Un en-tete que l'appelant controle n'est pas une identite.

Lancement :
    NOKIDO_BRIDGE_GITHUB_TOKEN=...    (environnement, jamais la ligne de commande)
    NOKIDO_BRIDGE_CAPABILITY_KEY=...  (idem)
    NOKIDO_BRIDGE_ALLOWED_IPS=1.2.3.4 (adresses appelantes autorisees, separees par ,)
    NOKIDO_BRIDGE_TRUSTED_PROXIES=... (relais dont on accepte l'en-tete transmis)
    LAFORGE_PYTHON tools/forge_github_bridge.py [--port 7790] [--host 127.0.0.1]
"""

from __future__ import annotations

__FORGE_COLOR__ = "membrane/passerelle-lecture"

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets as _alea
import time
import urllib.error
import urllib.parse
import urllib.request

_LOG = logging.getLogger("Nokido.GithubBridge")

# --------------------------------------------------------------------- contrat

#: Les cinq verbes publics. Toute addition est une DECISION, pas un effet de bord :
#: le NR `test_la_surface_publique_est_une_enumeration_fermee` echoue si cette liste
#: change sans que quelqu'un l'ait voulu.
OPERATIONS: tuple = ("repo_info", "branch_head", "commit_info", "compare", "read_file")

#: Ce module ne sait pas ecrire. Il n'emet que des GET.
METHODES_AUTORISEES: frozenset = frozenset({"GET"})

#: Liste BLANCHE des depots. Extensible explicitement, jamais par joker.
DEPOTS_AUTORISES: frozenset = frozenset({"Nokido-labs/nokido"})

AUDIENCE = "nokido-github-bridge"
SCOPE = "github:read"

HOTE_PAR_DEFAUT = "127.0.0.1"
PORT_PAR_DEFAUT = 7790

API = "https://api.github.com"
DELAI_S = 20
TAILLE_MAX = 512 * 1024          # plafond de lecture d'un fichier
FENETRE_REJEU_S = 900            # au-dela, un jti ne peut plus etre rejoue utilement
APPELS_PAR_MINUTE = 30

#: Formes strictes. Un parametre client qui n'y entre pas ne touche aucune URL.
_RE_DEPOT = re.compile(r"^[A-Za-z0-9][\w.-]{0,38}/[A-Za-z0-9][\w.-]{0,99}$")
_RE_REF = re.compile(r"^[A-Za-z0-9][\w./-]{0,98}$")
_RE_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_RE_CHEMIN = re.compile(r"^[A-Za-z0-9][\w./ -]{0,199}$")
_RE_IP = re.compile(r"^[0-9a-fA-F:.]{3,45}$")

_JTI_VUS: dict = {}
_DEBITS: dict = {}


def _ref_valide(valeur) -> bool:
    """Une reference (branche ou tag) bien formee et SANS remontee.

    La regex seule ne suffit pas : elle autorise `.` et `/`, donc
    `alpha/../../secrets` la traverse. L'encodage de l'URL le neutraliserait sans
    doute, mais on ne fait pas reposer une frontiere sur le comportement d'un
    encodeur en aval -- on refuse la forme, ici, explicitement.
    """
    return (isinstance(valeur, str) and bool(_RE_REF.match(valeur))
            and ".." not in valeur)


def _sha_valide(valeur) -> bool:
    return isinstance(valeur, str) and bool(_RE_SHA.match(valeur))


def _liste_env(nom: str, defaut: frozenset) -> frozenset:
    brut = (os.environ.get(nom) or "").strip()
    if not brut:
        return defaut
    return frozenset(x.strip() for x in brut.split(",")
                     if x.strip() and _RE_IP.match(x.strip()))


def adresses_autorisees() -> frozenset:
    """Qui a le droit d'appeler. Defaut : la machine elle-meme, personne d'autre."""
    return _liste_env("NOKIDO_BRIDGE_ALLOWED_IPS", frozenset({"127.0.0.1", "::1"}))


def filtre_adresse_actif() -> bool:
    """Le filtre d'adresse est une DEFENSE EN PROFONDEUR, pas l'autorite.

    L'autorite est l'habilitation : audience, portee, ressource, expiration. Une
    adresse de sortie n'est pas une identite -- celle d'un service d'inference
    varie, et s'y fier ferait dependre la securite d'une donnee que personne ne
    controle. On peut donc le couper EXPLICITEMENT (`NOKIDO_BRIDGE_IP_FILTER=off`)
    quand l'appelant n'a pas d'adresse stable ; l'habilitation, elle, reste exigee
    dans tous les cas. Le couper par defaut serait une autre affaire : c'est pour
    cela qu'il faut l'ecrire.
    """
    return (os.environ.get("NOKIDO_BRIDGE_IP_FILTER", "on") or "on").lower() != "off"


def revoquees() -> frozenset:
    """Identifiants d'habilitation revoques. Une cle qui fuit se coupe ici."""
    brut = (os.environ.get("NOKIDO_BRIDGE_REVOKED") or "").strip()
    return frozenset(x.strip() for x in brut.split(",") if x.strip())


def relais_de_confiance() -> frozenset:
    """Relais dont l'en-tete transmis fait foi. Vide par defaut : aucun."""
    return _liste_env("NOKIDO_BRIDGE_TRUSTED_PROXIES", frozenset())


def adresse_appelante(pair: str, entete_transmis: str = "") -> str:
    """L'adresse REELLE de l'appelant.

    `X-Forwarded-For` est fabricable par quiconque parle au port. On ne le lit donc
    que si le pair direct est un relais DECLARE ; sinon seul le pair compte. Faire
    l'inverse, c'est laisser l'appelant choisir son identite.
    """
    pair = (pair or "").strip()
    if entete_transmis and pair in relais_de_confiance():
        premier = entete_transmis.split(",")[0].strip()
        if _RE_IP.match(premier):
            return premier
    return pair


def adresse_admise(pair: str, entete_transmis: str = "") -> bool:
    if not filtre_adresse_actif():
        return True
    reelle = adresse_appelante(pair, entete_transmis)
    return bool(reelle) and reelle in adresses_autorisees()


def _cle_capacite() -> bytes:
    """Clef de signature des habilitations.

    Absente de l'environnement, on tire une clef ALEATOIRE de processus. C'est
    volontairement fail-closed : personne a l'exterieur ne peut alors forger de
    jeton valide, donc la passerelle refuse tout au lieu de s'ouvrir par defaut.
    """
    brut = os.environ.get("NOKIDO_BRIDGE_CAPABILITY_KEY", "")
    if brut:
        return brut.encode("utf-8")
    if not hasattr(_cle_capacite, "_ephemere"):
        _cle_capacite._ephemere = _alea.token_bytes(32)
        _LOG.warning("[bridge] aucune clef d'habilitation dans l'environnement : "
                     "clef ephemere de processus, aucun client externe ne passera")
    return _cle_capacite._ephemere


def _b64(donnees: bytes) -> str:
    return base64.urlsafe_b64encode(donnees).decode("ascii").rstrip("=")


def _deb64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def forger_capacite(charge: dict) -> str:
    """Emet une habilitation signee. Geste HORS LIGNE de l'operateur, pas une route."""
    corps = _b64(json.dumps(charge, sort_keys=True, separators=(",", ":")).encode())
    sceau = hmac.new(_cle_capacite(), corps.encode("ascii"), hashlib.sha256).digest()
    return corps + "." + _b64(sceau)


def lire_capacite(jeton, audience=None, portees=None, ressources=None) -> tuple:
    """Rend (charge, None) si l'habilitation est valide, sinon (None, motif).

    Chaque champ est verifie POSITIVEMENT : une valeur absente, vide ou jokerisee
    est un refus. Un joker accepte serait une elevation silencieuse.

    PARAMETREE, ET C'EST TOUT L'INTERET. Une autre passerelle a besoin de la MEME
    verification -- sceau, audience, portee, ressource, expiration, identifiant
    d'usage, revocation, rejeu -- avec d'autres valeurs. La recopier ailleurs
    fabriquerait une seconde implementation de l'autorisation, et c'est la plus
    permissive des deux qui finit toujours par faire loi.

    Les defauts sont ceux de la passerelle GitHub : son comportement ne change pas
    d'un iota, et ses NR le verifient.
    """
    audience = AUDIENCE if audience is None else audience
    portees = (SCOPE,) if portees is None else tuple(portees)
    ressources = DEPOTS_AUTORISES if ressources is None else frozenset(ressources)
    if not isinstance(jeton, str) or not jeton.strip():
        return None, "habilitation absente"
    parts = jeton.split(".")
    if len(parts) != 2:
        return None, "habilitation mal formee"
    corps, sceau = parts
    attendu = hmac.new(_cle_capacite(), corps.encode("ascii"), hashlib.sha256).digest()
    try:
        fourni = _deb64(sceau)
    except Exception:  # noqa: BLE001
        return None, "sceau illisible"
    if not hmac.compare_digest(attendu, fourni):
        return None, "sceau invalide"
    try:
        charge = json.loads(_deb64(corps))
    except Exception:  # noqa: BLE001
        return None, "charge illisible"
    if not isinstance(charge, dict):
        return None, "charge inattendue"

    if charge.get("aud") != audience:
        return None, "audience non reconnue"
    if charge.get("scope") not in portees:
        return None, "portee non reconnue"
    ressource = charge.get("resource")
    if not isinstance(ressource, str) or ressource not in ressources:
        return None, "ressource hors habilitation"
    exp = charge.get("exp")
    if not isinstance(exp, (int, float)):
        return None, "habilitation sans expiration"
    maintenant = time.time()
    if exp <= maintenant:
        return None, "habilitation expiree"
    jti = charge.get("jti")
    if not isinstance(jti, str) or not jti:
        return None, "identifiant d'usage absent"
    if jti in revoquees():
        return None, "habilitation revoquee"

    # Mode de rejeu EXPLICITE, et c'est une necessite, pas un confort.
    # Une Action d'un service d'inference s'authentifie par une cle STATIQUE : elle
    # presente le meme jeton a chaque appel. Un anti-rejeu a usage unique la
    # refuserait des la deuxieme requete, et la passerelle serait inutilisable pour
    # l'usage meme qui l'a fait naitre. Plutot que de desarmer le garde -- ce qui
    # l'aurait retire pour TOUT LE MONDE en silence -- le mode est ecrit DANS
    # l'habilitation, donc decide a l'emission et verifiable a la lecture.
    #   single (defaut) : usage unique, pour un client qui sait renouveler ;
    #   multi           : cle durable, mais alors expiration et revocation sont les
    #                     seuls freins -- on l'emet en connaissance de cause.
    rejeu = charge.get("replay", "single")
    if rejeu not in ("single", "multi"):
        return None, "mode de rejeu inconnu"
    if rejeu == "single":
        for vieux, quand in list(_JTI_VUS.items()):
            if quand < maintenant - FENETRE_REJEU_S:
                _JTI_VUS.pop(vieux, None)
        if jti in _JTI_VUS:
            return None, "habilitation deja utilisee"
        _JTI_VUS[jti] = maintenant
    return charge, None


def _lire_capacite(jeton) -> tuple:
    """La lecture de CETTE passerelle : `lire_capacite` avec ses propres valeurs.

    Conservee sous ce nom parce que c'est celui que `traiter()` appelle et que les
    NR surveillent. Un renommage n'apporterait rien et desarmerait des gardes qui
    cherchent ce symbole precis.

    ELARGISSEMENT DE LA PORTE, 2026-09-19. Elle n'acceptait qu'une portee et une
    ressource-depot. Elle en accepte desormais DEUX de chaque — et c'est
    precisement pourquoi `PORTEE_PAR_OUTIL` a ete posee AVANT : la porte laisse
    entrer plus large, la frontiere par outil tranche ensuite. Sans cette table,
    cet elargissement aurait donne a un jeton d'observation l'acces aux
    operations GitHub, et l'inverse.
    """
    return lire_capacite(jeton, portees=PORTEES_CONNUES,
                         ressources=frozenset(DEPOTS_AUTORISES) | {RESSOURCE_RUNTIME})


def _debit_ok(sujet: str) -> bool:
    maintenant = time.time()
    tirs = [t for t in _DEBITS.get(sujet, []) if t > maintenant - 60]
    if len(tirs) >= APPELS_PAR_MINUTE:
        _DEBITS[sujet] = tirs
        return False
    tirs.append(maintenant)
    _DEBITS[sujet] = tirs
    return True


# ---------------------------------------------------------------- appel sortant

def _appel_github(chemin: str, methode: str = "GET") -> tuple:
    """Unique porte de sortie. Rend (code, objet). N'emet que des GET."""
    if methode not in METHODES_AUTORISEES:
        return 405, {"erreur": "methode %s interdite ici" % methode}
    porteur = os.environ.get("NOKIDO_BRIDGE_GITHUB_TOKEN", "")
    entetes = {"Accept": "application/vnd.github+json",
               "User-Agent": "nokido-github-bridge"}
    if porteur:
        entetes["Authorization"] = "Bearer " + porteur
    requete = urllib.request.Request(API + chemin, headers=entetes, method=methode)
    try:
        with urllib.request.urlopen(requete, timeout=DELAI_S) as reponse:
            brut = reponse.read(TAILLE_MAX + 1)
            if len(brut) > TAILLE_MAX:
                return 413, {"erreur": "reponse amont > %d octets, NON tronquee "
                                       "pour ne pas rendre une structure mutilee"
                                       % TAILLE_MAX}
            return reponse.status, json.loads(brut.decode("utf-8", "replace"))
    except urllib.error.HTTPError as err:
        if err.code == 404 and not porteur:
            # Le piege paye le 2026-09-13 : sur un depot PRIVE, GitHub rend 404 et
            # non 403. Sans porteur, ce code ne distingue pas un appel mal forme
            # d'un acces refuse. On le NOMME au lieu de laisser deviner.
            return 404, {"erreur": "404 sur requete NON AUTHENTIFIEE : rien dans "
                                   "l'environnement du processus. Sur un depot "
                                   "prive, ce code ne dit pas si l'appel est mal "
                                   "forme ou l'acces refuse."}
        return err.code, {"erreur": "HTTP %d" % err.code}
    except Exception as err:  # noqa: BLE001
        return 0, {"erreur": "%s" % type(err).__name__}


# ------------------------------------------------------------------- operations

def _depot_valide(args: dict) -> tuple:
    depot = args.get("repo")
    if not isinstance(depot, str) or not _RE_DEPOT.match(depot):
        return None, "depot mal forme"
    if depot not in DEPOTS_AUTORISES:
        return None, "depot non autorise par la liste blanche"
    return depot, None


def _op_repo_info(args: dict) -> tuple:
    depot, motif = _depot_valide(args)
    if motif:
        return False, motif
    code, brut = _appel_github("/repos/" + depot)
    if code != 200:
        return False, brut.get("erreur", "HTTP %s" % code)
    perms = brut.get("permissions") or {}
    return True, {"full_name": brut.get("full_name"),
                  "private": brut.get("private"),
                  "default_branch": brut.get("default_branch"),
                  "permissions": {"pull": bool(perms.get("pull"))}}


def _op_branch_head(args: dict) -> tuple:
    depot, motif = _depot_valide(args)
    if motif:
        return False, motif
    branche = args.get("branch")
    if not _ref_valide(branche):
        return False, "branche mal formee"
    code, brut = _appel_github("/repos/%s/branches/%s"
                               % (depot, urllib.parse.quote(branche, safe="")))
    if code != 200:
        return False, brut.get("erreur", "HTTP %s" % code)
    sha = (brut.get("commit") or {}).get("sha") or brut.get("sha")
    return True, {"branch": brut.get("name", branche), "sha": sha}


def _op_commit_info(args: dict) -> tuple:
    depot, motif = _depot_valide(args)
    if motif:
        return False, motif
    sha = args.get("sha")
    if not _sha_valide(sha):
        return False, "sha mal forme"
    code, brut = _appel_github("/repos/%s/commits/%s" % (depot, sha))
    if code != 200:
        return False, brut.get("erreur", "HTTP %s" % code)
    detail = brut.get("commit") or {}
    auteur = detail.get("author") or {}
    return True, {"sha": brut.get("sha", sha), "author": auteur.get("name"),
                  "date": auteur.get("date"),
                  "message": (detail.get("message") or "").splitlines()[:1]}


def _op_compare(args: dict) -> tuple:
    depot, motif = _depot_valide(args)
    if motif:
        return False, motif
    base, tete = args.get("base"), args.get("head")
    for valeur in (base, tete):
        if not (_sha_valide(valeur) or _ref_valide(valeur)):
            return False, "reference de comparaison mal formee"
    code, brut = _appel_github("/repos/%s/compare/%s...%s" % (depot, base, tete))
    if code != 200:
        return False, brut.get("erreur", "HTTP %s" % code)
    fichiers = brut.get("files") or []
    CAP = 100
    return True, {"status": brut.get("status"), "ahead_by": brut.get("ahead_by"),
                  "behind_by": brut.get("behind_by"),
                  "commits": [{"sha": c.get("sha"),
                               "message": ((c.get("commit") or {}).get("message")
                                           or "").splitlines()[:1]}
                              for c in (brut.get("commits") or [])[:CAP]],
                  "files": [f.get("filename") for f in fichiers[:CAP]],
                  "files_total": len(fichiers),
                  "files_omis": max(0, len(fichiers) - CAP)}


def _op_read_file(args: dict) -> tuple:
    depot, motif = _depot_valide(args)
    if motif:
        return False, motif
    chemin = args.get("path")
    if not isinstance(chemin, str) or not _RE_CHEMIN.match(chemin):
        return False, "chemin mal forme"
    if ".." in chemin or chemin.startswith("/") or "\\" in chemin:
        return False, "chemin refuse : remontee de repertoire"
    ref = args.get("ref", "")
    if ref and not (_ref_valide(ref) or _sha_valide(ref)):
        return False, "reference mal formee"
    suffixe = ("?ref=" + urllib.parse.quote(ref, safe="")) if ref else ""
    code, brut = _appel_github("/repos/%s/contents/%s%s"
                               % (depot, urllib.parse.quote(chemin), suffixe))
    if code != 200:
        return False, brut.get("erreur", "HTTP %s" % code)
    contenu = ""
    if brut.get("encoding") == "base64":
        try:
            contenu = base64.b64decode(brut.get("content") or "").decode(
                "utf-8", "replace")
        except Exception:  # noqa: BLE001
            return False, "contenu indecodable"
    return True, {"path": chemin, "blob_sha": brut.get("sha"),
                  "size": brut.get("size"), "content": contenu}


def _op_runtime_observe(args) -> tuple:
    """Observation du runtime, en LECTURE SEULE, deleguee a l'organe sensoriel.

    On ne reimplemente rien ici : `app/forge_runtime_observer` porte le contrat
    (`OBSERVATION · FAITS · DECLARE · INCONNU · LIMITES`) et delegue lui-meme aux
    producteurs existants. Ce que cette passerelle ajoute, c'est l'habilitation
    et la portee — pas une seconde source de verite.

    Ce que l'observation REND est deja generise par l'organe : d'une variable
    d'environnement il ne donne que la PRESENCE, jamais la valeur.

    UNE PORTEE D'OBSERVATION INCONNUE N'EST PAS UN REFUS, et c'est un choix de
    l'organe, pas un oubli : il rend un constat dont le champ `inconnu` dit
    « portee inconnue » et dont les `limites` ENUMERENT les portees valides. Un
    appelant distant se corrige donc seul, la ou un refus sec l'enverrait
    chercher une panne qui n'existe pas.

    La premiere version de cette fonction attrapait `KeyError`/`ValueError` pour
    « refuser » ce cas. Le test l'a montre mort : l'organe ne leve jamais la. Un
    garde branche sur un signal que personne n'emet se relit comme une protection
    et n'en est pas une — il est retire plutot que garde « au cas ou ».
    """
    portee = args.get("portee") or args.get("scope_observation") or "tout"
    try:
        import sys as _s
        from pathlib import Path as _P
        _racine = str(_P(__file__).resolve().parent.parent)
        if _racine not in _s.path:
            _s.path.insert(0, _racine)
        from app.forge_runtime_observer import observer, observer_tout
    except Exception as e:  # noqa: BLE001
        return False, "organe d'observation indisponible (%s)" % type(e).__name__
    try:
        if portee == "tout":
            return True, observer_tout()
        return True, observer(str(portee))
    except Exception as e:  # noqa: BLE001 — un observateur ne casse pas son appelant
        return False, "observation impossible (%s)" % type(e).__name__


_TABLE = {"repo_info": _op_repo_info, "branch_head": _op_branch_head,
          "runtime_observe": _op_runtime_observe,
          "commit_info": _op_commit_info, "compare": _op_compare,
          "read_file": _op_read_file}

#: Ce que chaque verbe attend. Sert a DECRIRE, jamais a router : le routage reste
#: `_TABLE`, une table figee. Un client qui inventerait un champ ne gagnerait rien.
_SCHEMAS = {
    "repo_info": {"repo": "owner/name du depot, dans la liste blanche"},
    "branch_head": {"repo": "owner/name", "branch": "nom de branche"},
    "commit_info": {"repo": "owner/name", "sha": "sha de 7 a 40 caracteres"},
    "compare": {"repo": "owner/name", "base": "sha ou branche",
                "head": "sha ou branche"},
    "read_file": {"repo": "owner/name", "path": "chemin dans le depot",
                  "ref": "branche ou sha (optionnel)"},
}


def schema_openapi(base_url: str = "") -> dict:
    """Schema OpenAPI 3.1 de la surface publique.

    Un client externe -- une Action ChatGPT, par exemple -- ne peut declarer que ce
    qu'un schema decrit. On le SERT donc, plutot que de le tenir a jour a la main
    dans un coin : il est genere depuis `OPERATIONS`, si bien qu'une operation
    ajoutee ou retiree ne peut pas diverger de ce que la passerelle execute.

    Il ne divulgue aucun secret et aucune adresse : seulement les cinq verbes, leurs
    champs, et le fait que tout passe par une habilitation porteuse.
    """
    chemins = {}
    for nom in OPERATIONS:
        champs = _SCHEMAS[nom]
        chemins["/v1/" + nom] = {
            "post": {
                "operationId": nom,
                "summary": "lecture GitHub : %s" % nom,
                "security": [{"habilitation": []}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {c: {"type": "string", "description": d}
                                       for c, d in champs.items()},
                        "required": [c for c in champs if c != "ref"],
                        "additionalProperties": False,
                    }}},
                },
                "responses": {
                    "200": {"description": "donnee lue",
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {"ok": {"type": "boolean"},
                                               "data": {"type": "object"}}}}}},
                    "403": {"description": "habilitation, depot ou adresse refuses"},
                },
            }
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Nokido GitHub bridge (lecture seule)",
                 "version": "1.0.0",
                 "description": "Cinq operations de LECTURE sur une liste blanche "
                                "de depots. Aucune ecriture n'existe."},
        "servers": [{"url": base_url or "https://exemple.invalid"}],
        "paths": chemins,
        "components": {"securitySchemes": {
            "habilitation": {"type": "http", "scheme": "bearer",
                             "description": "capacite attenuee : audience, portee, "
                                            "ressource, expiration, usage unique"}}},
    }


# FRONTIERE DE CAPACITE : quelle portee autorise quelle operation.
#
# Posee le 2026-09-19, AVANT d'ajouter une seconde portee — et c'est tout le
# sujet. Jusqu'ici la portee etait verifiee UNE FOIS, a la porte
# (`scope not in portees`), et c'etait sain parce qu'il n'y en avait qu'une :
# la porte et la capacite coincidaient. Le jour ou une seconde apparait, par
# exemple une lecture du runtime, un jeton portant l'une OU l'autre franchit la
# meme porte et rien en aval ne distingue les operations atteignables.
#
# Ce n'est pas une faille cryptographique, c'est une ABSENCE DE FRONTIERE. Et
# l'ordre est l'inverse de l'intuition : la table d'abord, la portee ensuite.
# Un fil de detente (`tests/nr/test_pont_portee_par_outil_nr.py`) rougit si une
# seconde portee arrive SANS cette table ; il reconnait les portees a leur FORME
# (`domaine:action`) et non a leur nom, pour qu'un nom inattendu ne passe pas
# inapercu.
#
# TOUTE operation doit figurer ici : une operation absente est REFUSEE, jamais
# autorisee par defaut. C'est la difference entre une liste blanche et une liste
# noire, et ce depot a deja paye la seconde.
# Seconde portee, ajoutee le 2026-09-19 APRES la table ci-dessous et jamais
# avant. Elle ouvre en LECTURE l'etat du runtime — ce que le code commite ne dit
# pas : quel processus tourne, quelle base est ouverte, quelles files attendent.
# L'organe observe (`app/forge_runtime_observer.py`) est prouve en lecture seule
# par son propre NR (aucun subprocess, aucun `eval`, aucune ouverture en
# ecriture, aucun SQL mutant, et d'une variable d'environnement il ne rend que
# la PRESENCE, jamais la valeur).
SCOPE_RUNTIME = "runtime:read"
# La ressource d'une habilitation runtime n'est pas un depot : c'est l'instance.
RESSOURCE_RUNTIME = "runtime:local"
PORTEES_CONNUES = (SCOPE, SCOPE_RUNTIME)

PORTEE_PAR_OUTIL: dict[str, str] = {
    "repo_info": "github:read",
    "branch_head": "github:read",
    "commit_info": "github:read",
    "compare": "github:read",
    "read_file": "github:read",
    # Lecture du runtime : une seule operation, parametree par une portee
    # d'observation declaree par l'organe. Une operation par portee multiplierait
    # les surfaces sans rien ajouter.
    "runtime_observe": SCOPE_RUNTIME,
}


def portee_autorise(operation: str, portees) -> bool:
    """La portee presentee couvre-t-elle CETTE operation ?

    Liste BLANCHE : une operation qu'on ne sait pas classer n'est pas autorisee.
    Une portee absente ou vide ne vaut pas « toutes » — c'est la confusion
    `UNKNOWN`/`OUI` que la constitution semantique interdit.
    """
    attendue = PORTEE_PAR_OUTIL.get(operation)
    if not attendue:
        return False
    if isinstance(portees, str):
        portees = [portees]
    return attendue in {str(p) for p in (portees or [])}


def traiter(operation, args, capacite) -> tuple:
    """Point d'entree unique. Rend (succes, resultat|motif).

    L'ordre compte : on verifie l'habilitation AVANT de regarder l'operation,
    l'operation AVANT sa portee, et la portee AVANT de toucher au reseau. Un
    refus ne doit jamais avoir emis d'appel sortant -- les NR le verifient en
    comptant les appels.
    """
    charge, motif = _lire_capacite(capacite)
    if motif:
        return False, motif
    if not isinstance(operation, str) or operation not in _TABLE:
        return False, "operation inconnue"
    # FRONTIERE PAR OUTIL, et non plus seulement a la porte (cf.
    # `PORTEE_PAR_OUTIL`). Le refus NOMME la portee manquante : un refus opaque
    # se lit comme une panne et fait chercher au mauvais endroit.
    _portees = charge.get("scopes") or charge.get("scope") or []
    if not portee_autorise(operation, _portees):
        return False, ("portee insuffisante pour « %s » : il faut « %s »"
                       % (operation, PORTEE_PAR_OUTIL.get(operation, "(operation non classee)")))
    if not isinstance(args, dict):
        return False, "arguments inattendus"
    # LA RESSOURCE SE VERIFIE SELON LA PORTEE, pas uniformement. Une habilitation
    # GitHub est liee a UN depot, que l'appelant doit redire : c'est ce qui
    # empeche un jeton d'un depot d'en lire un autre. Une habilitation runtime
    # porte l'instance, qu'aucun argument client ne designe — exiger un `repo`
    # la rendrait inutilisable, et accepter n'importe quoi retirerait la liaison
    # a la ressource pour TOUT LE MONDE.
    if PORTEE_PAR_OUTIL.get(operation) == SCOPE_RUNTIME:
        if charge.get("resource") != RESSOURCE_RUNTIME:
            return False, "habilitation runtime liee a une autre ressource"
    elif args.get("repo") != charge.get("resource"):
        return False, "depot hors de l'habilitation presentee"
    if not _debit_ok(str(charge.get("sub", "?"))):
        return False, "debit depasse"
    return _TABLE[operation](args)


# ------------------------------------------------------------------- transport

def construire_app():
    """Routes EXPLICITES, une par verbe. Aucune route generique, aucun catch-all."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def _porteur(requete) -> str:
        brut = requete.headers.get("authorization", "")
        return brut[7:].strip() if brut[:7].lower() == "bearer " else ""

    def _pair(requete) -> str:
        client = getattr(requete, "client", None)
        return getattr(client, "host", "") or ""

    def _admis(requete) -> bool:
        return adresse_admise(_pair(requete),
                              requete.headers.get("x-forwarded-for", ""))

    def _fabrique(nom: str):
        async def _route(requete):
            if not _admis(requete):
                _LOG.info("[bridge] appel refuse : adresse hors liste blanche")
                return JSONResponse({"ok": False, "error": "adresse non autorisee"},
                                    403)
            try:
                corps = await requete.json()
            except Exception:  # noqa: BLE001
                return JSONResponse({"ok": False, "error": "corps JSON invalide"}, 400)
            if not isinstance(corps, dict):
                return JSONResponse({"ok": False, "error": "corps inattendu"}, 400)
            ok, res = traiter(nom, corps, _porteur(requete))
            if not ok:
                _LOG.info("[bridge] refus sur %s : %s", nom, res)
                return JSONResponse({"ok": False, "error": res}, 403)
            return JSONResponse({"ok": True, "data": res})
        return _route

    async def sante(requete):
        if not _admis(requete):
            return JSONResponse({"ok": False, "error": "adresse non autorisee"}, 403)
        return JSONResponse({"ok": True, "operations": list(OPERATIONS),
                             "repos": sorted(DEPOTS_AUTORISES)})

    async def schema(requete):
        if not _admis(requete):
            return JSONResponse({"ok": False, "error": "adresse non autorisee"}, 403)
        base = str(requete.base_url).rstrip("/")
        return JSONResponse(schema_openapi(base))

    routes = [Route("/health", sante, methods=["GET"]),
              Route("/openapi.json", schema, methods=["GET"])]
    routes += [Route("/v1/" + nom, _fabrique(nom), methods=["POST"])
               for nom in OPERATIONS]
    return Starlette(routes=routes)


def main(argv=None) -> int:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=HOTE_PAR_DEFAUT,
                    help="defaut loopback ; ouvrir au reseau est un geste explicite")
    ap.add_argument("--port", type=int, default=PORT_PAR_DEFAUT)
    opts = ap.parse_args(argv)
    if opts.host not in ("127.0.0.1", "localhost"):
        _LOG.warning("[bridge] ecoute sur %s : joignable hors de cette machine ; "
                     "adresses admises = %s", opts.host, sorted(adresses_autorisees()))
    uvicorn.run(construire_app(), host=opts.host, port=opts.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())