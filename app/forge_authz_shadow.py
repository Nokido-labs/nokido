"""Observation d'autorisation sur :8766 -- SHADOW, ne refuse RIEN.

__FORGE_COLOR__ = "immunitaire/tracabilite-des-appelants"

POURQUOI CE MODULE
==================
Mesure du 2026-09-02 sur les 81 routes declarees du hub : 41 sondables en GET,
dont **32 repondent 200 sans le moindre jeton** (3 sensibles), 5 refusent en
401, 3 redirigent vers une cible protegee. Les 40 autres (POST ou chemin
parametre) restent **UNKNOWN** : les mesurer exigerait de declencher la mutation
qu'on veut justement gouverner. Elles ne sont ni ouvertes ni protegees.

Ce module n'AUTORISE ni ne REFUSE rien. Il repond a une question que le corps ne
sait pas poser aujourd'hui : *qui* appelle *quoi*, sous quelle identite, depuis
quel processus. Sans cette matrice, armer un refus serait un pari -- et le pari
se paierait sur `/api/resource/should_spawn`, appelee par le superviseur
lui-meme : couper la regulation en croyant proteger le corps.

CE QU'IL N'EST PAS
------------------
**Pas un second systeme d'identite.** L'identite reste resolue par le chemin
existant du hub (`_resolve_ring` -> CapabilityToken ou HMAC -> `forge_videur`),
qui est injecte ici en callable. Le middleware du web_hub (`AuthMiddleware`)
n'est deliberement PAS reutilise : il authentifie un HUMAIN par cookie JWT et
formulaire de login, quand `:8766` authentifie des AGENTS par Bearer. Partager
le premier reviendrait a exiger un cookie de navigateur de processus machine.

**Pas un decouvreur de processus.** La resolution PID delegue a
`forge_port_callers._attribuer`, qui remonte deja la chaine des parents -- un
service `runAs=interactive` passe par un lanceur, donc le PID qui ouvre la
connexion n'est PAS celui du registre.

TROIS ETATS PARTOUT
-------------------
`SHADOW_ALLOW` / `SHADOW_DENY` / `AUTHZ_UNKNOWN`, et pour l'appelant :
pid trouve / **acces refuse** / **introuvable**. Une route absente de la matrice
ne devient jamais PUBLIC par defaut : elle sort en `AUTHZ_UNKNOWN`, a instruire.
"""
from __future__ import annotations

# Import oublie, mesure le 2026-09-08 : List[str] L489.
from typing import List

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__all__ = [
    "CLASSES", "PUBLIC_DECLARE", "classer_route", "decider",
    "resoudre_appelant", "trace_de", "observer", "matrice", "actif",
]

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "sandbox" / "authz_shadow.jsonl"
_TAILLE_MAX = 8 * 1024 * 1024

# TROIS AXES SEPARES -- la correction du 2026-09-02, apres le finding M2M #4.
#
# L'ancienne classe unique melangeait `LOCAL` (une propriete de TRANSPORT) avec
# PUBLIC/AUTH/ADMIN (des proprietes d'AUTORISATION). Le glissement etait
# invisible et fatal : proposer LOCAL pour 35 routes PARCE QU'un appelant local
# avait ete observe faisait de la provenance une autorisation par la porte de
# derriere -- exactement l'invariant que `decider()` protege par ailleurs. Un
# PID se reutilise, un nom de processus s'usurpe, et tout script tournant sur
# la machine aurait herite des droits sans jamais s'authentifier.
#
#   localite  != identite
#   identite  != autorisation
#   PID       != identite
#
# L'EXPOSITION dit jusqu'ou la route est joignable. Elle ne dit RIEN de la
# confiance : `LOCAL_ONLY` n'est pas `TRUSTED`.
EXPOSITIONS = ("PUBLIC", "LOCAL_ONLY", "UNKNOWN")

# L'AUTHENTIFICATION dit si une identite est exigee. C'est le SEUL axe que
# `decider()` consulte.
AUTHENTIFICATIONS = ("NONE", "REQUIRED", "UNKNOWN")

# Conserve pour les lecteurs existants : les verdicts, pas les classes.
CLASSES = ("PUBLIC", "LOCAL_ONLY", "UNKNOWN")

# Declaration EXPLICITE par route : exposition ET authentification, separement.
# Une entree ici est une decision prise, jamais une observation promue.
DECLARE: Dict[str, Dict[str, str]] = {
    "/health": {
        "exposure": "PUBLIC",
        "authentication": "NONE",
        "motif": "sonde de vie : doit repondre meme quand l'auth est cassee. "
                 "CONTRAINTE, pas commodite -- supervisor.ts la sonde via "
                 "probeHttp et un echec incremente _hubHealthFails jusqu'a "
                 "SIGTERM + restart du hub ; l'authentifier ferait lire un "
                 "REFUS comme un wedge et le superviseur tuerait le hub en "
                 "boucle. `authentication: NONE` est ici EXCEPTIONNEL et motive.",
    },
    # 2026-09-24, cloture du chantier d'authentification : deux routes en LECTURE PURE,
    # decidees publiques sur mesure du code (aucun effet), verrouillees par un NR de
    # non-mutation (tests/nr/test_routes_organes_authentifiees_nr.py).
    "/api/rag/tokenize": {
        "exposure": "PUBLIC",
        "authentication": "NONE",
        "motif": "calcul pur : compte des tokens sur un texte BORNE a 50 000 caracteres, "
                 "aucune donnee lue ni ecrite. Appelant : rag_dashboard.html (navigateur).",
    },
    "/api/sandbox/runtimes": {
        "exposure": "PUBLIC",
        "authentication": "NONE",
        "motif": "liste statique des runtimes WHITELISTES (list_allowed_runtimes), lecture "
                 "seule, aucune donnee utilisateur. Aucun appelant au depot.",
    },
    # /api/push SORTIE de la liste publique le 2026-09-26, DECISION OWNER : la route est RETIREE (410
    # `gone`, aucun effet, aucun appelant mesure) et une route retiree n'a pas a elargir la surface
    # publique declaree (plafond de 3, test_authz_shadow_nr). Elle n'est PAS declaree REQUIRED pour
    # autant : son handler du hub ne porte aucune garde, et le declarer l'affirmerait a tort. Elle
    # redevient NON TRANCHEE (AUTHZ_UNKNOWN), ce qui est son etat reel.
}

