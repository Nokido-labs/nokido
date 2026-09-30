"""Graphe de CAPACITES — ce qu'un skill EXIGE, ce qu'il PRODUIT.

Couche 3 sur 3 :

    CATALOGUE  forge_skill_catalogue   quels skills EXISTENT
    RETRIEVAL  forge_skill_retrieval   lesquels sont PERTINENTS
    CAPACITES  ce module               lesquels PERMETTENT d'atteindre un but

Le retrieval repond « quel skill ressemble a ma question ». C'est utile et
insuffisant : sur « diagnostiquer pourquoi le webhub ne repond plus », trois
candidats sortent a lexical 0.200 exactement, chacun sur un mot different, et
le bon arrive troisieme. Une ressemblance textuelle ne dit pas si un skill
PEUT faire avancer vers le but.

Ici le planner raisonne sur des dependances de connaissances :

    A produit F1 -> B exige F1 -> B produit F2 -> ...

CE QUE CINQ SKILLS REELS ONT IMPOSE AU MODELE
---------------------------------------------
Les declarations ci-dessous sont ecrites depuis les descriptions LUES de
skills volontairement dissemblables. Trois contraintes en sont sorties,
aucune n'etait prevue :

1. UN SKILL PORTE N CAPACITES. `netcfg-agent` annonce « preview/dry-run avant
   deploy SSH » : observer une derive de configuration et pousser une config
   sur un switch ne partagent ni les preconditions, ni le risque, ni la
   reversibilite. Un contrat unique serait trop permissif pour le deploy ou
   trop bloquant pour le preview.

2. EPISTEMIQUE != PHYSIQUE. `forge-anatomy` ne change rien au monde : il rend
   un fait CONNU. `netcfg deploy` modifie un equipement. Les confondre
   laisserait un planner croire qu'un deploiement SSH se rejoue ou s'annule
   comme on oublie un fait.

3. UN EFFET PEUT ETRE NON GARANTI. `forge-m2m-debat-mesure` porte dans sa
   propre description « delivered != lu ». Chainer sur un effet seulement
   DEMANDE, c'est REQUESTED != ACHIEVED — la faute que la constitution
   semantique interdit nommement. Un effet `A_VERIFIER` impose une
   observation avant qu'on puisse s'appuyer dessus.

PORTEE ASSUMEE : six skills declares sur trente. Le contrat se prouve sur des
familles dissemblables AVANT d'etre etendu ; declarer les trente d'abord
aurait fige une taxonomie qu'aucune mesure n'aurait validee.

NR : tests/nr/test_skill_capability_graph_nr.py
"""

from __future__ import annotations

import dataclasses
import sys

__FORGE_COLOR__ = "cognition/skill-capability-graph : dependances de connaissances entre skills"

EPISTEMIQUE = "EPISTEMIQUE"
PHYSIQUE = "PHYSIQUE"
ACQUISE = "ACQUISE"
A_VERIFIER = "A_VERIFIER"


@dataclasses.dataclass(frozen=True)
class Fait:
    """Une connaissance ou un etat du monde, identifie par son TYPE.

    `hors_controle` est exclu de l'identite : c'est une propriete du contexte
    (« Nokido ne peut pas produire ce fait lui-meme »), pas du fait. L'inclure
    empecherait de reconnaitre qu'un fait exige ici est bien celui produit la.
    """

    type: str
    qualif: tuple[tuple[str, str], ...] = ()
    hors_controle: bool = dataclasses.field(default=False, compare=False)

    def __init__(self, type: str, hors_controle: bool = False, **qualif: object):
        object.__setattr__(self, "type", type)
        object.__setattr__(self, "qualif",
                           tuple(sorted((k, str(v)) for k, v in qualif.items())))
        object.__setattr__(self, "hors_controle", hors_controle)

    def __str__(self) -> str:
        q = ", ".join("%s=%s" % kv for kv in self.qualif)
        return "%s(%s)" % (self.type, q) if q else self.type


@dataclasses.dataclass(frozen=True)
class Effet:
    """Un fait produit par une capacite, avec sa NATURE et sa GARANTIE."""

    fait: Fait
    garantie: str = ACQUISE
    nature: str = EPISTEMIQUE


