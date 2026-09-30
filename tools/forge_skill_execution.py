"""EXECUTION gouvernee d'un plan de skills, et PROVENANCE de la chaine.

Couche 4 sur 4 :

    CATALOGUE    quels skills existent
    RETRIEVAL    lesquels sont pertinents
    CAPACITES    lesquels permettent d'atteindre un but
    EXECUTION    ce module — agir, OBSERVER, et prouver

Sans cette couche, les trois precedentes forment un excellent planificateur
declaratif et rien de plus : un plan n'est pas un resultat.

LE VERROU, DIT PLUTOT QUE CONTOURNE
-----------------------------------
« Executer forge-anatomy » n'a pas de sens litteral : c'est une grille de
lecture, du texte destine a un LLM. Une capacite n'est executable PAR NOKIDO
que si elle est reliee a une route gouvernee. Sinon elle s'execute cote
CLIENT, ce qui n'est pas la meme chose.

Un executeur qui confond les deux fabrique un succes sans acte. Ici une
capacite sans realisation declaree rend `STEP_NON_EXECUTABLE` et le DIT ;
elle ne simule pas.

CE QUI FAIT QU'UNE ETAPE A REUSSI
---------------------------------
Pas le retour de l'appel. L'ETAT OBSERVE apres coup.

  rc=0                  n'est pas une postcondition
  « message envoye »    n'est pas une postcondition
  un .rc present        n'est pas une postcondition

Chaque realisation porte donc DEUX fonctions : `agir` et `observer`. Le
verdict se lit sur la seconde. C'est la meme regle que « le verdict d'un push
se lit sur le distant, jamais sur le code de retour » — un push Nokido sort en
rc=1 apres avoir publie, et `job_status` dit `running` apres un kill externe.

Et un effet declare `A_VERIFIER` n'entre jamais dans les faits ACQUIS, meme
observe au moment de l'action : `delivered != read`.

NR : tests/nr/test_skill_execution_nr.py
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
import uuid
from typing import Callable

import forge_skill_capability_graph as cg

__FORGE_COLOR__ = "cognition/skill-execution : execution gouvernee et provenance des plans de skills"

NOKIDO_NATIF = "NOKIDO_NATIF"
CLIENT_INSTRUCTION = "CLIENT_INSTRUCTION"

# Transports par client. Nokido possede le catalogue ; les LLM sont des
# effecteurs interchangeables, atteints chacun par son canal.
TRANSPORT_CLIENT = {
    "claude": "client:instruction resident",
    "antigravity": "m2m:notify to=antigravity",
    "agy": "m2m:notify to=antigravity",
    "codex": "client:instruction resident",
    "gemini": "m2m:postal gemini",
}


@dataclasses.dataclass
class Realisation:
    """Comment une capacite AGIT, et comment on OBSERVE son effet.

    `observer` n'est pas optionnel et ne doit jamais se contenter de relire ce
    que `agir` a retourne : il interroge l'etat resultant. Un observateur qui
    lit la sortie de l'action mesure l'intention, pas le monde.
    """

    mode: str
    transport: str
    agir: Callable[[dict], object]
    observer: Callable[[dict], set]


@dataclasses.dataclass
class Execution:
    execution_id: str
    execution_racine: str
    parent_execution_id: str | None
    skill: str
    capability_id: str
    execution_mode: str
    transport: str
    statut: str
    client_cible: str = ""
    # Qualite de l'effet : VERIFIE (un observateur Nokido a confirme),
    # DECLARE (le client l'affirme, rien ne le confirme), INFIRME (l'etat
    # contredit le client). Vide tant qu'aucune delegation n'est revenue.
    qualite_effet: str = ""
    faits_observes: tuple = ()
    faits_acquis: tuple = ()
    faits_manquants: tuple = ()
    motif: str = ""
    debut: float = 0.0
    duree_s: float = 0.0

    @property
    def provenance(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "parent_execution_id": self.parent_execution_id,
            "execution_racine": self.execution_racine,
            "skill_id": self.skill,
            "capability_id": self.capability_id,
            "execution_mode": self.execution_mode,
            "transport": self.transport,
            "client_cible": self.client_cible,
        }

    def ordre_de_mission(self) -> dict:
        """Ce qu'un autre client recoit pour executer cette etape.

        Il porte la LIGNEE : sans elle, ce que le client renverra ne pourra
        pas etre rattache a l'objectif qui l'a demande, et la chaine se
        romprait au premier saut inter-client.
        """
        return self.provenance | {
            "skill": self.skill,
            "mode": self.capability_id.split("::")[-1],
            "effets_attendus": list(self.faits_manquants),
            "a_observer_en_retour": True,
        }


@dataclasses.dataclass
class Trace:
    but: object
    executions: list = dataclasses.field(default_factory=list)
    evenements: list = dataclasses.field(default_factory=list)
    verdict: str = ""
    motif: str = ""
    execution_racine: str = ""
    # Contexte APRES execution. Sans lui, ce que les realisations ont produit
    # (un diagnostic, un etat lu) reste enferme dans la copie de travail :
    # le resultat est calcule puis perdu. Defaut trouve par le NR
    # d'integration, invisible depuis les tests de contrat.
    contexte: dict = dataclasses.field(default_factory=dict)


def _nouvel_id() -> str:
    return "exec_" + uuid.uuid4().hex[:12]


def executer_etape(cap, realisation, contexte: dict, execution_racine: str,
                   parent: str | None = None) -> Execution:
    """Execute UNE capacite, puis observe l'etat resultant.

    Rend toujours une Execution — jamais None, jamais une exception nue : une
    etape qui echoue doit rester dans la trace avec son motif, sinon la
    provenance a un trou et le replan n'a rien a lire.
    """
    e = Execution(
        execution_id=_nouvel_id(),
        execution_racine=execution_racine,
        parent_execution_id=parent,
        skill=cap.skill,
        capability_id=cap.capacite_id,
        execution_mode=CLIENT_INSTRUCTION,
        transport="",
        statut="STEP_NON_EXECUTABLE",
        debut=time.time(),
    )

    attendus = {p.fait for p in cap.postconditions if p.garantie == cg.ACQUISE}

    if realisation is None:
        # DELEGUE n'est pas NON_EXECUTABLE. Confondre les deux ferait lire une
        # impossibilite la ou il y a seulement un autre effecteur a solliciter
        # — meme famille que DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE.
        cibles = [c for c in (cap.clients or ()) if c != "nokido"]
        if cibles:
            e.statut = "STEP_DELEGUE"
            e.client_cible = cibles[0]
            e.transport = TRANSPORT_CLIENT.get(cibles[0], "client:inconnu")
            e.motif = ("Nokido n'a pas de route gouvernee pour cette capacite, "
                       "mais %s peut l'executer : delegation emise, effet NON "
                       "acquis tant qu'il n'est pas observe en retour"
                       % cibles[0])
        else:
            e.motif = ("aucune route gouvernee et aucun client declare capable : "
                       "cette capacite n'est executable par personne en l'etat")
        e.faits_manquants = tuple(sorted(str(f) for f in attendus))
        e.duree_s = round(time.time() - e.debut, 4)
        return e

    e.execution_mode = realisation.mode
    e.transport = realisation.transport

    try:
        realisation.agir(contexte)
    except Exception as exc:  # noqa: BLE001
        e.statut = "STEP_FAILED"
        e.motif = "l'action a leve : %s: %s" % (type(exc).__name__, exc)
        e.faits_manquants = tuple(sorted(str(f) for f in attendus))
        e.duree_s = round(time.time() - e.debut, 4)
        return e

    # L'OBSERVATION est le verdict. Elle est isolee de l'action : si elle
    # leve, on ne sait pas, et « on ne sait pas » n'est pas « ca a marche ».
    try:
        observes = set(realisation.observer(contexte) or ())
    except Exception as exc:  # noqa: BLE001
        e.statut = "STEP_FAILED"
        e.motif = ("l'action est passee mais l'etat resultant n'a pas pu etre "
                   "observe (%s) — indetermine, donc pas un succes" % type(exc).__name__)
        e.faits_manquants = tuple(sorted(str(f) for f in attendus))
        e.duree_s = round(time.time() - e.debut, 4)
        return e

    e.faits_observes = tuple(sorted(observes, key=str))
    manquants = attendus - observes
    # Seuls les effets ACQUIS rejoignent les faits acquis : un effet
    # A_VERIFIER observe au moment de l'action reste a verifier.
    e.faits_acquis = tuple(sorted(attendus & observes, key=str))

    if manquants:
        e.statut = "STEP_FAILED"
        e.faits_manquants = tuple(sorted(str(f) for f in manquants))
        e.motif = ("l'appel a abouti mais l'effet n'est pas observe : %s — "
                   "un retour d'appel n'est pas une postcondition"
                   % ", ".join(e.faits_manquants))
    else:
        e.statut = "STEP_COMPLETED"
        e.motif = "effets observes : %s" % ", ".join(str(f) for f in e.faits_acquis)

    e.duree_s = round(time.time() - e.debut, 4)
    return e


def executer_plan(plan, realisations: dict | None = None,
                  contexte: dict | None = None, racine: str | None = None) -> Trace:
    """Execute les etapes d'un plan dans l'ordre, en conservant la lignee.

    `racine` permet a plusieurs tentatives successives (plan initial puis
    replans) de partager UNE seule lignee : sinon chaque replan ouvrirait sa
    propre provenance et l'objectif ne serait plus rattachable a ce qui a
    reellement ete tente pour l'atteindre.
    """
    realisations = realisations or {}
    contexte = dict(contexte or {})
    racine = racine or _nouvel_id()
    trace = Trace(but=plan.but, execution_racine=racine, contexte=contexte)

    def evt(type_: str, **kw):
        ligne = {"type": type_, "execution_racine": racine,
                 "ts": round(time.time(), 3)}
        ligne.update(kw)
        trace.evenements.append(ligne)

    evt("PLAN_CREATED", but=str(plan.but), etapes=len(plan.etapes),
        verdict_plan=plan.verdict)

    if plan.verdict != "PLAN_TROUVE":
        trace.verdict = "PLAN_ABSENT"
        trace.motif = plan.motif or "aucun plan a executer"
        evt("PLAN_FAILED", motif=trace.motif)
        return trace

    parent = None
    for etape in plan.etapes:
        cap = cg.capacite(etape.skill, etape.mode)
        evt("STEP_SELECTED", capability_id=cap.capacite_id)
        evt("STEP_STARTED", capability_id=cap.capacite_id)

        e = executer_etape(cap, realisations.get(cap.capacite_id), contexte,
                           execution_racine=racine, parent=parent)
        trace.executions.append(e)

        if e.statut == "STEP_DELEGUE":
            # UN seul evenement par etape : en emettre un generique puis un
            # enrichi laisse un lecteur tomber sur le premier, incomplet.
            evt("STEP_DELEGUE", capability_id=cap.capacite_id,
                execution_id=e.execution_id, motif=e.motif,
                client_cible=e.client_cible, transport=e.transport,
                ordre_de_mission=e.ordre_de_mission())
            # Le plan ne peut pas continuer seul : il attend l'effet d'un
            # autre effecteur. Ce n'est ni un echec ni un succes.
            trace.verdict = "PLAN_SUSPENDU_DELEGATION"
            trace.motif = ("%s est delegue a %s : le plan reprend quand l'effet "
                           "sera observe en retour"
                           % (cap.capacite_id, e.client_cible))
            return trace

        evt(e.statut, capability_id=cap.capacite_id,
            execution_id=e.execution_id, motif=e.motif)

        if e.statut != "STEP_COMPLETED":
            trace.verdict = ("REPLAN_REQUIS" if e.faits_manquants else "PLAN_FAILED")
            trace.motif = "%s a %s : %s" % (cap.capacite_id, e.statut, e.motif)
            evt("PLAN_FAILED", motif=trace.motif)
            return trace

        # Les faits acquis alimentent le contexte des etapes suivantes.
        contexte.setdefault("faits", set()).update(e.faits_acquis)
        parent = e.execution_id

    trace.verdict = "PLAN_COMPLETED"
    trace.motif = "%d etape(s) executee(s) et observee(s)" % len(trace.executions)
    evt("PLAN_COMPLETED", motif=trace.motif)
    return trace


def fait_manquant(trace: Trace):
    """Le premier fait qu'une etape n'a pas su produire. NOMME, pas devine."""
    for e in reversed(trace.executions):
        if e.faits_manquants:
            brut = e.faits_manquants[0]
            return cg.Fait(brut.split("(")[0])
    return None


def _fait_depuis_texte(s: str):
    """Un `str(Fait)` redevient un Fait par son TYPE.

    Les qualifs ne sont pas reconstruits : un retour de client ne doit pas
    pouvoir fabriquer un fait plus precis que ce que la capacite declare.
    """
    return cg.Fait(str(s).split("(")[0].strip())


def recevoir_resultat(trace: Trace, retour: dict,
                      observateurs: dict | None = None) -> Execution:
    """Recoit le resultat d'un client delegue, le VERIFIE, et reprend l'etape.

    Trois refus, chacun adosse a un invariant :

      * un retour hors lignee est REJETE — sinon n'importe quel message
        fermerait l'etape d'un autre et injecterait un fait dans un plan
        auquel il n'appartient pas ;
      * un effet que l'observateur INFIRME fait echouer l'etape — le client
        affirme, l'etat dit non, l'etat gagne (`REQUESTED != ACHIEVED`) ;
      * un effet sans observateur reste DECLARE — utilisable pour continuer,
        jamais presente comme mesure (`SIGNAL != PREUVE DE VIE`).
    """
    observateurs = observateurs or {}
    racine = str(retour.get("execution_racine") or "")
    if racine != trace.execution_racine:
        raise ValueError(
            "retour hors lignee : racine %r attendue, %r recue — un resultat "
            "qui ne se rattache pas au plan est refuse"
            % (trace.execution_racine, racine))

    eid = str(retour.get("execution_id") or "")
    cibles = [e for e in trace.executions if e.execution_id == eid]
    if not cibles:
        raise ValueError("aucune etape %r dans cette lignee" % eid)
    e = cibles[0]
    if e.statut != "STEP_DELEGUE":
        raise ValueError("l'etape %s n'attend aucun resultat (statut %s)"
                         % (e.capability_id, e.statut))

    skill, mode = e.capability_id.split("::", 1)
    cap = cg.capacite(skill, mode)
    attendus = {p.fait for p in cap.postconditions if p.garantie == cg.ACQUISE}
    declares = {_fait_depuis_texte(f) for f in (retour.get("effets_declares") or ())}

    def evt(type_, **kw):
        ligne = {"type": type_, "execution_racine": trace.execution_racine,
                 "ts": round(time.time(), 3), "execution_id": e.execution_id}
        ligne.update(kw)
        trace.evenements.append(ligne)

    evt("RESULTAT_RECU", capability_id=e.capability_id,
        client=e.client_cible, effets_declares=sorted(str(f) for f in declares))

    manquants = attendus - declares
    if manquants:
        e.statut = "STEP_FAILED"
        e.qualite_effet = "EFFET_ABSENT"
        e.faits_manquants = tuple(sorted(str(f) for f in manquants))
        e.motif = ("le client %s n'a pas rendu : %s"
                   % (e.client_cible, ", ".join(e.faits_manquants)))
        evt("STEP_FAILED", motif=e.motif)
        return e

    obs = observateurs.get(e.capability_id)
    if obs is None:
        # Aucun observateur independant : on ne peut ni confirmer ni infirmer.
        # Accepter en le DISANT, plutot que bloquer toute delegation ou faire
        # passer une affirmation pour une mesure.
        e.statut = "STEP_COMPLETED"
        e.qualite_effet = "EFFET_DECLARE"
        e.faits_acquis = tuple(sorted(attendus, key=str))
        e.motif = ("effet DECLARE par %s, non verifiable par Nokido (aucun "
                   "observateur independant) — utilisable, pas une mesure"
                   % e.client_cible)
        evt("EFFET_DECLARE", motif=e.motif)
        return e

    try:
        observes = set(obs(trace.contexte) or ())
    except Exception as exc:  # noqa: BLE001
        e.statut = "STEP_FAILED"
        e.qualite_effet = "EFFET_NON_OBSERVABLE"
        e.motif = ("l'observation du retour a leve (%s) — indetermine, donc "
                   "pas un succes" % type(exc).__name__)
        evt("STEP_FAILED", motif=e.motif)
        return e

    if attendus <= observes:
        e.statut = "STEP_COMPLETED"
        e.qualite_effet = "EFFET_VERIFIE"
        e.faits_observes = tuple(sorted(observes, key=str))
        e.faits_acquis = tuple(sorted(attendus, key=str))
        e.motif = "effet VERIFIE apres retour de %s" % e.client_cible
        evt("EFFET_VERIFIE", motif=e.motif)
    else:
        e.statut = "STEP_FAILED"
        e.qualite_effet = "EFFET_INFIRME"
        e.faits_acquis = ()
        e.faits_manquants = tuple(sorted(str(f) for f in (attendus - observes)))
        e.motif = ("%s declare %s mais l'etat ne le confirme pas : l'etat "
                   "l'emporte" % (e.client_cible,
                                  ", ".join(sorted(str(f) for f in attendus))))
        evt("EFFET_INFIRME", motif=e.motif)
    return e


def reprendre(trace: Trace, realisations: dict | None = None,
              but=None, contexte: dict | None = None) -> Trace:
    """Reprend un plan suspendu, sous la MEME lignee.

    Les faits acquis par les etapes deja faites — retours de clients compris —
    deviennent les `connus` de la suite. Une nouvelle racine romprait le
    rattachement a l'objectif initial.
    """
    connus = set()
    for e in trace.executions:
        connus.update(_fait_depuis_texte(f) for f in e.faits_acquis)
    cible = but if but is not None else trace.but
    plan = cg.planifier(cible, connus=connus)
    suite = executer_plan(plan, realisations, contexte or trace.contexte,
                          racine=trace.execution_racine)
    suite.evenements = trace.evenements + suite.evenements
    suite.executions = trace.executions + suite.executions
    # Recalculer APRES fusion : le plan de reprise peut etre vide (tout etait
    # deja acquis) et son motif annoncerait « 0 etape » sur une chaine qui en
    # a execute trois. Un chiffre faux dans une preuve est pire qu'absent.
    if suite.verdict == "PLAN_COMPLETED":
        faites = sum(1 for e in suite.executions if e.statut == "STEP_COMPLETED")
        suite.motif = "%d etape(s) menees a leur effet" % faites
        # Corriger AUSSI le dernier evenement : la vue humaine et le journal
        # machine doivent dire la meme chose. Ne corriger que la premiere
        # laisse un chiffre faux dans ce qui sert de PREUVE exploitable —
        # c'est la moitie de la correction, donc une correction fausse.
        for ev in reversed(suite.evenements):
            if ev.get("type") == "PLAN_COMPLETED":
                ev["motif"] = suite.motif
                break
    return suite


def resume_qualite(trace: Trace) -> dict:
    """Sur quoi la preuve repose-t-elle : mesures ou declarations ?

    Un plan dont une etape repose sur une declaration ne doit pas se
    presenter comme entierement mesure.
    """
    compte: dict = {}
    for e in trace.executions:
        if e.qualite_effet:
            compte[e.qualite_effet] = compte.get(e.qualite_effet, 0) + 1
    compte["repose_sur_declaration"] = compte.get("EFFET_DECLARE", 0) > 0
    return compte


def capacites_echouees(trace: Trace) -> set:
    """Les capacites a ne PAS reproposer : elles viennent d'ECHOUER.

    Une etape DELEGUEE n'en fait pas partie : elle n'a pas echoue, elle
    attend un autre effecteur. L'exclure ferait chercher une alternative a
    quelque chose qui est simplement en cours — et, faute d'alternative, le
    plan se conclurait « absent » alors qu'il est suspendu.
    """
    return {e.capability_id for e in trace.executions
            if e.statut not in ("STEP_COMPLETED", "STEP_DELEGUE")}


def replanifier(trace: Trace, connus: set | None = None):
    """Replanifie en visant le FAIT observe comme manquant.

    Le replan est une recherche dans le graphe de capacites, pas une
    regeneration libre : on repart de ce que la mesure a montre absent, et on
    EXCLUT ce qui vient d'echouer — sans quoi on repropose exactement la
    capacite qui n'a pas marche et la boucle tourne.
    """
    besoin = fait_manquant(trace)
    acquis = set(connus or ())
    for e in trace.executions:
        acquis.update(cg.Fait(str(f).split("(")[0]) for f in e.faits_acquis)
    exclues = frozenset(capacites_echouees(trace))
    cible = besoin if besoin is not None else trace.but
    return cg.planifier(but=cible, connus=acquis, exclues=exclues)


def executer_avec_replan(but, realisations: dict | None = None,
                         connus: set | None = None, contexte: dict | None = None,
                         max_replans: int = 3) -> Trace:
    """Planifie, execute, et REJOUE par un autre chemin si une etape echoue.

    L'alternative n'est pas inventee : elle est cherchee dans le graphe parmi
    les producteurs du meme fait. Si le catalogue n'en offre aucun, la boucle
    s'arrete en le DISANT — c'est un manque de matiere, pas un echec du
    mecanisme, et les deux ne se rapportent pas de la meme facon.
    """
    racine = _nouvel_id()
    exclues: set = set()
    contexte = dict(contexte or {})
    derniere: Trace | None = None

    for essai in range(max(1, max_replans + 1)):
        plan = cg.planifier(but, connus=connus, exclues=frozenset(exclues))
        trace = executer_plan(plan, realisations, contexte, racine=racine)
        if derniere is not None:
            trace.evenements = derniere.evenements + [{
                "type": "PLAN_REPLANNED", "execution_racine": racine,
                "ts": round(time.time(), 3), "essai": essai,
                "exclues": sorted(exclues),
            }] + trace.evenements
            trace.executions = derniere.executions + trace.executions
        derniere = trace
        contexte = trace.contexte

        if trace.verdict in ("PLAN_COMPLETED", "PLAN_SUSPENDU_DELEGATION"):
            # Suspendu n'est pas echoue : on ne rejoue pas, on rend la main
            # avec l'ordre de mission a transmettre.
            return trace

        nouvelles = capacites_echouees(trace) - exclues
        if not nouvelles:
            trace.motif = (trace.motif + " ; aucune alternative dans le graphe : "
                           "manque de matiere, pas defaut du mecanisme")
            return trace
        exclues |= nouvelles

    return derniere


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print("usage: forge_skill_execution.py <type_de_fait_but> [--json]")
        return 0
    but = cg.Fait(args[0])
    contexte: dict = {}
    connus: set = set()
    if "--service" in args:
        service = args[args.index("--service") + 1]
        contexte["service"] = service
        # Fait d'ENTREE : fourni par l'appelant, pas produit par un skill.
        connus.add(cg.Fait("service_nomme"))
    trace = executer_avec_replan(but, realisations_reelles(), connus=connus,
                                 contexte=contexte)

    if "--retour-de" in args and trace.verdict == "PLAN_SUSPENDU_DELEGATION":
        # Un client a repondu a l'ordre de mission. Le retour est VERIFIE
        # comme n'importe quel effet : le deposer ne suffit pas a l'acquerir.
        import pathlib as _p

        chemin = args[args.index("--retour-de") + 1]
        recu = json.loads(_p.Path(chemin).read_text(encoding="utf-8"))
        recu.setdefault("execution_racine", trace.execution_racine)
        recu.setdefault("execution_id", trace.executions[-1].execution_id)
        try:
            recevoir_resultat(trace, recu)
        except ValueError as exc:
            print("RETOUR REFUSE : %s" % exc)
            return 1
        trace = reprendre(trace, realisations_reelles(), but=but)

    if "--json" in args:
        # `Fait` n'est pas serialisable : sans cette conversion le CLI meurt
        # en TypeError alors que toutes ses fonctions sont vertes. Troisieme
        # occurrence du motif « le point d'entree casse, pas la fonction ».
        print(json.dumps({
            "but": str(trace.but), "verdict": trace.verdict,
            "motif": trace.motif,
            "execution_racine": trace.execution_racine,
            "executions": [e.provenance | {
                "statut": e.statut,
                "faits_acquis": [str(f) for f in e.faits_acquis],
                "faits_observes": [str(f) for f in e.faits_observes],
                "faits_manquants": [str(f) for f in e.faits_manquants],
                "duree_s": e.duree_s,
                "motif": e.motif}
                for e in trace.executions],
            "evenements": trace.evenements,
            # Le RESULTAT, pas seulement la trace : une preuve qui montre le
            # parcours sans montrer ce qui a ete produit ne prouve que le
            # parcours. Filtre aux valeurs serialisables — le contexte porte
            # aussi des ensembles de faits internes.
            "resultat": {k: v for k, v in trace.contexte.items()
                         if isinstance(v, (str, int, float, bool)) or v is None},
        }, indent=2, ensure_ascii=False))
        return 0

    print("BUT      : %s" % trace.but)
    print("VERDICT  : %s (%s)" % (trace.verdict, trace.motif))
    print("LIGNEE   : %s" % trace.execution_racine)
    if trace.contexte.get("diagnostic"):
        print("RESULTAT : %s" % trace.contexte["diagnostic"])
    q = resume_qualite(trace)
    if q.get("repose_sur_declaration"):
        print("QUALITE  : au moins un effet repose sur une DECLARATION de "
              "client, non verifiee par Nokido — %s"
              % {k: v for k, v in q.items() if k != "repose_sur_declaration"})
    for e in trace.executions:
        print("  [%s] %s" % (e.statut, e.capability_id))
        print("      exec=%s parent=%s mode=%s transport=%s"
              % (e.execution_id, e.parent_execution_id, e.execution_mode,
                 e.transport))
        print("      %s" % e.motif)
    return 0


def realisations_reelles() -> dict:
    """Charge le cablage reel A LA DEMANDE, jamais a l'import.

    `forge_skill_realisations` importe ce module pour la classe `Realisation` ;
    le charger ici au moment de l'import creait un CYCLE. Le cycle ne levait
    pas toujours : selon qui importait en premier, le dictionnaire restait
    VIDE et toutes les capacites rendaient STEP_NON_EXECUTABLE — un
    comportement qui depend de l'ordre d'import est indetectable en lecture
    et se manifeste ailleurs (meme famille que « deux noms d'import = deux
    instances », payee le 2026-09-10).

    Mesure qui l'a revele : le CLI fonctionnait tandis que la meme chaine
    sous pytest journalisait « cablage reel indisponible (ImportError) ».
    """
    global _CACHE_REALISATIONS
    if _CACHE_REALISATIONS is not None:
        return _CACHE_REALISATIONS
    try:
        from forge_skill_realisations import REALISATIONS as _reelles

        _CACHE_REALISATIONS = dict(_reelles)
    except Exception as exc:  # noqa: BLE001  # muet-ok
        # Un garde journalise TOUJOURS, et son journal ne leve JAMAIS — le
        # garde RSS du wrapper de job est mort sur son propre journal.
        try:
            import sys as _s

            print("[skill_execution] cablage reel indisponible (%s) : les "
                  "capacites rendront STEP_NON_EXECUTABLE" % type(exc).__name__,
                  file=_s.stderr, flush=True)
        except Exception:  # noqa: BLE001  # muet-ok
            pass
        _CACHE_REALISATIONS = {}
    return _CACHE_REALISATIONS


_CACHE_REALISATIONS: dict | None = None


if __name__ == "__main__":
    sys.exit(main())