# Appelants internes OBSERVES. Etre observe ne vaut PAS etre autorise : ces
# routes sont `LOCAL_ONLY` (transport) et `UNKNOWN` en authentification, tant
# qu'aucune identite de service n'a ete delivree a leur appelant. C'est
# precisement le glissement que le finding M2M #4 a designe.
INTERNE_OBSERVE: Dict[str, str] = {
    "/api/resource/should_spawn":
        "appelee par proxy_deno/core/supervisor.ts (deno.exe, PID mesure). "
        "PROVENANCE etablie, IDENTITE absente : le chemin cible est une "
        "identite de service SERVICE_SUPERVISOR porteuse d'un token, puis "
        "capability resource.read via le videur. Pas avant.",
    # /api/services/list et /api/sandbox/runtimes SORTIES le 2026-09-24 : la premiere
    # est tranchee REQUIRED (AUTH_REQUISE), la seconde declaree PUBLIC (DECLARE).
}

# Compatibilite de lecture : l'ancien nom, derive de la declaration.
# Vues derivees, pour les lecteurs existants. Elles ne portent AUCUNE decision.
PUBLIC_DECLARE: Dict[str, str] = {
    r: d["motif"] for r, d in DECLARE.items() if d["exposure"] == "PUBLIC"
}

# Routes que le corps s'appelle a lui-meme sans jeton, connues et a instruire.
# Elles ne sont PAS autorisees ici -- elles sont NOMMEES, pour que la phase
# d'observation dise qui les appelle vraiment avant qu'on leur attribue une
# identite de service et une capability minimale.
# Alias historique. Le nom `LOCAL` ne designe PLUS une autorisation : ces routes
# sont `LOCAL_ONLY` en exposition et `UNKNOWN` en authentification.
LOCAL_A_INSTRUIRE: Dict[str, str] = INTERNE_OBSERVE


def actif() -> bool:
    """L'observation tourne-t-elle ? Desarmee par defaut.

    Meme en SHADOW, observer a un cout (journal, resolution PID). Un drapeau
    permet de l'eteindre sans redeployer si le hub souffre.
    """
    from nokido_agent.app.forge_drapeau_env import actif as _drapeau

    return _drapeau("LAFORGE_AUTHZ_SHADOW", True)


# --------------------------------------------------------------------------- #
# Decision THEORIQUE -- fonctions pures, aucun effet
# --------------------------------------------------------------------------- #

