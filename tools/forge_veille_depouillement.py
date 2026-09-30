"""Suivi du DEPOUILLEMENT de la moisson de veille -- ce qu'il reste a lire.

DEFAUT QU'IL CORRIGE. `forge_veille_moisson.py --par-depot` produit un artefact de
2,5 Mo couvrant 190 depots et 3 256 pages, declare "relisible sans recalcul". Mais
aucun outil ne disait LEQUEL avait deja ete lu : huit depots en ont ete tires, et
toute reprise recommencait en tete de fichier. Meme famille que les depots ignores
qui revenaient en tete de chaque lot avant qu'on les memorise -- un ordre stable
sans memoire des traites fait pietiner.

COMMENT IL SAIT. Un depot est DEPOUILLE si son identifiant `proprietaire/nom` est
cite dans la roadmap de veille. C'est une preuve d'usage, pas une declaration : on
ne coche pas une case, on constate que le depot a produit une ligne.

PORTEE DECLAREE, PAS DEPASSEE. Cet outil ne suit QUE les depots. Les pages sont
citees bibliographiquement (`arXiv 2507.03608`, un DOI, un billet) et non par un
identifiant : leur appliquer la meme regle fabriquerait un taux faux. Le nombre de
pages NON suivies est rendu a chaque appel, pour que la portee reste visible.

Un artefact ou une roadmap illisible rend `ILLISIBLE`, jamais "0 restant" : lire un
refus d'acces comme un corpus epuise ferait conclure a une couverture complete.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

__FORGE_COLOR__ = "cognition/veille : suivi du depouillement de la moisson"

RACINE = Path(__file__).resolve().parent.parent
ARTEFACT = RACINE / "sandbox" / "veille_par_depot.json"
ROADMAP = RACINE / "docs" / "roadmap_ameliorations_veille.md"
LUS = RACINE / "sandbox" / "veille_depouillement_lus.json"


def _lire_notes(lus):
    """(notes, illisible). Un fichier corrompu lu comme VIDE represenerait tout le
    corpus en silence : l'illisibilite est rendue, jamais avalee."""
    if not lus:
        return {}, False
    p = Path(lus)
    if not p.exists():
        return {}, False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - l'illisibilite est une reponse
        return {}, True
    if not isinstance(d, dict):
        return {}, True
    return d, False


def noter(ids, lus, verdict: str = "LU_RIEN_DANS_ECHANTILLON", vus=None) -> int:
    """Memorise des depots LUS. Idempotent : une relecture ne redate pas la note.

    SANS CETTE MEMOIRE, un depot lu dont on n'a RIEN tire est indistinguable d'un
    depot jamais lu -- il revient en tete de chaque lot pour toujours. C'est le
    defaut deja paye cote ingestion, et cet outil le reproduirait sans ce filet.

    LE NOM DU VERDICT DIT SA PORTEE, et c'est tout l'enjeu. Le jugement porte sur
    l'ECHANTILLON MONTRE -- 3 extraits par depot, la borne de la moisson -- pas sur
    le depot. `Shubhamsaboo/awesome-llm-apps` a 2 109 documents structurants NON
    MONTRES : ecrire "sans signal" sur 3 documents lus sur 2 112, ce serait
    transformer "je n'ai pas vu" en "il n'y a rien". D'ou `LU_RIEN_DANS_ECHANTILLON`,
    et le champ `non_montres` qui conserve la taille de ce qu'on n'a PAS regarde.

    Tout verdict prefixe `LU_` exclut du prochain lot. Le suffixe `_AGENT` attribue
    le jugement a un agent local : c'est une proposition, renversable.
    """
    p = Path(lus)
    d, _ill = _lire_notes(p)
    vus = vus or {}
    for i in ids:
        if i not in d:
            d[i] = {"verdict": verdict, "ts": time.time(),
                    "non_montres": vus.get(i)}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(d)


_ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)
_DOI = re.compile(r"doi\.org/(10\.[^\s?#]+)", re.I)
_OPENREVIEW = re.compile(r"openreview\.net/forum\?id=([A-Za-z0-9_-]+)", re.I)


def id_page(url: str) -> str:
    """Identifiant CANONIQUE d'une page, et non son URL.

    Une meme reference se cite de plusieurs manieres -- `https://arxiv.org/abs/X`,
    `arxiv.org/pdf/Xv2`, ou simplement `arXiv X` dans une entree de roadmap. Comparer
    des URL brutes declarerait non lues des pages deja depouillees : c'est le defaut
    paye cote depots avec `sigoden/aichat`, cite sous nom court et compte restant.

    A defaut d'identifiant connu, l'URL fait foi -- et la forme de la valeur le DIT
    (`url:`), pour qu'on ne prenne jamais un pis-aller pour une identite.
    """
    u = (url or "").strip()
    m = _ARXIV.search(u)
    if m:
        return "arxiv:" + m.group(1)
    m = _DOI.search(u)
    if m:
        return "doi:" + m.group(1)
    m = _OPENREVIEW.search(u)
    if m:
        return "openreview:" + m.group(1)
    return "url:" + u


_FAM_DOC = re.compile(r"https?://([^/]+)/(docs/[^/?#]+)", re.I)
_FAM_DEPOT = re.compile(r"https?://(github\.com|gitlab\.com)/([^/?#]+/[^/?#]+)", re.I)


def famille_page(url: str) -> str:
    """La FAMILLE d'une page, quand la page n'est pas la bonne unite.

    MESURE DU 2026-09-12 : sur 922 pages `huggingface.co`, **839 soit 91 %**
    sont de la documentation de bibliotheque crawlee page par page — `docs/hub`
    124, `docs/huggingface.js` 82, `docs/accelerate` 59, `docs/datasets` 59...
    Un lot de 22 y tire 18 pages de la MEME bibliotheque, dont les extraits ne
    montrent que le menu de navigation, identique d'une page a l'autre. Juger
    page par page demande 38 lots pour l'information que ~25 verdicts par
    bibliotheque donneraient.

    La famille n'AUTORISE AUCUNE SUPPRESSION : elle donne une unite de lecture.
    Une famille jugee interessante se redepouille page par page.

    Hors motif connu, l'hote fait foi — et le rendre tel quel le DIT, plutot que
    d'inventer un regroupement qui n'existe pas.
    """
    u = (url or "").strip()
    if not u:
        return "INCONNU"
    m = _FAM_DEPOT.search(u)
    if m:
        return "%s/%s" % (m.group(1).lower(), m.group(2))
    m = _FAM_DOC.search(u)
    if m:
        return "%s/%s" % (m.group(1).lower(), m.group(2))
    m = re.search(r"https?://([^/?#]+)", u)
    return m.group(1).lower() if m else "INCONNU"


def familles(urls, echantillon: int = 3) -> list[dict]:
    """Regroupe des pages par famille, la plus VOLUMINEUSE d'abord.

    Le compte est rendu avec l'echantillon : un regroupement qui ne dit pas
    COMBIEN il couvre ne permet pas de juger une famille sans la lire en entier.
    """
    par = {}
    for u in urls:
        par.setdefault(famille_page(u), []).append(u)
    out = [{"famille": f, "n": len(v), "echantillon": sorted(v)[:echantillon]}
           for f, v in par.items()]
    out.sort(key=lambda x: (-x["n"], x["famille"]))
    return out


