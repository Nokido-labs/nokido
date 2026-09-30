#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""NPSC — Nokido Protocol & Standards Conformance : le JUGE.

Moteur UNIQUE de conformite normative, multi-autorite (IETF, MCP, WHATWG, W3C,
OCI, OpenAPI, IANA, Unicode, NOKIDO). Il n'encode AUCUNE norme : tout vient de
`standards/registry.json`. Il ne MESURE rien non plus : le capteur est
`forge_npsc_scan.py`. Un capteur et un juge ne se melangent pas.

    standard -> version -> exigence -> applicabilite -> implementation
             -> test -> preuve -> verdict

REGLE FONDATRICE : une norme n'est pas applicable parce qu'elle existe, elle le
devient parce qu'une surface PROUVEE de Nokido l'active.

REGLE DE VERDICT : une exigence sans test n'est pas conforme, elle est
UNVERIFIED. Jamais PASS. Une surface applicable mais inatteignable rend
UNVERIFIED, jamais COMPLIANT.

AUDIT DE L'AUDITEUR : si un seul controle du capteur cede, TOUT passe en
NO_VERDICT. Un instrument muet ne prononce pas d'acquittement.

Federe, sans les remplacer :
  - tools/audit_rfc_compliance.py      presence des normes en corpus
  - tools/forge_rfc_freshness_gate.py  fraicheur amont IETF
  - app/forge_m2m_conformance.py       conformite du protocole interne M2M
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/conformite-normative"

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nokido_agent.tools.forge_npsc_scan import (  # noqa: E402
    ABSENT, PROVEN, ROOT, SUSPECT, UNREADABLE,
    charger_inventaire, inventorier, sauver_inventaire,
)

APPLICABILITE = ROOT / "sandbox" / "npsc_applicability.json"

REGISTRE = ROOT / "standards" / "registry.json"
RAPPORT = ROOT / "docs" / "NPSC_CONFORMANCE.md"
JSON_OUT = ROOT / "sandbox" / "npsc_state.json"

# Vocabulaire FERME. Une valeur hors de cet ensemble est un defaut du moteur.
VERDICTS = (
    "COMPLIANT",       # exigence testee et satisfaite
    "PARTIAL",         # partiellement satisfaite, perimetre nomme
    "VIOLATION",       # exigence testee et violee
    "NOT_APPLICABLE",  # aucune surface prouvee ne la declenche
    "UNVERIFIED",      # applicable, mais AUCUN test ne la confronte
    "UNKNOWN",         # indice sans preuve, ou test non concluant
    "NO_VERDICT",      # l'instrument n'a pas pu mesurer
)


def charger_registre(chemin=REGISTRE):
    """Rend (registre, erreur). `registre` est None si on n'a PAS PU le lire."""
    try:
        brut = Path(chemin).read_text(encoding="utf-8")
    except Exception as exc:
        return None, "registre illisible (%s) : %s" % (chemin, exc)
    try:
        reg = json.loads(brut)
    except Exception as exc:
        return None, "registre non parsable : %s" % exc
    for cle in ("standards", "surfaces", "autorites"):
        if cle not in reg:
            return None, "registre incomplet : section '%s' absente" % cle
    return reg, None


def applicabilite(reg, surfaces):
    """Quel standard est applicable, et PAR QUOI. Rien n'est enterre en silence."""
    etat = {}
    for sid in reg["standards"]:
        etat[sid] = {"applicable": False, "declenche_par": [], "conditionnel_de": [],
                     "illisible_de": [], "indice_de": []}
    for nom, spec in reg["surfaces"].items():
        mesure = surfaces.get(nom) or {}
        e = mesure.get("etat")
        for sid in spec.get("standards") or []:
            if sid not in etat:
                continue
            if e == PROVEN:
                etat[sid]["applicable"] = True
                etat[sid]["declenche_par"].append(nom)
            elif e == SUSPECT:
                etat[sid]["indice_de"].append(nom)
            elif e == UNREADABLE:
                etat[sid]["illisible_de"].append(nom)
        for sid in spec.get("conditionnels") or []:
            if sid in etat and e == PROVEN:
                etat[sid]["conditionnel_de"].append(nom)
    return etat


