"""Ledger d'identite cryptographique — agent_id -> generation -> jkt -> status.

Implemente le contrat fige par `tests/nr/test_agent_keys_ledger_nr.py` (24 NR).
Ce module ne CONCOIT rien : il est subordonne au contrat, et toute ambiguite se
rapporte au lieu de se resoudre en modifiant un NR.

POURQUOI IL EXISTE, mesure le 2026-09-21 sur le chemin reel
===========================================================
`forge_integrity.revoke` revoque par `agent_id` dans des dict d'INSTANCE :

    verify APRES revocation       False
    ---- REDEMARRAGE (manager neuf, meme secret) ----
    revoke_status                 {}
    MEME jeton revoque            True   <-- il repasse, tout son TTL restant

Deux niveaux existaient -- agent et token -- et AUCUN niveau CLE. Or une
signature reste cryptographiquement valide apres compromission de la cle :
`cnf.jkt` prouve « cette preuve correspond a cette cle », jamais « cette cle est
encore autorisee ». C'est ce second enonce que ce ledger porte.

CE QU'IL NE FAIT PAS, et c'est deliberement beaucoup
====================================================
  * AUCUNE crypto. La signature reste au TPM, la verification a
    `forge_integrity`. Ici on tient l'ETAT.
  * AUCUNE autorisation. Posseder une cle prouve la possession, jamais le ring.
    Un ledger qui porterait un ring ferait de la detention d'un secret un
    privilege -- exactement le defaut LAFORGE_CLI/NOKIDO_CLI transpose.
  * AUCUN secret. Une JWK portant un membre prive est REFUSEE : un ledger qui
    l'accepte devient un magasin de secrets, et il est lu par le RAG.

FAIL-CLOSED, ET IL NE S'HERITE PAS
==================================
Le patron de persistance reutilisable du corps (`app/web_hub/jti_cache.py`) est
explicitement FAIL-OPEN : « une panne persister ne fait JAMAIS echouer
revoke() ». Ce choix est bon pour de l'anti-rejeu et INTERDIT ici. On lui
emprunte donc le PATRON -- etat persiste, relu au demarrage, aucun repli
memoire -- et surtout pas sa politique d'echec.

Le format est JSON et non SQLite parce que le CONTRAT le fixe : la fixture des
NR pointe `_CHEMIN` sur `agent_keys.json` et y ecrit du JSON invalide pour
eprouver l'illisibilite. Le contrat prime sur la preference d'implementation.

TROIS ETATS DE LECTURE, JAMAIS DEUX
===================================
    ABSENT      aucun ledger encore ecrit -- etat LEGITIME, liste blanche vide
    LU          etat connu
    ILLISIBLE   corrompu ou inaccessible -- on REFUSE, on ne devine pas

`statut_de_jkt` rend `UNKNOWN` pour une empreinte qu'il ne connait pas et pour
un ledger illisible : `UNKNOWN` n'est pas `REVOKED`. Fabriquer une revocation a
partir d'une ignorance serait la faute symetrique de celle qu'on corrige.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/memoire-des-cles"

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Ordre de progression : une transition AVANCE, elle ne recule jamais.
ETATS = ("ACTIVE", "SUSPENDED", "REVOKED", "DESTROYED")
_ORDRE = {e: i for i, e in enumerate(ETATS)}

#: Rendu quand l'empreinte est inconnue OU le ledger illisible. Ce n'est PAS un
#: etat du cycle de vie : `UNKNOWN != NO`, et il n'appartient donc pas a `ETATS`.
INCONNU = "UNKNOWN"

#: Membres PRIVES d'une JWK, toutes familles confondues (RFC 7517/7518).
_MEMBRES_PRIVES = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})

_RACINE = Path(__file__).resolve().parent.parent


def _chemin_par_defaut() -> Path:
    """`%ProgramData%\\NokidoCles\\agent_keys.json` (decision owner 2026-09-28).

    Le ledger vivait sous `sandbox/`, modifiable par les comptes bac a sable : n'importe
    lequel pouvait y enregistrer la cle publique d'un agent. Le dossier est cree PAR
    L'OWNER (ecriture SYSTEM + Administrateurs, lecture Utilisateurs) et le module ne le
    cree JAMAIS : cree ici, il heriterait l'ACL de ProgramData, ou tout utilisateur peut
    creer des sous-dossiers -- un compte bac a sable aurait pu le pre-creer a son profit.
    """
    return Path(os.environ.get("ProgramData") or r"C:\ProgramData") / "NokidoCles" / "agent_keys.json"


_CHEMIN = Path(os.environ.get("FORGE_AGENT_KEYS_PATH") or _chemin_par_defaut())

_ILLISIBLE = object()
_CACHE: Any = None


def _vider_cache() -> None:
    """Oublie l'etat en memoire. Le prochain appel RELIT le disque.

    C'est ce que les NR utilisent pour simuler un redemarrage : sans relecture
    reelle, le test de survie ne prouverait que la memoire du processus.
    """
    global _CACHE
    _CACHE = None


def _thumbprint(jwk: Dict[str, Any]) -> str:
    """Empreinte RFC 7638, par la primitive que `cnf.jkt` utilise DEJA.

    Resolue a chaque appel : deux noms d'import donnent deux instances, et un
    module fige au chargement ne verrait pas un patch de test.
    """
    echecs = []
    for nom in ("nokido_agent.app.forge_dpop", "app.forge_dpop", "forge_dpop"):
        try:
            mod = __import__(nom, fromlist=["thumbprint"])
        except Exception as exc:  # noqa: BLE001
            echecs.append("%s (%s)" % (nom, type(exc).__name__))
            continue
        return mod.thumbprint(jwk)
    # ABSENT et CASSE ne se confondent pas : un module present dont une
    # dependance leve donnerait « introuvable » et enverrait chercher une
    # installation manquante la ou il faut reparer un import.
    raise RuntimeError("forge_dpop inutilisable : le jkt ne peut pas etre "
                       "calcule. Tentatives : " + " | ".join(echecs))


def _key_id(agent_id: str) -> str:
    """Identifiant canonique de la cle. LEVE si l'agent n'est pas declare.

    On ne redefinit pas cette regle : `forge_persona_tpm.nom_cle_agent` resout
    deja par le SSoT (`agt_claude` et `CLAUDE` sont le MEME agent) et refuse un
    agent inconnu. Une seconde convention de nommage divergerait en silence.
    """
    echecs = []
    for nom in ("nokido_agent.app.forge_persona_tpm", "app.forge_persona_tpm",
                "forge_persona_tpm"):
        try:
            mod = __import__(nom, fromlist=["nom_cle_agent"])
        except Exception as exc:  # noqa: BLE001
            echecs.append("%s (%s)" % (nom, type(exc).__name__))
            continue
        return mod.nom_cle_agent(agent_id)
    raise RuntimeError("forge_persona_tpm inutilisable : l'agent ne peut pas "
                       "etre resolu. Tentatives : " + " | ".join(echecs))


def _canon(agent_id: str) -> str:
    """Nom canonique de l'agent, ou la chaine telle quelle si non resolvable."""
    echecs = []
    for nom in ("nokido_agent.app.forge_m2m_protocol", "app.forge_m2m_protocol",
                "forge_m2m_protocol"):
        try:
            mod = __import__(nom, fromlist=["_resoudre_agent"])
        except Exception as exc:  # noqa: BLE001
            echecs.append("%s (%s)" % (nom, type(exc).__name__))
            continue
        canon, _surface = mod._resoudre_agent(agent_id)
        return canon or agent_id
    # Repli DIT : on retient la chaine brute, et on le journalise. Le `key_id`
    # reste canonique (il vient du SSoT via `_key_id`), donc l'identite du
    # ledger n'est pas menacee -- seul le libelle l'est.
    logger.warning("[agent_keys] SSoT d'identite injoignable (%s) : libelle "
                   "brut %r retenu, le key_id reste canonique.",
                   " | ".join(echecs), agent_id)
    return agent_id


