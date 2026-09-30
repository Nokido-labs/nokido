"""Arbitre des piliers lourds : la regulation EMANE du corps, le client RECLAME.

POURQUOI CE MODULE EXISTE (incident owner du 2026-09-01, mesure).

Le vocabulaire d'intention `sandbox/*.wanted` a ete pose pour donner un DECLARANT
aux gardes qui n'en avaient aucun -- defaut reel, paye sur `llama.wanted`. Il a
produit l'asymetrie INVERSE : le client pose le drapeau au moment ou il echoue,
et le corps n'a aucun moyen de REFUSER. Chaine mesuree :

    forge_embed_router._embed_llama8099 echoue
      -> declare_embed_wanted() pose `embed.wanted`
      -> forge_llama_keeper._piliers_on_demand rallume NokidoLlamaEmbed
         (1,38 Go au repos, jusqu'a 10,92 Go mesures le 2026-08-06)
      -> forge_resource_manager evince le service pour rendre la RAM
      -> le drain ne trouve plus :8099, il repose le drapeau (19 s plus tard)

Le pilier local a ainsi ete rallume pendant qu'une campagne Modal vectorisait la
MEME file 26 fois plus vite, la machine montant a 98 % de RAM. Le defaut n'est
pas le drapeau : c'est qu'il n'existe AUCUN arbitre entre la reclamation et
l'effecteur. Ce module est cet arbitre.

    reclamer(flag) -> {etat, accorde, motif, substitut}

TROIS ETATS, JAMAIS DEUX -- ACCORDE / REFUSE / INCONNU. Une politique illisible
ou un flag non declare ne se lisent PAS comme un refus : sans politique le corps
se comporte comme avant, sinon un fichier absent couperait en silence des piliers
que personne n'a decide de couper (c'est le piege « la source qui se tait »).

UN REFUS NOMME SON SUBSTITUT. Un refus muet renvoie le client a son echec, donc a
reposer le drapeau : exactement la boucle qu'on ferme ici.

La politique est une DONNEE (`config/pillar_policy.json`), editable par l'owner
sans toucher au code -- une politique compilee dans un `if` n'est pas reglable
par celui qui en repond.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

__FORGE_COLOR__ = "endocrinien/arbitrage-des-piliers"

_RACINE = Path(__file__).resolve().parent.parent
_POLITIQUE = _RACINE / "config" / "pillar_policy.json"

ACCORDE = "ACCORDE"
REFUSE = "REFUSE"
INCONNU = "INCONNU"

# Cache court : `embed_batch` peut interroger l'arbitre des milliers de fois par
# campagne. On relit le disque au plus une fois par _FRAICHEUR_S, et on invalide
# sur le mtime pour qu'une edition owner prenne effet sans redemarrage.
_FRAICHEUR_S = 20.0
_CACHE: dict = {"lu_a": 0.0, "mtime": None, "data": None}

# Anti-spam de journal : un refus repete 10 000 fois noie le log de l'organe.
_DERNIER_LOG: dict = {}
_LOG_COOLDOWN_S = 300.0


def _politique() -> dict | None:
    """La politique du corps, ou None si ABSENTE/ILLISIBLE (jamais un dict vide).

    None veut dire « je n'ai pas pu voir », pas « il n'y a rien » : les appelants
    doivent le traiter en INCONNU, donc en accord, jamais en refus.
    """
    maintenant = time.time()
    if _CACHE["data"] is not None and (maintenant - _CACHE["lu_a"]) < _FRAICHEUR_S:
        return _CACHE["data"]
    try:
        mtime = _POLITIQUE.stat().st_mtime
    except FileNotFoundError:
        _CACHE.update(lu_a=maintenant, mtime=None, data=None)
        return None
    except OSError as exc:
        logger.warning("[arbitre] politique ILLISIBLE (%r) -- traitee en INCONNU", exc)
        _CACHE.update(lu_a=maintenant, mtime=None, data=None)
        return None
    if _CACHE["data"] is not None and mtime == _CACHE["mtime"]:
        _CACHE["lu_a"] = maintenant
        return _CACHE["data"]
    try:
        data = json.loads(_POLITIQUE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("[arbitre] politique NON PARSABLE (%r) -- traitee en INCONNU", exc)
        _CACHE.update(lu_a=maintenant, mtime=None, data=None)
        return None
    if not isinstance(data, dict):
        logger.warning("[arbitre] politique de type %s, attendu un objet", type(data).__name__)
        data = None
    _CACHE.update(lu_a=maintenant, mtime=mtime, data=data)
    return data


def _journal(cle: str, message: str) -> None:
    """Journalise au plus une fois par cle et par _LOG_COOLDOWN_S."""
    maintenant = time.time()
    if maintenant - _DERNIER_LOG.get(cle, 0.0) < _LOG_COOLDOWN_S:
        return
    _DERNIER_LOG[cle] = maintenant
    logger.warning("%s", message)


def _capacite() -> dict:
    """Ce que le corps a de DISPONIBLE maintenant. Valeur None = non mesurable.

    Jamais d'invention : une grandeur qu'on n'a pas pu lire reste None, et une
    condition portant sur None n'est PAS consideree remplie (voir `_conditions_tenues`).
    """
    out = {"ram_libre_go": None, "cpu_pct": None}
    try:
        import psutil

        out["ram_libre_go"] = psutil.virtual_memory().available / (1024 ** 3)
        # Mesure instantanee volontairement NON bloquante : un `interval=1` ici
        # gelerait l'appelant une seconde a chaque reclamation.
        out["cpu_pct"] = psutil.cpu_percent(interval=None)
    except Exception as exc:  # noqa: BLE001 - capacite illisible : on ne l'invente pas
        logger.debug("[arbitre] capacite non mesurable (%r)", exc)
    return out


def _conditions_tenues(regles: dict, capacite: dict) -> tuple:
    """Les conditions de capacite sont-elles remplies ? Rend (bool, explication).

    ASYMETRIE DES COUTS, assumee : rater une fenetre d'opportunite ne coute qu'un
    cycle de consolidation differe ; consommer la ressource sous pression fait
    tomber le poste. Donc une grandeur NON MESURABLE bloque l'accord au lieu de le
    laisser passer -- c'est le contraire d'un capteur muet lu comme un feu vert.
    """
    manques = []
    for cle, mini in (("ram_libre_go_min", "ram_libre_go"),):
        if cle in regles:
            v = capacite.get(mini)
            if v is None:
                manques.append(f"{mini} NON MESURABLE")
            elif v < float(regles[cle]):
                manques.append(f"{mini}={v:.1f} < {float(regles[cle]):.1f}")
    if "cpu_pct_max" in regles:
        v = capacite.get("cpu_pct")
        if v is None:
            manques.append("cpu_pct NON MESURABLE")
        elif v > float(regles["cpu_pct_max"]):
            manques.append(f"cpu_pct={v:.0f} > {float(regles['cpu_pct_max']):.0f}")
    return (not manques), ("; ".join(manques) if manques else "conditions de capacite tenues")


def reclamer(flag: str, motif: str = "") -> dict:
    """Reponse du corps a une reclamation de pilier.

    `flag` est le vocabulaire deja partage par l'organisme : `docker.wanted`,
    `llama.wanted`, `rerank.wanted`, `embed.wanted`, `snn.wanted`.

    Rend toujours un dict : {etat, accorde, motif, substitut}. `accorde` est vrai
    en ACCORDE **et en INCONNU** -- l'absence de politique n'est pas un refus.
    """
    politique = _politique()
    if politique is None:
        return {"etat": INCONNU, "accorde": True, "substitut": None,
                "motif": "aucune politique lisible : le corps ne refuse rien"}
    fiche = (politique.get("piliers") or {}).get(flag)
    if not isinstance(fiche, dict):
        return {"etat": INCONNU, "accorde": True, "substitut": None,
                "motif": f"{flag} non declare dans la politique"}
    accorde = bool(fiche.get("accorde", True))
    detail_cap = ""
    # ACCORD CONDITIONNEL (2026-09-01) : un pilier peut etre refuse EN REGIME NORMAL
    # et neanmoins accorde dans une fenetre de capacite inutilisee -- c'est le
    # principe de la consolidation opportuniste : transformer des ressources qui
    # dorment en qualite memoire, JAMAIS concurrencer l'activite en cours.
    regles = fiche.get("accorde_si")
    if not accorde and isinstance(regles, dict) and regles:
        tenues, detail_cap = _conditions_tenues(regles, _capacite())
        if tenues:
            accorde = True
    reponse = {
        "etat": ACCORDE if accorde else REFUSE,
        "accorde": accorde,
        "motif": str(fiche.get("motif") or ""),
        "substitut": fiche.get("substitut"),
    }
    if detail_cap:
        reponse["capacite"] = detail_cap
        reponse["conditionnel"] = True
    if not accorde:
        _journal(
            f"reclam:{flag}",
            "[arbitre] %s REFUSE par le corps%s -- %s%s" % (
                flag,
                (" (reclame pour : " + motif + ")") if motif else "",
                reponse["motif"],
                (" | substitut : " + str(reponse["substitut"])) if reponse["substitut"] else "",
            ),
        )
    return reponse


def pilier_accorde(flag: str, motif: str = "") -> bool:
    """Raccourci booleen de `reclamer`. INCONNU compte comme accorde."""
    return bool(reclamer(flag, motif).get("accorde", True))


def backends_autorises(role: str) -> list | None:
    """Backends que le corps autorise pour un role (`embed`, ...).

    None = pas de politique pour ce role => AUCUN filtre (etat INCONNU). Une liste
    vide dans le fichier est traitee comme None : couper tous les backends d'un
    role par omission serait un effet de bord, pas une decision.
    """
    politique = _politique()
    if politique is None:
        return None
    valeur = (politique.get("backends") or {}).get(role)
    if not isinstance(valeur, list) or not valeur:
        return None
    return [str(x) for x in valeur]


def backend_autorise(role: str, nom: str) -> bool:
    """Ce backend nomme est-il autorise pour ce role ? True si aucune politique."""
    autorises = backends_autorises(role)
    if autorises is None:
        return True
    ok = nom in autorises
    if not ok:
        _journal(f"backend:{role}:{nom}",
                 "[arbitre] backend %s ecarte pour le role %s (autorises : %s)"
                 % (nom, role, ", ".join(autorises)))
    return ok


def etat() -> dict:
    """Vue lisible pour un journal, un panneau ou l'owner."""
    politique = _politique()
    if politique is None:
        return {"politique": str(_POLITIQUE), "lisible": False, "piliers": {}, "backends": {}}
    piliers = {f: reclamer(f) for f in (politique.get("piliers") or {})}
    return {
        "politique": str(_POLITIQUE),
        "lisible": True,
        "version": politique.get("version"),
        "maj": politique.get("maj"),
        "piliers": piliers,
        "backends": politique.get("backends") or {},
    }


def main() -> int:
    print(json.dumps(etat(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