def etat_pages(artefact=ARTEFACT, roadmap=ROADMAP, lus=None) -> dict:
    """Meme contrat que `etat`, applique aux PAGES, avec ventilation par hote.

    329 hotes : sans la ventilation, un taux global ne dit pas si l'on a lu de la
    recherche relue ou des billets, ce qui est precisement la question posee en T.
    """
    notes, notes_ill = _lire_notes(lus)
    data, texte, motif = _charger(artefact, roadmap)
    if data is None:
        return {"etat": "ILLISIBLE", "motif": motif, "total": None,
                "depouillees": [], "lues_sans_rien": [], "restantes": [],
                "restantes_par_hote": {}, "notes_illisibles": notes_ill}
    pages = data.get("pages") or {}
    bas = texte.lower()
    cites, sans, reste = [], [], []
    for url in sorted(pages):
        ident = id_page(url)
        aiguille = ident.split(":", 1)[1].lower()
        if aiguille and (aiguille in bas or url.lower() in bas):
            cites.append(url)
        # ⚠️ La note se cherche sur l'IDENTIFIANT CANONIQUE, pas sur l'URL brute.
        # Correctif du 2026-09-12 : `ident` etait calcule juste au-dessus et
        # IGNORE ici au profit de `url`. Or `noter()` memorise ce que le lot
        # AFFICHE, c'est-a-dire l'identifiant (`arxiv:2605.00820`), pendant que
        # `pages` est indexe par URL (`http://arxiv.org/abs/2605.00820v1`). Deux
        # espaces d'identite compares l'un a l'autre : aucune note ne matchait,
        # donc 17 pages notees laissaient le compteur fige a 2904 jamais
        # ouvertes et la campagne ne pouvait pas converger. C'est exactement ce
        # que la docstring d'`id_page` annonce deux fonctions plus haut.
        # L'URL reste acceptee en second recours : d'anciennes notes ont pu etre
        # posees sous cette forme, et les perdre reouvrirait du travail fait.
        elif str(((notes.get(ident) or notes.get(url)) or {}).get("verdict") or "").startswith(
                ("LU_", "SANS_SIGNAL")):
            sans.append(url)
        else:
            reste.append(url)
    return {
        "etat": "LU", "motif": "", "total": len(pages),
        "depouillees": cites, "lues_sans_rien": sans, "restantes": reste,
        "restantes_par_hote": dict(Counter((pages[u] or {}).get("hote") or "INCONNU"
                                           for u in reste).most_common()),
        "notes_illisibles": notes_ill,
    }


def lot_pages(artefact=ARTEFACT, roadmap=ROADMAP, taille: int = 40,
              decalage: int = 0, lus=None, hotes=None) -> dict:
    """Le prochain lot de pages non citees, filtrable par HOTE.

    3 245 pages jamais ouvertes sur 329 hotes : les prendre dans l'ordre des URL
    revient a lire au hasard. Le filtre permet d'attaquer par valeur -- les hotes de
    recherche d'abord. Un filtre qui ecarte des donnees le DIT : `restantes_filtrees`
    est rendu a cote des restantes GLOBALES, faute de quoi un filtre etroit se lirait
    comme un corpus epuise.
    """
    e = etat_pages(artefact, roadmap, lus=lus)
    if e["etat"] == "ILLISIBLE":
        return {**e, "lot": [], "decalage": decalage, "restantes_filtrees": None,
                "filtre_hotes": hotes}
    data, _t, _m = _charger(artefact, roadmap)
    pages = (data or {}).get("pages") or {}
    retenues = e["restantes"]
    if hotes:
        vises = {h.strip().lower() for h in hotes if h and h.strip()}
        retenues = [u for u in retenues
                    if str((pages.get(u) or {}).get("hote") or "").lower() in vises]
    choisies = retenues[decalage:decalage + taille]
    e = {**e, "restantes_filtrees": len(retenues), "filtre_hotes": list(hotes or [])}
    return {**e, "decalage": decalage, "lot": [{
        "url": u, "id": id_page(u),
        "hote": (pages.get(u) or {}).get("hote") or "INCONNU",
        "texte": (pages.get(u) or {}).get("texte") or "",
    } for u in choisies]}