def exigences(sid, reg):
    """Exigences atomisees d'un standard. Vide tant que l'atomisation n'est pas faite.

    Le moteur le DIT au lieu de le masquer : c'est ce qui force UNVERIFIED.
    """
    return (reg["standards"].get(sid) or {}).get("exigences") or []


def _git_grep(racine, motif, globs=None):
    """Cherche un motif dans le code VERSIONNE. Rend (fichiers, erreur).

    Rend None si l'outil echoue : « je n'ai pas pu chercher » n'est pas « il n'y
    a rien ». C'est cette distinction qui empeche un executeur casse de
    prononcer une VIOLATION imaginaire.
    """
    # `-e <motif>` et NON un motif POSITIONNEL. Mesure 2026-09-05 : l'exigence
    # JSON-RPC sur les codes d'erreur reserves (`-32700|-3260[0-3]`) commence par un
    # tiret, que git lit comme une OPTION -> `rc=129 unknown switch` -> NO_VERDICT sur
    # une exigence parfaitement verifiable. Corriger ici supprime la classe entiere,
    # au lieu de tordre chaque motif du registre.
    cmd = ["git", "-c", "safe.directory=*", "-C", str(racine), "grep", "-l", "-I",
           "-E", "-e", motif]
    if globs:
        cmd.append("--")
        cmd.extend(globs)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
    except Exception as exc:
        return None, "git grep indisponible : %s" % exc
    # rc=1 signifie « aucune correspondance » : ce n'est pas une erreur.
    if proc.returncode not in (0, 1):
        detail = (proc.stderr or b"").decode("utf-8", "replace")[:200]
        return None, "git grep rc=%s : %s" % (proc.returncode, detail)
    sortie = (proc.stdout or b"").decode("utf-8", "replace")
    return [f for f in sortie.splitlines() if f.strip()], None


def executer_exigence(exigence, racine):
    """Confronte UNE exigence atomisee au depot. Rend un dict de resultat.

    Deux types branches, symetriques :

      presence_requise  la norme impose qu'un mecanisme EXISTE.
                        Son absence totale est une violation.
      absence_requise   la norme interdit une construction.
                        Sa presence est une violation.

    Le second accepte `exemptions` : des chemins ou le motif est LEGITIME —
    typiquement les detecteurs qui citent le motif pour le chercher, et les
    tests qui le fabriquent. Sans cela l'exigence se declencherait sur son
    propre garde : trois fois le meme piege paye le 2026-09-04.

    Un type inconnu rend NO_VERDICT, jamais un acquittement : un executeur qui
    ne sait pas verifier ne conclut pas que tout va bien.
    """
    detecteur = exigence.get("detecteur") or {}
    type_det = detecteur.get("type")
    resultat = {"id": exigence.get("id"), "texte": exigence.get("texte"), "preuve": []}
    if type_det not in ("presence_requise", "absence_requise"):
        resultat["verdict"] = "NO_VERDICT"
        resultat["motif"] = "type de detecteur non branche : %r" % type_det
        return resultat

    fichiers, err = _git_grep(racine, detecteur.get("motif") or "", detecteur.get("globs"))
    if fichiers is None:
        resultat["verdict"] = "NO_VERDICT"
        resultat["motif"] = err
        return resultat

    if type_det == "presence_requise":
        if fichiers:
            resultat["verdict"] = "COMPLIANT"
            resultat["motif"] = "mecanisme present dans %d fichier(s)" % len(fichiers)
            resultat["preuve"] = sorted(fichiers)[:5]
        else:
            resultat["verdict"] = exigence.get("si_absent") or "VIOLATION"
            resultat["motif"] = "aucune occurrence de `%s` dans le code versionne" % (detecteur.get("motif") or "")
        return resultat

    exemptions = tuple(detecteur.get("exemptions") or ())
    fautifs = []
    exemptes = []
    for chemin in fichiers:
        norme = chemin.replace("\\", "/")
        if any(norme.startswith(e) or norme == e for e in exemptions):
            exemptes.append(norme)
        else:
            fautifs.append(norme)
    if fautifs:
        resultat["verdict"] = exigence.get("si_present") or "VIOLATION"
        resultat["motif"] = "construction interdite dans %d fichier(s)" % len(fautifs)
        resultat["preuve"] = sorted(fautifs)[:5]
    else:
        resultat["verdict"] = "COMPLIANT"
        # Le denominateur est RENDU : « 0 fautif » sur 0 fichier examine et
        # « 0 fautif » sur 12 dont 12 exemptes ne valent pas la meme chose.
        resultat["motif"] = "aucune occurrence hors exemptions (%d exemptee(s) sur %d vue(s))" % (
            len(exemptes), len(fichiers))
        resultat["preuve"] = sorted(exemptes)[:5]
    return resultat