# Routes dont la politique a ete TRANCHEE apres observation. Vides aujourd'hui,
# et c'est le fait le plus important de ce module : la matrice se remplit avec
# des mesures, jamais avec des suppositions. Tant qu'une route n'est pas ici,
# elle sort en AUTHZ_UNKNOWN -- ni autorisee, ni refusee, A INSTRUIRE.
# Routes dont l'AUTHENTIFICATION a ete tranchee apres observation. Vide
# aujourd'hui, et c'est le fait le plus important du module : elle se remplira
# de mesures, jamais de suppositions, et surtout jamais d'une provenance
# observee. Tant qu'une route n'y est pas, elle sort en AUTHZ_UNKNOWN.
AUTH_REQUISE: Dict[str, str] = {
    # 2026-09-24, cloture du chantier d'authentification. Mesure : AUCUN appel observe
    # sur ces trois routes dans le journal du jour (depuis 09:22) ; chaque appelant du
    # depot presente desormais le porteur rendu par forge_hub_client.entetes_organe
    # (jeton propre, sinon SERVICES, jamais le maitre). Garde : `_exiger_identite`.
    "/api/services/list": (
        "TRANCHEE 2026-09-24 : TOPOLOGIE des services (CONFIDENTIAL). Mesure : 0 appel "
        "au journal d'observation du jour (09:22 -> 16:16) ; lecteurs au depot inventories "
        "(laforge_tui, agent_sre_observabilite), dotes du porteur d'organe."
    ),
    "/api/ingest": (
        "TRANCHEE 2026-09-24 : ECRIT dans le RAG. Mesure : 0 appel au journal "
        "d'observation du jour ; appelants au depot inventories (forge_clawhub_bridge "
        "SAST, forge_dsl INGEST), dotes du porteur d'organe."
    ),
    "/nervous_system/emit": (
        "TRANCHEE 2026-09-24 : INJECTE un evenement dans le systeme nerveux (Deno "
        ":8000/event). Mesure : 0 appel au journal d'observation du jour ; appelant "
        "au depot inventorie (forge_dt_router_wire), dote du porteur d'organe."
    ),
    "/mcp": (
        "TRANCHEE 2026-09-02 sur mesure : 538 appels authentifies sur 541, "
        "11 identites distinctes (GEMINI, CLAUDE, COAGULATION, CLAUDE_HOOK, "
        "RESCUE, ORGAN_PULSE, ANTIGRAVITY, STATE_ENCODER, OPENAI_PROXY, "
        "DENOHUBMCP, TASK_EXECUTOR), rings 1 a 4. Les 3 exceptions sont MES "
        "propres sondes d'audit, identifiees par leur signature (rafale de "
        "routes dans la meme seconde) et par le fuseau du journal. La route "
        "REFUSE deja en 401 sans jeton : declarer REQUIRED ENTERINE l'existant, "
        "ca ne l'impose pas."
    ),
    "/api/resource/should_spawn": (
        "TRANCHEE 2026-09-02 apres bascule MESUREE : dernier appel anonyme a "
        "10:14:24, premier SUPERVISOR a 10:22:36, et ZERO anonyme depuis sur "
        "209 appels. Les 517 anonymes du journal sont tous anterieurs au "
        "cablage de l'identite. ATTENTION avant tout enforcement : le "
        "superviseur doit avoir REDEMARRE apres le semis de "
        "FORGE_TOKEN_SUPERVISOR, sinon il porte encore le master ; et un 401 "
        "ici DIFFERE le demarrage des services (par conception, cf. le contrat "
        "AUTHZ_DENIED != SERVICE_DEAD). C'est la route ou une erreur se paierait "
        "le plus cher."
    ),
    "/inbox/agt_gemini": (
        "TRANCHEE 2026-09-02 : 4 appels sur 4 authentifies, tous GEMINI ring 1. "
        "Aucun appelant anonyme observe. Volume faible -- la conclusion tient "
        "sur peu de trafic, a re-mesurer si un client anonyme apparait."
    ),
}

# Compat : anciens noms, desormais sans effet sur la decision.
AUTH_DECLARE: Dict[str, str] = AUTH_REQUISE
ADMIN_DECLARE: Dict[str, str] = {}


def exposition_de(route: str) -> Tuple[str, str]:
    """Jusqu'ou la route est joignable. TRANSPORT, jamais confiance.

    `LOCAL_ONLY` n'est PAS `TRUSTED` : un script lance sur la machine reste un
    client non authentifie. Cette fonction existe pour la documentation et le
    futur edge (`:8766` local vs `:8443` mTLS) -- `decider()` ne l'appelle pas,
    et un test verifie qu'il ne l'appellera jamais.
    """
    d = DECLARE.get(route)
    if d:
        return d["exposure"], d["motif"]
    if route in INTERNE_OBSERVE:
        return "LOCAL_ONLY", INTERNE_OBSERVE[route]
    return "UNKNOWN", "exposition non declaree"


def authentification_de(route: str) -> Tuple[str, str]:
    """Une identite est-elle exigee ? SEUL axe que la decision consulte.

    `NONE` doit rester EXCEPTIONNEL et motive : c'est le seul etat qui autorise
    sans identite. `UNKNOWN` est la valeur par defaut, volontairement majoritaire
    tant que la matrice n'est pas construite -- une route dont personne n'a
    tranche l'authentification ne se traite ni comme ouverte ni comme protegee.
    """
    d = DECLARE.get(route)
    if d:
        return d["authentication"], d["motif"]
    if route in AUTH_REQUISE:
        return "REQUIRED", AUTH_REQUISE[route]
    if route in INTERNE_OBSERVE:
        return "UNKNOWN", (
            "appelant interne OBSERVE, identite NON delivree : la provenance "
            "n'authentifie pas. " + INTERNE_OBSERVE[route])
    return "UNKNOWN", "route absente de la matrice : a instruire, pas a autoriser"


def classer_route(route: str) -> Tuple[str, str]:
    """DEPRECIE -- rend l'EXPOSITION, qui n'est plus un verdict d'autorisation.

    Conserve pour les lecteurs existants. Le melange des deux axes dans une
    classe unique est precisement le defaut corrige le 2026-09-02 : se servir de
    ce retour pour decider ferait de la localite une autorisation.
    """
    return exposition_de(route)