@dataclasses.dataclass(frozen=True)
class Capacite:
    skill: str
    mode: str
    preconditions: tuple[Fait, ...]
    postconditions: tuple[Effet, ...]
    side_effects: tuple[str, ...] = ()
    risque: str = "FAIBLE"
    reversible: bool = True
    cout: int = 1
    clients: tuple[str, ...] = ("claude",)

    @property
    def capacite_id(self) -> str:
        return "%s::%s" % (self.skill, self.mode)


# --- Declarations, ecrites depuis les descriptions LUES des skills -----------
CAPACITES: tuple[Capacite, ...] = (
    # Lecture pure. « Grille de lecture anatomique », « charge la cartographie
    # organes -> modules ». Rien ne change dans le monde : que du su.
    Capacite(
        skill="forge-anatomy", mode="diagnostiquer",
        preconditions=(),
        postconditions=(
            Effet(Fait("organe_identifie"), ACQUISE, EPISTEMIQUE),
            Effet(Fait("pathologie_nommee"), ACQUISE, EPISTEMIQUE),
        ),
        cout=1,
    ),
    # Diagnostic de pipeline : consommateur vivant, vocabulaire, backlog.
    # Sixieme temoin, ajoute parce que le scenario de chainage l'exige — c'est
    # LUI qui remonte a une cause, la ou l'anatomie s'arrete a la pathologie.
    Capacite(
        skill="forge-workflow-autopsy", mode="autopsier",
        preconditions=(Fait("pathologie_nommee"),),
        postconditions=(
            Effet(Fait("consommateur_vivant_connu"), ACQUISE, EPISTEMIQUE),
            Effet(Fait("cause_de_panne_connue"), ACQUISE, EPISTEMIQUE),
        ),
        cout=2,
    ),
    # --- Les deux capacites ci-dessous sont EXECUTABLES PAR NOKIDO ----------
    # Le reste du catalogue est, a ce stade, du corpus d'instructions destine
    # a un client LLM. Ces deux-la pointent vers un etat REEL et observable
    # (les 49 heartbeats de sandbox/), en LECTURE SEULE : elles permettent un
    # E2E complet sans qu'aucun effet irreversible ne serve de demonstration.
    Capacite(
        skill="forge-workflow-autopsy", mode="sonder_consommateur",
        preconditions=(Fait("service_nomme"),),
        postconditions=(Effet(Fait("etat_consommateur_connu"), ACQUISE, EPISTEMIQUE),),
        risque="FAIBLE", reversible=True, cout=1,
        clients=("nokido",),
    ),
    # SECOND OBSERVATEUR du meme fait, par un chemin INDEPENDANT.
    # Ce n'est pas un doublon de complaisance : RULES_SHARED impose qu'aucune
    # decision ne repose sur un signal unique quand plusieurs observateurs
    # existent. Mesure du 2026-09-12 : 6 services declarent un pouls dont le
    # fichier est ABSENT et portent `disabled = true`. Le heartbeat ne peut
    # rien en dire ; la declaration, si — et elle rend DISABLED_BY_POLICY,
    # pas « mort ». Sans ce second chemin on enverrait reparer un CHOIX.
    # Cout superieur : le plan essaie d'abord le pouls, moins cher.
    Capacite(
        skill="forge-hub", mode="sonder_service_declare",
        preconditions=(Fait("service_nomme"),),
        postconditions=(Effet(Fait("etat_consommateur_connu"), ACQUISE, EPISTEMIQUE),),
        risque="FAIBLE", reversible=True, cout=3,
        clients=("nokido",),
    ),
    # Mecanise la checklist du skill : consommateur fige => drain mort ; frais
    # => chercher en aval. C'est la procedure que le skill DOCUMENTE ; la
    # laisser vivre uniquement dans la session d'un agent la fait re-payer.
    Capacite(
        skill="forge-workflow-autopsy", mode="conclure_cause",
        preconditions=(Fait("etat_consommateur_connu"),),
        postconditions=(Effet(Fait("diagnostic_pipeline_rendu"), ACQUISE, EPISTEMIQUE),),
        risque="FAIBLE", reversible=True, cout=1,
        clients=("nokido",),
    ),
    # DELEGUEE par nature. `forge-anatomy` documente organe -> pathologie ->
    # REMEDE. Les deux premiers se mecanisent ; le troisieme demande du
    # jugement sur un cas particulier, et Nokido n'a aucune route gouvernee
    # pour cela. La declarer executable localement serait mentir sur ce que
    # le corps sait faire.
    Capacite(
        skill="forge-anatomy", mode="proposer_remede",
        preconditions=(Fait("diagnostic_pipeline_rendu"),),
        postconditions=(Effet(Fait("remede_propose"), ACQUISE, EPISTEMIQUE),),
        risque="FAIBLE", reversible=True, cout=5,
        clients=("claude",),
    ),
    # Ecriture locale, reversible par git.
    Capacite(
        skill="skill-creator", mode="creer",
        preconditions=(Fait("intention_de_skill_formulee"),),
        postconditions=(Effet(Fait("skill_ecrit"), ACQUISE, PHYSIQUE),),
        side_effects=("ecriture_disque",),
        risque="MOYEN", reversible=True, cout=3,
    ),
    # netcfg-agent, capacite 1 : OBSERVER. « drift detection running-config »,
    # « preview/dry-run ». Lit l'equipement, ne le modifie pas.
    Capacite(
        skill="netcfg-agent", mode="observer",
        preconditions=(Fait("equipement_joignable", hors_controle=True),
                       Fait("credentials_disponibles", hors_controle=True)),
        postconditions=(
            Effet(Fait("config_observee"), ACQUISE, EPISTEMIQUE),
            Effet(Fait("derive_de_config_connue"), ACQUISE, EPISTEMIQUE),
        ),
        risque="FAIBLE", reversible=True, cout=2,
    ),
    # netcfg-agent, capacite 2 : DEPLOYER. « deploy SSH ». Modifie un
    # equipement reseau reel. Aucun rollback automatique : un switch mal
    # configure peut couper l'acces par lequel on le configurait.
    Capacite(
        skill="netcfg-agent", mode="deployer",
        preconditions=(Fait("equipement_joignable", hors_controle=True),
                       Fait("credentials_disponibles", hors_controle=True),
                       Fait("derive_de_config_connue")),
        postconditions=(Effet(Fait("config_deployee"), ACQUISE, PHYSIQUE),),
        side_effects=("modification_equipement_reseau", "coupure_possible"),
        risque="HAUT", reversible=False, cout=8,
    ),
    # Pipeline 7 etapes : SearXNG + Ollama + Groq + crawl. Tous hors controle.
    Capacite(
        skill="forge-veille-approfondie", mode="veiller",
        preconditions=(Fait("theme_exploratoire_fourni"),
                       Fait("services_de_veille_disponibles", hors_controle=True)),
        postconditions=(Effet(Fait("corpus_ingere"), ACQUISE, PHYSIQUE),),
        side_effects=("ecriture_rag",),
        risque="MOYEN", reversible=True, cout=8,
    ),
    # Debat M2M. Sa description dit « delivered != lu » : l'emission est
    # acquise, la LECTURE par le pair ne l'est pas.
    Capacite(
        skill="forge-m2m-debat-mesure", mode="debattre",
        preconditions=(Fait("pair_m2m_vivant", hors_controle=True),
                       Fait("sujet_de_debat_pose")),
        postconditions=(
            Effet(Fait("message_emis"), ACQUISE, PHYSIQUE),
            Effet(Fait("debat_tenu"), A_VERIFIER, EPISTEMIQUE),
        ),
        risque="FAIBLE", reversible=True, cout=4,
        clients=("claude", "antigravity"),
    ),
)