def rendre_markdown_pages(r: dict, extrait_max: int = 700) -> str:
    lignes = [
        "# Lot de depouillement — PAGES non encore citees dans la roadmap", "",
        "%s pages au total, %s citees, %s lues sans rien, %s jamais ouvertes ; "
        "lot de %d a partir du decalage %d."
        % (r.get("total"), len(r.get("depouillees") or []),
           len(r.get("lues_sans_rien") or []), len(r.get("restantes") or []),
           len(r.get("lot") or []), r.get("decalage", 0)), "",
        "Restantes par hote : " + ", ".join(
            "%s=%d" % (h, n) for h, n in list((r.get("restantes_par_hote") or {}).items())[:20]),
        "",
    ]
    for p in r.get("lot") or []:
        t = (p.get("texte") or "").replace("\n", " ")
        coupe = len(t) - extrait_max
        lignes.append("## %s" % p["id"])
        lignes.append("- `%s` (%s)" % (p["url"], p["hote"]))
        lignes.append("  > %s%s" % (t[:extrait_max],
                                    " […%d caracteres non montres]" % coupe
                                    if coupe > 0 else ""))
        lignes.append("")
    return "\n".join(lignes)


def _charger(artefact, roadmap):
    try:
        data = json.loads(Path(artefact).read_text(encoding="utf-8"))
        texte = Path(roadmap).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - l'illisibilite est une reponse
        return None, None, "%s: %s" % (type(exc).__name__, exc)
    return data, texte, ""


def etat(artefact=ARTEFACT, roadmap=ROADMAP, lus=None) -> dict:
    """total / depouilles / sans_signal / restants, plus les pages non suivies.

    TROIS etats et non deux : un depot CITE a produit une ligne, un depot
    SANS_SIGNAL a ete lu pour rien, un RESTANT n'a jamais ete ouvert. Les fondre
    ferait croire le corpus plus fecond -- ou plus vaste -- qu'il n'est.
    """
    notes, notes_ill = _lire_notes(lus)
    data, texte, motif = _charger(artefact, roadmap)
    if data is None:
        return {"etat": "ILLISIBLE", "motif": motif, "total": None,
                "depouilles": [], "sans_signal": [], "restants": [],
                "pages_non_suivies": None, "notes_illisibles": notes_ill}
    depots = data.get("depots") or {}
    bas = texte.lower()
    ids = sorted(depots)
    cites = [i for i in ids if i.lower() in bas]
    # Tout verdict prefixe `LU_` exclut du prochain lot ; le suffixe `_AGENT` dit QUI
    # a juge. Un verdict d'agent est une proposition, pas une cloture : on doit
    # pouvoir le retrouver et le renverser sans redepouiller le corpus.
    # `SANS_SIGNAL` est l'ancien nom, conserve pour les notes deja ecrites -- il
    # affirmait plus que la mesure ne permet (cf. docstring de `noter`).
    sans = [i for i in ids
            if i not in cites
            and str((notes.get(i) or {}).get("verdict") or "").startswith(
                ("LU_", "SANS_SIGNAL"))]
    return {
        "etat": "LU", "motif": "", "total": len(ids),
        "depouilles": cites, "sans_signal": sans,
        "restants": [i for i in ids if i not in cites and i not in sans],
        "pages_non_suivies": len(data.get("pages") or {}),
        "notes_illisibles": notes_ill,
    }


def lot(artefact=ARTEFACT, roadmap=ROADMAP, taille: int = 20,
        decalage: int = 0, lus=None) -> dict:
    """Le prochain lot de depots NON depouilles, extraits compris.

    L'ordre est stable (tri sur l'identifiant) : c'est ce qui rend `decalage`
    utilisable sans recouvrement d'un appel a l'autre.
    """
    e = etat(artefact, roadmap, lus=lus)
    if e["etat"] == "ILLISIBLE":
        return {**e, "lot": [], "decalage": decalage}
    data, _texte, _m = _charger(artefact, roadmap)
    depots = (data or {}).get("depots") or {}
    choisis = e["restants"][decalage:decalage + taille]
    return {**e, "decalage": decalage, "lot": [{
        "id": i,
        "ecartes": (depots.get(i) or {}).get("ecartes", 0),
        "extraits": (depots.get(i) or {}).get("extraits", []),
    } for i in choisis]}


