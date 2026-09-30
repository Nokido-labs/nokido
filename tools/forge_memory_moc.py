#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_memory_moc.py — l'index chaud devient un ROUTEUR, pas un annuaire.

Constat du compacteur lui-meme, imprime a chaque session : « CIBLE NON ATTEINTE
(21.2KB > 17.0KB) au plancher de 2 jours : l'index demande une revue editoriale,
pas davantage de compaction. » Il a raison, et aucune compaction supplementaire
n'y changera rien : adresser 776 fiches — bientot des milliers — depuis une
racine UNIQUE sous cap de 17 Ko est arithmetiquement intenable.

## Ce que ce module fait, et ce qu'il ne refait pas

Il ne reimplemente NI le decoupage, NI la datation, NI l'archivage : tout cela
vit dans `forge_memory_compactor` et y est deja eprouve (`_segments` sait ne pas
couper un libelle contenant « · », piege paye le 2026-08-10). Ce module ajoute
UNE chose : la REPARTITION de l'index chaud en cartes thematiques, et la
reecriture de `MEMORY.md` en routeur vers ces cartes.

    MEMORY.md            etat courant + pointeurs vers les cartes  (charge tjrs)
    index_<theme>.md     les entrees de ce theme                    (ouvert au besoin)
    MEMORY_ARCHIVE.md    froid, deja gere par le compacteur         (jamais charge)

## L'invariant qui rend l'operation sure

**Aucune entree ne disparait.** Le nombre de liens `](x.md)` presents avant doit
se retrouver EXACTEMENT, reparti entre le routeur et les cartes. Si le compte ne
tombe pas juste, on n'ecrit RIEN et on le dit. C'est le seul garde qui compte
ici : une reecriture d'index qui perd une ligne fait disparaitre une memoire de
la traversee statique, silencieusement.

Le filet de second niveau existe deja : `forge_memory_ledger.sync()` est appele
AVANT toute ecriture, donc chaque version d'avant reste recuperable.

## Et l'adressabilite semantique