def _key_id_ou_none(agent_id: str) -> Optional[str]:
    """Variante de `_key_id` pour les LECTURES : un echec vaut refus.

    Une lecture ne doit jamais lever a cause d'un SSoT indisponible -- mais elle
    ne doit pas non plus repondre « actif ». Elle rend None, et l'appelant
    refuse.
    """
    try:
        return _key_id(agent_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[agent_keys] identite %r non resolvable (%s) : lecture "
                       "REFUSEE. Ce n'est pas « agent inactif », c'est « non "
                       "mesurable » -- et les deux se refusent, pas pour la "
                       "meme raison.", agent_id, type(exc).__name__)
        return None


def _garde_jwk_publique(public_key: Any) -> None:
    """Refuse tout materiau prive. NE REPRODUIT JAMAIS LA VALEUR REFUSEE.

    Seuls les NOMS des membres fautifs sont nommes : un message d'erreur qui
    recopierait la valeur transformerait le refus lui-meme en fuite -- et il
    partirait dans les journaux, donc dans le RAG.
    """
    if not isinstance(public_key, dict):
        raise ValueError("public_key doit etre une JWK (dict) : le jkt ne se "
                         "calcule pas autrement, et une chaine opaque rendrait "
                         "l'empreinte inverifiable")
    prives = sorted(_MEMBRES_PRIVES & set(public_key))
    if prives:
        raise ValueError("JWK PRIVEE refusee : membres %s presents. Le ledger "
                         "tient un etat, il n'est pas un magasin de secrets."
                         % (prives,))
    if not public_key.get("kty"):
        raise ValueError("JWK sans `kty` : l'empreinte RFC 7638 est indefinie")