def decider(route: str, ring: int, agent: str, via: str = "") -> Dict[str, Any]:
    """Ce qu'un enforcement RENDRAIT. N'applique rien.

    INVARIANT -- LE PID N'EST PAS UNE AUTORISATION.
    Cette signature ne prend NI pid, NI process, NI service, et ce n'est pas un
    oubli : c'est le garde. Le PID prouve la PROVENANCE d'un appel ; le droit
    d'agir vient du videur, jamais du nom d'un executable. Ecrire un jour
    `if process == "supervisor.exe": ALLOW` ferait du nom de binaire un
    credential -- or un nom de processus s'usurpe, et l'usurpateur heriterait
    du privilege du superviseur. La provenance NOMME l'appelant pour qu'on lui
    attribue ensuite une identite de service et une capability ; elle ne le
    remplace pas. Un test verrouille cette signature.

    `ring` suit la convention du hub : plus PETIT = plus privilegie, et **-1
    signifie que l'authentification a ECHOUE** (pas d'en-tete, jeton invalide,
    capability expiree). Confondre -1 avec « ring tres bas donc admin » serait
    lire un echec comme un privilege.
    """
    # L'EXPOSITION N'ENTRE PLUS DANS LA DECISION -- correction du 2026-09-02,
    # finding M2M #4. Auparavant `classer_route` melangeait la localite et
    # l'autorisation, si bien qu'une route classee LOCAL parce qu'un appelant
    # local avait ete OBSERVE devenait autorisee de fait : la provenance
    # redevenait un credential, malgre l'invariant qui protege cette fonction
    # du PID. Seule l'authentification est consultee ici ; `exposition_de` est
    # deliberement NON appelee, et un test le verifie.
    _auth, motif = authentification_de(route)
    classe = {"NONE": "PUBLIC", "REQUIRED": "AUTH"}.get(_auth, "UNKNOWN")
    authentifie = isinstance(ring, int) and ring >= 0

    if classe == "PUBLIC":
        return {"decision": "SHADOW_ALLOW", "classe": classe,
                "reason": "publique par declaration : %s" % motif}
    # Une route dont la politique n'a JAMAIS ete tranchee ne peut pas etre
    # « refusee » : un DENY affirmerait une decision que personne n'a prise, et
    # gonflerait le compteur de refus theoriques d'un bruit qui n'apprend rien.
    # Elle sort en AUTHZ_UNKNOWN, avec ou sans identite. C'est la sortie
    # majoritaire au debut de l'observation, et c'est l'etat REEL du corps.
    if classe == "UNKNOWN":
        return {"decision": "AUTHZ_UNKNOWN", "classe": classe,
                "reason": "route non classee (%s) ; identite=%s ring=%s : %s"
                          % (route, agent or "aucune", ring, motif)}
    if not authentifie:
        if classe == "LOCAL":
            return {"decision": "AUTHZ_UNKNOWN", "classe": classe,
                    "reason": "appel interne presume sans identite (%s) -- "
                              "identifier l'appelant AVANT de refuser : %s"
                              % (agent or "sans agent", motif)}
        # AUTH/ADMIN : la politique EST tranchee, l'identite manque. Seul cas
        # ou un refus theorique veut dire quelque chose.
        return {"decision": "SHADOW_DENY", "classe": classe,
                "reason": "route %s exige une identite, aucune prouvee "
                          "(ring=%r, agent=%r, via=%r)" % (classe, ring, agent, via)}
    return {"decision": "SHADOW_ALLOW", "classe": classe,
            "reason": "identite prouvee : %s ring %s via %s" % (agent, ring, via or "?")}


# --------------------------------------------------------------------------- #
# Appelant -- delegue a forge_port_callers, jamais reimplemente
# --------------------------------------------------------------------------- #

_CACHE_CONN: Dict[str, Any] = {"ts": 0.0, "par_port": {}, "raison": "",
                               "dernier_refresh_miss": 0.0}
_TTL_CONN = 2.0
# Chaine d'ancetres par pid (2026-10-01) : sous Windows chaque `parent()` re-enumere
# TOUS les processus ; 4 niveaux = ~1 s, sur la boucle du hub (7 gels, 7,6 s en 7 jours,
# journal de forge_loop_sentinel), pour un appelant qui revient avec le MEME pid.
_CACHE_ANCETRES: Dict[int, Tuple[float, int, List[str]]] = {}
_TTL_ANCETRES = 15.0
# Budget de rafraichissement sur echec : `net_connections` coute cher et
# `/api/resource/should_spawn` arrive ~40 fois par minute. Sans plafond, chaque
# miss declencherait un balayage complet des sockets.
_THROTTLE_MISS = 1.0


# --------------------------------------------------------------- porteurs
# Le `via` decrit la FORME du credential presente. Il ne DECIDE rien :
# l'autorisation reste au videur. C'est pour cela qu'il peut distinguer un
# jeton a bail REFUSE d'une chaine inconnue sans verifier de signature --
# les deux etats sont egalement non-autorisants.
#
# MESURE qui a impose ce classement (2026-09-02) : un jeton a bail
# parfaitement valide (HTTP 200, ring resolu identique au statique) sortait
# `bearer_inconnu`, le MEME mot que le `bad_token` refuse 18 fois dans la
# meme fenetre. Cabler les organes sur des jetons a bail aurait donc rendu
# leur trafic legitime indistinguable d'un intrus : un durcissement qui
# DEGRADE la tracabilite qu'il est cense servir.

PORTEURS = (
    "bearer_maitre",             # passe-partout : peut usurper toute identite
    "bearer_derive",             # credential statique d'organe (permanent)
    "bearer_capability",         # jeton a bail, decodage VERIFIE
    "bearer_capability_refuse",  # forme de jeton a bail, verification REFUSEE
    "bearer_inconnu",            # ne ressemble a aucun credential connu
    "bearer_indecidable",        # comparaison impossible : ni oui, ni non
    "header_agent",              # se declare, ne prouve rien
    "anonyme",
)


