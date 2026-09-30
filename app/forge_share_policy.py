"""forge_share_policy.py -- « ai-je le droit de donner CETTE information a CE cerveau ? »

Chainon manquant du swarm, mesure 2026-09-02 : `forge_swarm_router.route_subtask`
valide QUI parle (`forge_videur.authorize`) puis appelle `router_call`, qui choisit
un fournisseur -- sans que personne ne demande jamais si la donnee a le droit de
partir la. Le `SemanticFirewall` redige le CONTENU, la `SovereignMembrane` l'aliase :
aucun des deux ne decide de la DESTINATION.

Ce module ne route pas et ne remplace aucun routeur -- il y en a deja une vingtaine.
Il rend un POOL ADMISSIBLE, en amont, et le routeur choisit dedans.

    requete -> preflight() -> pool admissible -> forge_swarm_router -> provider

TROIS DIMENSIONS, jamais une seule :

    data_class      PUBLIC / INTERNAL / CONFIDENTIAL / SECRET
    collaboration   PRIVATE / SELECTED_AGENTS / SWARM
    audience        les agents nommes

**La collaboration n'efface JAMAIS la sensibilite.** Une tache peut etre
COLLABORATIVE et CONFIDENTIAL : le caractere collaboratif elargit l'audience, il ne
declasse pas la donnee. C'est la confusion qui ferait sortir un secret « parce que
c'est un travail d'equipe ».

MODE. Par defaut `shadow` : la decision est calculee et JOURNALISEE, jamais
appliquee. Aucun appelant ne declare encore sa classe de donnee ; armer le refus
d'emblee bloquerait tout et rendrait le corps muet -- l'erreur exacte payee sur le
M2M le 2026-09-01 (mode `error` arme sur une mauvaise mesure, 100 % de refus,
recul immediat). `LAFORGE_SHARE_POLICY_MODE=error` arme, quand la mesure le dira.

PORTEE REELLE -- A LIRE AVANT DE CROIRE CE MODULE COUVRANT.
Ce preflight est branche dans `forge_swarm_router.route_subtask`, et NULLE PART
AILLEURS. Or `forge_llm_router.router_call` est atteint par plusieurs autres chemins
(`forge_handoff`, `forge_internal_sampling`, `forge_router_gateway`, et le tool MCP
`mcp_server_tools.llm_router_call`) qui ne consultent PAS cette politique. Mesure du
2026-09-02 : un chemin garde sur six.

C'est une DETTE DE CABLAGE, pas une securite. Elle est surveillee par
`tests/nr/test_share_policy_couverture_nr.py`, qui fige la liste des chemins non
gardes et echoue si un nouveau apparait -- sans quoi la couverture se degraderait
sans que rien ne s'allume. Le remede de fond est de porter le preflight au point de
convergence reel (`router_call`), ce qui touche TOUS les appels LLM du systeme :
decision owner, non prise a ce jour.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/politique-de-partage"

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "config" / "share_policy.json"

ALLOW = "ALLOW"
REFUSE = "REFUSE"
INCONNU = "UNKNOWN"

_cache: Optional[dict] = None


@dataclass(frozen=True)
class SwarmRequestContext:
    """Ce qu'une requete doit porter pour qu'on puisse decider de son partage.

    POURQUOI UN OBJET, ET PAS DES `**kwargs`. Mesure 2026-09-02 : `router_call` est
    le point de convergence des sorties LLM, et AUCUN de ses cinq appelants ne lui
    transmet la classe de donnee. Un champ libre dans `**kwargs` s'OUBLIE en silence ;
    un contexte declare se voit -- par un lecteur comme par un test AST.

    **UNKNOWN N'EST PAS ABSENT, et c'est tout l'interet.** Un appelant historique qui
    ne sait pas encore classer sa donnee produit un contexte dont les champs valent
    `UNKNOWN` : le systeme distingue alors « cet appelant a ete instrumente et ignore
    la classe » de « cet appelant n'a jamais ete instrumente ». Sans cette
    distinction, on ne peut pas mesurer la progression, donc pas decider d'armer.

    Les valeurs sont des PROPRIETES DE LA REQUETE, jamais du fournisseur : un
    fournisseur gratuit et joignable ne se rend pas admissible tout seul.
    """

    identity: str = INCONNU
    audience: Tuple[str, ...] = ()
    data_class: str = INCONNU
    collaboration: str = INCONNU
    required_capabilities: Tuple[str, ...] = ()
    provenance: str = ""          # pointer_ref -- le contenu lourd reste hors canal

    def est_instrumente(self) -> bool:
        """Vrai si l'appelant a REELLEMENT classe sa donnee.

        Sert au denominateur : « combien de chemins portent une classe connue ? ».
        Un contexte tout en UNKNOWN compte comme instrumente au sens du CABLAGE et
        NON instrumente au sens de la DECISION -- les deux se mesurent separement.
        """
        return self.data_class != INCONNU and self.collaboration != INCONNU

    def resume(self) -> Dict[str, Any]:
        """Metadonnees journalisables. Ne porte aucun contenu, seulement le pointeur."""
        return {"identity": self.identity, "audience": list(self.audience),
                "data_class": self.data_class, "collaboration": self.collaboration,
                "required_capabilities": list(self.required_capabilities),
                "provenance": self.provenance,
                "instrumente": self.est_instrumente()}


def contexte_legacy(identity: str = INCONNU, provenance: str = "") -> SwarmRequestContext:
    """Contexte d'un appelant PAS ENCORE instrumente.

    A utiliser explicitement plutot que de laisser le contexte absent : le chemin
    devient visible et comptable. Ne JAMAIS y mettre de valeur permissive inventee
    -- inventer `PUBLIC` pour faire passer un appel serait exactement la faute que
    ce module existe pour empecher.
    """
    return SwarmRequestContext(identity=identity or INCONNU, provenance=provenance)


def mode() -> str:
    """`shadow` (defaut) ou `error`. Toute autre valeur retombe sur shadow."""
    brut = (os.environ.get("LAFORGE_SHARE_POLICY_MODE", "") or "").strip().lower()
    if brut in ("shadow", "error"):
        return brut
    try:
        return str(_politique().get("mode_defaut", "shadow"))
    except Exception:  # noqa: BLE001  # muet-ok : le defaut sur, sans dependre du disque
        return "shadow"


def _politique(rafraichir: bool = False) -> dict:
    global _cache
    if _cache is None or rafraichir:
        _cache = json.loads(POLICY.read_text(encoding="utf-8"))
    return _cache


def _pools_de(classe: str, collab: str, pol: dict) -> tuple[Optional[List[str]], str]:
    """Intersection ORDONNEE des pools permis par la classe et par la collaboration.

    Rend (None, raison) si l'un des deux est inconnu -- ne JAMAIS retomber sur un
    pool par defaut : une classe inconnue est precisement le cas ou l'on ignore la
    sensibilite.
    """
    dc = (pol.get("data_class") or {}).get(classe)
    if dc is None:
        return None, "classe de donnee inconnue: %r" % classe
    co = (pol.get("collaboration") or {}).get(collab)
    if co is None:
        return None, "mode de collaboration inconnu: %r" % collab
    permis = [p for p in (dc.get("pools") or []) if p in (co.get("pools_max") or [])]
    return permis, ""


def preflight(data_class: Optional[str], collaboration: Optional[str], *,
              audience: Optional[Iterable[str]] = None,
              providers_candidats: Optional[Iterable[str]] = None,
              joignables: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Rend {decision, pool, exclus, data_class, collaboration, mode, raison}.

    `providers_candidats` : ce que le routeur envisagerait (defaut : tout le
    catalogue de la politique). `joignables` : ce que la MESURE dit joignable
    (`forge_free_tier_census`). Les deux sont distincts a dessein -- autorise et
    joignable sont deux choses, et l'exclusion dit LAQUELLE a manque.
    """
    aud = [a for a in (audience or []) if a]
    exclus: List[Dict[str, str]] = []

    def _refus(raison: str, **extra) -> Dict[str, Any]:
        return {"decision": REFUSE, "pool": [], "exclus": exclus, "raison": raison,
                "data_class": data_class, "collaboration": collaboration,
                "audience": aud, "mode": mode(), **extra}

    try:
        pol = _politique()
    except Exception as e:  # noqa: BLE001
        # Politique ILLISIBLE : troisieme etat. On refuse, et on dit pourquoi --
        # un fichier absent ne doit pas se lire comme « aucune restriction ».
        return _refus("politique de partage illisible: %s" % e)

    if not data_class or not collaboration:
        return _refus("classe de donnee ou mode de collaboration NON DECLARE "
                      "(ne pas savoir n'est pas autoriser)")

    permis, souci = _pools_de(str(data_class), str(collaboration), pol)
    if permis is None:
        return _refus(souci)

    if (pol.get("collaboration") or {}).get(collaboration, {}).get("audience_requise") and not aud:
        return _refus("collaboration %s exige une audience NOMMEE ; une audience vide "
                      "n'est pas un partage universel" % collaboration)

    catalogue = pol.get("pools") or {}
    autorises: List[str] = []
    for nom in permis:
        for prov in (catalogue.get(nom) or {}).get("providers", []):
            if prov not in autorises:
                autorises.append(prov)

    if providers_candidats is not None:
        candidats = [p for p in providers_candidats]
        for p in candidats:
            if p not in autorises:
                exclus.append({"provider": p, "raison": "hors des pools %s pour %s/%s"
                               % (permis, data_class, collaboration)})
        retenus = [p for p in candidats if p in autorises]
    else:
        retenus = list(autorises)

    if joignables is not None:
        joi = set(joignables)
        for p in list(retenus):
            if p not in joi:
                exclus.append({"provider": p, "raison": "autorise mais NON JOIGNABLE (mesure)"})
        retenus = [p for p in retenus if p in joi]

    if not retenus:
        # Pool vide = REFUSE. Le repli vers « le moins mauvais » est precisement
        # le chemin par lequel une donnee SECRET partirait au cloud.
        return _refus("aucun fournisseur admissible pour %s/%s -- pas de repli"
                      % (data_class, collaboration), pools_permis=permis)

    return {"decision": ALLOW, "pool": retenus, "exclus": exclus,
            "raison": "pools %s" % permis, "data_class": data_class,
            "collaboration": collaboration, "audience": aud,
            "pools_permis": permis, "mode": mode()}


