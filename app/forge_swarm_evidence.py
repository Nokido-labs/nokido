#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_swarm_evidence.py -- le swarm compte des PREUVES, pas des voix.

POURQUOI CE MODULE (2026-08-20). Le swarm actuel traite un provider comme un
juge : `infer_fn()` reussit ou echoue, et un echec fait basculer sur le suivant.
Deux consequences mesurees ce jour meme :

  1. « groq indisponible » et « le patch casse les tests » etaient traites
     pareil, alors que le premier ne dit RIEN sur la tache et le second
     beaucoup. Un timeout de transport n'est pas un verdict sur le probleme.
  2. Trois modeles d'accord peuvent avoir copie la MEME erreur conceptuelle.
     Compter les reponses revient a compter des echos.

Ce module pose trois primitives, et une seule these :

    UNE REPONSE DE LLM N'EST PAS UNE VERITE.
    C'EST UNE OBSERVATION ISSUE D'UNE SOURCE PARTIELLEMENT FIABLE.

  - `classer_erreur`   : distingue l'echec de TRANSPORT de l'echec de TACHE.
  - `groupe_independance` : Claude via trois passerelles = UNE voix, pas trois.
  - `arbitrer`         : tranche sur les preuves DETERMINISTES (tests, AST,
                         invariants), les LLM ne servant qu'a PROPOSER.

Et un etat que les architectures de swarm oublient presque toujours :
`CONTESTED`. Deux solutions differentes qui passent toutes deux les tests ne
donnent pas un gagnant a la majorite -- elles donnent un desaccord, qui appelle
un contradicteur. De meme, `ABSTAIN` est une REUSSITE du systeme : conclure sans
preuve independante suffisante serait le seul vrai echec.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `resoudre_pointer_ref` — Resout un pointer_ref M2M (`schema:reste`) vers {present, verifie, detail}.
- `verdict_livrable` — Verdict sur un livrable M2M (task_result / OK_DONE / postal) : preuve != parole.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

__FORGE_COLOR__ = "GREEN"

# --------------------------------------------------------------------------
# 1. Classer l'erreur AVANT de decider quoi retenter
# --------------------------------------------------------------------------

# Echecs de TRANSPORT : ils ne disent rien de la tache. Changer de provider est
# utile ; s'acharner sur le meme ne l'est pas toujours.
TRANSPORT_TIMEOUT = "TRANSPORT_TIMEOUT"
RATE_LIMIT = "RATE_LIMIT"
AUTH = "AUTH"
QUOTA = "QUOTA"
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
MODEL_CONTEXT = "MODEL_CONTEXT"

# Echecs de GENERATION : le provider a repondu, mais la forme est inutilisable.
GENERATION_EMPTY = "GENERATION_EMPTY"
FORMAT_INVALID = "FORMAT_INVALID"
PATCH_INVALID = "PATCH_INVALID"

# Echecs de TACHE : ceux-la portent une information sur le probleme lui-meme.
TEST_FAILURE = "TEST_FAILURE"
SEMANTIC_FAILURE = "SEMANTIC_FAILURE"
DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"

# Refus de sûrete : JAMAIS de retry aveugle -- reessayer jusqu'a passer est
# exactement la manière de contourner un garde.
SECURITY_REJECTION = "SECURITY_REJECTION"

INCONNU = "UNKNOWN"

TRANSPORT = (TRANSPORT_TIMEOUT, RATE_LIMIT, AUTH, QUOTA,
             PROVIDER_UNAVAILABLE, MODEL_CONTEXT)
GENERATION = (GENERATION_EMPTY, FORMAT_INVALID, PATCH_INVALID)
TACHE = (TEST_FAILURE, SEMANTIC_FAILURE, DEPENDENCY_FAILURE)

