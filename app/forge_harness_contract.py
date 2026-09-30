"""forge_harness_contract.py — CONTRAT d'execution par etape de la facade harness.

Chantier Harness Controller, pas 2 : le SCHEMA seul, structure pure. Aucune execution,
aucun organe reimplemente. Une etape = UNE ligne de douze colonnes :

    OBJECTIF · ETAT AVANT · CAPACITE CHOISIE · PRECONDITIONS · AUTORISATION · ACTION ·
    OBSERVATION · EFFET ATTENDU · EFFET OBSERVE · PREUVE · ETAT APRES · PROCHAIN OBJECTIF

Chaque colonne est remplie par l'organe qui la SAIT deja (fiche chantier-harness-controller) :
capacite = forge_goap.decompose_goal (methodes eprouvees) ; autorisation = forge_tool_gate /
S5 ; effet observe = forge_effect_surface.effet_observe ; preuve = forge_swarm_evidence.
verdict_livrable. Tant qu'un organe ne l'a pas remplie, une colonne vaut UNKNOWN — jamais
une valeur par defaut qui se lirait comme un NON.

Pourquoi ne pas etendre `forge_trajectory.TrajectoryStep` : c'est la trace PERSISTEE de GOAP
(intent / result / status) ; ajouter des champs change le schema d'execution_traces.db. Et son
`completed` dit seulement que le dispatch n'a pas leve d'erreur : c'est ACCEPTED, jamais
ACHIEVED (constitution : REQUESTED != ACCEPTED != ACHIEVED). Le contrat LIT la trace
(`depuis_trajectory_step`) et porte les colonnes qu'elle n'a pas.

Verdict par liste BLANCHE : n'est ACHIEVED que l'etape PROUVEE sur tous ses champs (ALLOW,
EFFECT_OBSERVED, preuve acceptee, effet attendu declare). Toute autre combinaison tombe du
cote non prouve, et une contradiction (DENY mais le monde a bouge) est CONSERVEE, pas
resolue en silence — meme patron que forge_wiring_view.
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/harness : contrat d'execution par etape, federation des organes harness"

from dataclasses import dataclass, fields
from typing import Any

UNKNOWN = "UNKNOWN"  # meme sentinelle que forge_swarm_evidence.UNKNOWN

# Ordre canonique des colonnes : il fait partie du contrat (une ligne par etape).
COLONNES = (
    "objectif", "etat_avant", "capacite", "preconditions", "autorisation", "action",
    "observation", "effet_attendu", "effet_observe", "preuve", "etat_apres",
    "prochain_objectif",
)

# Statuts d'une etape. REQUESTED != ACCEPTED != ACHIEVED ; INCERTAIN != FAILED.
REQUESTED = "REQUESTED"      # action emise, rien observe
REFUSED = "REFUSED"          # DENY, et le monde n'a pas bouge
FAILED = "FAILED"            # l'action a rendu un echec observe
INCERTAIN = "INCERTAIN"      # une observation existe mais ne dit ni oui ni non
ACCEPTED = "ACCEPTED"        # l'action a ete acceptee ; l'effet n'est pas prouve
ACHIEVED = "ACHIEVED"        # effet observe ET prouve ET attendu
CONTRADICTION = "CONTRADICTION"  # les organes se contredisent : conserve, jamais tranche


@dataclass
class EtapeContrat:
    objectif: Any = UNKNOWN
    etat_avant: Any = UNKNOWN
    capacite: Any = UNKNOWN          # methode choisie (forge_goap)
    preconditions: Any = UNKNOWN     # liste, ou UNKNOWN — jamais [] fabrique
    autorisation: Any = UNKNOWN      # ALLOW | DENY | UNKNOWN
    action: Any = UNKNOWN            # intent emis
    observation: Any = UNKNOWN       # {"ok": True|False|None, "retour": ...}
    effet_attendu: Any = UNKNOWN
    effet_observe: Any = UNKNOWN     # sortie de forge_effect_surface.effet_observe
    preuve: Any = UNKNOWN            # Verdict.action : accept|challenge|retry|abstain
    etat_apres: Any = UNKNOWN
    prochain_objectif: Any = UNKNOWN

    def colonnes_inconnues(self) -> list[str]:
        """Les colonnes qu'aucun organe n'a remplies — dites, pas cachees."""
        return [c for c in COLONNES if getattr(self, c) == UNKNOWN]

    def to_dict(self) -> dict:
        return {c: getattr(self, c) for c in COLONNES}


assert tuple(f.name for f in fields(EtapeContrat)) == COLONNES


def _observation_ok(obs: Any) -> bool | None:
    """True / False / None. None = l'observation ne tranche pas (jamais lu comme False)."""
    if not isinstance(obs, dict):
        return None
    ok = obs.get("ok")
    if ok is True or ok is False:
        return ok
    return None