Elle n'est plus une promesse : les fiches ET les index sont ingeres en RAG par
`tools/forge_memory_ingest.py`, avec un chemin VOLATIL qui remplace au lieu
d'empiler. Une entree sortie du routeur reste donc joignable de deux facons —
par sa carte (traversee statique) et par la recherche (lexicale, puis
vectorielle quand la chaine d'embedding aura tourne).

Usage :
    LAFORGE_PYTHON tools/forge_memory_moc.py                # dry-run, montre la repartition
    LAFORGE_PYTHON tools/forge_memory_moc.py --appliquer
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/hippocampe"

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.tools.forge_memory_compactor import _LIEN, _date_entree, _date_libelle, _segments  # noqa: E402

# Fenetre CHAUDE : une entree plus recente que N jours reste dans le routeur.
# C'est la rotation demandee — l'index chaud porte l'etat courant, les cartes
# portent le fond. Trois jours et non deux : le plancher du compacteur vaut 2,
# et une fenetre EGALE au plancher ferait sortir du routeur, des le lendemain,
# ce que le compacteur refuse encore d'archiver.
CHAUD_JOURS = 3

# Le dossier memoire vit DANS le depot depuis la jonction du 2026-09-04
# (`tools/forge_memory_junction.py`). C'est le seul chemin lisible par tous les
# comptes : celui du compacteur passe par `expanduser("~")`, or le compte
# sandbox a `HOME=C:\\Users\\Default` — il y trouve un dossier ABSENT et non le
# dossier de l'owner (gotcha_run_job_home_default_vs_launcher).
_DEFAULT_DIR = ROOT / "memory"

# --- Les cartes -------------------------------------------------------------
# L'ordre COMPTE : la premiere carte dont le motif accroche une entree la prend.
# Les motifs portent sur le NOM DE FICHIER cible, jamais sur la prose du libelle
# — un theme devine depuis une phrase est une etiquette inventee, et une
# etiquette inventee se propage (le filet « deviner l'organe depuis la
# docstring » a ete essaye puis RETIRE le 2026-07-25 pour cette raison).
CARTES = (
    (
        "index_directives_owner",
        "Consignes et arbitrages de l'owner",
        "Ce que l'owner a demande ou tranche. Intemporel : ne part jamais au froid.",
        re.compile(r"\]\((feedback_|decision_|politique_|loi_|doctrine_|vision_)"),
    ),
    (
        "index_gotchas_execution",
        "Pieges d'execution mesures",
        "Un echec paye, suivi de la forme qui marche. A lire avant de conclure "
        "qu'une capacite manque.",
        re.compile(r"\]\((gotcha_)"),
    ),
    (
        "index_reference",
        "Pointeurs externes et ressources",
        "Ce qui vit hors du depot : services, URLs, comptes, materiel.",
        re.compile(r"\]\((reference_)"),
    ),
    (
        "index_mesures_et_incidents",
        "Mesures, incidents et diagnostics",
        "Constats dates. Se perime — verifier la date avant de s'en servir.",
        # Attrape-tout, en DERNIER. La classe de caracteres est celle de `_LIEN`
        # et PAS une version simplifiee : ecrire `[a-z0-9_]+` laissait tomber
        # tout nom portant un tiret — c'est-a-dire toute fiche datee
        # (`..._2026-09-04.md`). Mesure : 17 entrees sur 68 s'evaporaient, et
        # seul l'invariant de conservation l'a dit.
        re.compile(r"\]\([A-Za-z0-9_.-]+\.md\)"),
    ),
)

_ENTETE_ROUTEUR = """<!-- Index CHAUD : etat courant + routage. Genere par tools/forge_memory_moc.py.
     Les entrees detaillees vivent dans les cartes listees en fin de fichier ;
     elles restent joignables par recherche (rag_chunks_fts, source memory:*). -->
"""


def _entete_carte(nom: str, titre: str, quoi: str) -> str:
    return (
        "---\n"
        "name: %s\n"
        'description: "%s"\n'
        "metadata:\n"
        "  node_type: memory\n"
        "  type: reference\n"
        "---\n\n"
        "# %s\n\n%s\n\n" % (nom.replace("_", "-"), quoi.replace('"', "'"), titre, quoi)
    )


def repartir(memory_dir: Path = _DEFAULT_DIR, chaud_jours: int = CHAUD_JOURS) -> dict:
    """Calcule la repartition SANS rien ecrire. Rend le plan et son controle."""
    import datetime

    cutoff = (datetime.date.today() - datetime.timedelta(days=chaud_jours)).isoformat()
    memory_dir = Path(memory_dir)
    mem = memory_dir / "MEMORY.md"
    try:
        brut = mem.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"NO_VERDICT": "%s absent" % mem}
    except OSError as exc:
        # Ni « vide » ni « absent » : illisible. Un dossier hors ACL rend
        # exactement ce type d'erreur, et le lire comme « rien a faire »
        # fabriquerait un succes sur une mesure jamais prise.
        return {"NO_VERDICT": "%s illisible (%s)" % (mem, type(exc).__name__)}
    lignes = brut.splitlines()

    entrees_avant = sum(len(_LIEN.findall(l)) for l in lignes)
    par_carte: dict = {c[0]: [] for c in CARTES}
    routeur: list = []
    chaudes: list = []

    for ligne in lignes:
        if not (ligne.lstrip().startswith("- ") and _LIEN.search(ligne)):
            routeur.append(ligne)  # preambule, titres, lignes sans lien : intactes
            continue
        tete, sep, corps = ligne.partition(" : ")
        # Une ligne « - **Theme** : a · b » se ventile segment par segment ; une
        # ligne « - [x](x.md) ... » n'a pas de tete thematique et part entiere.
        segments = _segments(corps) if sep and corps.strip() else [ligne]
        contexte = ""
        if sep:
            # La TETE peut elle-meme porter un lien (« - **X** -> [index](i.md) : a · b »).
            # La recopier devant chaque segment DUPLIQUE ce lien autant de fois
            # qu'il y a de segments — mesure : 68 entrees devenaient 71, et seul
            # l'invariant de conservation l'a dit. La tete part donc comme UNE
            # entree a part entiere, et ne sert ensuite que de contexte TEXTUEL.
            if _LIEN.search(tete):
                t = tete.lstrip("- ").strip()
                if _date_entree(t) >= cutoff and _date_entree(t):
                    chaudes.append("- %s" % t)
                else:
                    for nom, _titre, _quoi, motif in CARTES:
                        if motif.search(t):
                            par_carte[nom].append("- %s" % t)
                            break
            contexte = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", tete).lstrip("- ").strip()
        d_tete = _date_libelle(tete) if sep else ""
        for seg in segments:
            s = seg.strip()
            if not s or not _LIEN.search(s):
                continue
            entree = "- %s%s" % (contexte + " — " if contexte else "", s)
            # La date la plus RECENTE portee par l'entree (libelle, nom de
            # fichier, ligne-theme) : une memoire re-touchee aujourd'hui n'est
            # pas ancienne, meme si son fichier date de juin.
            d = _date_entree(s, d_tete)
            if d and d >= cutoff:
                chaudes.append(entree)
                continue
            for nom, _titre, _quoi, motif in CARTES:
                if motif.search(s):
                    par_carte[nom].append(entree)
                    break

    entrees_apres = sum(len(_LIEN.findall(l)) for l in routeur)
    entrees_apres += sum(len(_LIEN.findall(e)) for e in chaudes)
    entrees_apres += sum(len(_LIEN.findall(e)) for v in par_carte.values() for e in v)

    return {
        "entrees_avant": entrees_avant,
        "entrees_apres": entrees_apres,
        "conserve": entrees_avant == entrees_apres,
        "routeur_lignes": routeur,
        "chaudes": chaudes,
        "cartes": par_carte,
        "cutoff_chaud": cutoff,
        "taille_avant_ko": round(len(brut.encode("utf-8")) / 1024, 1),
    }


