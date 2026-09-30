"""Balayage MULTI-SURFACE avant toute affirmation d'absence.

Motif paye le 2026-09-03 : « aucune RFC ingeree », affirme TROIS fois, alors que
2 582 chunks etaient en base ET qu'un outil dedie (`audit_rfc_compliance`) rendait
36/36 en 150 ms. La recherche avait interroge UNE surface (le texte d'un seul des
deux index FTS) avec les mauvais termes (`ietf`, `datatracker` -- la convention
est `rfc:rfcNNNN`), puis conclu pour toutes les autres.

Ce depot repond souvent par un OUTIL, pas par un chunk. Une methode de retrieval
qui ne balaie pas la surface « outils » est structurellement borgne.

L'INVARIANT, et c'est tout l'objet du module :

    ABSENT n'est rendu QUE si toutes les surfaces sont LISIBLES et vides.
    Une seule surface illisible -> INDETERMINE, jamais ABSENT.

Trois etats par surface, jamais deux : `hits` (mesure), `vide` (mesure), ou
`illisible` (on n'a PAS pu regarder) avec sa raison. Un scanner qui repond
« rien trouve » alors qu'il n'a pas pu regarder se lit comme rassurant.

Usage :
    python tools/forge_retrieval_sweep.py rfc
    python tools/forge_retrieval_sweep.py "token bearer" --json
"""

__FORGE_COLOR__ = "cognition/retrieval-souverain"

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_CANDIDATS = [ROOT / "RAG" / "embeddings.db", Path("%NOKIDO_DATA%\embeddings.db")]
PLAFOND = 500
# Le comptage des sources DISTINCTES n'a pas la meme borne que l'echantillon : un
# ensemble de sources est borne par le nombre de fichiers, pas de chunks. Cette
# borne-ci n'existe que pour un terme pathologique, et le resultat dit quand elle
# mord (`distinctes_exactes: False`).
PLAFOND_SOURCES = 200_000


def _db():
    """Premiere base joignable, et la RAISON des autres.

    Le module refuse de conclure sur ce qu'il n'a pas lu : sa propre selection de
    base ne peut donc pas avaler ses echecs. Les raisons partent dans la surface
    illisible, ou elles seront affichees.
    """
    raisons = []
    for c in DB_CANDIDATS:
        try:
            if c.exists():
                return c
            raisons.append("%s: absent" % c)
        except OSError as e:
            raisons.append("%s: %s" % (c, type(e).__name__))
    _db.raisons = raisons
    return None