def ressemble_a_capability(jeton: str) -> bool:
    """FORME seulement : payload JSON portant `sub`, en 2 OU 3 segments.

    Ne prouve RIEN sur la validite -- un jeton forge passe ce test. Sert
    uniquement a separer `bearer_capability_refuse` de `bearer_inconnu`,
    deux etats qui n'autorisent ni l'un ni l'autre.

    DEFAUT MESURE LE JOUR MEME DE L'ECRITURE (2026-09-02) : cette fonction
    n'acceptait qu'UN point, alors que les jetons reellement emis par le corps
    en portent DEUX -- `payload.hmac.signature_tpm`, le troisieme segment
    venant de `encode(tpm_sign=True)`. Consequence : un jeton a bail EXPIRE
    retombait en `bearer_inconnu`, c'est-a-dire exactement le mot du
    `bad_token` que ce module venait d'etre ecrit pour en distinguer.
    La cause du trou est instructive : le test forgeait ses propres jetons a
    deux segments et validait donc la convention de son auteur, pas la forme
    du corps. Un materiau de test fabrique ne mesure pas le monde -- depuis,
    un cas ancre la forme REELLE a trois segments.
    """
    if not jeton or jeton.count(".") not in (1, 2):
        return False
    tete = jeton.split(".", 1)[0]
    try:
        brut = base64.urlsafe_b64decode(tete + "=" * (-len(tete) % 4))
        charge = json.loads(brut.decode("utf-8"))
    except Exception:  # muet-ok : pas un payload lisible, donc pas la forme
        return False
    return isinstance(charge, dict) and "sub" in charge


# ── Axe TPM de l'observation (CAP V9, P4.3.3) ────────────────────────────
# CINQ etats. `EMIS_AVEC_TPM` n'est PAS atteignable depuis l'observation
# seule, et c'est voulu : voir `etat_tpm_observable`.
EMIS_AVEC_TPM = "EMIS_AVEC_TPM"
EMIS_SANS_TPM = "EMIS_SANS_TPM"
TPM_DEMANDE_REFUSEE = "TPM_DEMANDE_REFUSEE"
TPM_NON_DEMANDE = "TPM_NON_DEMANDE"
TPM_NON_MESURABLE = "NON_MESURABLE"


def etat_tpm_observable(jeton: str) -> Tuple[str, str]:
    """(etat, raison) de la dimension TPM d'un porteur. FORME seulement.

    UN TROISIEME SEGMENT N'EST PAS UNE PREUVE. Il est un INDICE STRUCTUREL :
    `encode(tpm_sign=True)` en ajoute un quand la signature a ete obtenue,
    mais rien ici ne verifie qu'il s'agit d'une signature valide, ni qu'elle
    correspond a l'identite annoncee. Un jeton forge en porte un aussi.

    C'est pourquoi `EMIS_AVEC_TPM` N'EST JAMAIS RENDU par cette fonction :
    l'observateur ne possede pas la cle publique et ne verifie rien. Un
    troisieme segment donne NON_MESURABLE, avec la raison qui le dit. Le
    classer « avec TPM » fabriquerait un taux de couverture a partir d'une
    forme -- exactement le genre de faux calme que la campagne traque.

    L'absence de troisieme segment, elle, est STRUCTURELLEMENT certaine : il
    n'y a aucun emplacement ou une preuve pourrait se trouver.
    """
    if not ressemble_a_capability(jeton):
        return TPM_NON_MESURABLE, "pas la forme d'un capability"
    if jeton.count(".") == 1:
        return EMIS_SANS_TPM, "deux segments : aucun emplacement de preuve"
    return TPM_NON_MESURABLE, ("segment de preuve present, validite NON "
                               "verifiee par l'observateur")


def classer_porteur(entete: str, *, est_maitre: Optional[Callable] = None,
                    est_statique: Optional[Callable] = None,
                    decoder: Optional[Callable] = None) -> str:
    """Etiquette d'observation pour l'en-tete Authorization presente.

    Le jeton n'est ni retourne ni journalise : on compare, on garde le
    verdict. Les comparateurs sont INJECTES -- le hub detient les secrets,
    ce module ne les lit pas.

    `decoder` rend un objet pour un jeton a bail verifie, None sinon. Son
    absence n'est pas un refus : sans decodeur, un jeton de la bonne forme
    sort `bearer_indecidable`, parce que « je n'ai pas pu regarder » n'est
    pas « invalide ».
    """
    if not entete or not entete.lower().startswith("bearer "):
        return ""
    jeton = entete[7:].strip()
    if not jeton:
        return "bearer_indecidable"
    try:
        if est_maitre is not None and est_maitre(jeton):
            return "bearer_maitre"
        if est_statique is not None and est_statique(jeton):
            return "bearer_derive"
    except Exception:  # une comparaison qui casse n'absout pas le porteur
        return "bearer_indecidable"
    forme = ressemble_a_capability(jeton)
    if decoder is None:
        return "bearer_indecidable" if forme else "bearer_inconnu"
    try:
        decode = decoder(jeton)
    except Exception:
        return "bearer_indecidable" if forme else "bearer_inconnu"
    if decode is not None:
        return "bearer_capability"
    return "bearer_capability_refuse" if forme else "bearer_inconnu"


