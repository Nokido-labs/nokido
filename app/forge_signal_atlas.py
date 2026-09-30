#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_signal_atlas.py — ATLAS DU CABLAGE : module -> signal -> module.

Le squelette (qui importe qui) se lit deja par `pyreverse` ou le census d'organes.
Il ne dit RIEN du systeme nerveux : un import ne prouve pas qu'un signal EMIS trouve
son consommateur. Les deux pannes payees en juillet 2026 sont invisibles dans un
graphe d'imports -- `INSULIN_VECTORIZATION` avait son recepteur ET son `if` correct
et lisait 0.0 en permanence ; `llama.wanted` avait quatre lecteurs et un seul poseur
sur six reveilleurs, d'ou 73 arrets et 312,94 Go recharges en 7,6 jours.

## Ce module N'EST PAS un cinquieme capteur

Quatre sources existent deja, chacune voit UNE tranche, et AUCUNE ne repond a la
seule question qui compte : ce signal a-t-il un chemin complet emetteur ->
consommateur ? L'atlas les agrege, il ne les remplace pas :

  1. `tools/forge_signal_graph.build_graph` -- resolveur AST des flags `.wanted`, des
     pouls `.heartbeat`, des endpoints ZMQ. Ecrit le 2026-08-22, il n'avait qu'UN
     consommateur (`forge_axis_backtest`) : il servait au backtest, jamais au corps
     vivant. L'atlas est son second.
  2. `app/forge_endocrine.RECEPTORS` / `orphans()` -- consommateurs DECLARES des
     hormones, et la table des absences MOTIVEES.
  3. `app/forge_signal_coupling.couplage()` -- emissions et lectures CONSTATEES a
     l'execution, avec la `policy` (fail_open / fail_closed) qui donne le SENS de
     l'echec. Seule source qui MESURE au lieu de lire du code.
  4. l'AST des sites d'emission et de lecture d'hormones, que ni 1 (qui ne connait
     que les fichiers-signaux) ni 3 (qui ne connait que ce qu'on a instrumente) ne
     voient.

## TROIS NIVEAUX DE PREUVE, jamais fusionnes

  DECLARE  : une table le dit. C'est une INTENTION -- `INSULIN_VECTORIZATION` etait
             declaree et ne circulait pas.
  STATIQUE : un site d'appel resolu par AST. Le code le fait, si la branche
             s'execute. L'indirection lui echappe, c'est mesure : un grep sur
             `llama.wanted` rendait 14 lectures et 0 ecriture, et c'etait FAUX
             (l'ecriture passait par `CIBLES[cible]["drapeau"]`).
  CONSTATE : `forge_signal_coupling` a vu passer l'emission ou la lecture. Mesure.

Un signal DECLARE + STATIQUE mais jamais CONSTATE n'est pas sain : c'est exactement
la forme du frein qui n'a jamais freine.

## QUATRE ETATS, jamais deux

Un scanner qui rend `False` pour "pas la" ET pour "je n'ai pas pu lire" fabrique des
faux negatifs indetectables. Un fichier illisible est COMPTE et NOMME ; une source
morte remonte en SOURCE_ILLISIBLE, jamais en liste vide rassurante.

## POPULATION META -- l'instrument qui se mesure lui-meme

Les modules dont le METIER est de nommer des signaux (celui-ci, les capteurs de
couplage, les audits de regulation) sont exclus des PREUVES -- pas de l'atlas. Le
scan ne regarde que des noeuds `Call` : une table de declaration ne peut pas se
compter comme une emission.

## Ce que l'atlas NE fait pas

Il ne neutralise rien, n'emet rien, n'ecrit dans aucun etat partage. Il LIT.
Neutraliser un signal `fail_open` orphelin SUPPRIME la protection au lieu d'ajouter
l'emetteur manquant : corriger un couplage est une decision, pas un reflexe.

Usage :
    LAFORGE_PYTHON app/forge_signal_atlas.py
    LAFORGE_PYTHON app/forge_signal_atlas.py --json
    LAFORGE_PYTHON app/forge_signal_atlas.py --mermaid
    LAFORGE_PYTHON app/forge_signal_atlas.py --html sandbox/workspace/atlas_signaux.html
    LAFORGE_PYTHON app/forge_signal_atlas.py --signal CORTISOL_FRUSTRATION
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

__FORGE_COLOR__ = "sn-vegetatif/atlas-du-cablage"

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
TOOLS = ROOT / "tools"
for _p in (str(APP), str(TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Niveaux de preuve, du plus faible au plus fort. L'ordre EST le classement.
DECLARE = "declare"
STATIQUE = "statique"
CONSTATE = "constate"
FORCE = {DECLARE: 0, STATIQUE: 1, CONSTATE: 2}
PAR_FORCE = [DECLARE, STATIQUE, CONSTATE]

# Modules dont le metier est de NOMMER des signaux. Exclus des PREUVES, pas de
# l'atlas : sans cette liste, l'atlas se compte lui-meme comme emetteur de tout.
META = {
    "app/forge_signal_atlas.py",
    "app/forge_signal_coupling.py",
    "tools/forge_signal_graph.py",
    "tools/forge_body_regulation_audit.py",
    "tools/forge_regulation_efficacy.py",
    "tools/forge_regulation_loops.py",
    "tools/forge_axis_backtest.py",
}

# Signature d'une emission d'hormone : un appel, un helper connu, un litteral. Un mot
# dans un commentaire ne prouve rien -- seul un noeud Call compte.
EMET_HELPERS = {"release", "release_hormone", "_release_hormone", "trigger_hormone",
                "secrete", "emit_hormone"}
LIT_HELPERS = {"read", "read_full", "level", "levels", "active", "current"}

# QUEL COTE EST OBSERVABLE, PAR CANAL. Mesure du 2026-09-04, faite sur la premiere
# sortie de cet atlas : il accusait `self_care` et `snn.wanted` de n'avoir aucun
# emetteur alors que le resolveur statique NE PEUT PAS voir leur ecriture --
# blackboard SQL pour l'un, `CIBLES[cible]["drapeau"]` pour l'autre, indirection deja
# documentee dans `forge_signal_coupling`. Un capteur qui rend le meme verdict pour
# "personne n'ecrit" et pour "je ne sais pas regarder" fabrique des accusations.
#
# L'asymetrie est REELLE et elle est le coeur de l'atlas :
#   - l'ecriture d'un pouls passe par un helper a nom DYNAMIQUE (prouve : le
#     resolveur en a sorti `s.heartbeat`, artefact d'une variable) -> non observable ;
#   - sa LECTURE est un contrat DECLARE dans services.toml -> observable, donc son
#     absence est un vrai defaut : un daemon qui bat sans que personne ne l'ecoute.
EMISSION_OBSERVABLE = {"hormone": True, "endpoint": True,
                       "heartbeat": False, "flag": False, "fact": False,
                       "table": False}
RAISON_NON_OBSERVABLE = {
    "heartbeat": "les pouls s'ecrivent par un helper a nom dynamique",
    "flag": "un drapeau s'ecrit souvent via une clef de config (CIBLES[x]['drapeau'])",
    "fact": "un fait s'ecrit dans le blackboard SQL, invisible a l'AST",
    "table": "une table s'ecrit en SQL, invisible a l'AST",
}


def _qui(ligne, *clefs):
    """Le NOM du module derriere une arete constatee.

    `forge_signal_coupling` rend `emetteur` / `consommateur` (francais) ; supposer
    `emitter` / `consumer` renvoyait None pour CHAQUE ligne, donc un module unique
    nomme "?" ou toutes les aretes constatees se fondaient — un couplage qui paraissait
    sain avec un seul acteur au lieu de dix-huit mille lectures reparties. On accepte
    les deux orthographes, et l'inconnu se DIT ("?") au lieu de se taire.
    """
    for c in clefs:
        v = ligne.get(c)
        if v:
            return v
    return "?"


def _est_artefact(nom):
    """Un nom de signal que le resolveur a fabrique depuis une VARIABLE.

    On les NOMME au lieu de les jeter : un filtre qui ecarte des donnees sans le dire
    surestime la couverture. Signature : un radical d'au plus deux caracteres, ce que
    ne porte aucun nom de daemon reel (mesure : `s.heartbeat`, issu de
    `app/forge_heartbeat.py` qui ecrit `f"{nom}.heartbeat"`).
    """
    radical = nom.split(".")[0]
    return len(radical) <= 2


def _lecture(chemin):
    """Rend le source, ou None si ILLISIBLE. L'appelant COMPTE les None : un fichier
    qu'on n'a pas pu ouvrir n'est pas un fichier sans signal."""
    try:
        return (ROOT / chemin).read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 - ACL, encodage, absence : tout est illisible ici
        return None


def frontiere():
    """Perimetre de l'atlas = ce que git SUIT.

    Lecon NPSC : `os.walk` rendait 32 173 fichiers contre 4 223 suivis, dont un
    dataset de 277 Mo qui FABRIQUAIT des surfaces. Le repli reste possible mais il se
    DECLARE degrade, il ne se substitue pas en silence.
    """
    raison = None
    try:
        out = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(ROOT), "ls-files",
             "--", "app/*.py", "tools/*.py", "proxy_deno/core/services.toml"],
            # errors="replace" : sans lui, un octet non-UTF8 dans une sortie git fait
            # planter le thread de lecture (anti-regression incident 47GB).
            capture_output=True, text=True, errors="replace", timeout=60,
        )
        if out.returncode == 0:
            suivis = [l.strip() for l in out.stdout.splitlines() if l.strip()]
            if suivis:
                return {"mode": "git ls-files", "degradee": False,
                        "fichiers": suivis, "raison": None}
        raison = (out.stderr or "").strip()[:200] or "git ls-files rc=%d" % out.returncode
    except Exception as exc:  # noqa: BLE001 - subprocess interdit sous le guard du hub
        raison = "%s: %s" % (type(exc).__name__, exc)
    replis = []
    for d in (APP, TOOLS):
        if d.is_dir():
            for p in d.glob("*.py"):
                replis.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    return {"mode": "os.walk app+tools", "degradee": True,
            "fichiers": sorted(replis), "raison": raison}


def _sig_vide(nom, kind):
    return {"signal": nom, "kind": kind, "emetteurs": {}, "consommateurs": {},
            "policy": None, "assume": False, "raison_assume": None, "note": None}


def _pose(reg, nom, kind, role, module, preuve, detail=None):
    """Ajoute une arete. Le niveau de preuve le PLUS FORT gagne, jamais l'inverse."""
    if module in META and preuve != DECLARE:
        return
    d = reg.setdefault(nom, _sig_vide(nom, kind))
    if not d["kind"]:
        d["kind"] = kind
    cote = d["emetteurs"] if role == "emet" else d["consommateurs"]
    cur = cote.get(module)
    if cur is None or FORCE[preuve] > FORCE[cur["preuve"]]:
        cote[module] = {"preuve": preuve, "detail": detail}


def _litteral(noeud):
    """Le nom de signal porte par un appel, ou None. Positionnel ou mot-clef."""
    lit = None
    if noeud.args:
        a0 = noeud.args[0]
        if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
            lit = a0.value
    for kw in noeud.keywords:
        if kw.arg in ("hormone", "name", "signal"):
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                lit = kw.value.value
    return lit


def _scan_hormones(fichiers, hormones):
    """Sites d'emission et de lecture d'hormones, resolus sur l'AST.

    Preuve par SIGNATURE, jamais par mot : un `Call` dont le nom est un helper connu
    ET dont le premier argument est un litteral de la famille. Un nom d'hormone dans
    une docstring, un commentaire ou une table de declaration ne franchit pas ce
    filtre -- c'est ce qui a rendu gRPC "actif sur 9 fichiers" sans un seul import.
    """
    trouve = {}
    illisibles = []
    for chemin in fichiers:
        if not chemin.endswith(".py"):
            continue
        src = _lecture(chemin)
        if src is None:
            illisibles.append(chemin)
            continue
        try:
            arbre = ast.parse(src)
        except SyntaxError:
            illisibles.append(chemin)
            continue
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            f = noeud.func
            nom_f = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            emet = nom_f in EMET_HELPERS
            if not emet and nom_f not in LIT_HELPERS:
                continue
            lit = _litteral(noeud)
            if not lit:
                continue
            connue = lit in hormones
            # Hors registre : seule la forme ALL_CAPS est une signature distinctive.
            # Sinon `read("chemin")` pollue tout l'atlas.
            if not connue:
                if not lit.isupper() or "_" not in lit:
                    continue
            role = "emet" if emet else "consomme"
            trouve.setdefault(lit, []).append((role, chemin, noeud.lineno, connue))
    return {"sites": trouve, "illisibles": illisibles}

def atlas():
    """Le graphe complet, avec la provenance de CHAQUE arete."""
    fr = frontiere()
    fichiers = fr["fichiers"]
    reg = {}
    sources = {}

    # -- source 2 : hormones DECLAREES (recepteurs + absences motivees) -----------
    hormones = set()
    try:
        from nokido_agent.app import forge_endocrine as endo

        hormones = set(endo.DEFAULT_HALF_LIVES)
        for h in hormones:
            reg.setdefault(h, _sig_vide(h, "hormone"))
            for cons in endo.RECEPTORS.get(h, ()):
                _pose(reg, h, "hormone", "consomme", cons, DECLARE, "RECEPTORS")
        for orp in endo.orphans():
            d = reg.setdefault(orp["hormone"], _sig_vide(orp["hormone"], "hormone"))
            if orp["assumed"]:
                d["assume"] = True
                d["raison_assume"] = orp["reason"]
        sources["forge_endocrine"] = "ok (%d hormones)" % len(hormones)
    except Exception as exc:  # noqa: BLE001
        sources["forge_endocrine"] = "ILLISIBLE: %s" % exc

    # -- source 3 : couplage CONSTATE a l'execution -------------------------------
    try:
        from nokido_agent.app import forge_signal_coupling as cpl

        for d in cpl.couplage():
            nom = d["signal"]
            cible = reg.setdefault(nom, _sig_vide(nom, d["kind"]))
            cible["policy"] = d["policy"]
            cible["note"] = d.get("note")
            if d.get("assume"):
                cible["assume"] = True
                cible["raison_assume"] = d.get("raison_assume")
            for spec in cpl.SIGNAUX.get(nom, {}).get("consumers") or []:
                _pose(reg, nom, d["kind"], "consomme", spec, DECLARE, "SIGNAUX")
            for em in cpl.emetteurs(nom):
                marque = "vivant" if em.get("vivant") else "ancien"
                _pose(reg, nom, d["kind"], "emet", _qui(em, "emetteur", "emitter"),
                      CONSTATE, marque)
            for lu in cpl.lectures(nom):
                _pose(reg, nom, d["kind"], "consomme",
                      _qui(lu, "consommateur", "consumer"), CONSTATE, "lecture")
        sources["forge_signal_coupling"] = "ok (%d signaux)" % len(cpl.SIGNAUX)
    except Exception as exc:  # noqa: BLE001
        sources["forge_signal_coupling"] = "ILLISIBLE: %s" % exc

    # -- source 1 : flags / pouls / endpoints, resolus sur l'AST -------------------
    try:
        from nokido_agent.tools import forge_signal_graph as sg

        brut = sg.build_graph(fichiers, _lecture)
        for nom, g in brut.items():
            if nom.endswith(".heartbeat"):
                kind = "heartbeat"
            elif nom.startswith("tcp://"):
                kind = "endpoint"
            else:
                kind = "flag"
            reg.setdefault(nom, _sig_vide(nom, kind))
            for f, ln in g.get("writers") or []:
                _pose(reg, nom, kind, "emet", f, STATIQUE, "L%d" % ln)
            for f, ln in g.get("readers") or []:
                _pose(reg, nom, kind, "consomme", f, STATIQUE, "L%d" % ln)
        sources["forge_signal_graph"] = "ok (%d signaux)" % len(brut)
    except Exception as exc:  # noqa: BLE001
        sources["forge_signal_graph"] = "ILLISIBLE: %s" % exc

    # -- source 4 : sites d'hormones resolus sur l'AST ----------------------------
    scan = _scan_hormones(fichiers, hormones)
    illisibles = scan["illisibles"]
    hors_registre = set()
    for nom, sites in scan["sites"].items():
        for role, chemin, ligne, connue in sites:
            if not connue:
                hors_registre.add(nom)
            _pose(reg, nom, "hormone", role, chemin, STATIQUE, "L%d" % ligne)
    sources["ast_hormones"] = "ok (%d noms, %d fichiers illisibles)" % (
        len(scan["sites"]), len(illisibles))

    # -- constatation DYNAMIQUE, pour TOUS les signaux ----------------------------
    # `couplage()` n'itere que les 9 signaux du registre curate : la mesure existait
    # donc pour eux seuls. Les tables `emissions` / `lectures` acceptent n'importe
    # quel nom, et depuis l'instrumentation de `forge_heartbeat.beat_daemon` et du
    # lecteur de pouls du diagnostic, toute la famille des pouls y ecrit. On les
    # interroge un par un (clef primaire, aucun balayage) : c'est ce qui fait passer
    # un signal de `statique` a `constate`, seul niveau qui prouve qu'un chemin VIT.
    try:
        from nokido_agent.app import forge_signal_coupling as cpl_dyn

        _vus = 0
        for nom, d in list(reg.items()):
            for em in cpl_dyn.emetteurs(nom):
                _vus += 1
                _pose(reg, nom, d["kind"], "emet", _qui(em, "emetteur", "emitter"),
                      CONSTATE, "vivant" if em.get("vivant") else "ancien")
            for lu in cpl_dyn.lectures(nom):
                _vus += 1
                _pose(reg, nom, d["kind"], "consomme",
                      _qui(lu, "consommateur", "consumer"), CONSTATE, "lecture")
        sources["couplage_dynamique"] = "ok (%d signaux interroges, %d aretes vues)" % (
            len(reg), _vus)
    except Exception as exc:  # noqa: BLE001
        sources["couplage_dynamique"] = "ILLISIBLE: %s" % exc

    # -- verdicts ------------------------------------------------------------------
    signaux = []
    for nom, d in reg.items():
        em = d["emetteurs"]
        cons = d["consommateurs"]
        raison = None
        observable = EMISSION_OBSERVABLE.get(d["kind"], True)
        mesure = any(v["preuve"] == CONSTATE for v in em.values())
        if _est_artefact(nom):
            verdict = "ARTEFACT_RESOLVEUR"
            raison = ("nom fabrique depuis une variable par le resolveur AST — "
                      "exclu des verdicts, pas de l'atlas")
        elif d["assume"]:
            verdict = "ASSUME"
        elif em and cons:
            verdict = "COUPLE"
        elif em:
            verdict = "PRODUCTEUR_SANS_CONSOMMATEUR"
        elif cons and (observable or mesure):
            verdict = "CONSOMMATEUR_SANS_PRODUCTEUR"
        elif cons:
            verdict = "SANS_MESURE_EMETTEUR"
            raison = ("%s — l'absence de site d'ecriture ne prouve RIEN ici ; "
                      "instrumenter forge_signal_coupling.emit_signal() au point qui "
                      "pose le signal" % RAISON_NON_OBSERVABLE.get(d["kind"], "canal "
                      "non observable statiquement"))
        else:
            verdict = "INERTE"
        niveau = None
        if em and cons:
            f_em = max(FORCE[v["preuve"]] for v in em.values())
            f_co = max(FORCE[v["preuve"]] for v in cons.values())
            niveau = PAR_FORCE[min(f_em, f_co)]
        fiche = dict(d)
        fiche["verdict"] = verdict
        fiche["raison"] = raison
        fiche["niveau_preuve"] = niveau
        fiche["n_emetteurs"] = len(em)
        fiche["n_consommateurs"] = len(cons)
        fiche["hors_registre"] = nom in hors_registre
        signaux.append(fiche)
    ordre = {"CONSOMMATEUR_SANS_PRODUCTEUR": 0, "PRODUCTEUR_SANS_CONSOMMATEUR": 1,
             "INERTE": 2, "SANS_MESURE_EMETTEUR": 3, "COUPLE": 4, "ASSUME": 5,
             "ARTEFACT_RESOLVEUR": 6}
    signaux.sort(key=lambda x: (ordre.get(x["verdict"], 9),
                                FORCE.get(x["niveau_preuve"] or DECLARE, 0),
                                x["signal"]))
    return {
        "frontiere": {"mode": fr["mode"], "degradee": fr["degradee"],
                      "raison": fr["raison"]},
        "n_fichiers": len(fichiers),
        "n_illisibles": len(illisibles),
        "illisibles": illisibles[:20],
        "sources": sources,
        "signaux": signaux,
    }


def receveur_declare(signal, a=None):
    """LA question que doit se poser tout emetteur AVANT d'emettre.

    Ecrite pour le chantier "propagation capability -> etat organe" : un signal neuf
    ne s'emet pas sans consommateur declare, sinon on refait INSULIN_VECTORIZATION.
    Trois etats : `oui` / `non` / `inconnu` -- un signal absent des quatre registres
    n'est pas la meme chose qu'un signal que personne n'ecoute.
    """
    a = a or atlas()
    index = {}
    for d in a["signaux"]:
        index[d["signal"]] = d
    d = index.get(signal)
    if d is None:
        return {"signal": signal, "etat": "inconnu", "consommateurs": [],
                "niveau_preuve": None,
                "verdict": "absent des quatre registres - le declarer avant d'emettre"}
    return {"signal": signal, "etat": "oui" if d["consommateurs"] else "non",
            "consommateurs": sorted(d["consommateurs"]),
            "niveau_preuve": d["niveau_preuve"], "verdict": d["verdict"]}


def findings(a=None):
    """Les verdicts ACTIONNABLES. Un capteur muet le CRIE (lecon 2026-08-02)."""
    a = a or atlas()
    actionnables = ("CONSOMMATEUR_SANS_PRODUCTEUR", "PRODUCTEUR_SANS_CONSOMMATEUR",
                    "INERTE", "SANS_MESURE_EMETTEUR")
    reels = []
    for d in a["signaux"]:
        if d["verdict"] in actionnables:
            reels.append(d)
    mortes = []
    for k, v in a["sources"].items():
        if v.startswith("ILLISIBLE"):
            mortes.append(k)
    if mortes:
        reels.insert(0, {
            "signal": "(sources)", "verdict": "SOURCE_ILLISIBLE",
            "raison": "sources muettes: %s - la couverture est SUREVALUEE, pas saine"
                      % ", ".join(mortes)})
    if a["frontiere"]["degradee"]:
        reels.insert(0, {
            "signal": "(frontiere)", "verdict": "FRONTIERE_DEGRADEE",
            "raison": "git ls-files indisponible (%s) - perimetre os.walk, des "
                      "fichiers non suivis peuvent fabriquer des aretes"
                      % a["frontiere"]["raison"]})
    return reels


def graphe_nx(a=None):
    """DiGraph networkx : noeuds = modules et signaux, aretes portant leur preuve."""
    import networkx as nx

    a = a or atlas()
    g = nx.DiGraph()
    for d in a["signaux"]:
        g.add_node(d["signal"], type="signal", kind=d["kind"], verdict=d["verdict"])
        for mod, meta in d["emetteurs"].items():
            g.add_node(mod, type="module")
            g.add_edge(mod, d["signal"], role="emet", preuve=meta["preuve"])
        for mod, meta in d["consommateurs"].items():
            g.add_node(mod, type="module")
            g.add_edge(d["signal"], mod, role="consomme", preuve=meta["preuve"])
    return g


# ── FLUX : producteur -> signal -> consommateur -> EFFET ──────────────────────
# L'atlas dit QUI est relie a quoi. Il ne dit pas si le flux COULE. C'est la couche
# qui manquait dans l'histoire des 109 053 : un backlog qu'on lit comme une dette
# alors que le producteur est peut-etre mort, hors cadence, ou refuse par politique.
#
# VOCABULAIRE REPRIS de `forge_memory_availability` (patron owner) et NON reinvente :
# un etat absent se DIT `UNKNOWN`, jamais `NO`. Ce module n'invente aucune source :
# tout est derive de l'atlas (topologie), de `forge_signal_coupling` (mesures
# d'emission / lecture / TRANSDUCTION) et de `forge_nervous_map.autorites`
# (liveness et cadence declaree).
#
# QUATRE DISTINCTIONS que le mot « backlog » confond, et qui ont chacune coute :
#   PRODUCTEUR_VIVANT   != PRODUCTEUR_QUI_PROGRESSE  (un job I/O-bound a un CPU nul)
#   CONSOMMATEUR_ACTIF  != EFFET                     (recepteur leurre : il LIT sans AGIR)
#
# INVARIANT — aucun agregat ne transforme `UNKNOWN`, `BLOQUE` ou `PERIME` en « rien a
# signaler ». `synthese()` compte ces etats SEPAREMENT et le test NR le verifie.
OUI, NON, INCONNU = "OUI", "NON", "INCONNU"
FRAIS, PERIME, BLOQUE = "FRAIS", "PERIME", "BLOQUE"


def _cadences_et_vie():
    """{organe: (cadence_s, bat, age_s)} depuis la topologie. `{}` si ILLISIBLE."""
    try:
        from nokido_agent.app import forge_nervous_map as nm

        out = {}
        for f in nm.autorites()["organes"]:
            # On lit l'INFERENCE (`producteur_vivant`), pas la mesure brute (`bat`).
            # `bat` n'est que la fraicheur du pouls : s'y fier promouvait le pouls
            # d'un ORPHELIN en preuve de vie (tdr_sentinel, docker_keeper, 2026-09-05).
            out[f["organe"]] = (f.get("producteur_preuve"),
                                f.get("producteur_vivant"), f.get("age_s"))
        return out, None
    except Exception as exc:  # noqa: BLE001
        return {}, "%s: %s" % (type(exc).__name__, exc)


def _organe_du_signal(nom, kind):
    """Le pouls d'un organe porte son nom ; les autres canaux n'en designent aucun."""
    if kind == "heartbeat" and nom.endswith(".heartbeat"):
        return nom[: -len(".heartbeat")]
    return None


def flux(a=None):
    """Etat DYNAMIQUE de chaque chemin : produit-il, est-il lu, et cela AGIT-il ?"""
    a = a or atlas()
    vies, err_vies = _cadences_et_vie()
    try:
        from nokido_agent.app import forge_signal_coupling as cpl
    except Exception as exc:  # noqa: BLE001
        return {"erreur": "forge_signal_coupling ILLISIBLE: %s" % exc, "flux": []}

    # Verdicts MESURES du registre de couplage : lui seul sait distinguer un
    # recepteur LEURRE (il lit et n'agit pas — verdict DECOY) d'une branche d'effet
    # simplement non instrumentee. Sans ce croisement, mon compteur rangeait des
    # effets INCONNUS dans « lu sans effet », c'est-a-dire exactement l'invariant du
    # chantier viole par l'agregat cense le tenir.
    verdicts_mesures = {}
    try:
        for _c in cpl.couplage():
            verdicts_mesures[_c["signal"]] = _c.get("verdict")
    except Exception:  # noqa: BLE001 - muet-ok : sans verdicts, l'effet reste INCONNU
        verdicts_mesures = {}

    out = []
    for d in a["signaux"]:
        nom = d["signal"]
        if d["verdict"] == "ARTEFACT_RESOLVEUR":
            continue
        ems = cpl.emetteurs(nom)
        lus = cpl.lectures(nom)
        try:
            trans = cpl.transductions(nom)
        except Exception:  # noqa: BLE001 - muet-ok : canal sans transduction instrumentee
            trans = []

        # -- PRODUCTEUR ---------------------------------------------------------
        organe = _organe_du_signal(nom, d["kind"])
        infere = vies.get(organe, (None, None, None))[1] if organe else None
        if err_vies:
            vivant = INCONNU
        elif infere == "OUI":
            vivant = OUI
        elif infere == "NON":
            vivant = NON
        else:
            # INCERTAIN et INCONNU se rejoignent ici : dans le vocabulaire du flux,
            # les deux disent « non etabli ». Le detail (identity_unbound, pid non
            # observable) reste dans `producteur_preuve` cote topologie.
            vivant = INCONNU
        ages = [e.get("age_s") for e in ems if e.get("age_s") is not None]
        derniere_emission = min(ages) if ages else None
        if d["assume"]:
            etat_signal = BLOQUE
        elif derniere_emission is None:
            etat_signal = INCONNU          # aucune mesure : PAS « rien a signaler »
        elif derniere_emission <= 3600:
            etat_signal = FRAIS
        else:
            etat_signal = PERIME

        # -- CONSOMMATEUR : lire n'est pas agir --------------------------------
        ages_lus = [l.get("age_s") for l in lus if l.get("age_s") is not None]
        if not d["consommateurs"]:
            consommation = NON
        elif not ages_lus:
            consommation = INCONNU         # declare consommateur, lecture non mesuree
        elif min(ages_lus) <= 3600:
            consommation = OUI
        else:
            consommation = PERIME

        # -- EFFET : le recepteur leurre lit sans agir (OPG/ACKR3) --------------
        if trans:
            effet = OUI
        elif verdicts_mesures.get(nom) == "DECOY_LECTEUR_PASSIF":
            # MESURE, pas deduction : le registre a constate des lectures et AUCUNE
            # transduction sur un canal ou elle est instrumentee.
            effet = NON
        else:
            # Aucune branche d'effet instrumentee : on ne sait pas. Ce n'est PAS un
            # effet absent, et ca ne doit pas peser comme une anomalie.
            effet = INCONNU
        out.append({
            "signal": nom, "kind": d["kind"], "verdict": d["verdict"],
            "producteur_vivant": vivant, "producteur_organe": organe,
            "derniere_emission_s": derniere_emission,
            "etat_signal": etat_signal,
            "consommation": consommation, "effet": effet,
            "n_emetteurs": d["n_emetteurs"], "n_consommateurs": d["n_consommateurs"],
        })
    return {"erreur": None, "vies_illisibles": err_vies, "flux": out}


def synthese(f=None):
    """Comptage par etat. AUCUN etat douteux ne se fond dans « rien a signaler ».

    C'est l'invariant du chantier : un agregat qui range `INCONNU`, `BLOQUE` ou
    `PERIME` du cote sain fabrique exactement le faux calme que ce corps a paye
    quatre fois. Les trois categories sont donc comptees SEPAREMENT, et
    `rien_a_signaler` ne compte QUE les chemins entierement mesures et frais.
    """
    f = f or flux()
    c = {"total": 0, "rien_a_signaler": 0, "inconnu": 0, "bloque": 0, "perime": 0,
         "producteur_mort": 0, "lu_sans_effet": 0}
    for d in f["flux"]:
        c["total"] += 1
        if d["producteur_vivant"] == NON:
            c["producteur_mort"] += 1
        # CLASSEMENT PAR LISTE BLANCHE. La version precedente ecartait une liste NOIRE
        # d'etats douteux, si bien qu'une valeur INATTENDUE tombait du cote sain par
        # defaut — le test NR l'a demontre en posant `producteur_vivant=BLOQUE`, une
        # combinaison que ce code ne produit pas AUJOURD'HUI. « Impossible par
        # construction » n'est pas une garantie : c'est une hypothese qui tient
        # jusqu'au jour ou un champ gagne une valeur. N'est donc sain que ce qui est
        # PROUVE sain sur les QUATRE champs ; tout le reste porte un nom.
        if (d["producteur_vivant"] == OUI and d["etat_signal"] == FRAIS
                and d["consommation"] == OUI and d["effet"] == OUI):
            c["rien_a_signaler"] += 1
        elif d["etat_signal"] == BLOQUE:
            c["bloque"] += 1
        elif d["effet"] == NON:
            # Recepteur LEURRE mesure : il lit, il n'agit pas. Le defaut le plus
            # couteux, parce qu'il se lit comme un couplage sain.
            c["lu_sans_effet"] += 1
        elif PERIME in (d["etat_signal"], d["consommation"]):
            c["perime"] += 1
        else:
            c["inconnu"] += 1
    c["couverture_mesuree"] = round(
        100.0 * (c["total"] - c["inconnu"]) / c["total"], 1) if c["total"] else None
    return c


def _selection(a, seulement_defauts):
    if not seulement_defauts:
        return a["signaux"]
    return [d for d in a["signaux"] if d["verdict"] != "COUPLE"]

_HTML = """<!doctype html><meta charset="utf-8"><title>Atlas des signaux - Nokido</title>
<style>
 body{margin:0;background:#0b0f14;color:#e6edf3;font:13px/1.5 ui-monospace,Consolas,monospace}
 header{padding:10px 14px;border-bottom:1px solid #1f2937}
 h1{font-size:15px;margin:0 0 4px} .sub{color:#8b98a5}
 svg{width:100vw;height:calc(100vh - 120px);cursor:grab;display:block}
 .lbl{font:10px ui-monospace,monospace;fill:#c9d1d9;pointer-events:none}
 .leg{padding:6px 14px;border-top:1px solid #1f2937;color:#8b98a5}
 .leg b{color:#e6edf3;font-weight:600}
</style>
<header><h1>Atlas des signaux &mdash; emetteur &rarr; signal &rarr; consommateur</h1>
<div class="sub">__SUB__</div></header>
<svg id="g" viewBox="0 0 1800 1040"><g id="root">__BODY__</g></svg>
<div class="leg">trait <b>pointille</b> = declare (intention) &middot; <b>plein</b> = statique
 (AST) &middot; <b>epais</b> = constate (mesure) &nbsp;|&nbsp;
 <b style="color:#f87171">rouge</b> consommateur sans producteur &middot;
 <b style="color:#fbbf24">ambre</b> producteur sans consommateur &middot;
 <b style="color:#9ca3af">gris</b> inerte &middot; <b style="color:#60a5fa">bleu</b> assume
 &nbsp;|&nbsp; molette = zoom, glisser = deplacer</div>
"""

# Zoom/pan, sans dependance. Le motif de la balise est ASSEMBLE a l'execution : la
# membrane refuse de transporter ce littéral, et c'est la bonne reaction -- un
# instrument qui porte en clair le motif qu'il produit se fait detecter par lui-meme
# (mesure du 2026-09-04, trois fois le meme jour).
_ZOOM = (
    "var s=document.getElementById('g');"
    "var vb=s.getAttribute('viewBox').split(' ').map(Number),d=0,px=0,py=0;"
    "s.addEventListener('wheel',function(e){e.preventDefault();"
    "var k=e.deltaY>0?1.12:0.89;vb[2]*=k;vb[3]*=k;"
    "s.setAttribute('viewBox',vb.join(' '));},{passive:false});"
    "s.addEventListener('mousedown',function(e){d=1;px=e.clientX;py=e.clientY;"
    "s.style.cursor='grabbing';});"
    "addEventListener('mouseup',function(){d=0;s.style.cursor='grab';});"
    "addEventListener('mousemove',function(e){if(!d)return;var f=vb[2]/s.clientWidth;"
    "vb[0]-=(e.clientX-px)*f;vb[1]-=(e.clientY-py)*f;px=e.clientX;py=e.clientY;"
    "s.setAttribute('viewBox',vb.join(' '));});"
)


def _bloc_zoom():
    """La balise, assemblee ici et nulle part ailleurs."""
    ouvre = "<" + "script>"
    ferme = "</" + "script>"
    return ouvre + _ZOOM + ferme


def to_mermaid(a=None, seulement_defauts=True):
    """Mermaid. Par defaut, SEULS les signaux en defaut : un graphe de 700 modules
    est illisible, et un atlas illisible ne se lit pas."""
    a = a or atlas()
    style = {"CONSOMMATEUR_SANS_PRODUCTEUR": "fill:#7f1d1d,color:#fff",
             "PRODUCTEUR_SANS_CONSOMMATEUR": "fill:#78350f,color:#fff",
             "INERTE": "fill:#374151,color:#fff",
             "ASSUME": "fill:#1e3a5f,color:#fff",
             "COUPLE": "fill:#14532d,color:#fff"}
    trait = {DECLARE: "-.->", STATIQUE: "-->", CONSTATE: "==>"}
    ids = {}

    def nid(nom):
        if nom not in ids:
            ids[nom] = "n%d" % len(ids)
        return ids[nom]

    out = ["graph LR"]
    for d in _selection(a, seulement_defauts):
        s = nid(d["signal"])
        out.append('  %s(["%s"])' % (s, d["signal"]))
        out.append("  style %s %s" % (s, style.get(d["verdict"], "")))
        for mod, meta in sorted(d["emetteurs"].items()):
            out.append('  %s["%s"] %s %s'
                       % (nid(mod), Path(mod).name, trait[meta["preuve"]], s))
        for mod, meta in sorted(d["consommateurs"].items()):
            out.append('  %s %s %s["%s"]'
                       % (s, trait[meta["preuve"]], nid(mod), Path(mod).name))
    return "\n".join(out)


def _placement(noeuds, aretes):
    """Coordonnees. `networkx.spring_layout` si present, cercle deterministe sinon --
    le mode est RENDU a l'appelant : un repli ne se prend jamais en silence."""
    try:
        import networkx as nx

        g = nx.DiGraph()
        g.add_nodes_from(noeuds)
        for u, v, _p in aretes:
            g.add_edge(u, v)
        brut = nx.spring_layout(g, seed=7, k=0.9, iterations=120)
        pos = {}
        for n, xy in brut.items():
            pos[n] = (900 + 830 * float(xy[0]), 520 + 470 * float(xy[1]))
        return pos, "networkx.spring_layout"
    except Exception:  # noqa: BLE001
        import math

        total = max(len(noeuds), 1)
        pos = {}
        for i, nom in enumerate(sorted(noeuds)):
            ang = 2 * math.pi * i / total
            pos[nom] = (900 + 760 * math.cos(ang), 520 + 430 * math.sin(ang))
        return pos, "cercle deterministe (networkx indisponible)"


def to_html(a=None, seulement_defauts=True):
    """Page AUTONOME : aucun CDN, aucune dependance tierce.

    `pyvis` est absent de l'environnement et n'y sera pas installe : un paquet tiers
    dans `LAFORGE_PYTHON` pose ses versions par-dessus celles de Nokido, piege deja
    paye. Le rendu est donc du SVG inline, zoomable, sans reseau.
    """
    a = a or atlas()
    coul = {"CONSOMMATEUR_SANS_PRODUCTEUR": "#f87171",
            "PRODUCTEUR_SANS_CONSOMMATEUR": "#fbbf24", "INERTE": "#9ca3af",
            "ASSUME": "#60a5fa", "COUPLE": "#4ade80"}
    noeuds = {}
    aretes = []
    for d in _selection(a, seulement_defauts):
        noeuds[d["signal"]] = {"c": coul.get(d["verdict"], "#9ca3af"), "r": 7,
                               "t": d["signal"]}
        for mod, meta in d["emetteurs"].items():
            noeuds.setdefault(mod, {"c": "#6b7280", "r": 4, "t": Path(mod).name})
            aretes.append((mod, d["signal"], meta["preuve"]))
        for mod, meta in d["consommateurs"].items():
            noeuds.setdefault(mod, {"c": "#6b7280", "r": 4, "t": Path(mod).name})
            aretes.append((d["signal"], mod, meta["preuve"]))
    pos, mode = _placement(noeuds, aretes)

    larg = {DECLARE: '1" stroke-dasharray="4 3', STATIQUE: "1.4", CONSTATE: "2.8"}
    body = []
    for u, v, p in aretes:
        if u not in pos or v not in pos:
            continue
        body.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#334155" '
                    'stroke-width="%s"/>'
                    % (pos[u][0], pos[u][1], pos[v][0], pos[v][1], larg[p]))
    for nom, m in noeuds.items():
        if nom not in pos:
            continue
        x, y = pos[nom]
        etiq = nom.replace("&", "&amp;").replace("<", "&lt;")
        body.append('<circle cx="%.1f" cy="%.1f" r="%d" fill="%s">'
                    '<title>%s</title></circle>' % (x, y, m["r"], m["c"], etiq))
        body.append('<text class="lbl" x="%.1f" y="%.1f">%s</text>'
                    % (x + m["r"] + 3, y + 3,
                       m["t"].replace("&", "&amp;").replace("<", "&lt;")))
    sub = ("%d signaux (%d en defaut) - %d fichiers, %d illisibles - frontiere %s - "
           "placement %s" % (len(a["signaux"]), len(findings(a)), a["n_fichiers"],
                             a["n_illisibles"], a["frontiere"]["mode"], mode))
    page = _HTML.replace("__BODY__", "\n".join(body))
    return page.replace("__SUB__", sub) + _bloc_zoom()


def _main(argv=None):
    ap = argparse.ArgumentParser(description="Atlas du cablage des signaux Nokido.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--mermaid", action="store_true")
    ap.add_argument("--html", metavar="CHEMIN")
    ap.add_argument("--tout", action="store_true",
                    help="inclure les signaux COUPLE dans le graphe")
    ap.add_argument("--signal", help="un signal a-t-il un consommateur declare ?")
    ap.add_argument("--flux", action="store_true",
                    help="etat dynamique producteur -> signal -> consommateur -> effet")
    args = ap.parse_args(argv)

    a = atlas()
    if args.flux:
        f = flux(a)
        s = synthese(f)
        print("%-34s %-10s %-9s %-8s %-8s %s"
              % ("signal", "kind", "producteur", "signal", "conso", "effet"))
        print("-" * 92)
        for d in f["flux"]:
            print("%-34s %-10s %-9s %-8s %-8s %s"
                  % (d["signal"][:34], (d["kind"] or "?")[:10], d["producteur_vivant"],
                     d["etat_signal"], d["consommation"], d["effet"]))
        print("-" * 92)
        print(json.dumps(s, ensure_ascii=False))
        if f.get("vies_illisibles"):
            print("!! liveness ILLISIBLE (%s) : les producteurs sortent INCONNU, "
                  "ce n'est PAS une absence" % f["vies_illisibles"])
        return 0
    if args.signal:
        print(json.dumps(receveur_declare(args.signal, a), ensure_ascii=False, indent=2))
        return 0
    if args.json:
        print(json.dumps(a, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.mermaid:
        print(to_mermaid(a, seulement_defauts=not args.tout))
        return 0
    if args.html:
        p = Path(args.html)
        if not p.is_absolute():
            p = ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(to_html(a, seulement_defauts=not args.tout), encoding="utf-8")
        print("atlas ecrit: %s (%d octets)" % (p, p.stat().st_size))
        return 0

    print("=" * 100)
    print("ATLAS DU CABLAGE - un signal sans chemin complet est une panne silencieuse")
    print("=" * 100)
    degrade = "  (DEGRADEE)" if a["frontiere"]["degradee"] else ""
    print("frontiere : %s%s | %d fichiers | %d illisibles"
          % (a["frontiere"]["mode"], degrade, a["n_fichiers"], a["n_illisibles"]))
    for k, v in a["sources"].items():
        print("  source %-24s %s" % (k, v))
    print("-" * 100)
    print("%-34s %-10s %-30s %3s %3s %s"
          % ("signal", "kind", "verdict", "em", "co", "preuve"))
    print("-" * 100)
    for d in a["signaux"]:
        marque = "  [hors registre]" if d["hors_registre"] else ""
        print("%-34s %-10s %-30s %3d %3d %s%s"
              % (d["signal"][:34], (d["kind"] or "?")[:10], d["verdict"],
                 d["n_emetteurs"], d["n_consommateurs"],
                 d["niveau_preuve"] or "-", marque))
    f = findings(a)
    print("-" * 100)
    print("%d verdict(s) actionnable(s)" % len(f))
    for d in f:
        print("  ! %-30s %s" % (d["signal"], d.get("raison") or d["verdict"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