def verdict_des_exigences(atomes, racine):
    """Agrege les verdicts d'exigences. Rend (verdict, motif, details).

    Un seul NO_VERDICT contamine l'ensemble : on ne declare pas conforme un
    standard dont une exigence n'a pas pu etre verifiee.
    """
    details = [executer_exigence(a, racine) for a in atomes]
    rendus = [d["verdict"] for d in details]
    if "NO_VERDICT" in rendus:
        indecis = [d for d in details if d["verdict"] == "NO_VERDICT"][0]
        return "NO_VERDICT", "exigence non verifiable : %s" % indecis["motif"], details
    violations = [d for d in details if d["verdict"] == "VIOLATION"]
    if violations and len(violations) == len(details):
        return "VIOLATION", violations[0]["motif"], details
    if violations:
        return "PARTIAL", "%d/%d exigences violees, dont %s" % (
            len(violations), len(details), violations[0]["id"]), details
    return "COMPLIANT", "%d/%d exigences satisfaites" % (len(details), len(details)), details


def evaluer(reg, surfaces, diag, racine=None):
    """Verdict par standard. Aucun COMPLIANT sans test — par construction.

    Sans `racine`, les exigences ne sont pas executees et le standard reste
    UNKNOWN : un juge sans acces au depot ne prononce rien.
    """
    appl = applicabilite(reg, surfaces)
    casses = []
    for cle, valeur in (diag.get("controles") or {}).items():
        if not valeur:
            casses.append(cle)
    lignes = []
    for sid in sorted(reg["standards"]):
        meta = reg["standards"][sid]
        a = appl.get(sid) or {}
        atomes = exigences(sid, reg)
        details = None
        if not diag.get("instrument_ok"):
            verdict = "NO_VERDICT"
            motif = "instrument non concluant : " + (", ".join(casses) or "cause non nommee")
        elif a.get("applicable"):
            if atomes and racine is not None:
                verdict, motif, details = verdict_des_exigences(atomes, racine)
                motif = motif + " (declenche par " + ", ".join(a["declenche_par"]) + ")"
            elif atomes:
                verdict = "UNKNOWN"
                motif = "%d exigences declarees, juge sans acces au depot" % len(atomes)
            else:
                verdict = "UNVERIFIED"
                motif = "applicable via " + ", ".join(a["declenche_par"]) + " - aucune exigence atomisee ni test"
        elif a.get("illisible_de"):
            verdict = "NO_VERDICT"
            motif = "surfaces illisibles : " + ", ".join(a["illisible_de"])
        elif a.get("indice_de"):
            verdict = "UNKNOWN"
            motif = "surface CITEE sans preuve structurelle (" + ", ".join(a["indice_de"]) + ") - a instruire"
        elif a.get("conditionnel_de"):
            verdict = "UNVERIFIED"
            motif = "conditionnel de " + ", ".join(a["conditionnel_de"]) + " - activation a confirmer au runtime"
        else:
            verdict = "NOT_APPLICABLE"
            motif = "aucune surface prouvee ne la declenche"
        if verdict not in VERDICTS:
            raise AssertionError("verdict hors vocabulaire : %s" % verdict)
        lignes.append({
            "standard": sid, "autorite": meta.get("autorite"), "titre": meta.get("titre"),
            "statut_amont": meta.get("statut"), "verdict": verdict, "motif": motif,
            "declenche_par": a.get("declenche_par") or [],
            "remplace_par": meta.get("remplace_par") or [],
            "exigences": details,
        })
    return lignes


def compter(lignes):
    compte = {}
    for ligne in lignes:
        compte[ligne["verdict"]] = compte.get(ligne["verdict"], 0) + 1
    return compte