def _table_connexions(psutil, force: bool = False) -> Tuple[Dict[int, int], str]:
    """{port_source: pid}, et la RAISON quand la table est vide.

    `net_connections()` est cher : on le met en cache 2 s. Et un refus de
    lecture n'est PAS « aucune connexion » -- sans cette distinction, un compte
    sans privilege rendrait « appelant introuvable » pour tout le monde, ce qui
    se lirait comme un corps sans appelants.
    """
    now = time.time()
    if not force and now - _CACHE_CONN["ts"] < _TTL_CONN:
        return _CACHE_CONN["par_port"], _CACHE_CONN["raison"]
    par_port: Dict[int, int] = {}
    raison = ""
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.pid and c.laddr:
                par_port[c.laddr.port] = c.pid
    except Exception as e:  # noqa: BLE001
        raison = "net_connections refuse (%s)" % type(e).__name__
    _CACHE_CONN.update({"ts": now, "par_port": par_port, "raison": raison})
    return par_port, raison


def resoudre_appelant(port_source: Optional[int]) -> Dict[str, Any]:
    """Qui a ouvert cette connexion. Trois etats, jamais une identite inventee.

    Rend toujours les clefs `pid`/`process`/`parent_pid`/`service`, a `None`
    quand on n'a pas pu voir, avec `raison` qui dit POURQUOI. Un appelant
    indeterminable reste `UNKNOWN` : lui coller un nom plausible ferait entrer
    une supposition dans une matrice d'autorisation.
    """
    vide = {"pid": None, "process": None, "parent_pid": None, "service": None}
    if not port_source:
        return dict(vide, raison="port source absent de la requete")
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return dict(vide, raison="psutil_absent")

    par_port, raison_table = _table_connexions(psutil)
    if raison_table:
        return dict(vide, raison=raison_table)
    pid = par_port.get(int(port_source))
    if pid is None:
        # Le cache a pu etre pris AVANT que cette connexion existe : mesure du
        # 2026-09-02, 33 appels sur 102 sortaient sans PID pour cette seule
        # raison. Une relecture immediate les recupere -- sous budget, sinon un
        # flux a 40 requetes/min declencherait autant de balayages de sockets.
        maintenant = time.time()
        if maintenant - _CACHE_CONN["dernier_refresh_miss"] >= _THROTTLE_MISS:
            _CACHE_CONN["dernier_refresh_miss"] = maintenant
            par_port, raison_table = _table_connexions(psutil, force=True)
            if raison_table:
                return dict(vide, raison=raison_table)
            pid = par_port.get(int(port_source))
    if pid is None:
        return dict(vide, raison="aucune socket ne porte ce port source apres "
                                 "relecture (connexion fermee, ou hors perimetre "
                                 "du compte)")
    out: Dict[str, Any] = {"pid": pid, "process": None,
                           "parent_pid": None, "service": None, "raison": ""}
    try:
        p = psutil.Process(pid)
        try:
            out["process"] = p.name()
        except Exception:  # noqa: BLE001
            out["raison"] = "nom du process illisible (compte)"
        try:
            par = p.parent()
            out["parent_pid"] = par.pid if par else None
        except Exception:  # muet-ok : parent optionnel ; `raison` porte deja le defaut principal
            pass
    except Exception as e:  # noqa: BLE001
        out["raison"] = "process %s illisible (%s)" % (pid, type(e).__name__)
        return out

    # Rattachement a un service supervise -- module existant, remonte les parents.
    try:
        from nokido_agent.app import forge_port_callers as pc

        nom, comment = pc._attribuer(pid, pc._registre(), psutil)
        out["service"] = nom
        out["service_via"] = comment
        if comment == "hors superviseur":
            # Le lanceur n'est PAS un service connu. Mesure du 2026-09-02 : un
            # `curl.exe` interrogeait /inbox/CLAUDE toutes les 5 minutes avec un
            # PID PARENT DIFFERENT a chaque fois -- des shells ephemeres. Le
            # parent immediat ne dit donc rien ; c'est plus haut dans la chaine
            # que se trouve le processus qui dure. Sans cette remontee, un
            # appelant periodique reste indefiniment « inconnu » alors qu'il a
            # un responsable stable a deux ou trois sauts.
            out["ancetres"] = _chaine_ancetres(psutil, pid)
    except Exception as e:  # noqa: BLE001
        out["raison"] = (out["raison"] + " ; " if out["raison"] else "") + \
            "rattachement service indisponible (%s)" % type(e).__name__
    return out


def _chaine_ancetres(psutil, pid: int, profondeur: int = 4) -> List[str]:
    """['curl.exe(123)', 'cmd.exe(456)', 'pwsh.exe(789)'] -- ou ce qu'on a pu voir.

    Rend une liste TRONQUEE et le dit (`...` final) plutot que de pretendre
    remonter jusqu'a la racine : un ancetre illisible (autre compte) arrete la
    chaine, et l'appelant doit savoir que la chaine s'est arretee la.
    """
    _deja = _CACHE_ANCETRES.get(pid)
    if _deja and time.time() - _deja[0] < _TTL_ANCETRES and _deja[1] == profondeur:
        return list(_deja[2])
    chaine: List[str] = []
    try:
        cur = psutil.Process(pid)
    except Exception:  # noqa: BLE001
        return ["illisible"]
    for _ in range(profondeur):
        try:
            chaine.append("%s(%d)" % (cur.name(), cur.pid))
        except Exception:  # noqa: BLE001
            chaine.append("illisible(%d)" % getattr(cur, "pid", -1))
            break
        try:
            cur = cur.parent()
        except Exception:  # noqa: BLE001
            chaine.append("parent illisible")
            break
        if cur is None:
            break
    else:
        chaine.append("...")   # tronquee : ne pas la lire comme complete
    if len(_CACHE_ANCETRES) > 512:  # borne : les pids passent, le cache ne grossit pas
        _CACHE_ANCETRES.clear()
    _CACHE_ANCETRES[pid] = (time.time(), profondeur, list(chaine))
    return chaine