_INDEX = {c.capacite_id: c for c in CAPACITES}


def capacite(skill: str, mode: str) -> Capacite:
    """Rend une capacite, ou LEVE. Jamais None.

    Un None silencieux se propagerait jusqu'a un plan vide dont personne ne
    saurait dire s'il est impossible ou mal interroge.
    """
    cle = "%s::%s" % (skill, mode)
    if cle not in _INDEX:
        raise KeyError("capacite inconnue : %s" % cle)
    return _INDEX[cle]


def satisfait(effets, besoin: Fait) -> bool:
    """Un besoin n'est satisfait que par un effet ACQUIS.

    C'est le garde REQUESTED != ACHIEVED : un effet `A_VERIFIER` est une
    intention. S'appuyer dessus, c'est batir un plan sur un fait qu'on espere.
    """
    for e in effets or ():
        f = e.fait if isinstance(e, Effet) else e
        garantie = e.garantie if isinstance(e, Effet) else ACQUISE
        if f == besoin and garantie == ACQUISE:
            return True
    return False


def vers_action_goap(cap: Capacite) -> dict:
    """Projette une capacite sur le contrat Action de forge_goap_hub_bridge.

    On REUTILISE le moteur BFS existant : il porte deja
    preconditions/effects/cost. En ecrire un second serait le systeme
    parallele que la discipline de chantier interdit.
    """
    return {
        "nom": cap.capacite_id,
        "cost": cap.cout,
        "preconditions": {str(p): True for p in cap.preconditions},
        "effects": {str(e.fait): True for e in cap.postconditions
                    if e.garantie == ACQUISE},
        "risque": cap.risque,
        "reversible": cap.reversible,
        "side_effects": list(cap.side_effects),
    }