# Motifs lus sur les messages REELS rencontres dans ce depot. Chacun est ancre
# sur une observation, pas sur une supposition : les libelles de rotation de
# cles (« ECARTEE par la rotation »), les 503 d'ollama satures, les refus du
# garde de mutation.
_MOTIFS: tuple[tuple[str, str], ...] = (
    (r"timed?[ _-]?out|timeout|deadline", TRANSPORT_TIMEOUT),
    (r"rate.?limit|429|too many requests", RATE_LIMIT),
    (r"\b401\b|unauthor|invalid api key|authentication", AUTH),
    (r"quota|credit|billing|ECARTEE par la rotation|\b403\b", QUOTA),
    (r"\b50[023]\b|server busy|unavailable|indisponible|connection refused|"
     r"could not connect", PROVIDER_UNAVAILABLE),
    (r"context length|too long|maximum context|token limit", MODEL_CONTEXT),
    (r"REFUS DU GARDE|security|secret|interdit|forbidden", SECURITY_REJECTION),
    (r"patch failed|does not apply|git apply", PATCH_INVALID),
    (r"SEARCH/REPLACE|format|json decode|parse", FORMAT_INVALID),
    (r"^\s*$|empty|aucune sortie", GENERATION_EMPTY),
    (r"assertionerror|failed|test.*fail", TEST_FAILURE),
    (r"modulenotfound|importerror|no module named", DEPENDENCY_FAILURE),
)


def classer_erreur(message: str | None) -> str:
    """Range un echec dans une classe. `None`/vide -> GENERATION_EMPTY.

    L'ordre des motifs compte : la sûrete d'abord, pour qu'un refus de garde
    ne soit jamais relu comme un simple probleme de format.
    """
    if message is None or not str(message).strip():
        return GENERATION_EMPTY
    texte = str(message)
    for motif, classe in _MOTIFS:
        if re.search(motif, texte, re.I):
            return classe
    return INCONNU


def strategie_reprise(classe: str) -> dict:
    """Que faire d'un echec de cette classe -> {autre_provider, meme_provider,
    escalade, motif}.

    C'est la matrice qui manquait : aujourd'hui un timeout et un test rouge
    declenchent le meme comportement, alors qu'ils demandent l'inverse.
    """
    if classe == SECURITY_REJECTION:
        return {"autre_provider": False, "meme_provider": False,
                "escalade": True,
                "motif": "un refus de sûrete ne se retente pas : reessayer "
                         "jusqu'a passer, c'est contourner le garde"}
    if classe in (AUTH, QUOTA):
        return {"autre_provider": True, "meme_provider": False,
                "escalade": False,
                "motif": "la cle est en cause, pas la tache : changer de source"}
    if classe in (TRANSPORT_TIMEOUT, RATE_LIMIT, PROVIDER_UNAVAILABLE):
        return {"autre_provider": True, "meme_provider": True,
                "escalade": False,
                "motif": "transport : le meme provider peut repartir apres recul"}
    if classe == MODEL_CONTEXT:
        return {"autre_provider": True, "meme_provider": False,
                "escalade": False,
                "motif": "fenetre trop courte : il faut un autre modele"}
    if classe in GENERATION:
        return {"autre_provider": True, "meme_provider": True,
                "escalade": True,
                "motif": "la forme est inutilisable : autre modele, ou agent"}
    if classe == DEPENDENCY_FAILURE:
        return {"autre_provider": False, "meme_provider": False,
                "escalade": True,
                "motif": "l'environnement manque : reessayer ne le fera pas apparaitre"}
    if classe in (TEST_FAILURE, SEMANTIC_FAILURE):
        return {"autre_provider": True, "meme_provider": True,
                "escalade": True,
                "motif": "echec de TACHE : porteur d'information, a reinjecter "
                         "comme contexte plutot qu'a jeter"}
    return {"autre_provider": True, "meme_provider": True, "escalade": True,
            "motif": "classe inconnue : ne rien affirmer, tout garder ouvert"}


# --------------------------------------------------------------------------
# 2. L'independance : trois passerelles vers un modele ne font pas trois voix
# --------------------------------------------------------------------------