def _lire() -> Any:
    """Etat du ledger, relu du disque au besoin. Rend `_ILLISIBLE` sur doute.

    ABSENT et ILLISIBLE sont distingues : un ledger jamais ecrit est un etat
    legitime (liste blanche vide), un ledger corrompu est un REFUS. Les deux
    refusent tout, mais pour des raisons differentes -- et le journal le dit.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    chemin = Path(_CHEMIN)
    try:
        brut = chemin.read_text(encoding="utf-8")
    except FileNotFoundError:
        _CACHE = {"version": 1, "agents": {}}
        return _CACHE
    except OSError as exc:
        logger.error("[agent_keys] ledger ILLISIBLE (%s) -> aucune cle "
                     "acceptee, aucun agent actif. Ce n'est pas une absence "
                     "de revocation, c'est un refus.", type(exc).__name__)
        _CACHE = _ILLISIBLE
        return _CACHE
    try:
        donnees = json.loads(brut)
        if not isinstance(donnees, dict):
            raise ValueError("racine non-objet")
        if not isinstance(donnees.get("agents"), dict):
            raise ValueError("cle `agents` absente ou non-objet")
    except Exception as exc:  # noqa: BLE001
        logger.error("[agent_keys] ledger CORROMPU (%s) -> fail-closed. Le "
                     "fichier n'est PAS reecrit : un etat douteux se gele, il "
                     "ne s'ecrase pas.", type(exc).__name__)
        _CACHE = _ILLISIBLE
        return _CACHE
    _CACHE = donnees
    return _CACHE


def _etat_pour_ecriture() -> Dict[str, Any]:
    """Etat mutable, ou LEVE si le ledger est illisible.

    Ecraser un ledger corrompu detruirait les revocations qu'il contenait
    peut-etre. « Geler, jamais supprimer » : on refuse d'ecrire par-dessus.
    """
    etat = _lire()
    if etat is _ILLISIBLE:
        raise ValueError("ledger ILLISIBLE : ecriture refusee. Ecraser cet "
                         "etat detruirait les revocations qu'il porte "
                         "peut-etre : instruire le fichier d'abord.")
    return etat


def _ecrire(etat: Dict[str, Any]) -> None:
    """Ecriture ATOMIQUE. Un echec LEVE : il ne passe jamais pour un succes.

    Aucun repli memoire : si le disque refuse, l'appelant doit le savoir. Une
    revocation qu'on croit posee et qui n'est pas persistee est precisement le
    defaut que ce module corrige.
    """
    global _CACHE
    chemin = Path(_CHEMIN)
    if not chemin.parent.is_dir():
        # JAMAIS de creation : le dossier porte l'ACL qui protege le ledger (voir
        # `_chemin_par_defaut`). Absent -> la transition n'est pas persistee, et on le DIT.
        logger.error("[agent_keys] dossier du ledger ABSENT (%s) : a creer par l'owner "
                     "avec son ACL. La transition demandee n'est PAS persistee.",
                     chemin.parent)
        raise FileNotFoundError(f"dossier du ledger absent : {chemin.parent}")
    fd, tmp = tempfile.mkstemp(dir=str(chemin.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(etat, fh, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, chemin)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:  # muet-ok : menage du tmp, l'erreur qui compte suit
            # Nettoyage best-effort du fichier temporaire : son echec n'affecte
            # NI l'etat du ledger (os.replace n'a pas eu lieu) NI ce que
            # l'appelant apprend -- le `raise` ci-dessous porte la cause reelle.
            pass
        logger.error("[agent_keys] ECHEC d'ecriture : la transition demandee "
                     "n'est PAS persistee.")
        raise
    _CACHE = etat


def enregistrer(agent_id: str, public_key: Dict[str, Any]) -> Dict[str, Any]:
    """Enregistre une cle publique et rend son entree de ledger.

    IL N'Y A VOLONTAIREMENT PAS DE PARAMETRE `jkt`. L'empreinte est TOUJOURS
    recalculee depuis la cle publique ; accepter un `jkt` de l'appelant, ce
    serait enregistrer deux affirmations independantes dont l'une peut mentir.
    Un appel qui en fournit un echoue en `TypeError` : on ne peut pas mentir a
    un parametre qui n'existe pas.
    """
    key_id = _key_id(agent_id)
    _garde_jwk_publique(public_key)
    jkt = _thumbprint(public_key)
    etat = _etat_pour_ecriture()
    fiche = etat["agents"].setdefault(
        key_id, {"agent_id": _canon(agent_id), "actif": True, "cles": []})
    generation = max((c["generation"] for c in fiche["cles"]), default=0) + 1
    entree = {
        "agent_id": fiche["agent_id"],
        "key_id": key_id,
        "public_key": public_key,
        "generation": generation,
        "status": "ACTIVE",
        "jkt": jkt,
        "created_at": time.time(),
    }
    fiche["cles"].append(entree)
    _ecrire(etat)
    logger.info("[agent_keys] %s generation=%d enregistree", key_id, generation)
    return dict(entree)


def transition(agent_id: str, nouvel_etat: str, par: str = "",
               motif: str = "",
               generation: Optional[int] = None) -> Dict[str, Any]:
    """Fait AVANCER l'etat d'une cle. Ne recule jamais.

    Sans `generation`, agit sur la generation COURANTE. `par` et `motif` sont
    exiges : un etat sans auteur ni motif ne se relit pas six mois plus tard.
    """
    if nouvel_etat not in _ORDRE:
        raise ValueError("etat inconnu : %r (attendus : %s)"
                         % (nouvel_etat, ", ".join(ETATS)))
    if not par or not motif:
        raise ValueError("transition sans `par` ni `motif` : un etat sans "
                         "provenance est illisible plus tard")
    key_id = _key_id(agent_id)
    etat = _etat_pour_ecriture()
    fiche = etat["agents"].get(key_id)
    if not fiche or not fiche["cles"]:
        raise KeyError("aucune cle enregistree pour %r" % (agent_id,))
    if generation is None:
        cibles = [max(fiche["cles"], key=lambda c: c["generation"])]
    else:
        cibles = [c for c in fiche["cles"] if c["generation"] == generation]
        if not cibles:
            raise KeyError("generation %r inconnue pour %r"
                           % (generation, agent_id))
    maintenant = time.time()
    for cle in cibles:
        if _ORDRE[nouvel_etat] <= _ORDRE[cle["status"]]:
            raise ValueError("transition %s -> %s refusee : un etat AVANCE, "
                             "il ne recule jamais (revoquer n'est pas "
                             "detruire, et rien ne se rearme)"
                             % (cle["status"], nouvel_etat))
        cle["status"] = nouvel_etat
        cle["revoked_by"] = par
        cle["reason"] = motif
        cle["revoked_at"] = maintenant
    _ecrire(etat)
    return dict(cibles[-1])


def revoquer_agent(agent_id: str, par: str = "",
                   motif: str = "") -> Dict[str, Any]:
    """Revocation d'AGENT : toutes ses cles deviennent inutilisables.

    Le niveau le plus fort des trois. L'historique n'est PAS efface -- revoquer
    n'est pas detruire, et une lecture forensique doit rester possible.
    """
    if not par or not motif:
        raise ValueError("revocation d'agent sans `par` ni `motif` : refusee")
    key_id = _key_id(agent_id)
    etat = _etat_pour_ecriture()
    fiche = etat["agents"].get(key_id)
    if not fiche:
        raise KeyError("agent %r absent du ledger" % (agent_id,))
    maintenant = time.time()
    fiche["actif"] = False
    fiche["revoked_by"] = par
    fiche["reason"] = motif
    fiche["revoked_at"] = maintenant
    for cle in fiche["cles"]:
        if _ORDRE[cle["status"]] < _ORDRE["REVOKED"]:
            cle["status"] = "REVOKED"
            cle["revoked_by"] = par
            cle["reason"] = motif
            cle["revoked_at"] = maintenant
    _ecrire(etat)
    logger.warning("[agent_keys] AGENT %s revoque par %s", key_id, par)
    return dict(fiche)


def cles_acceptees(agent_id: str) -> List[Dict[str, Any]]:
    """Cles utilisables, par generation croissante. LISTE BLANCHE.

    N'est rendue que la cle PROUVEE `ACTIVE` d'un agent PROUVE actif. Une liste
    noire laisserait toute valeur inattendue tomber du cote sain.
    """
    etat = _lire()
    if etat is _ILLISIBLE:
        return []
    key_id = _key_id_ou_none(agent_id)
    if key_id is None:
        return []
    fiche = etat["agents"].get(key_id)
    if not fiche or not fiche.get("actif", False):
        return []
    ordonnees = sorted(fiche["cles"], key=lambda c: c["generation"])
    return [dict(c) for c in ordonnees if c.get("status") == "ACTIVE"]


def agent_actif(agent_id: str) -> bool:
    """Vrai seulement si l'agent est PROUVE actif dans un ledger LISIBLE."""
    etat = _lire()
    if etat is _ILLISIBLE:
        return False
    key_id = _key_id_ou_none(agent_id)
    if key_id is None:
        return False
    fiche = etat["agents"].get(key_id)
    return bool(fiche and fiche.get("actif", False))


