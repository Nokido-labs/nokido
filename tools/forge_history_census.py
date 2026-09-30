#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_history_census.py — Phase 7 : census de l'HISTOIRE (pas des cadavres).

POURQUOI. Les phases 1 a 6 partent toutes de `git log --diff-filter=D` : elles
ne voient que ce qui a ete SUPPRIME (1732 .py). L'ecosysteme compte 4000+
commits depuis le 2026-03-08 (creation de `nokido`), tous depots confondus :
tout ce qui a ete CONSTRUIT, reecrit, renomme, et l'intention portee par les
messages de commit, restait hors du champ.

Ce module lit l'histoire COMPLETE, tous depots, toutes branches, tous types de
fichiers, depuis le commit racine. LECTURE SEULE : aucun checkout, aucune
ecriture dans les depots analyses.

Sortie : sandbox/history_census.json + resume stdout.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import time

# Socle commun (cf. forge_archeo_socle) : `_git`, `_est_bruit` et la decouverte
# de depots etaient recopies a l'identique dans huit outils -- le cliquet de
# duplication l'a signale le 2026-08-18, il avait raison.

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
from nokido_agent.tools.forge_archeo_socle import CODE_EXT, DOC_EXT, ROOT, decouvrir_depots
from nokido_agent.tools.forge_archeo_socle import est_bruit as _est_bruit
from nokido_agent.tools.forge_archeo_socle import git as _git


def decouvrir(extra):
    """Depots analysables : super-repo, submodules, clones d'archeologie."""
    return decouvrir_depots(extra)


def _prefixe(sujet):
    """Type conventionnel du commit (feat/fix/chore...) ou 'autre'."""
    tete = sujet.split(":", 1)[0].strip().lower()
    tete = tete.split("(", 1)[0].strip()
    connus = {"feat", "fix", "chore", "refactor", "docs", "test", "perf",
              "ci", "build", "style", "revert", "merge", "wip", "hotfix"}
    return tete if tete in connus else "autre"


