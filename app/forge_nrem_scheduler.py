"""NREM — consolidation OPPORTUNISTE : decider QUAND vectoriser, et par quelle voie.

__FORGE_COLOR__ = "vegetatif/consolidation-opportuniste"

PRINCIPE (cadrage owner 2026-09-01). La consolidation ne doit JAMAIS concurrencer
l'intelligence active. Elle transforme des ressources qui DORMENT en qualite memoire :

    capacite inutilisee + travail memoire en attente  ->  consolider
    le corps a besoin de ses ressources               ->  s'arreter, tout de suite

CE MODULE NE VECTORISE PAS. Il DECIDE. L'execution existe deja et n'est pas dupliquee :
`forge_embed_auto_trigger` draine, `forge_llama_keeper._drain_auto` l'allume sur dette +
embedder disponible + RAM. Ce qui leur manquait, c'est le CHOIX DE LA VOIE -- le keeper
ne connait que le pilier local, et ignore qu'un backend cloud peut faire le meme travail
sans un octet de RAM locale. D'ou un decideur unique, consulte, plutot qu'un troisieme
mecanisme qui finirait par contredire les deux autres.

TROIS ISSUES, jamais deux :
    CLOUD   un backend autorise repond : voie preferee, zero RAM locale ;
    LOCAL   le cloud ne repond pas ET le corps ACCORDE le pilier local (l'arbitre
            tranche, avec ses conditions de capacite) ;
    WAIT    rien a faire, ou pas la place. C'est une decision, pas un echec.

CE QUE CE MODULE NE PRETEND PAS FAIRE — et pourquoi (mesure du 2026-09-01) : il
n'ORDONNE pas la file. Sur 20 000 chunks en attente, 2 seulement portent un
`access_count > 0` et AUCUN un `last_validated_at`. Prioriser « les chunks les plus
utiles » sur ces colonnes reviendrait a trier sur une variance nulle, c'est-a-dire a
habiller un ordre arbitraire en priorite cognitive. L'emetteur de ce signal, c'est le
futur routeur observable (« ce chunk est souvent pertinent lexicalement et son embedding
manque »). Tant qu'il n'emet pas, la file reste dans son ordre naturel et ce module le
DIT au lieu de faire semblant.
"""

from __future__ import annotations

import logging

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger(__name__)

# `sommeil/` n'est PAS reconnu par le deducteur du census (mesure 2026-09-01) : le
# module ressortait `? non classe`, donc hors de toute surveillance de regulation.
# Les mots-cles qui classent ici sont `vegetatif/` et `autonome/` -- la consolidation
# nocturne EST une fonction vegetative.
__FORGE_COLOR__ = "vegetatif/consolidation-opportuniste"

CLOUD = "CLOUD"
LOCAL = "LOCAL"
WAIT = "WAIT"

# En dessous, reveiller quoi que ce soit coute plus que le gain de consolidation.
BACKLOG_MIN = 500


def _backlog() -> int | None:
    """Travail en attente, lu au capteur DEJA calcule (pas de rescan).

    None = non mesurable. On ne consolide pas sur une non-mesure : agir sans savoir
    combien de travail attend, c'est reveiller un pilier pour rien.

    POURQUOI UNE BORNE ET NON LE CHIFFRE EXACT. Le decompte exact des seuls PENDING
    exige de classer chaque ligne par palier : mesure a 237 s sur 2 030 595 chunks.
    Un decideur consulte a chaque tick ne peut pas rescanner la table -- c'est la
    regle que le keeper s'applique deja (« on ne recompte pas 700k lignes a chaque
    tick : `embed_consolidation_debt` est emis par le capteur, on le CONSOMME »).
    On reutilise donc ce meme capteur.

    CE QUE CE CHIFFRE VAUT, MESURE et non suppose (2026-09-01) : le capteur a rendu
    145 619 quand le decompte par palier rendait 145 618 PENDING, alors que le total
    des chunks SANS VECTEUR etait de 772 264. Il applique donc deja un filtre
    d'eligibilite, et ce n'est PAS une borne grossiere -- j'avais d'abord ecrit
    l'inverse dans cette docstring, la mesure l'a corrige avant le commit.

    Le decompte de reference, lui, vit dans `forge_memory_availability.compteurs()` :
    exact, ventile par etat, et a lancer DEPORTE (237 s de balayage).
    """
    try:
        import sys as _sys
        from pathlib import Path as _P

        _tools = str(_P(__file__).resolve().parent.parent / "tools")
        if _tools not in _sys.path:
            _sys.path.insert(0, _tools)
        from nokido_agent.tools.forge_llama_keeper import _dette_embed

        n = _dette_embed()
        # Le capteur rend -1 quand il est MUET : jamais lu comme « plus de dette ».
        return None if n is None or n < 0 else int(n)
    except Exception as exc:  # noqa: BLE001 - capteur illisible : on s'abstient
        logger.debug("[nrem] backlog non mesurable (%r)", exc)
        return None