def preflight_contexte(ctx: Optional[SwarmRequestContext], *,
                       providers_candidats: Optional[Iterable[str]] = None,
                       joignables: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """`preflight` a partir d'un contexte. Distingue ABSENT de UNKNOWN.

    Un contexte ABSENT est un chemin NON INSTRUMENTE : c'est un defaut de cablage, et
    le verdict le dit (`contexte: "ABSENT"`). Un contexte present mais tout en UNKNOWN
    est un chemin instrumente dont l'appelant ignore encore la classe. Les deux
    refusent en mode error, mais ils ne se comptent pas ensemble -- sans quoi on ne
    pourrait pas mesurer la progression du cablage.
    """
    if ctx is None:
        v = preflight(None, None, providers_candidats=providers_candidats,
                      joignables=joignables)
        v["contexte"] = "ABSENT"
        v["raison"] = "aucun contexte de requete : chemin NON INSTRUMENTE"
        return v
    v = preflight(ctx.data_class, ctx.collaboration, audience=ctx.audience,
                  providers_candidats=providers_candidats, joignables=joignables)
    v["contexte"] = "PRESENT" if ctx.est_instrumente() else "PRESENT_MAIS_INCONNU"
    v["identity"] = ctx.identity
    v["provenance"] = ctx.provenance
    return v


# --------------------------------------------------------------------------- #
# Observation PERSISTEE de l'instrumentation
# --------------------------------------------------------------------------- #

_OBS = ROOT / "sandbox" / "share_context_observation.json"
_verrou = threading.Lock()


def noter_appel(ctx: Optional[SwarmRequestContext]) -> None:
    """Compte un passage au point de convergence. OBSERVATION SEULE.

    POURQUOI PERSISTER. `router_call` joint deja le contexte a chaque reponse, mais
    une reponse n'est lue que par son appelant : depuis l'exterieur du hub, on ne
    peut RIEN en savoir. Sans agregat sur disque, le denominateur ---- combien
    d'appels reels sortent non classes ---- reste invisible, et sans lui on ne peut
    pas decider d'armer la politique. Meme manque que le M2M avant le 2026-09-01 :
    un signal emis, jamais compte.

    Trois etats separes, jamais fondus : ABSENT (chemin non instrumente),
    PRESENT_MAIS_INCONNU (instrumente, classe ignoree), PRESENT (classe declaree).
    Les fondre ferait passer un cablage a moitie fait pour une politique appliquee.
    """
    try:
        if ctx is None:
            etat = "ABSENT"
            provenance = "?"
        else:
            etat = "PRESENT" if ctx.est_instrumente() else "PRESENT_MAIS_INCONNU"
            provenance = ctx.provenance or "?"
        with _verrou:
            try:
                donnees = json.loads(_OBS.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001  # muet-ok : premier passage ou fichier abime
                donnees = {}
            donnees.setdefault("depuis", time.strftime("%Y-%m-%dT%H:%M:%S"))
            donnees["total"] = int(donnees.get("total", 0)) + 1
            par_etat = donnees.setdefault("par_etat", {})
            par_etat[etat] = int(par_etat.get(etat, 0)) + 1
            par_prov = donnees.setdefault("par_provenance", {})
            fiche = par_prov.setdefault(provenance, {})
            fiche[etat] = int(fiche.get(etat, 0)) + 1
            donnees["maj"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            # Ecriture atomique : un fichier tronque par un arret brutal se lirait
            # comme « aucun trafic », c'est-a-dire l'inverse de la verite.
            tmp = _OBS.with_suffix(".tmp")
            tmp.write_text(json.dumps(donnees, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, _OBS)
    except Exception:  # noqa: BLE001  # muet-ok : une observation ne casse jamais un appel
        pass


def observation() -> Dict[str, Any]:
    """Lit l'agregat. `total: 0` avec `etat: JAMAIS_ECRIT` si le fichier n'existe
    pas -- un zero mesure et une absence de mesure ne se confondent pas."""
    try:
        d = json.loads(_OBS.read_text(encoding="utf-8"))
        d["etat"] = "MESURE"
        t = int(d.get("total", 0))
        pe = d.get("par_etat", {})
        d["taux_classe"] = (int(pe.get("PRESENT", 0)) / t) if t else None
        return d
    except FileNotFoundError:
        return {"etat": "JAMAIS_ECRIT", "total": 0, "taux_classe": None}
    except Exception as e:  # noqa: BLE001
        return {"etat": "ILLISIBLE", "detail": str(e)[:120], "total": 0,
                "taux_classe": None}


def enveloppe_m2m(ctx: Optional[SwarmRequestContext], intent: str,
                  pointer_ref: str = "", ttl: int = 900) -> Dict[str, Any]:
    """Metadonnees d'acheminement M2M pour une requete. AUCUN contenu lourd.

    Le canal M2M transporte de quoi ROUTER et DECIDER -- qui envoie, a qui, de
    quelle classe, pour quelle collaboration -- et un POINTEUR vers l'artefact. Le
    rapport, le diff, le code restent hors canal : c'est ce qui distingue un systeme
    nerveux d'un tuyau a gros paquets.

    `pointer_ref` prend `ctx.provenance` par defaut, et un pointeur VIDE leve ici.

    ECART MESURE 2026-09-02 : le validateur M2M verifie la PRESENCE du champ, pas
    qu'il soit renseigne -- une enveloppe avec `pointer_ref: ""` passe en M2M_OK.
    Present n'est pas renseigne, meme famille que le `perimetre` d'un REVIEW_OK. On
    ne modifie pas le validateur (politique M2M hors perimetre) : on rend simplement
    impossible d'EMETTRE un message sans artefact, puisqu'une revue sans artefact
    n'est qu'une opinion.
    """
    ctx = ctx or SwarmRequestContext()
    ref = pointer_ref or ctx.provenance
    if not str(ref).strip():
        raise ValueError(
            "enveloppe M2M sans pointer_ref : le canal transporte un POINTEUR vers "
            "l'artefact, pas une affirmation nue")
    return {
        "intent": intent,
        "pointer_ref": ref,
        "sender": ctx.identity,
        "audience": list(ctx.audience),
        "data_class": ctx.data_class,
        "collaboration": ctx.collaboration,
        "required_capabilities": list(ctx.required_capabilities),
        "ttl": int(ttl),
    }


def applique(verdict: Dict[str, Any]) -> bool:
    """Le verdict doit-il BLOQUER ? Faux en `shadow` : on mesure sans couper.

    Sert a distinguer, dans les journaux, « la politique aurait refuse » de « la
    politique a refuse » -- confondre les deux ferait croire un garde actif alors
    qu'il observe.
    """
    return mode() == "error" and verdict.get("decision") == REFUSE