# Familles cognitives. Deux sources de la MEME famille partagent leurs biais :
# les compter separement fabrique un faux consensus.
_FAMILLES: tuple[tuple[str, str], ...] = (
    (r"claude|anthropic|sonnet|opus|haiku", "anthropic"),
    (r"gpt|openai|codex|o[134]\b", "openai"),
    (r"gemini|google|antigravity", "google"),
    (r"mistral|codestral|magistral", "mistral"),
    (r"qwen|qwq", "qwen"),
    (r"llama", "meta"),
    (r"deepseek", "deepseek"),
    (r"glm|zhipu|z\.ai", "zhipu"),
    (r"kimi|moonshot", "moonshot"),
    (r"grok|xai", "xai"),
    (r"command|cohere", "cohere"),
)


def famille_modele(modele: str | None) -> str:
    """Famille cognitive d'un modele. Inconnu -> son propre nom, jamais fondu
    dans un groupe fourre-tout : deux inconnus ne sont pas forcement parents."""
    nom = (modele or "").strip().lower()
    if not nom:
        return "inconnu"
    for motif, famille in _FAMILLES:
        if re.search(motif, nom):
            return famille
    return nom


def groupe_independance(modele: str | None, strategie: str = "") -> str:
    """Identite d'une VOIX.

    `openrouter`, `together` et un endpoint direct peuvent servir le MEME
    modele : ce sont trois routes, une seule voix. En revanche le meme modele
    interroge sous un ANGLE different (corriger au minimum / chercher la cause
    racine / verifier le contrat) apporte une information neuve -- la strategie
    fait donc partie de l'identite.
    """
    return "%s::%s" % (famille_modele(modele), (strategie or "defaut").strip().lower())


# --------------------------------------------------------------------------
# 3. Observations, preuves, arbitrage
# --------------------------------------------------------------------------

@dataclass
class Tentative:
    """Ce qu'un exécutant a produit -- une OBSERVATION, pas un verdict."""

    worker: str = ""
    provider: str = ""
    modele: str = ""
    runtime: str = "cloud"          # local | cloud | agent
    strategie: str = ""             # l'angle demande, pas le modele
    sortie: str | None = None
    solution_id: str = ""           # deux tentatives d'accord partagent cet id

    transport_ok: bool = True
    format_ok: bool | None = None
    test_ok: bool | None = None     # None = NON MESURE, jamais « pas grave »
    invariants_ok: bool | None = None

    erreur: str | None = None
    preuves: list[str] = field(default_factory=list)
    latence_ms: float = 0.0
    # Le COUT de cette observation. `latence_ms` existait depuis l'origine et n'a
    # jamais ete rempli ; `tokens` manquait. Sans les deux, la question « ce que le
    # collectif apporte vaut-il ce qu'il coute » n'a pas de denominateur, et un
    # fanout de 5 se lit comme un fanout de 1 (mesure 2026-08-26). La source les
    # produit deja : `forge_llm_router.router_call` rend `elapsed_ms` et `tokens` --
    # c'est l'appelant qui les jetait.
    tokens: int = 0

    @property
    def classe_erreur(self) -> str | None:
        if self.erreur is None and self.transport_ok and self.format_ok is not False:
            return None
        return classer_erreur(self.erreur)

    @property
    def voix(self) -> str:
        return groupe_independance(self.modele, self.strategie)

    @property
    def utilisable(self) -> bool:
        """Une tentative n'entre dans l'arbitrage que si elle a PRODUIT."""
        return bool(self.solution_id) and self.transport_ok and self.format_ok is not False


# Etats d'une solution. Six, parce que « reussi / echoue » ecrase justement les
# cas ou le systeme doit continuer a chercher.
PROPOSED = "PROPOSED"
SUPPORTED = "SUPPORTED"
CONTESTED = "CONTESTED"
REJECTED = "REJECTED"
UNKNOWN = "UNKNOWN"