def rapport(reg, surfaces, diag, lignes):
    horo = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    o = []
    o.append("# NPSC - Nokido Protocol & Standards Conformance")
    o.append("")
    o.append("_Genere le %s par `tools/forge_npsc.py`, registre v%s._" % (horo, reg.get("version")))
    o.append("")
    o.append("> Une norme devient applicable parce qu'une surface **prouvee** l'active,")
    o.append("> jamais parce qu'elle existe. Une surface se prouve par une signature")
    o.append("> structurelle (import, route, appel) dans du code **versionne**, jamais")
    o.append("> par un mot. Une exigence sans test est `UNVERIFIED`, jamais `PASS`.")
    o.append("")
    o.append("## Instrument")
    o.append("")
    o.append("- source : **%s**, %d fichiers suivis, %d lus" % (diag.get("source"), diag.get("suivis", 0), diag.get("lus", 0)))
    pops = diag.get("populations") or {}
    o.append("- populations : " + " / ".join(["%s %d" % (k, pops[k]) for k in sorted(pops)]))
    ex_ill = ", ".join(diag.get("illisibles_exemples") or [])
    ligne_ill = "- illisibles : **%d** (%.2f %%)" % (diag.get("illisibles", 0), diag.get("taux_illisible", 0) * 100)
    if ex_ill:
        ligne_ill += " - ex. " + ex_ill
    o.append(ligne_ill)
    ex_vol = ", ".join(diag.get("volumineux_exemples") or [])
    ligne_vol = "- ecartes car volumineux : **%d**" % diag.get("volumineux_ecartes", 0)
    if ex_vol:
        ligne_vol += " - ex. " + ex_vol
    o.append(ligne_vol)
    ex_ast = ", ".join(diag.get("ast_echecs_exemples") or [])
    ligne_ast = "- AST : %d tentes, **%d echecs** (%.2f %%)" % (
        diag.get("ast_tentes", 0), diag.get("ast_echecs", 0), diag.get("taux_ast_echec", 0) * 100)
    if ex_ast:
        ligne_ast += " - ex. " + ex_ast
    o.append(ligne_ast)
    o.append("")
    o.append("### Controles de l'auditeur")
    o.append("")
    o.append("| controle | etat |")
    o.append("|---|---|")
    for cle, valeur in (diag.get("controles") or {}).items():
        o.append("| `%s` | %s |" % (cle, "OK" if valeur else "**ECHEC**"))
    if diag.get("sanity_manquantes"):
        o.append("")
        o.append("Surfaces structurellement certaines NON prouvees : **" +
                 ", ".join(diag["sanity_manquantes"]) +
                 "**. C'est le scanner qu'il faut corriger, pas le depot.")
    o.append("")
    if diag.get("instrument_ok"):
        o.append("**Verdict de l'instrument : CONCLUANT**")
    else:
        o.append("**Verdict de l'instrument : NON CONCLUANT - tout passe en NO_VERDICT**")
    o.append("")
    o.append("## Surfaces mesurees")
    o.append("")
    o.append("| surface | etat | preuve | indice | priorite | temoins |")
    o.append("|---|---|---:|---:|---|---|")
    rang = {PROVEN: 0, SUSPECT: 1, UNREADABLE: 2, ABSENT: 3}
    noms = sorted(surfaces, key=lambda n: (rang.get(surfaces[n]["etat"], 9), -(surfaces[n].get("score_preuve") or 0)))
    for nom in noms:
        m = surfaces[nom]
        temoins = ", ".join(m.get("temoins") or []) or "-"
        o.append("| `%s` | %s | %s | %s | %s | %s |" % (
            nom, m["etat"], m.get("score_preuve"), m.get("score_indice"), m.get("priorite") or "-", temoins))
    sans = [n for n in surfaces if surfaces[n].get("sans_autorite") and surfaces[n]["etat"] == PROVEN]
    if sans:
        o.append("")
        o.append("### Surfaces PROUVEES sans autorite normative")
        o.append("")
        o.append("Aucun referentiel public ne les couvre. Les omettre les rendrait")
        o.append("invisibles ; elles relevent d'une regle NOKIDO.")
        o.append("")
        for nom in sans:
            o.append("- **`%s`** (%d signatures) : %s" % (nom, surfaces[nom]["score_preuve"], surfaces[nom]["sans_autorite"]))
    o.append("")
    o.append("## Verdicts par standard")
    o.append("")
    o.append("| standard | autorite | verdict | motif |")
    o.append("|---|---|---|---|")
    ordre = {}
    for i, v in enumerate(VERDICTS):
        ordre[v] = i
    for ligne in sorted(lignes, key=lambda x: (ordre.get(x["verdict"], 9), x["standard"])):
        alerte = ""
        if ligne["remplace_par"]:
            alerte = " (OBSOLETE, remplace par " + ", ".join(ligne["remplace_par"]) + ")"
        o.append("| `%s` | %s | **%s** | %s%s |" % (
            ligne["standard"], ligne["autorite"], ligne["verdict"], ligne["motif"], alerte))
    compte = compter(lignes)
    o.append("")
    o.append("## Bilan")
    o.append("")
    o.append(" / ".join(["**%s** %d" % (v, compte[v]) for v in VERDICTS if v in compte]))
    o.append("")
    o.append("Aucun `COMPLIANT` n'est possible tant que les exigences ne sont pas")
    o.append("atomisees et confrontees a un test executable. C'est le sens de ce")
    o.append("rapport, pas son defaut.")
    o.append("")
    return "\n".join(o)