def appliquer(memory_dir: Path = _DEFAULT_DIR, dry_run: bool = True,
              chaud_jours: int = CHAUD_JOURS) -> dict:
    memory_dir = Path(memory_dir)
    plan = repartir(memory_dir, chaud_jours)
    if "NO_VERDICT" in plan:
        return plan

    if not plan["conserve"]:
        # On ne « repare » pas un ecart en le tolerant : une entree perdue ici
        # sort de la traversee statique sans que rien ne le signale.
        return {
            "ARRET": "repartition NON conservatrice : %d entrees avant, %d apres. "
                     "Rien ecrit." % (plan["entrees_avant"], plan["entrees_apres"]),
        }

    # Le routeur : l'existant, moins les entrees parties en carte, plus l'index
    # des cartes. Les lignes sans lien (preambule, titres) sont conservees telles.
    lignes = list(plan["routeur_lignes"])
    while lignes and not lignes[-1].strip():
        lignes.pop()
    if plan["chaudes"]:
        lignes.append("")
        lignes.append("## Chaud — appris depuis le %s" % plan["cutoff_chaud"])
        lignes.append("")
        lignes.extend(plan["chaudes"])
    lignes.append("")
    lignes.append("## Cartes — ouvrir celle du domaine avant d'affirmer une absence")
    lignes.append("")
    for nom, titre, quoi, _m in CARTES:
        n = len(plan["cartes"][nom])
        if not n:
            continue
        lignes.append("- **[%s](%s.md)** — %d entrees. %s" % (titre, nom, n, quoi))
    lignes.append("")
    lignes.append("_Une entree absente d'ici n'est pas perdue : elle vit dans sa carte, "
                  "et reste retrouvable par recherche (`source GLOB 'memory:*'`)._")
    routeur_txt = "\n".join(lignes).rstrip() + "\n"

    res = {
        "entrees": plan["entrees_avant"],
        "chaudes_gardees": len(plan["chaudes"]),
        "cutoff_chaud": plan["cutoff_chaud"],
        "taille_avant_ko": plan["taille_avant_ko"],
        "taille_apres_ko": round(len((_ENTETE_ROUTEUR + routeur_txt).encode("utf-8")) / 1024, 1),
        "cartes": {n: len(v) for n, v in plan["cartes"].items() if v},
        "dry_run": dry_run,
    }
    if dry_run:
        res["apercu_routeur"] = routeur_txt[-700:]
        return res

    try:  # filet : chaque version d'avant reste dans la chaine
        from nokido_agent.tools import forge_memory_ledger as _ml

        _ml.sync(memory_dir)
    except Exception as exc:
        return {"ARRET": "ledger indisponible (%s) — rien reecrit" % type(exc).__name__}

    ecrits = []
    for nom, titre, quoi, _m in CARTES:
        entrees = plan["cartes"][nom]
        if not entrees:
            continue
        texte = _entete_carte(nom, titre, quoi) + "\n".join(entrees) + "\n"
        (memory_dir / ("%s.md" % nom)).write_text(texte, encoding="utf-8")
        ecrits.append(nom)
    (memory_dir / "MEMORY.md").write_text(_ENTETE_ROUTEUR + routeur_txt, encoding="utf-8")
    res["cartes_ecrites"] = ecrits
    res["suite"] = ("reingerer pour que les cartes soient servies en lexical : "
                    "LAFORGE_PYTHON tools/forge_memory_ingest.py --appliquer")
    return res


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # muet-ok : confort d'affichage, sans effet sur le resultat
        pass
    p = argparse.ArgumentParser(description="Repartit l'index chaud en cartes thematiques")
    p.add_argument("--memory-dir", default=str(_DEFAULT_DIR))
    p.add_argument("--appliquer", action="store_true", help="ecrit reellement (defaut : dry-run)")
    p.add_argument("--chaud-jours", type=int, default=CHAUD_JOURS,
                   help="fenetre gardee dans le routeur (defaut : %d)" % CHAUD_JOURS)
    a = p.parse_args(argv)
    import json

    print(json.dumps(appliquer(Path(a.memory_dir), dry_run=not a.appliquer,
                               chaud_jours=a.chaud_jours),
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