@dataclass
class Verdict:
    etat: str = UNKNOWN
    solution: str | None = None
    motif: str = ""
    voix_independantes: int = 0
    preuves_deterministes: int = 0
    action: str = "abstain"          # accept | challenge | retry | abstain


def arbitrer(tentatives: list[Tentative], min_voix: int = 2,
             exiger_preuve: bool = True) -> Verdict:
    """Tranche SANS voter.

    Regles, dans l'ordre :
      1. Un refus de sûrete domine tout : aucune quantite d'accord ne l'annule.
      2. Seules les tentatives qui ont PRODUIT comptent -- un timeout ne vote ni
         pour ni contre.
      3. Le soutien se mesure en VOIX INDEPENDANTES (famille x strategie), pas
         en nombre de reponses.
      4. Une solution dont les tests sont VERTS bat une solution plus populaire
         dont les tests ne sont pas mesures : la preuve prime sur le nombre.
      5. Deux solutions differentes toutes deux prouvees -> CONTESTED, et on
         demande un contradicteur. Ce n'est pas un echec, c'est un desaccord.
      6. Sans preuve deterministe, on s'ABSTIENT. Conclure sans preuve serait le
         seul vrai echec du systeme.
    """
    if any(t.classe_erreur == SECURITY_REJECTION for t in tentatives):
        return Verdict(etat=REJECTED, motif="refus de sûrete : aucun accord ne "
                                            "le renverse", action="abstain")

    produites = [t for t in tentatives if t.utilisable]
    if not produites:
        classes = sorted({t.classe_erreur or INCONNU for t in tentatives})
        return Verdict(etat=UNKNOWN, action="retry",
                       motif="aucune tentative n'a produit (%s) -- ces echecs "
                             "ne disent rien de la tache" % ", ".join(classes))

    # Regroupement par solution, avec voix DEDUPLIQUEES par independance.
    par_solution: dict[str, dict] = {}
    for t in produites:
        fiche = par_solution.setdefault(t.solution_id, {"voix": set(), "preuves": set(),
                                                        "tests": set()})
        fiche["voix"].add(t.voix)
        fiche["preuves"].update(t.preuves)
        if t.test_ok is not None:
            fiche["tests"].add(t.test_ok)

    def _prouvee(f: dict) -> bool:
        return f["tests"] == {True} and (bool(f["preuves"]) or not exiger_preuve)

    prouvees = [s for s, f in par_solution.items() if _prouvee(par_solution[s])]

    if len(prouvees) > 1:
        return Verdict(etat=CONTESTED, action="challenge",
                       voix_independantes=max(len(par_solution[s]["voix"]) for s in prouvees),
                       preuves_deterministes=max(len(par_solution[s]["preuves"]) for s in prouvees),
                       motif="%d solutions differentes sont prouvees : un "
                             "contradicteur doit trancher, pas la majorite"
                             % len(prouvees))

    if len(prouvees) == 1:
        s = prouvees[0]
        f = par_solution[s]
        etat = SUPPORTED if len(f["voix"]) >= min_voix else PROPOSED
        action = "accept" if etat == SUPPORTED else "challenge"
        return Verdict(etat=etat, solution=s, action=action,
                       voix_independantes=len(f["voix"]),
                       preuves_deterministes=len(f["preuves"]),
                       motif="" if etat == SUPPORTED else
                             "prouvee mais portee par %d voix independante(s) : "
                             "sous le seuil de %d" % (len(f["voix"]), min_voix))

    # Aucune solution prouvee : des solutions existent, rien ne les etaye.
    rouges = [s for s, f in par_solution.items() if f["tests"] == {False}]
    if rouges and len(rouges) == len(par_solution):
        return Verdict(etat=REJECTED, action="retry",
                       motif="toutes les solutions echouent aux tests")
    return Verdict(etat=UNKNOWN, action="abstain",
                   motif="aucune preuve deterministe : s'abstenir est ici une "
                         "REUSSITE, pas un renoncement")