def censer(nom, chemin):
    """Un depot -> volumetrie, rythme, churn, faux departs, intentions."""
    sep = "\x1e"  # record separator : un message de commit ne le contient pas
    brut = _git(chemin, "log", "--all", "--no-merges", "--date=short",
                "--name-status", "-M",
                "--format=" + sep + "%H|%ad|%an|%s")
    if not brut:
        return {"erreur": "git log vide ou acces refuse"}

    vivants = set(l.strip() for l in
                  _git(chemin, "ls-tree", "-r", "HEAD", "--name-only").splitlines())
    commits = 0
    auteurs = collections.Counter()
    mots_mois = collections.defaultdict(collections.Counter)
    par_mois = collections.Counter()
    types_mois = collections.defaultdict(collections.Counter)
    ext_actes = collections.defaultdict(collections.Counter)
    churn = collections.Counter()
    naissance = {}
    mort = {}
    # Avant juin 2026 il n'existe AUCUN historique de conversation : le message
    # du commit qui supprime est la seule trace d'intention accessible.
    mort_motif = {}
    renommages = 0
    premier = None
    dernier = None

    for bloc in brut.split(sep):
        bloc = bloc.strip("\n")
        if not bloc:
            continue
        tete, _, corps = bloc.partition("\n")
        parts = tete.split("|", 3)
        if len(parts) < 4:
            continue
        _sha, date, auteur, sujet = parts
        commits += 1
        auteurs[auteur] += 1
        mois = date[:7]
        par_mois[mois] += 1
        types_mois[mois][_prefixe(sujet)] += 1
        for mot in re.findall(r"[a-zA-Z_]{4,}", sujet.lower()):
            if mot not in STOPWORDS:
                mots_mois[mois][mot] += 1
        if premier is None or date < premier:
            premier = date
        if dernier is None or date > dernier:
            dernier = date

        for ligne in corps.splitlines():
            if not ligne.strip():
                continue
            champs = ligne.split("\t")
            acte = champs[0][:1]
            cible = champs[-1]
            if _est_bruit(cible):
                continue
            ext = os.path.splitext(cible)[1].lower()
            if ext not in CODE_EXT and ext not in DOC_EXT:
                continue
            ext_actes[ext][acte] += 1
            if acte == "R":
                renommages += 1
            if acte in ("M", "A", "R"):
                churn[cible] += 1
            if acte == "A":
                if cible not in naissance or date < naissance[cible]:
                    naissance[cible] = date
            elif acte == "D":
                if cible not in mort or date > mort[cible]:
                    mort[cible] = date
                    mort_motif[cible] = sujet[:160]

    # Troisieme etat : present sur DISQUE mais hors suivi git. Ni vivant pour le
    # depot, ni mort dans l'histoire -- donc invisible du RAG, de la CI, des
    # gates et de toute archeologie basee sur git. C'est un angle mort, pas une
    # perte : le code est la, il suffit de le re-tracker.
    hors_suivi = []
    for racine, dirs, fichiers in os.walk(chemin):
        dirs[:] = [d for d in dirs
                   if d != ".git" and not _est_bruit(d.rstrip("/") + "/")]
        for f in fichiers:
            if os.path.splitext(f)[1].lower() not in CODE_EXT:
                continue
            rel = os.path.relpath(os.path.join(racine, f), chemin).replace("\\", "/")
            if _est_bruit(rel) or rel in vivants:
                continue
            hors_suivi.append(rel)
    hs_racines = collections.Counter(f.split("/")[0] for f in hors_suivi)

    # faux departs : ne dans l'histoire, mort peu apres, jamais revenu
    faux = []
    for f, dn in naissance.items():
        dm = mort.get(f)
        if not dm or dm < dn:
            continue
        try:
            jours = (time.mktime(time.strptime(dm, "%Y-%m-%d"))
                     - time.mktime(time.strptime(dn, "%Y-%m-%d"))) / 86400
        except ValueError:
            # date git illisible : le fichier reste hors du compte des faux departs
            print("[census] date illisible sur %s (%s -> %s)" % (f, dn, dm))
            continue
        if jours <= 14 and os.path.splitext(f)[1].lower() in CODE_EXT:
            faux.append({"chemin": f, "ne": dn, "mort": dm, "jours": int(jours)})
    faux.sort(key=lambda x: x["jours"])

    # Ce que chaque mois a produit, et ce qui en vit encore dans HEAD.
    naiss_mois = {}
    morts_locaux = {}
    for f, dn in naissance.items():
        if os.path.splitext(f)[1].lower() not in CODE_EXT:
            continue
        cell = naiss_mois.setdefault(dn[:7], {"nes": 0, "survivants": 0})
        cell["nes"] += 1
        if f in vivants:
            cell["survivants"] += 1
        else:
            # Le churn mesure le travail investi : une capacite retravaillee 40
            # fois puis supprimee est une regression couteuse, pas un brouillon.
            morts_locaux[f] = {"mois": dn[:7], "ne": dn,
                               "mort": mort.get(f, "?"), "churn": churn.get(f, 0),
                               "motif": mort_motif.get(f, "")}
    for m, cell in naiss_mois.items():
        cell["survie_pct"] = round(100.0 * cell["survivants"] / cell["nes"], 1)

    return {
        "hors_suivi_n": len(hors_suivi),
        "hors_suivi_racines": dict(hs_racines.most_common(15)),
        "hors_suivi": sorted(hors_suivi)[:300],
        "morts_locaux": morts_locaux,
        "naissances_par_mois": dict(sorted(naiss_mois.items())),
        "themes_par_mois": dict((m, c.most_common(12))
                                for m, c in sorted(mots_mois.items())),
        "chemin": chemin,
        "commits": commits,
        "premier": premier,
        "dernier": dernier,
        "auteurs": dict(auteurs.most_common(10)),
        "par_mois": dict(sorted(par_mois.items())),
        "types_par_mois": dict((m, dict(c.most_common()))
                               for m, c in sorted(types_mois.items())),
        "actes_par_ext": dict((e, dict(c)) for e, c in sorted(
            ext_actes.items(), key=lambda kv: -sum(kv[1].values()))[:14]),
        "renommages": renommages,
        "fichiers_vus": len(churn),
        "top_churn": churn.most_common(25),
        "faux_departs_n": len(faux),
        "faux_departs": faux[:40],
    }