def historique(agent_id: str) -> List[Dict[str, Any]]:
    """TOUTES les cles connues, tous etats confondus, generation croissante.

    Les cles revoquees y restent : c'est ce qui rend une lecture forensique
    possible apres une rotation ou une compromission.
    """
    etat = _lire()
    if etat is _ILLISIBLE:
        return []
    key_id = _key_id_ou_none(agent_id)
    if key_id is None:
        return []
    fiche = etat["agents"].get(key_id)
    if not fiche:
        return []
    return [dict(c) for c in sorted(fiche["cles"],
                                    key=lambda c: c["generation"])]


def statut_de_jkt(jkt: str) -> str:
    """Etat de la cle portant cette empreinte, SANS connaitre l'agent.

    C'est le maillon qui manquait : un verificateur derive le `jkt` du JETON, il
    ne sait pas a l'avance de quelle identite il s'agit. S'il devait le savoir,
    le ledger ne servirait a rien.

    Rend `UNKNOWN` pour une empreinte inconnue ou un ledger illisible -- jamais
    `REVOKED`, qui serait une revocation fabriquee a partir d'une ignorance.
    """
    if not jkt:
        return INCONNU
    etat = _lire()
    if etat is _ILLISIBLE:
        return INCONNU
    for fiche in etat["agents"].values():
        for cle in fiche.get("cles", []):
            if cle.get("jkt") == jkt:
                if not fiche.get("actif", False):
                    return "REVOKED"
                return cle.get("status", INCONNU)
    return INCONNU


__all__ = [
    "ETATS",
    "INCONNU",
    "enregistrer",
    "transition",
    "revoquer_agent",
    "cles_acceptees",
    "agent_actif",
    "historique",
    "statut_de_jkt",
]