# --------------------------------------------------------------------------
# 4. Preuve != parole : un OK_DONE ne s'accepte qu'apres verification de l'artefact
# --------------------------------------------------------------------------
# Manque paye 3x le 27/09 : un OK_DONE (GEMINI sur gh_run:36257981298, run CANCELLED) pris pour un succes.
# REQUESTED != ACHIEVED, SIGNAL != PREUVE DE VIE. Le corps resout le pointer_ref M2M vers un artefact et
# n'accepte que s'il est PRESENT ET VERIFIE. Les resolveurs sont INJECTES (par schema) : sans resolveur, on
# ne peut pas verifier -> on s'ABSTIENT (fail-safe), jamais on ne fabrique une preuve.

def _fichier_present(reste: str) -> dict:
    """Resolveur par defaut du schema `fichier:` : present ET non vide."""
    import os
    try:
        return {"present": os.path.isfile(reste) and os.path.getsize(reste) > 0,
                "verifie": os.path.isfile(reste) and os.path.getsize(reste) > 0}
    except OSError:
        return {"present": False, "verifie": None}


_RESOLVEURS_DEFAUT = {"fichier": _fichier_present}
# commit / gh_run / bb : fournis par le consommateur au moment du cablage (chacun avec son NR).


def resoudre_pointer_ref(pointer_ref, resolveurs=None) -> dict:
    """Resout un pointer_ref M2M (`schema:reste`) vers {present, verifie, detail}.

    Ne FABRIQUE jamais : un schema sans resolveur, un pointer_ref absent ou un resolveur qui leve rendent
    present=False / verifie=None (UNKNOWN, non verifiable). Un resolveur rend un bool (present==verifie) ou
    un dict {present, verifie, detail}. Fonction pure vis-a-vis des resolveurs injectes.
    """
    if not pointer_ref or not isinstance(pointer_ref, str):
        return {"present": False, "verifie": None, "detail": "pointer_ref absent"}
    schema, _, reste = pointer_ref.partition(":")
    r = (resolveurs if resolveurs is not None else _RESOLVEURS_DEFAUT).get(schema)
    if r is None:
        return {"present": False, "verifie": None,
                "detail": "aucun resolveur pour '%s' -- non verifiable, on s'abstient" % schema}
    try:
        res = r(reste)
    except Exception as e:  # muet-ok : un resolveur qui leve = non verifiable, jamais une preuve
        return {"present": False, "verifie": None, "detail": "resolveur a leve: %s" % type(e).__name__}
    if isinstance(res, bool):
        return {"present": res, "verifie": res, "detail": ""}
    return {"present": bool(res.get("present")), "verifie": res.get("verifie"),
            "detail": str(res.get("detail", ""))}


def verdict_livrable(message: dict, resolveurs=None, min_voix: int = 1) -> Verdict:
    """Verdict sur un livrable M2M (task_result / OK_DONE / postal) : preuve != parole.

    Resout `message['pointer_ref']`, en fait UNE tentative, et laisse `arbitrer` trancher (exiger_preuve).
    Accepte SEULEMENT si l'artefact est present ET verifie ; un run resolu mais non reussi est REJETE ; un
    pointer_ref absent ou non resoluble fait s'ABSTENIR (UNKNOWN), jamais accepter sur la seule parole.
    """
    pref = message.get("pointer_ref")
    r = resoudre_pointer_ref(pref, resolveurs)
    prouve = bool(r["present"]) and r["verifie"] is True
    test_ok = True if prouve else (False if (r["present"] and r["verifie"] is False) else None)
    t = Tentative(
        worker=str(message.get("source") or "?"),
        solution_id=(pref or "(sans pointer_ref)"),
        transport_ok=True,
        format_ok=True,
        test_ok=test_ok,
        preuves=[pref] if prouve else [],
        sortie=str(message.get("intent") or ""),
    )
    return arbitrer([t], min_voix=min_voix, exiger_preuve=True)