def verdict_etape(e: EtapeContrat) -> dict:
    """{statut, motif, colonnes_inconnues}. Liste BLANCHE : ACHIEVED seulement si tout est prouve."""
    inconnues = e.colonnes_inconnues()

    def _v(statut: str, motif: str) -> dict:
        return {"statut": statut, "motif": motif, "colonnes_inconnues": inconnues}

    if e.action == UNKNOWN:
        return _v(UNKNOWN, "aucune action emise")
    effet = e.effet_observe if isinstance(e.effet_observe, str) else UNKNOWN
    if e.autorisation == "DENY":
        if effet.startswith("EFFECT_OBSERVED"):
            return _v(CONTRADICTION, "DENY rendu mais effet observe : %s" % effet)
        if effet == "EFFECT_BLOCKED":
            return _v(REFUSED, "DENY et monde inchange")
        return _v(REFUSED, "DENY ; blocage non certifie (%s)" % effet)
    if e.observation == UNKNOWN:
        return _v(REQUESTED, "action emise, rien observe")
    ok = _observation_ok(e.observation)
    if ok is False:
        return _v(FAILED, "echec observe")
    if ok is None:
        return _v(INCERTAIN, "observation presente mais sans verdict ok/echec")
    manque = []
    if e.autorisation != "ALLOW":
        manque.append("autorisation=%s" % e.autorisation)
    if effet != "EFFECT_OBSERVED":
        manque.append("effet_observe=%s" % effet)
    if e.preuve != "accept":
        manque.append("preuve=%s" % e.preuve)
    if e.effet_attendu == UNKNOWN:
        manque.append("effet_attendu non declare")
    if manque:
        return _v(ACCEPTED, "effet non prouve : " + " ; ".join(manque))
    return _v(ACHIEVED, "effet attendu, observe et prouve")


def depuis_trajectory_step(step: Any, objectif: Any = UNKNOWN) -> EtapeContrat:
    """Lit une etape de trace GOAP (TrajectoryStep) sans la modifier.

    Seules ACTION et OBSERVATION sont connues de la trace ; tout le reste reste UNKNOWN.
    `completed` -> ok=True (ACCEPTED au mieux), `failed` -> ok=False, pending/running -> rien observe.
    """
    intent = getattr(step, "intent", None)
    status = getattr(step, "status", None)
    if status == "completed":
        obs: Any = {"ok": True, "retour": getattr(step, "result", None)}
    elif status == "failed":
        obs = {"ok": False, "retour": getattr(step, "result", None)}
    else:
        obs = UNKNOWN
    return EtapeContrat(
        objectif=objectif,
        capacite=intent.get("method", UNKNOWN) if isinstance(intent, dict) else UNKNOWN,
        action=intent if intent else UNKNOWN,
        observation=obs,
    )


def ligne(e: EtapeContrat, largeur: int = 40) -> str:
    """Rendu une-ligne (journal) : les douze colonnes dans l'ordre du contrat, puis le statut."""
    def _court(v: Any) -> str:
        s = v if isinstance(v, str) else repr(v)
        return s if len(s) <= largeur else s[: largeur - 1] + "…"
    cols = " · ".join("%s=%s" % (c.upper(), _court(getattr(e, c))) for c in COLONNES)
    return "%s || %s" % (cols, verdict_etape(e)["statut"])