def rendre_markdown(r: dict, extrait_max: int = 700) -> str:
    lignes = [
        "# Lot de depouillement — depots non encore cites dans la roadmap", "",
        "%s depots au total, %s depouilles, %s restants ; lot de %d a partir du "
        "decalage %d." % (r.get("total"), len(r.get("depouilles") or []),
                          len(r.get("restants") or []), len(r.get("lot") or []),
                          r.get("decalage", 0)),
        "", "Pages NON suivies par cet outil : %s (portee declaree)."
        % r.get("pages_non_suivies"), "",
    ]
    for d in r.get("lot") or []:
        lignes.append("## %s" % d["id"])
        if d.get("ecartes"):
            lignes.append("_%d autre(s) document(s) structurant(s) non montre(s)._"
                          % d["ecartes"])
        for e in d.get("extraits") or []:
            t = (e.get("texte") or "").replace("\n", " ")
            coupe = len(t) - extrait_max
            lignes.append("- `%s`" % e.get("source"))
            lignes.append("  > %s%s" % (t[:extrait_max],
                                        " […%d caracteres non montres]" % coupe
                                        if coupe > 0 else ""))
        lignes.append("")
    return "\n".join(lignes)


def main() -> int:
    ap = argparse.ArgumentParser(prog="forge_veille_depouillement")
    ap.add_argument("--artefact", default=str(ARTEFACT))
    ap.add_argument("--roadmap", default=str(ROADMAP))
    ap.add_argument("--taille", type=int, default=20)
    ap.add_argument("--decalage", type=int, default=0)
    ap.add_argument("--lus", default=str(LUS),
                    help="memoire des depots LUS (pour qu'un lu sans signal ne revienne pas)")
    ap.add_argument("--noter-sans-signal", default="",
                    help="identifiants separes par des virgules : LUS, rien dans "
                         "l'echantillon montre (ce n'est PAS un jugement sur le depot)")
    ap.add_argument("--sortie", default="sandbox/veille_depouillement_lot.md")
    ap.add_argument("--extrait-max", type=int, default=700,
                    help="borne PAR EXTRAIT ; ce qui est coupe est compte et dit")
    ap.add_argument("--pages", action="store_true",
                    help="suit les PAGES (identite bibliographique) au lieu des depots")
    ap.add_argument("--hote", default="",
                    help="hotes vises, separes par des virgules (pages seulement)")
    ap.add_argument("--familles", action="store_true",
                    help="groupe les pages restantes par FAMILLE (bibliotheque de "
                         "doc, depot) au lieu de les lister une par une")
    a = ap.parse_args()

    # ⚠️ LA NOTATION PASSE AVANT L'AIGUILLAGE DE MODE, et c'est le correctif du
    # 2026-09-12. Elle vivait APRES le bloc `if a.pages:`, qui se termine par un
    # `return 0` : `--noter-sans-signal` etait donc INATTEIGNABLE en mode pages,
    # et rien ne le disait. Mesure : 17 pages notees, compteurs inchanges (250
    # lues sans rien avant, 250 apres). Consequence, pire que la perte des notes
    # elle-meme : chaque lot re-presentait les memes pages, donc la campagne ne
    # pouvait pas converger. Meme famille qu'un parametre avale en silence.
    if a.noter_sans_signal.strip():
        ids = [x.strip() for x in a.noter_sans_signal.split(",") if x.strip()]
        n = noter(ids, a.lus, verdict="LU_RIEN_DANS_ECHANTILLON")
        print("[depouillement] %d %s notes LU_RIEN_DANS_ECHANTILLON, %d au "
              "total (rien n'est supprime : le verdict porte sur les extraits "
              "MONTRES, pas sur la source)"
              % (len(ids), "page(s)" if a.pages else "depot(s)", n), flush=True)

    if a.pages and a.familles:
        hotes = [x.strip() for x in a.hote.split(",") if x.strip()]
        e = etat_pages(a.artefact, a.roadmap, lus=a.lus)
        if e["etat"] == "ILLISIBLE":
            print("[depouillement] ILLISIBLE -- %s" % e["motif"], flush=True)
            return 1
        reste = e["restantes"]
        if hotes:
            reste = [u for u in reste if any(h in u for h in hotes)]
        fams = familles(reste)
        couvert = sum(f["n"] for f in fams)
        print("[depouillement] %d page(s) restantes -> %d famille(s) ; "
              "la page n'est pas toujours la bonne unite de lecture"
              % (couvert, len(fams)), flush=True)
        cumul = 0
        for i, f in enumerate(fams[:a.taille or 40], 1):
            cumul += f["n"]
            print("  %3d. %-46s %4d page(s)  (cumul %d/%d = %.1f %%)"
                  % (i, f["famille"], f["n"], cumul, couvert, 100 * cumul / couvert),
                  flush=True)
            for u in f["echantillon"]:
                print("        %s" % u[:150], flush=True)
        if len(fams) > (a.taille or 40):
            montrees = sum(f["n"] for f in fams[:a.taille or 40])
            print("  [borne] %d famille(s) montrees sur %d ; %d page(s) non "
                  "affichees, elles ne sont PAS ecartees"
                  % (a.taille or 40, len(fams), couvert - montrees), flush=True)
        return 0

    if a.pages:
        hotes = [x.strip() for x in a.hote.split(",") if x.strip()]
        rp = lot_pages(a.artefact, a.roadmap, taille=a.taille, decalage=a.decalage,
                       lus=a.lus, hotes=hotes or None)
        if rp["etat"] == "ILLISIBLE":
            print("[depouillement] ILLISIBLE -- %s" % rp["motif"], flush=True)
            return 1
        print("[depouillement] %d pages au total, %d citees, %d lues sans rien, "
              "%d jamais ouvertes" % (rp["total"], len(rp["depouillees"]),
                                      len(rp["lues_sans_rien"]), len(rp["restantes"])),
              flush=True)
        if hotes:
            print("[depouillement] filtre hotes=%s -> %d page(s) retenue(s) sur %d "
                  "jamais ouvertes" % (",".join(hotes), rp["restantes_filtrees"],
                                       len(rp["restantes"])), flush=True)
        Path(a.sortie).write_text(rendre_markdown_pages(rp, a.extrait_max),
                                  encoding="utf-8")
        print("[depouillement] lot de %d page(s) ecrit -> %s"
              % (len(rp["lot"]), a.sortie), flush=True)
        return 0

    r = lot(a.artefact, a.roadmap, taille=a.taille, decalage=a.decalage, lus=a.lus)
    if r["etat"] == "ILLISIBLE":
        print("[depouillement] ILLISIBLE -- %s" % r["motif"], flush=True)
        return 1
    if r.get("notes_illisibles"):
        print("[depouillement] ATTENTION : memoire des lus ILLISIBLE -- les depots "
              "deja lus vont etre represents", flush=True)

    print("[depouillement] %d depots au total, %d ont produit une entree, %d lus "
          "sans rien dans l'echantillon montre, %d jamais ouverts "
          "(+%s pages NON suivies par cet outil)"
          % (r["total"], len(r["depouilles"]), len(r["sans_signal"]),
             len(r["restants"]), r["pages_non_suivies"]), flush=True)
    Path(a.sortie).write_text(rendre_markdown(r, a.extrait_max), encoding="utf-8")
    print("[depouillement] lot de %d ecrit -> %s" % (len(r["lot"]), a.sortie),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
