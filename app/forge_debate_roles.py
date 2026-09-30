# -*- coding: utf-8 -*-
"""
forge_debate_roles.py — RÔLES DIALECTIQUES du débat M2M (organe : cognition)
============================================================================

Complète `forge_roles.ROLES` (rôles d'exécution : PLANNER, EXECUTOR, REVIEWER…)
par les rôles de DÉBAT, et s'appuie sur `forge_swarm_team.Participant` pour
savoir QUI incarne un rôle (local_llm / remote_llm / agent) avec sa priorité
d'appel. Rien n'est dupliqué : un rôle dit CE QU'IL FAUT FAIRE et COMMENT le
vérifier ; le swarm dit QUI le fait et par quel chemin.

POURQUOI CES RÔLES, ET PAS UN SEUL
==================================
Mesure externe (arXiv 2509.23055, « Peacemaker or Troublemaker ») : la
sycophancy est un mode de défaillance CENTRAL du débat multi-agents. Elle
provoque un effondrement du désaccord avant la bonne conclusion et rend le
débat MOINS précis qu'un agent seul. Deux sources distinctes : les débatteurs
ET le juge. Un juge complaisant ne corrige donc rien — il ratifie.
Mesure externe (ACL 2026, « When Identity Skews Debate ») : la complaisance est
pilotée par l'IDENTITÉ du pair. Remède retenu : anonymiser les tours.

Mesures internes qui contraignent ce module (2026-08-13) :
- Un juge LLM a rendu « recall 100 % » trois fois de suite alors que le modèle
  répondait MISSED partout : numérotation ajoutée, puis `**MISSED**` en gras.
  87,5 points d'écart pour une étoile de markdown. -> EXTRACTION FAIL-CLOSED.
- Un panel LLM GÉNÈRE, il ne VALIDE jamais : une annotation sans preuve
  exécutable entre comme CANDIDATE, jamais comme fait.
- `rc=0` et `ok:true` ne valent rien : lire le contenu, jamais le code retour.

CE QUE CHAQUE RÔLE DOIT PRODUIRE
================================
`cot_tags` = balises OBLIGATOIRES (le séquençage cognitif imposé).
`publie`   = la SEULE balise transmise aux autres. Les autres sont un
             scratchpad : elles stabilisent le raisonnement sans polluer le fil
             ni permettre à l'adversaire de répondre à un brouillon.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Chemins d'exécution possibles pour un rôle.
LOCAL_ONLY = "local_only"      # ne doit JAMAIS partir au cloud (preuve/arbitrage)
LOCAL_FIRST = "local_first"    # local si dispo, cloud en repli
CLOUD_FIRST = "cloud_first"    # CoT lourde : cloud d'abord, local en dégradé


@dataclass
class DebateRole:
    """Un rôle dialectique : sa fonction, sa contrainte, son timing, son chemin."""

    name: str
    fonction: str
    system_prompt: str
    cot_tags: tuple = ()          # balises obligatoires, dans l'ordre
    publie: str = ""              # balise transmise au fil (vide = rien)
    chemin: str = LOCAL_FIRST
    timeout_s: float = 90.0
    max_tokens: int = 900
    ordre: int = 5                # ordre de parole (1 = en premier)
    anonymise_entrees: bool = True   # masque l'identité des pairs (ACL 2026)
    exige_preuve: bool = False       # toute affirmation doit porter une source
    participants: list = field(default_factory=list)  # ids Participant préférés


_ANTI_CONSENSUS = (
    "LOIS ABSOLUES, tout manquement est une erreur critique :\n"
    "1. Tu ne cherches JAMAIS le compromis, le consensus ni le terrain d'entente.\n"
    "2. Interdiction stricte des formules de politesse rhetorique : « je comprends », "
    "« c'est vrai que », « tu as un bon point », « c'est une perspective interessante ».\n"
    "3. Tu ne t'excuses JAMAIS, meme en corrigeant une erreur factuelle signalee.\n"
    "4. Ta condition de victoire est d'EXPOSER les failles logiques, factuelles ou "
    "philosophiques de l'adversaire — PAS de le rallier. Convaincre l'autre modele est "
    "impossible et sterile : tu t'adresses a l'Orchestrateur et a l'observateur.\n"
)

_IRONMAN = (
    "PROTOCOLE OBLIGATOIRE (REGLE DE L'HOMME DE FER). Structure ta reponse "
    "EXACTEMENT ainsi, sans sauter d'etape :\n"
    "<ironman_reconstruction>Formule la version la plus FORTE et la plus rationnelle "
    "de l'argument adverse. Supprime ses maladresses, renforce sa logique interne. "
    "Prouve que tu en as saisi l'essence.</ironman_reconstruction>\n"
    "<flaw_extraction>Isole chirurgicalement 1 a 3 failles de l'argument que tu viens "
    "de RECONSTRUIRE : biais, premisse fausse, conclusion hative.</flaw_extraction>\n"
    "<refutation>Ta reponse finale — la SEULE qui sera entendue. Attaque les failles "
    "de l'etape 2 et avance ton contre-argument. Clinique, direct, implacable."
    "</refutation>\n"
)

DEBATE_ROLES: dict[str, DebateRole] = {
    # ── Le cadre ────────────────────────────────────────────────────────────
    "ORCHESTRATEUR": DebateRole(
        name="ORCHESTRATEUR",
        fonction="President d'assemblee : tient le cadre, jamais le fond.",
        system_prompt=(
            "Tu es l'ORCHESTRATEUR du debat. Tu ne prends JAMAIS parti sur le fond. "
            "Tu imposes le format, distribues la parole, coupes un agent qui boucle "
            "sur un argument deja avance, et relances par une question de "
            "clarification quand les debatteurs tournent en rond. Tu verifies que "
            "chaque tour respecte le protocole de balises ; un tour hors format est "
            "REJETE, jamais rattrape."
        ),
        cot_tags=("<decision>",),
        publie="<decision>",
        chemin=LOCAL_FIRST, timeout_s=45.0, max_tokens=400, ordre=1,
        anonymise_entrees=False,   # il DOIT savoir qui parle pour arbitrer le tour
    ),
    "GARDIEN_DU_TEMPS": DebateRole(
        name="GARDIEN_DU_TEMPS",
        fonction="Borne les tours, detecte la boucle et l'emballement.",
        system_prompt=(
            "Tu es le GARDIEN DU TEMPS. Tu ne discutes pas : tu comptes. Tu signales "
            "un argument deja avance a l'identique, un tour hors budget, et l'absence "
            "de progression (aucun axe/tension/acquis nouveau sur 2 tours)."
        ),
        cot_tags=("<verdict>",), publie="<verdict>",
        chemin=LOCAL_ONLY, timeout_s=20.0, max_tokens=200, ordre=2,
    ),
    # ── Le fond, polarise ───────────────────────────────────────────────────
    "DEBATTEUR_POUR": DebateRole(
        name="DEBATTEUR_POUR",
        fonction="Defend la these A, refute la these B.",
        system_prompt=(
            "Tu es un moteur dialectique strictement focalise sur la DEFENSE de la "
            "these qui t'est assignee et la refutation methodique de la these "
            "adverse.\n\n" + _ANTI_CONSENSUS + "\n" + _IRONMAN
        ),
        cot_tags=("<ironman_reconstruction>", "<flaw_extraction>", "<refutation>"),
        publie="<refutation>",
        chemin=CLOUD_FIRST, timeout_s=120.0, max_tokens=1200, ordre=3,
    ),
    "DEBATTEUR_CONTRE": DebateRole(
        name="DEBATTEUR_CONTRE",
        fonction="Defend la these B, refute la these A.",
        system_prompt=(
            "Tu es un moteur dialectique strictement focalise sur la DEFENSE de la "
            "these qui t'est assignee et la refutation methodique de la these "
            "adverse.\n\n" + _ANTI_CONSENSUS + "\n" + _IRONMAN
        ),
        cot_tags=("<ironman_reconstruction>", "<flaw_extraction>", "<refutation>"),
        publie="<refutation>",
        chemin=CLOUD_FIRST, timeout_s=120.0, max_tokens=1200, ordre=4,
    ),
    # ── La verite factuelle ─────────────────────────────────────────────────
    "ARBITRE_EPISTEMIQUE": DebateRole(
        name="ARBITRE_EPISTEMIQUE",
        fonction="Fact-checker asynchrone : annote, n'argumente jamais.",
        system_prompt=(
            "Tu es l'ARBITRE EPISTEMIQUE. Tu n'as AUCUNE these a defendre et tu ne "
            "participes pas au debat. Tu verifies les affirmations factuelles avec "
            "tes outils (RAG local, backtest git, recherche). REGLE ABSOLUE : toute "
            "annotation doit porter sa SOURCE VERIFIABLE. Sans source, tu ecris "
            "'INDETERMINE' — jamais un jugement. Un chiffre invente par un debatteur "
            "est signale avec la mesure qui le contredit, pas avec ton opinion."
        ),
        cot_tags=("<annotation>",), publie="<annotation>",
        # LOCAL_ONLY : sa valeur est l'acces aux PREUVES et l'independance, pas la
        # finesse de raisonnement. Un arbitre cloud sans outil n'arbitre rien : il
        # genere un avis — et le juge est justement l'une des deux sources de
        # sycophancy mesurees (arXiv 2509.23055).
        chemin=LOCAL_ONLY, timeout_s=60.0, max_tokens=500, ordre=6,
        exige_preuve=True,
    ),
    "TESTEUR": DebateRole(
        name="TESTEUR",
        fonction="Mesure executable : aucun axe admis sans detecteur qui tire.",
        system_prompt=(
            "Tu es le TESTEUR. Tu n'as pas d'avis. Tu executes le backtest et tu "
            "inscris la MESURE avec son denominateur. Un axe sans detecteur "
            "executable est RETROGRADE en candidat, jamais rejete ni admis."
        ),
        cot_tags=("<mesure>",), publie="<mesure>",
        chemin=LOCAL_ONLY, timeout_s=180.0, max_tokens=600, ordre=7,
        exige_preuve=True,
    ),
    # ── La sortie ───────────────────────────────────────────────────────────
    "SYNTHETISEUR": DebateRole(
        name="SYNTHETISEUR",
        fonction="Cartographie le desaccord ; ne designe AUCUN vainqueur.",
        system_prompt=(
            "Tu es le SYNTHETISEUR. Tu ne designes PAS de vainqueur et tu ne tranches "
            "pas. Tu rediges une CARTOGRAPHIE du debat : points de divergence "
            "fondamentaux, axiomes sur lesquels les positions sont irreconciliables, "
            "et ce qui reste indetermine faute de mesure. Neutralite absolue."
        ),
        cot_tags=("<cartographie>",), publie="<cartographie>",
        chemin=CLOUD_FIRST, timeout_s=150.0, max_tokens=1600, ordre=8,
    ),
    "GREFFIER": DebateRole(
        name="GREFFIER",
        fonction="Journalise le SSoT du debat et anonymise les tours.",
        system_prompt=(
            "Tu es le GREFFIER. Tu n'interpretes rien : tu enregistres le delta de "
            "chaque tour (AXE / TENSION / ACQUIS) dans le SSoT et tu tiens le "
            "journal separe."
        ),
        cot_tags=("<delta>",), publie="<delta>",
        chemin=LOCAL_ONLY, timeout_s=30.0, max_tokens=400, ordre=9,
    ),
}


class TourInvalide(Exception):
    """Le tour ne respecte pas le protocole : il est REJETE, jamais rattrape."""


def extract_cot(texte: str, role: str) -> dict:
    """Extrait les balises d'un tour. FAIL-CLOSED : si UNE balise obligatoire
    manque, le tour est INVALIDE.

    Ne JAMAIS se rabattre sur « prendre tout le texte comme reponse » : c'est ce
    repli qui a produit trois « recall 100 % » mensongers d'affilee (2026-08-13),
    ou un `**MISSED**` en gras devenait une couverture. La sortie BRUTE est
    conservee dans le retour pour que l'ecart reste auditable.
    """
    r = DEBATE_ROLES.get(role.upper())
    if r is None:
        raise TourInvalide(f"role inconnu: {role}")
    out, manquantes = {}, []
    for tag in r.cot_tags:
        nom = tag.strip("<>")
        m = re.search(rf"<{nom}>(.*?)</{nom}>", texte or "", re.S | re.I)
        if not m or not m.group(1).strip():
            manquantes.append(nom)
        else:
            out[nom] = m.group(1).strip()
    # LE CONTRAT PORTE SUR CE QUI EST TRANSMIS, PAS SUR LE BROUILLON.
    # Mesure 2026-08-14 : exiger les TROIS balises rejetait des tours pourtant
    # substantiels — cerebras rendait 758 car. en mettant tout dans les deux
    # premieres, openrouter_free 1917 car. sans respecter la moindre balise.
    # Or les etapes intermediaires sont un SCRATCHPAD : elles ne sont jamais lues
    # par les autres. Imposer un processus interne qu'on ne peut pas verifier
    # revient a jeter du contenu valide ; le fail-closed doit proteger le SSoT,
    # pas discipliner la pensee. Il porte donc sur la SEULE balise publiee.
    pub_nom = (r.publie or "").strip("<>")
    if pub_nom and pub_nom in manquantes:
        raise TourInvalide(
            f"{role}: balise PUBLIEE <{pub_nom}> absente ou vide -> tour REJETE "
            f"(fail-closed ; {len(texte or '')} car. bruts conserves ; "
            f"autres manquantes: {[m for m in manquantes if m != pub_nom]})"
        )
    return {"role": role, "parts": out,
            "publie": out.get(pub_nom, ""), "brut": texte,
            # Signale sans bloquer : un role qui saute son ironmanning est a
            # surveiller (il argumente peut-etre contre un homme de paille).
            "incompletes": [m for m in manquantes if m != pub_nom]}


def anonymise(fil: list, moi: str) -> list:
    """Remplace les identites des pairs par des etiquettes stables (Agent B, C…).

    La complaisance est pilotee par l'IDENTITE du pair (ACL 2026) : un agent
    adopte plus volontiers l'avis d'un pair qu'il identifie. On masque donc QUI
    a parle, jamais CE QUI a ete dit.
    """
    etiquettes, n, sortie = {}, 0, []
    for tour in fil:
        src = str(tour.get("agent") or "?")
        if src.upper() == (moi or "").upper():
            label = "TOI"
        else:
            if src not in etiquettes:
                n += 1
                etiquettes[src] = f"Agent {chr(64 + n)}"
            label = etiquettes[src]
        sortie.append({**tour, "agent": label})
    return sortie


def participants_pour(role: str, equipe=None) -> list:
    """Participants du swarm eligibles a ce role, tries par priorite d'appel.

    Le swarm reste la source de QUI existe (`forge_swarm_team.get_team`) ; ce
    module ne redeclare aucun intervenant. Import paresseux et fail-open : un
    swarm indisponible ne doit pas empecher un debat en local.
    """
    r = DEBATE_ROLES.get(role.upper())
    if r is None:
        return []
    try:
        if equipe is None:
            from nokido_agent.app.forge_swarm_team import get_team

            equipe = get_team()
        vivants = [p for p in getattr(equipe, "participants", []) if getattr(p, "active", False)]
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger("forge.debate").warning(
            "[debat] equipe du swarm ILLISIBLE (%s: %s) | consequence: aucun "
            "participant propose pour %s, l'appelant retombera sur son defaut",
            type(e).__name__, str(e)[:80], role)
        return []
    if r.chemin == LOCAL_ONLY:
        vivants = [p for p in vivants if getattr(p, "kind", "") == "local_llm"]
    elif r.chemin == CLOUD_FIRST:
        vivants.sort(key=lambda p: (getattr(p, "kind", "") != "remote_llm",
                                    getattr(p, "priority", 5)))
        return vivants
    vivants.sort(key=lambda p: (getattr(p, "kind", "") != "local_llm",
                                getattr(p, "priority", 5)))
    return vivants


def ordre_de_parole() -> list:
    """Rôles tries par ordre de parole — le cadre parle avant le fond."""
    return sorted(DEBATE_ROLES.values(), key=lambda r: r.ordre)