@dataclasses.dataclass
class Etape:
    skill: str
    mode: str
    produit: tuple[str, ...]


@dataclasses.dataclass
class Plan:
    but: Fait
    etapes: list[Etape]
    verdict: str
    motif: str = ""
    manquants: list[str] = dataclasses.field(default_factory=list)
    connus_initiaux: set = dataclasses.field(default_factory=set)


def _producteurs(besoin: Fait, exclues: frozenset = frozenset()) -> list[Capacite]:
    """Capacites dont un effet ACQUIS porte le type demande.

    `exclues` porte les capacites deja essayees et echouees : sans elles, un
    replan repropose exactement ce qui vient d'echouer et la boucle tourne.
    """
    return [c for c in CAPACITES
            for e in c.postconditions
            if e.garantie == ACQUISE and e.fait.type == besoin.type
            and c.capacite_id not in exclues]


def planifier(but: Fait, connus: set | None = None, profondeur_max: int = 6,
              exclues: frozenset | None = None) -> Plan:
    """Chainage arriere : quels skills produisent ce qui manque pour le but.

    Les preconditions `hors_controle` ne sont PAS traitees comme des sous-buts :
    aucun skill ne les produit, et les poursuivre ferait tourner la recherche
    en rond. Elles sont des CONDITIONS D'ENTREE, rapportees telles quelles.
    """
    connus = set(connus or ())
    exclues = frozenset(exclues or ())
    etapes: list[Etape] = []
    acquis = set(connus)
    manquants: list[str] = []

    def resoudre(besoin: Fait, profondeur: int) -> bool:
        if any(f.type == besoin.type for f in acquis):
            return True
        if profondeur > profondeur_max:
            manquants.append(str(besoin) + " (profondeur max atteinte)")
            return False
        prods = _producteurs(besoin, exclues)
        if not prods:
            manquants.append(str(besoin))
            return False
        # Le moins couteux d'abord ; a cout egal, ordre declare (deterministe).
        for cap in sorted(prods, key=lambda c: (c.cout, c.capacite_id)):
            pres = [p for p in cap.preconditions if not p.hors_controle]
            if all(resoudre(p, profondeur + 1) for p in pres):
                if cap.capacite_id not in {"%s::%s" % (e.skill, e.mode)
                                           for e in etapes}:
                    etapes.append(Etape(
                        skill=cap.skill, mode=cap.mode,
                        produit=tuple(str(e.fait) for e in cap.postconditions
                                      if e.garantie == ACQUISE)))
                    acquis.update(e.fait for e in cap.postconditions
                                  if e.garantie == ACQUISE)
                return True
        return False

    ok = resoudre(but, 0)
    if ok:
        return Plan(but=but, etapes=etapes, verdict="PLAN_TROUVE",
                    motif="%d etape(s)" % len(etapes), connus_initiaux=connus)
    verdict = "AUCUN_PRODUCTEUR" if not _producteurs(but, exclues) else "PLAN_IMPOSSIBLE"
    return Plan(but=but, etapes=etapes, verdict=verdict,
                motif=("aucune capacite declaree ne produit ce fait — chercher "
                       "un skill qui le produit, ou etendre les declarations"),
                manquants=manquants or [str(but)], connus_initiaux=connus)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print("usage: forge_skill_capability_graph.py <type_de_fait_but>")
        print("faits productibles :")
        for t in sorted({e.fait.type for c in CAPACITES for e in c.postconditions}):
            print("  " + t)
        return 0
    plan = planifier(Fait(args[0]))
    print("BUT     : %s" % plan.but)
    print("VERDICT : %s  (%s)" % (plan.verdict, plan.motif))
    for i, e in enumerate(plan.etapes, 1):
        print("  %d. %s::%s -> %s" % (i, e.skill, e.mode, ", ".join(e.produit)))
    if plan.manquants:
        print("MANQUE  : %s" % "; ".join(plan.manquants))
    return 0


if __name__ == "__main__":
    sys.exit(main())