# --------------------------------------------------------------------------- #
# Trace -- jamais de secret
# --------------------------------------------------------------------------- #

_INTERDITS = ("authorization", "cookie", "x-api-key", "token", "secret", "password")


def trace_de(route: str, methode: str, ring: int, agent: str, via: str,
             appelant: Dict[str, Any], scope_source: Optional[str] = None,
             verdict: Optional[Dict[str, Any]] = None,
             etat_tpm: Optional[str] = None,
             raison_tpm: str = "") -> Dict[str, Any]:
    """Ligne de journal. Ne contient AUCUN materiau d'authentification.

    Pas de Bearer, pas de JWT, pas de cookie, pas de corps de requete : un
    journal d'autorisation qui recopie les jetons transforme une trace en
    magasin de secrets, et il est lu par le RAG.
    """
    v = verdict or decider(route, ring, agent, via)
    t = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "route": route,
        "method": methode,
        "identity": agent or "UNKNOWN",
        "ring": ring,
        "scope": scope_source or "UNKNOWN",
        "via": via or "UNKNOWN",
        # Les deux axes sont traces SEPAREMENT : les fusionner est exactement le
        # defaut corrige le 2026-09-02. `exposure` documente la frontiere reseau
        # et n'a AUCUN effet sur `decision` -- il est ici pour le diagnostic et
        # le futur edge, pas pour la politique.
        "exposure": exposition_de(route)[0],
        "authentication": authentification_de(route)[0],
        "classe": v.get("classe"),
        "decision": v.get("decision"),
        "reason": v.get("reason"),
        "pid": appelant.get("pid"),
        "process": appelant.get("process"),
        "parent_pid": appelant.get("parent_pid"),
        "service": appelant.get("service"),
        "appelant_raison": appelant.get("raison") or "",
        # Chaine d'ancetres quand le lanceur n'est pas un service connu : sans
        # elle, un appelant periodique lance par des shells ephemeres reste
        # « inconnu » indefiniment (mesure : curl toutes les 5 min, PID parent
        # different a chaque fois).
        "ancetres": appelant.get("ancetres") or [],
        # Sonde de l'audit interne. Un instrument qui se mesure lui-meme
        # fabrique les anomalies qu'il rapporte : trois sondes ont ete relevees
        # comme « appels non authentifies sur /mcp » le 2026-09-02 avant qu'on
        # ne reconnaisse leur signature.
        #
        # ⚠ DETTE DE CABLAGE DECLAREE, mesuree en l'ecrivant : `_resolve_ring`
        # rend `(-1, "no_auth")` AVANT de lire `LaForge-Agent-Name` des lors
        # qu'il n'y a pas de Bearer -- et la sonde n'en porte pas, par
        # conception (elle doit mesurer ce qu'un anonyme obtient). L'en-tete
        # `AUDIT_PROBE` est donc EMIS par l'audit mais n'arrive pas jusqu'ici :
        # ce champ vaut False aujourd'hui, quoi qu'il arrive. Le rendre vrai
        # demande que le middleware lise l'en-tete brut de la requete et le
        # transmette -- un patch du hub, pas une correction ici. Il est ecrit
        # maintenant pour que le jour ou ce chemin existe, la place soit prete
        # et NOMMEE ; un test constate cette dette plutot que de la masquer.
        "sonde_interne": (agent or "").upper() == "AUDIT_PROBE",
        # AXE TPM (CAP V9, P4.3.3). Une ETIQUETTE, jamais le jeton : cette
        # fonction ne recoit aucun materiau d'authentification, et ce contrat
        # ne bouge pas. L'etat est calcule EN AMONT par `etat_tpm_observable`,
        # la ou le porteur est lu.
        #
        # Le defaut est NON_MESURABLE et non « sans TPM » : un appelant qui ne
        # fournit pas l'etat n'a pas mesure une absence, il n'a rien mesure du
        # tout. Les 2501 traces anterieures a ce champ sont dans ce cas.
        "etat_tpm": etat_tpm or TPM_NON_MESURABLE,
        "raison_tpm": raison_tpm or ("axe non renseigne par l'appelant"
                                     if not etat_tpm else ""),
    }
    for k in list(t):
        if any(x in k.lower() for x in _INTERDITS):
            t.pop(k)
    return t