def cmd_discover(args):
    """ETAPE 1 — « qu'est-ce qui existe ? ». Ne connait AUCUNE norme.

    Scanne le depot et pose une photographie des surfaces. C'est la seule etape
    qui lit des fichiers ; les deux suivantes travaillent sur son artefact.
    """
    reg, err = charger_registre()
    if reg is None:
        print("NO_VERDICT - %s" % err)
        return 2
    surfaces, diag = inventorier(reg, Path(args.racine))
    pose = sauver_inventaire(surfaces, diag)
    if args.json:
        print(json.dumps({"surfaces": surfaces, "instrument": diag}, ensure_ascii=False))
        return 0
    print("DISCOVER - %d suivis, %d lus, %d illisibles" % (
        diag.get("suivis", 0), diag.get("lus", 0), diag.get("illisibles", 0)))
    casses = [k for k, v in (diag.get("controles") or {}).items() if not v]
    print("  instrument : %s" % ("CONCLUANT" if not casses else "NON CONCLUANT -> " + ", ".join(casses)))
    for etiquette in (PROVEN, SUSPECT, ABSENT, UNREADABLE):
        noms = sorted([n for n in surfaces if surfaces[n]["etat"] == etiquette])
        if noms:
            print("  %-10s (%2d) : %s" % (etiquette, len(noms), ", ".join(noms)))
    print("  inventaire : %s" % (pose or "NON POSE"))
    return 0


def cmd_applicable(args):
    """ETAPE 2 — « quelles regles s'appliquent ? ». Ne scanne RIEN.

    Lit l'inventaire pose par `discover` et le croise au registre. Quasi
    instantane, parce qu'aucun fichier du depot n'est rouvert.
    """
    reg, err = charger_registre()
    if reg is None:
        print("NO_VERDICT - %s" % err)
        return 2
    surfaces, diag, err_inv = charger_inventaire()
    if surfaces is None:
        print("NO_VERDICT - %s (lancer `discover` d'abord)" % err_inv)
        return 2
    appl = applicabilite(reg, surfaces)
    actifs = {sid: a for sid, a in appl.items() if a["applicable"]}
    charge = {"genere": datetime.now(timezone.utc).isoformat(), "registre": reg.get("version"),
              "instrument": diag, "applicabilite": appl}
    try:
        APPLICABILITE.parent.mkdir(parents=True, exist_ok=True)
        APPLICABILITE.write_text(json.dumps(charge, ensure_ascii=False, indent=2), encoding="utf-8")
        pose = APPLICABILITE
    except Exception as exc:
        pose = None
        print("[npsc] matrice non posee : %s" % exc)
    if args.json:
        print(json.dumps(charge, ensure_ascii=False))
        return 0
    atomises = [sid for sid in actifs if exigences(sid, reg)]
    print("APPLICABLE - %d standards au registre, %d applicables" % (len(reg["standards"]), len(actifs)))
    print("  atomises   : %d (%s)" % (len(atomises), ", ".join(sorted(atomises)) or "aucun"))
    print("  a atomiser : %d — c'est ICI que le travail d'atomisation commence,"
          " pas sur les %d standards du registre" % (len(actifs) - len(atomises), len(reg["standards"])))
    print("  matrice    : %s" % (pose or "NON POSEE"))
    return 0