def _cloud_repond(timeout: float = 20.0) -> tuple:
    """Un backend AUTORISE par la politique repond-il ? (une seule sonde reelle)

    On ne lit pas un registre de quotas : un provider se declare disponible et rend
    403 dans la seconde. Seule une sonde qui obtient un vecteur prouve la voie.
    """
    try:
        from nokido_agent.app.forge_embed_router import embed

        v = embed("sonde nrem consolidation")
        if v and len(v) >= 256:
            return True, f"backend autorise vivant (dim={len(v)})"
        return False, "aucun backend d'embedding autorise ne rend de vecteur"
    except Exception as exc:  # noqa: BLE001
        return False, f"routeur d'embedding indisponible ({type(exc).__name__})"


def decider(backlog_min: int = BACKLOG_MIN, sonder_cloud: bool = True) -> dict:
    """Faut-il consolider maintenant, et par quelle voie ?

    Rend toujours {action, motif, backlog, ...}. L'ordre des questions n'est pas
    indifferent : on regarde d'abord s'il y a du TRAVAIL, ensuite seulement les
    ressources -- sonder les backends quand la file est vide serait du bruit.
    """
    backlog = _backlog()
    if backlog is None:
        return {"action": WAIT, "backlog": None,
                "motif": "backlog NON MESURABLE : on ne consolide pas sur une non-mesure"}
    if backlog < backlog_min:
        return {"action": WAIT, "backlog": backlog,
                "motif": f"backlog {backlog} < seuil {backlog_min} : le reveil couterait "
                         f"plus que le gain"}

    if sonder_cloud:
        ok, detail = _cloud_repond()
        if ok:
            return {"action": CLOUD, "backlog": backlog, "motif": detail,
                    "voie": "cloud (zero RAM locale)"}
    else:
        detail = "sonde cloud non demandee"

    # Le cloud ne repond pas : le corps ACCORDE-t-il le pilier local ? Ce n'est pas a
    # ce module d'en decider -- il reclame, l'arbitre tranche (politique + capacite).
    try:
        from nokido_agent.app.forge_pillar_arbiter import reclamer

        verdict = reclamer("embed.wanted", "consolidation NREM opportuniste")
    except Exception as exc:  # noqa: BLE001 - arbitre absent : on n'allume rien de lourd
        return {"action": WAIT, "backlog": backlog,
                "motif": f"arbitre indisponible ({type(exc).__name__}) : "
                         f"aucun pilier lourd ne s'allume sans accord"}

    if verdict.get("accorde"):
        return {"action": LOCAL, "backlog": backlog,
                "motif": "cloud muet (%s) et le corps accorde le pilier local%s"
                         % (detail, " (fenetre de capacite)"
                            if verdict.get("conditionnel") else ""),
                "capacite": verdict.get("capacite")}
    return {"action": WAIT, "backlog": backlog,
            "motif": "cloud muet (%s) et le corps REFUSE le pilier local : %s"
                     % (detail, verdict.get("capacite") or verdict.get("motif") or "sans motif"),
            "substitut": verdict.get("substitut")}


def main() -> int:
    import json

    print(json.dumps(decider(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