STOPWORDS = set("""le la les de des du un une et ou a au aux en dans pour par sur
sans avec ce cet cette ces son sa ses leur leurs il elle on nous vous ils elles
est sont ete etre fait faire plus moins tout tous toute toutes que qui quoi dont
the a an and or of to in for on with is are be was were it this that not no
add adds added update updates fix fixes new via use uses using from into
""".split())


def focus(depots, mois, out):
    """Ce qu'un mois a produit : ne pendant la periode, survivant ou mort."""
    debut = mois + "-01"
    an, m = mois.split("-")
    fin = ("%s-01-01" % (int(an) + 1)) if m == "12" else ("%s-%02d-01" % (an, int(m) + 1))
    res = {"mois": mois, "depots": {}}
    for nom, chemin in depots.items():
        vivants = set()
        for ligne in _git(chemin, "ls-tree", "-r", "HEAD", "--name-only").splitlines():
            vivants.add(ligne.strip())
        sep = "\x1e"
        # --since/--until filtrent sur la date de COMMITTER : une histoire
        # reecrite (rebase, import) y echappe entierement. On lit tout et on
        # filtre sur la date d'AUTEUR, seule fidele au moment du travail.
        brut = _git(chemin, "log", "--all", "--no-merges", "--date=short",
                    "--name-status", "-M",
                    "--format=" + sep + "%ad|%s")
        if not brut:
            continue
        mots = collections.Counter()
        nes = {}
        commits = 0
        for bloc in brut.split(sep):
            bloc = bloc.strip("\n")
            if not bloc:
                continue
            tete, _, corps = bloc.partition("\n")
            if "|" not in tete:
                continue
            date, sujet = tete.split("|", 1)
            if not (debut <= date < fin):
                continue
            commits += 1
            for mot in re.findall(r"[a-zA-Z_]{4,}", sujet.lower()):
                if mot not in STOPWORDS:
                    mots[mot] += 1
            for ligne in corps.splitlines():
                champs = ligne.split("\t")
                if not champs or champs[0][:1] != "A":
                    continue
                cible = champs[-1]
                if _est_bruit(cible) or os.path.splitext(cible)[1].lower() not in CODE_EXT:
                    continue
                nes.setdefault(cible, date)
        survivants = sorted(f for f in nes if f in vivants)
        morts = sorted(f for f in nes if f not in vivants)
        res["depots"][nom] = {
            "commits": commits,
            "nes": len(nes),
            "survivants_n": len(survivants),
            "morts_n": len(morts),
            "taux_survie": round(100.0 * len(survivants) / len(nes), 1) if nes else None,
            "themes": mots.most_common(30),
            "survivants": survivants[:120],
            "morts": morts[:120],
        }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print("[focus] %s" % mois)
    for nom, x in sorted(res["depots"].items(), key=lambda kv: -kv[1]["commits"]):
        print("  %-20s commits=%-5s nes=%-5s survivants=%-5s morts=%-5s survie=%s%%"
              % (nom, x["commits"], x["nes"], x["survivants_n"], x["morts_n"], x["taux_survie"]))
        print("     themes: %s" % ", ".join("%s(%s)" % (w, c) for w, c in x["themes"][:12]))
    print("[focus] ecrit : %s" % os.path.relpath(out, ROOT))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Census de l'histoire git (Phase 7)")
    ap.add_argument("--repos", nargs="*", default=[], help="nom=chemin en plus")
    ap.add_argument("--out", default=os.path.join(ROOT, "sandbox", "history_census.json"))
    ap.add_argument("--focus", default=None, help="AAAA-MM : ce que ce mois a produit")
    a = ap.parse_args()

    depots, refuses = decouvrir(a.repos)
    if a.focus:
        return focus(depots, a.focus,
                     os.path.join(ROOT, "sandbox", "history_focus_%s.json" % a.focus))
    res = {"genere": time.strftime("%Y-%m-%dT%H:%M:%S"), "depots": {}}
    for nom, chemin in depots.items():
        print("[census] " + nom + " ...", flush=True)
        res["depots"][nom] = censer(nom, chemin)

    ok = dict((n, d) for n, d in res["depots"].items() if "erreur" not in d)
    total_mois = collections.Counter()
    for d in ok.values():
        total_mois.update(d["par_mois"])
    res["total"] = {
        "depots_ok": sorted(ok),
        "depots_ko": dict((n, d["erreur"]) for n, d in res["depots"].items()
                          if "erreur" in d),
        "depots_refuses": refuses,
        "compte": os.environ.get("USERNAME", "?"),
        "commits": sum(d["commits"] for d in ok.values()),
        "par_mois": dict(sorted(total_mois.items())),
        "premier": min([d["premier"] for d in ok.values() if d["premier"]] or [None]),
        "faux_departs": sum(d["faux_departs_n"] for d in ok.values()),
    }

    t = res["total"]
    print("\n[census] %s commits sur %s depots, depuis %s"
          % (t["commits"], len(ok), t["premier"]))
    # Un fichier absent du HEAD de son depot mais present dans celui d'un AUTRE
    # n'est pas mort : il a MIGRE. Sans ce croisement, le deplacement du code du
    # super-repo vers le submodule se lit comme une destruction totale.
    union_chemins = set()
    union_bases = set()
    for chemin in depots.values():
        for ligne in _git(chemin, "ls-tree", "-r", "HEAD", "--name-only").splitlines():
            f = ligne.strip()
            if f:
                union_chemins.add(f)
                union_bases.add(os.path.basename(f))

    surv = {}
    for d in ok.values():
        for m, x in d.get("naissances_par_mois", {}).items():
            cell = surv.setdefault(m, [0, 0, 0])
            cell[0] += x["nes"]
            cell[1] += x["survivants"]
        for f, info in d.get("morts_locaux", {}).items():
            if f in union_chemins or os.path.basename(f) in union_bases:
                surv.setdefault(info["mois"], [0, 0, 0])[2] += 1
    res["total"]["survie_par_mois"] = dict(
        (m, {"nes": v[0], "sur_place": v[1], "migres": v[2],
             "morts_reels": v[0] - v[1] - v[2]})
        for m, v in sorted(surv.items()))

    # On ne garde que les disparitions REELLES : ni sur place, ni ailleurs.
    for d in ok.values():
        perdus = [dict(info, chemin=f) for f, info in d.get("morts_locaux", {}).items()
                  if f not in union_chemins and os.path.basename(f) not in union_bases]
        perdus.sort(key=lambda x: -x["churn"])
        d["morts_reelles_n"] = len(perdus)
        d["morts_reelles"] = perdus[:80]
        d.pop("morts_locaux", None)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)

    for m, n in t["par_mois"].items():
        ne, sv, mi = surv.get(m, [0, 0, 0])
        pct = ("%.0f%%" % (100.0 * (sv + mi) / ne)) if ne else "-"
        print("  %s : %5s commits | %5s nes | %5s sur place | %5s migres | %5s morts (vit: %s)"
              % (m, n, ne, sv, mi, ne - sv - mi, pct))
    if t["depots_refuses"]:
        print("[census] REFUSES sous le compte %s : %s"
              % (t["compte"], ", ".join(sorted(t["depots_refuses"]))))
    if t["depots_ko"]:
        print("[census] INACCESSIBLES : %s" % (t["depots_ko"],))
    print("[census] faux departs (ne+mort en <=14j) : %s" % t["faux_departs"])
    couteux = []
    for nom, d in ok.items():
        for x in d.get("morts_reelles", []):
            couteux.append((x["churn"], nom, x["chemin"], x["ne"], x["mort"],
                            x.get("motif", "")))
    couteux.sort(reverse=True)
    hs_total = sum(d.get("hors_suivi_n", 0) for d in ok.values())
    if hs_total:
        print("[census] code VIVANT hors suivi git : %s fichiers" % hs_total)
        for nom, d in sorted(ok.items(), key=lambda kv: -kv[1].get("hors_suivi_n", 0)):
            if d.get("hors_suivi_n"):
                print("    %-20s %5s  %s" % (nom, d["hors_suivi_n"],
                                             d.get("hors_suivi_racines")))
    print("[census] capacites perdues les plus couteuses (churn = reprises) :")
    for c, nom, f, ne, mo, motif in couteux[:20]:
        print("  %3sx  %s:%s  (%s -> %s)" % (c, nom, f, ne, mo))
        if motif:
            print("        motif : %s" % motif)
    print("[census] ecrit : %s" % os.path.relpath(a.out, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