def main(argv=None):
    parseur = argparse.ArgumentParser(description="Moteur de conformite normative multi-autorite")
    parseur.add_argument("etape", nargs="?", default="all",
                         choices=("discover", "applicable", "verify", "all"),
                         help="discover: photographie les surfaces (seule etape qui lit le depot) | "
                              "applicable: derive les normes depuis l'inventaire | "
                              "verify: execute les exigences des seuls standards applicables | "
                              "all: enchaine les trois")
    parseur.add_argument("--json", action="store_true", help="sortie machine sur stdout")
    parseur.add_argument("--racine", default=str(ROOT))
    args = parseur.parse_args(argv)

    if args.etape == "discover":
        return cmd_discover(args)
    if args.etape == "applicable":
        return cmd_applicable(args)

    reg, err = charger_registre()
    if reg is None:
        print("NO_VERDICT - %s" % err)
        return 2

    if args.etape == "verify":
        surfaces, diag, err_inv = charger_inventaire()
        if surfaces is None:
            print("NO_VERDICT - %s (lancer `discover` d'abord)" % err_inv)
            return 2
    else:
        surfaces, diag = inventorier(reg, Path(args.racine))
        sauver_inventaire(surfaces, diag)
    lignes = evaluer(reg, surfaces, diag, racine=Path(args.racine))
    etat = {"genere": datetime.now(timezone.utc).isoformat(), "registre": reg.get("version"),
            "instrument": diag, "surfaces": surfaces, "verdicts": lignes}

    cibles = [(JSON_OUT, json.dumps(etat, ensure_ascii=False, indent=2)),
              (RAPPORT, rapport(reg, surfaces, diag, lignes))]
    ecrits = {}
    for cible, contenu in cibles:
        pose = None
        for candidat in (cible, JSON_OUT.parent / cible.name):
            try:
                candidat.parent.mkdir(parents=True, exist_ok=True)
                candidat.write_text(contenu, encoding="utf-8")
                pose = candidat
                break
            except Exception as exc:
                # Le compte sandbox n'ecrit pas dans `docs/`. Un verdict qui ne
                # se pose nulle part est un verdict perdu : on REPLIE vers une
                # zone accessible et on DIT ou, plutot que de se contenter d'un
                # message d'echec.
                print("[npsc] %s refuse (%s)" % (candidat, type(exc).__name__))
        if pose is None:
            print("[npsc] AUCUNE trace posee pour %s - le verdict reste valide, sa trace non" % cible.name)
        else:
            ecrits[cible.name] = str(pose)
            if pose != cible:
                print("[npsc] repli : %s ecrit dans %s (cible %s inaccessible)" % (cible.name, pose.parent, cible.parent))
    etat["traces"] = ecrits

    if args.json:
        print(json.dumps(etat, ensure_ascii=False))
        return 0

    print("NPSC - registre v%s | source %s" % (reg.get("version"), diag.get("source")))
    print("  index      : %d suivis, %d lus, %d illisibles, %d volumineux ecartes" % (
        diag.get("suivis", 0), diag.get("lus", 0), diag.get("illisibles", 0), diag.get("volumineux_ecartes", 0)))
    pops = diag.get("populations") or {}
    print("  populations: " + " ".join(["%s=%d" % (k, pops[k]) for k in sorted(pops)]))
    print("  AST        : %d tentes, %d echecs" % (diag.get("ast_tentes", 0), diag.get("ast_echecs", 0)))
    casses = [k for k, v in (diag.get("controles") or {}).items() if not v]
    if casses:
        print("  controles  : ECHEC -> " + ", ".join(casses))
    else:
        print("  controles  : tous OK")
    for etiquette in (PROVEN, SUSPECT, ABSENT, UNREADABLE):
        noms = sorted([n for n in surfaces if surfaces[n]["etat"] == etiquette])
        if noms:
            print("  %-11s: %s" % (etiquette, ", ".join(noms)))
    compte = compter(lignes)
    print("  verdicts   : " + " ".join(["%s=%d" % (v, compte[v]) for v in VERDICTS if v in compte]))
    obsoletes = [item["standard"] for item in lignes if item["remplace_par"]]
    if obsoletes:
        print("  OBSOLETES  : " + ", ".join(obsoletes))
    print("  rapport    : %s" % ecrits.get(RAPPORT.name, "NON POSE"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