def observer(trace: Dict[str, Any]) -> bool:
    """Ecrit une ligne. Rend False si l'ecriture a echoue -- jamais d'exception.

    L'appelant est un middleware : il ne doit JAMAIS casser une requete pour un
    journal. Mais l'echec est rendu, pas avale : un observateur muet qui croit
    observer est pire que pas d'observateur.
    """
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        if JOURNAL.exists() and JOURNAL.stat().st_size > _TAILLE_MAX:
            JOURNAL.replace(JOURNAL.with_suffix(".jsonl.1"))
        with JOURNAL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(trace, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001
        return False


def matrice(limite: int = 50000) -> Dict[str, Any]:
    """Agrege le journal : qui appelle quoi, et ce qu'on n'a pas pu voir.

    Le denominateur est rendu explicite (`lues`, `illisibles`) : sans lui, « 0
    appelant inconnu » ne se distingue pas de « je n'ai pas pu regarder ».
    """
    out: Dict[str, Any] = {"lues": 0, "illisibles": 0, "routes": {},
                           "decisions": {}, "appelants": {},
                           "pid_indetermine": 0, "journal": str(JOURNAL),
                           # AXE TPM. `sans_axe_tpm` compte les traces qui
                           # PRECEDENT ce champ : elles ne sont pas « sans
                           # TPM », elles n'ont PAS ETE MESUREES. Les fondre
                           # dans NON_MESURABLE perdrait la distinction entre
                           # « l'instrument a regarde et n'a pas pu trancher »
                           # et « l'instrument ne regardait pas encore ».
                           "tpm": {}, "sans_axe_tpm": 0}
    if not JOURNAL.exists():
        out["raison"] = "aucun journal : l'observation n'a pas encore tourne"
        return out
    with JOURNAL.open(encoding="utf-8", errors="replace") as fh:
        for i, ligne in enumerate(fh):
            if i >= limite:
                break
            try:
                t = json.loads(ligne)
            except Exception:  # noqa: BLE001
                out["illisibles"] += 1
                continue
            out["lues"] += 1
            r = t.get("route", "?")
            d = t.get("decision", "?")
            out["routes"].setdefault(r, {"n": 0, "decisions": {}, "appelants": {}})
            out["routes"][r]["n"] += 1
            out["routes"][r]["decisions"][d] = out["routes"][r]["decisions"].get(d, 0) + 1
            qui = t.get("service") or t.get("process") or "UNKNOWN"
            out["routes"][r]["appelants"][qui] = out["routes"][r]["appelants"].get(qui, 0) + 1
            out["decisions"][d] = out["decisions"].get(d, 0) + 1
            out["appelants"][qui] = out["appelants"].get(qui, 0) + 1
            if t.get("pid") is None:
                out["pid_indetermine"] += 1
            if "etat_tpm" in t:
                e = t.get("etat_tpm") or TPM_NON_MESURABLE
                out["tpm"][e] = out["tpm"].get(e, 0) + 1
            else:
                out["sans_axe_tpm"] += 1
    return out


def enveloppe_m2m(pointer_ref: str, sujet: str = "") -> Dict[str, Any]:
    """Sortie M2M : un POINTEUR, jamais le contenu.

    Le detail (routes, appelants, PID) reste dans le journal ; le message porte
    de quoi aller le chercher. Un pair peut ainsi verifier un appelant sans
    recevoir la matrice.
    """
    if not pointer_ref:
        raise ValueError("pointer_ref obligatoire : un M2M sans pointeur oblige "
                         "a mettre le contenu dans le message")
    return {"intent": "AUTHZ_OBSERVATION", "pointer_ref": pointer_ref,
            "sender": "CLAUDE", "audience": "*",
            "summary": (sujet or "observation d'autorisation :8766")[:120]}


def _main(argv=None) -> int:
    """Lecture de la matrice observee. N'ecrit rien, ne decide rien."""
    import argparse

    ap = argparse.ArgumentParser(description="Matrice d'observation :8766 (SHADOW)")
    ap.add_argument("--sensibles", action="store_true",
                    help="ne montrer que les routes sensibles prioritaires")
    ap.add_argument("--top", type=int, default=25, help="routes les plus appelees")
    a = ap.parse_args(argv)

    m = matrice()
    print("journal   : %s" % m["journal"])
    print("lues      : %d   illisibles : %d   pid indetermine : %d"
          % (m["lues"], m["illisibles"], m["pid_indetermine"]))
    if m.get("raison"):
        print("raison    : %s" % m["raison"])
        return 0
    print("decisions : %s" % dict(sorted(m["decisions"].items())))
    print("appelants : %s" % dict(sorted(m["appelants"].items(),
                                         key=lambda kv: -kv[1])[:12]))
    cibles = sorted(LOCAL_A_INSTRUIRE) if a.sensibles else \
        [r for r, _ in sorted(m["routes"].items(), key=lambda kv: -kv[1]["n"])][:a.top]
    print("\n%-34s %6s  %s" % ("ROUTE", "APPELS", "APPELANTS -> DECISIONS"))
    for r in cibles:
        d = m["routes"].get(r)
        if not d:
            # Distinguer « jamais appelee pendant la fenetre » de « absente du
            # corps » : sans cette ligne, une route silencieuse disparait du
            # rapport et se lit comme inexistante.
            print("%-34s %6s  (aucun appel observe dans la fenetre)" % (r, 0))
            continue
        qui = ", ".join("%s x%d" % (k, v) for k, v in
                        sorted(d["appelants"].items(), key=lambda kv: -kv[1])[:4])
        dec = ", ".join("%s x%d" % (k, v) for k, v in sorted(d["decisions"].items()))
        print("%-34s %6d  %s | %s" % (r, d["n"], qui, dec))
    return 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(_main())