def _surface(nom, fn):
    """Enveloppe TOUTE surface : une exception devient `illisible`, pas `vide`."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - la raison est CONSERVEE, pas avalee
        return {"surface": nom, "etat": "illisible",
                "raison": "%s: %s" % (type(e).__name__, e)}


def _requete_fts(terme: str) -> str:
    """Le terme cherche est du TEXTE, pas une requete FTS5.

    Mesure 2026-09-12 : `balayer("forge-core")` rendait les DEUX index
    `illisible` — `OperationalError: no such column: core`. Le terme partait brut
    dans `MATCH ?`, donc FTS5 l'interpretait avec sa syntaxe (colonnes `x:`,
    operateurs `OR`/`NOT`, prefixes `*`, parentheses). Un tiret suffisait. Et les
    surfaces restantes portant des hits, le verdict global restait `PRESENT` : la
    panne des deux index principaux ne remontait nulle part.

    On quote donc chaque MOT separement, en doublant les guillemets internes.
    Pourquoi pas le terme entier : quoter d'un bloc ferait une PHRASE EXACTE, et
    « forge web » cesserait de trouver un document qui contient les deux mots
    separement. On echangerait un faux negatif contre un autre. Mot par mot,
    l'ET implicite de FTS5 est preserve.
    """
    mots = [m for m in (terme or "").split() if m]
    if not mots:
        return '""'
    return " ".join('"%s"' % m.replace('"', '""') for m in mots)


def _fts(terme):
    """Les DEUX index lexicaux, jamais un seul.

    `rag_fts` (agents) et `rag_chunks_fts` (moteur) ne portent pas le meme
    contenu -- mesure 2026-09-01 : `litellm` -> 84 980 vs 16 517. Interroger un
    seul et conclure pour les deux est un faux negatif garanti.
    """
    out = []
    db = _db()
    if db is None:
        return [{"surface": "fts", "etat": "illisible",
                 "raison": "aucune base d'embeddings joignable — %s"
                           % "; ".join(getattr(_db, "raisons", []) or ["?"])}]
    con = sqlite3.connect("file:%s?mode=ro" % str(db).replace("\\", "/"), uri=True)
    q = _requete_fts(terme)
    tables = {n for (n,) in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("rag_fts", "rag_chunks_fts"):
        if t not in tables:
            out.append({"surface": t, "etat": "illisible",
                        "raison": "table absente de %s" % db.name})
            continue
        try:
            n = len(list(con.execute(
                "SELECT rowid FROM %s WHERE %s MATCH ? LIMIT %d" % (t, t, PLAFOND),
                (q,))))
            # 2026-09-12 : le PLAFOND borne l'ECHANTILLON, il ne doit jamais
            # laisser le VOLUME inconnu. Mesure sur `ShinkaEvolve` : cette surface
            # affichait 500 pour 7747 chunks reels (x15,5), et un agent en a tire
            # une conclusion fausse sur la profondeur d'une ingestion. Un drapeau
            # `plafonne` dit qu'on ne sait pas ; il ne dispense pas d'aller savoir.
            # Un COUNT(*) sur un MATCH FTS5 est peu couteux : il n'y avait aucune
            # raison de s'en priver.
            total = con.execute(
                "SELECT COUNT(*) FROM %s WHERE %s MATCH ?" % (t, t), (q,)
            ).fetchone()[0]
        except sqlite3.Error as e:
            out.append({"surface": t, "etat": "illisible",
                        "raison": "%s: %s" % (type(e).__name__, e)})
            continue
        out.append({"surface": t, "etat": "hits" if total else "vide", "n": n,
                    "n_total": total,
                    # `total > PLAFOND`, pas `n >= PLAFOND` : un corpus qui compte
                    # EXACTEMENT le plafond n'est pas tronque, et se declarait
                    # tronque a tort.
                    "plafonne": total > PLAFOND})
    # La colonne `source` porte les CONVENTIONS de nommage (ex `rfc:rfc9110`) que
    # le texte ne contient pas. C'est elle qui manquait le 2026-09-03.
    if "rag_chunks_fts" in tables:
        try:
            # 2026-09-12 : cette branche appliquait le meme `LIMIT PLAFOND` que
            # les surfaces ci-dessus mais **ne posait aucun drapeau**, et derivait
            # `distinctes` de l'echantillon tronque. Elle affichait donc un nombre
            # de sources qui etait un PLANCHER presente comme un total, sans le
            # moindre marqueur — mesure reelle : 53 annoncees pour 301 existantes.
            # C'etait le defaut le plus couteux des deux : les autres surfaces
            # disaient au moins « (plafonne) », celle-ci tronquait EN SILENCE.
            #
            # Le comptage des sources se fait desormais SANS limite : un ensemble
            # de sources est borne par le nombre de FICHIERS, pas de chunks. Une
            # borne de securite reste posee pour un terme pathologique, et quand
            # elle mord le resultat le DIT au lieu de rendre un chiffre net.
            srcs = {}
            total = con.execute(
                "SELECT COUNT(*) FROM rag_chunks_fts WHERE rag_chunks_fts MATCH ?",
                ("source:%s" % q,)).fetchone()[0]
            lus = 0
            for (s,) in con.execute(
                    "SELECT source FROM rag_chunks_fts WHERE rag_chunks_fts "
                    "MATCH ? LIMIT %d" % PLAFOND_SOURCES, ("source:%s" % q,)):
                srcs[(s or "?")] = srcs.get((s or "?"), 0) + 1
                lus += 1
            exact = lus < PLAFOND_SOURCES
            out.append({"surface": "sources", "etat": "hits" if total else "vide",
                        "n": min(lus, PLAFOND), "n_total": total,
                        "plafonne": total > PLAFOND,
                        "distinctes": len(srcs),
                        # Un chiffre derive d'un echantillon se DECLARE comme tel.
                        "distinctes_exactes": exact,
                        "exemples": sorted(srcs, key=srcs.get, reverse=True)[:8]})
        except sqlite3.Error as e:
            out.append({"surface": "sources", "etat": "illisible",
                        "raison": "%s: %s" % (type(e).__name__, e)})
    return out


def _affichable(f) -> str:
    """Chemin lisible, meme HORS du depot.

    DEFAUT MESURE le 2026-09-05 : `relative_to(ROOT)` levait `ValueError` sur les
    fiches memoire, qui vivent dans le profil owner et non sous la racine Nokido.
    La surface la plus riche de toutes ressortait donc « ILLISIBLE » -- d'abord
    par ACL, puis, une fois les droits poses, par ce calcul de chemin. Deux
    defauts empiles, le premier masquant le second.

    Patron deja applique le 2026-08-28 sur le meme motif (artefact hors depot sous
    RUNNER_TEMP) : se rabattre sur le NOM plutot que de lever. Un outil de
    retrieval qui echoue sur un chemin rend un FAUX NEGATIF, et un faux negatif de
    retrieval fait re-enqueter sur ce qui etait deja resolu.
    """
    try:
        return str(f.relative_to(ROOT))
    except ValueError:
        return f.name


def _fichiers(nom, dossiers, motifs, terme):
    """Surface fichier : le NOM et le contenu. Un dossier illisible se DECLARE."""
    mot = re.compile(re.escape(terme), re.I)
    par_nom, par_contenu, illisibles = [], [], []
    for d in dossiers:
        try:
            if not d.exists():
                illisibles.append("%s: absent" % d.name)
                continue
        except OSError as e:
            illisibles.append("%s: %s" % (d.name, type(e).__name__))
            continue
        for motif in motifs:
            try:
                fichiers = list(d.glob(motif))
            except OSError as e:
                illisibles.append("%s/%s: %s" % (d.name, motif, type(e).__name__))
                continue
            for f in fichiers:
                if mot.search(f.name):
                    par_nom.append(_affichable(f))
                    continue
                try:
                    if mot.search(f.read_text(encoding="utf-8", errors="replace")):
                        par_contenu.append(_affichable(f))
                except OSError:
                    illisibles.append(str(f.name))
    etat = "hits" if (par_nom or par_contenu) else (
        "illisible" if illisibles and not (par_nom or par_contenu) else "vide")
    r = {"surface": nom, "etat": etat, "par_nom": par_nom[:12],
         "par_contenu": par_contenu[:12],
         "n": len(par_nom) + len(par_contenu)}
    if illisibles:
        r["illisibles"] = illisibles[:8]
        # Un garde qui dit « je n'ai pas pu voir » sans dire POURQUOI oblige a
        # rouvrir l'enquete pour rien. La raison voyage avec le verdict.
        r["raison"] = "; ".join(illisibles[:4])
    return r


def verdict_global(surfaces):
    """L'INVARIANT du module, isole pour etre testable sans toucher au disque.

    PRESENT des qu'une surface a des hits · ABSENT seulement si TOUTES sont
    lisibles et vides · INDETERMINE des qu'une seule est illisible. C'est ce
    dernier cas qui compte : le 2026-09-03, « aucune RFC ingeree » a ete affirme
    trois fois sur des surfaces jamais regardees.
    """
    if any(s.get("etat") == "hits" for s in surfaces):
        return "PRESENT"
    if any(s.get("etat") == "illisible" for s in surfaces):
        return "INDETERMINE"
    return "ABSENT"


def balayer(terme):
    """Toutes les surfaces. Le verdict global refuse de conclure sur un trou."""
    surfaces = []
    # `_fts` rend une LISTE de surfaces (deux index + les sources). Si elle leve,
    # l'enveloppe rend un dict unique : les deux formes sont normalisees ici,
    # sinon l'echec de la surface ferait tomber tout le balayage.
    _f = _surface("fts", lambda: _fts(terme))
    surfaces += _f if isinstance(_f, list) else [_f]
    # OUTILS d'abord dans la lecture du rapport : c'est la surface oubliee.
    surfaces.append(_surface("outils", lambda: _fichiers(
        "outils", [ROOT / "tools", ROOT / "app"], ["*.py"], terme)))
    surfaces.append(_surface("docs", lambda: _fichiers(
        "docs", [ROOT / "docs"], ["*.md", "*_state.json"], terme)))
    surfaces.append(_surface("skills", lambda: _fichiers(
        "skills", [ROOT / "docs" / "skills", ROOT / ".agents" / "skills"],
        ["**/SKILL.md"], terme)))
    # DECLARATIONS de service : un module absent du disque peut etre conteneurise
    # (mesure 2026-08-30, crawl4ai declare 'ABSENT' par find_spec).
    surfaces.append(_surface("declarations", lambda: _fichiers(
        "declarations", [ROOT / "docker" / "nokido", ROOT / "proxy_deno" / "core",
                         ROOT / "config"],
        ["*.yml", "*.yaml", "*.toml", "*.json"], terme)))
    surfaces.append(_surface("memoires", lambda: _fichiers(
        "memoires",
        [Path(r"%USERPROFILE%/.claude/projects/"
              "C--Users-user-Script-python-IA/memory")], ["*.md"], terme)))

    lisibles = [s for s in surfaces if s.get("etat") != "illisible"]
    illisibles = [s for s in surfaces if s.get("etat") == "illisible"]
    return {"terme": terme, "verdict": verdict_global(surfaces),
            "surfaces": surfaces,
            "surfaces_lues": len(lisibles), "surfaces_total": len(surfaces),
            "illisibles": [s["surface"] for s in illisibles],
            "note": ("ABSENT n'est rendu que si TOUTES les surfaces sont lisibles"
                     " et vides ; sinon INDETERMINE.")}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    termes = [a for a in argv if not a.startswith("--")]
    if not termes:
        print("usage: forge_retrieval_sweep.py <terme> [--json]", file=sys.stderr)
        return 64
    res = balayer(" ".join(termes))
    if "--json" in argv:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["verdict"] != "INDETERMINE" else 3

    print("=== « %s » : %s  (%d/%d surfaces lues)" % (
        res["terme"], res["verdict"], res["surfaces_lues"], res["surfaces_total"]))
    for s in res["surfaces"]:
        if s["etat"] == "illisible":
            print("  %-16s ILLISIBLE — %s" % (s["surface"], s.get("raison", "?")))
        elif s["etat"] == "vide":
            print("  %-16s vide" % s["surface"])
        else:
            det = ""
            if s.get("distinctes"):
                det = " (%d source(s) distinctes%s : %s)" % (
                    s["distinctes"],
                    "" if s.get("distinctes_exactes", True) else " AU MOINS",
                    ", ".join(s.get("exemples", [])[:4]))
            elif s.get("par_nom"):
                det = " — dont par le NOM : %s" % ", ".join(s["par_nom"][:4])
            # Le TOTAL prime sur l'echantillon dans ce qu'on IMPRIME : c'est le
            # chiffre qu'un lecteur retient. Afficher « 500 (plafonne) » sans le
            # total a fait conclure a 500 la ou il y en avait 7747 (2026-09-12).
            total = s.get("n_total")
            if s.get("plafonne") and total is not None:
                tete = "%d  (echantillon %d)" % (total, s.get("n", 0))
            else:
                tete = "%d" % (total if total is not None else s.get("n", 0))
            print("  %-16s %s%s" % (s["surface"], tete, det))
    if res["illisibles"]:
        print("\nNE PAS conclure a une absence : %d surface(s) non lue(s) — %s"
              % (len(res["illisibles"]), ", ".join(res["illisibles"])))
    return 0 if res["verdict"] != "INDETERMINE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
