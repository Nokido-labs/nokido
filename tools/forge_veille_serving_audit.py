"""SERVING AUDIT : prouver, source par source, qu'une veille est RECUPERABLE.

__FORGE_COLOR__ = "memoire/serving-audit"

DIRECTIVE OWNER 2026-09-07 :

    « Nokido sait deja beaucoup mieux ingerer la veille qu'il ne sait encore
      l'exploiter comme carburant cognitif. [...] La prochaine mesure utile est de
      prouver, source par source, ingeree -> vectorisee -> recuperable -> servie. »

CE MODULE N'EST PAS UN MOTEUR, et c'est deliberé. Le corps possede deja :
  - `forge_epistemic_retrieve` : consensus / minorite / conflit / temporalite ;
  - `forge_vec_coverage`       : couverture vectorielle (total / vectorise / non) ;
  - `forge_rag_engine`         : le retrieval vivant.
Ce qui manquait est le passage du COVERAGE AUDIT au SERVING AUDIT : un VERDICT par
source, avec ses manques NOMMES. On mesure ; on ne re-juge pas.

LE DEFAUT QUE CA FERME (mesure du meme soir). Interroge sur une vraie question de
session -- une doublure de test incapable d'echouer -- le RAG rend le code de Nokido et
ZERO chunk de veille. La meme question restreinte aux sources academiques rend en
premier « An Empirical Study of Flaky Tests in Python » (22 352 projets, 876 186 tests).
Le savoir est present et pertinent, mais NOYE : 591 chunks de veille du jour contre
2,18 M en base. **`n_stored > 0` ne prouve pas la recuperabilite.**

TROIS ETATS, jamais deux :
    SERVABLE      tous les invariants tenus
    NON_SERVABLE  au moins un manque, NOMME
    INDETERMINE   on n'a pas pu voir (base absente/illisible) -- jamais confondu
                  avec « rien a voir »
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

# Demi-vie epistemique de `watch_veille` : ~1,5 jour. Une veille ancienne reste une
# trace VALIDE -- elle cesse seulement d'etre l'etat present. On requalifie, on ne
# supprime pas (« geler, jamais supprimer »).
_DEMI_VIE_J = 1.5
_HISTORIQUE_APRES_J = 14.0


def _conn(db_path: str | None):
    """Connexion lecture seule, ou None si la base n'est pas joignable (DIT)."""
    if db_path is None:
        try:
            from nokido_agent.app.forge_db_path import db_path as _dp
            db_path = _dp()
        except Exception:  # noqa: BLE001
            return None
    p = Path(db_path)
    if not p.exists():
        return None
    try:
        return sqlite3.connect("file:%s?mode=ro" % p.as_posix(), uri=True, timeout=20)
    except sqlite3.Error:
        return None


def _age_jours(created: str | None):
    if not created:
        return None
    try:
        d = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (datetime.now(tz=timezone.utc) - d).total_seconds() / 86400.0
    except (TypeError, ValueError):
        return None  # date illisible -> INCONNUE, jamais 0 (qui ferait « tout frais »)


def _classe(age_j):
    """VEILLE (etat present) · HISTORIQUE (trace, plus l'etat) · INCONNUE."""
    if age_j is None:
        return "INCONNUE"
    return "HISTORIQUE" if age_j > _HISTORIQUE_APRES_J else "VEILLE"


def _termes(question: str) -> str:
    """Requete FTS5 depuis une question en langage courant, sans syntaxe piegeuse."""
    mots = [m for m in "".join(c if c.isalnum() else " " for c in question).split()
            if len(m) > 2]
    return " OR ".join('"%s"' % m for m in mots[:8])


def auditer_source(source: str, db_path: str | None = None,
                   question: str | None = None) -> dict:
    """Verdict de SERVABILITE d'une source, avec ses manques nommes."""
    fiche: dict = {"source": source, "verdict": "INDETERMINE", "manques": [],
                   "chunks": 0, "vectorises": 0, "fts": 0,
                   "age_j": None, "classe": "INCONNUE", "recuperable": None}
    conn = _conn(db_path)
    if conn is None:
        fiche["manques"].append("base absente ou illisible -- rien n'a pu etre verifie")
        return fiche

    try:
        lignes = conn.execute(
            "SELECT id, embedding, domain, role_hint, created_at, text "
            "FROM rag_chunks WHERE source = ?", (source,)).fetchall()
    except sqlite3.Error as exc:
        fiche["manques"].append("lecture rag_chunks impossible (%s)" % type(exc).__name__)
        conn.close()
        return fiche

    manques = fiche["manques"]
    fiche["chunks"] = len(lignes)
    if not lignes:
        fiche["verdict"] = "NON_SERVABLE"
        manques.append("aucun chunk pour cette source (contenu jamais ingere)")
        conn.close()
        return fiche

    fiche["vectorises"] = sum(1 for r in lignes if r[1] is not None)
    if fiche["vectorises"] < len(lignes):
        manques.append("embedding manquant sur %d chunk(s) sur %d -- le dense ne les "
                       "rendra jamais" % (len(lignes) - fiche["vectorises"], len(lignes)))

    if any(not r[2] or not r[3] for r in lignes):
        manques.append("provenance incomplete (domain/role_hint) -- un passage servi "
                       "sans provenance n'est pas remontable a sa source")

    ids = [r[0] for r in lignes]
    try:
        marques = {r[0] for r in conn.execute(
            "SELECT chunk_id FROM rag_fts WHERE source = ?", (source,)).fetchall()}
    except sqlite3.Error as exc:
        marques = set()
        manques.append("index lexical illisible (%s)" % type(exc).__name__)
    fiche["fts"] = len(marques)
    if len(marques) < len(ids):
        manques.append("index lexical desynchronise : %d chunk(s) sur %d absents du "
                       "FTS -- BM25 ne les retrouvera pas" % (len(ids) - len(marques),
                                                              len(ids)))

    ages = [a for a in (_age_jours(r[4]) for r in lignes) if a is not None]
    if ages:
        fiche["age_j"] = round(min(ages), 2)
    fiche["classe"] = _classe(fiche["age_j"])
    if fiche["age_j"] is None:
        manques.append("fraicheur incalculable (created_at absent ou illisible)")

    # LE TEST DECISIF : une question de controle doit ramener un chunk DE CETTE SOURCE.
    # Un contenu present mais introuvable n'est pas servi -- c'est tout l'objet de cet
    # auditeur, et la seule preuve qui ne se deduit d'aucun compteur.
    if question:
        try:
            trouves = {r[0] for r in conn.execute(
                "SELECT chunk_id FROM rag_fts WHERE rag_fts MATCH ? AND source = ? "
                "LIMIT 50", (_termes(question), source)).fetchall()}
            fiche["recuperable"] = bool(trouves)
            if not trouves:
                manques.append("NON RECUPERABLE : la question de controle ne ramene "
                               "aucun chunk de cette source")
        except sqlite3.Error as exc:
            fiche["recuperable"] = None
            manques.append("epreuve de recuperabilite impossible (%s)"
                           % type(exc).__name__)

    conn.close()
    fiche["verdict"] = "NON_SERVABLE" if manques else "SERVABLE"
    return fiche


def auditer(sources, db_path: str | None = None, question: str | None = None) -> dict:
    """Audit d'un lot. Le bilan porte son DENOMINATEUR, indetermines compris."""
    fiches = [auditer_source(s, db_path=db_path, question=question) for s in sources]
    compte: dict = {"SERVABLE": 0, "NON_SERVABLE": 0, "INDETERMINE": 0}
    for f in fiches:
        compte[f["verdict"]] = compte.get(f["verdict"], 0) + 1
    return {"total": len(fiches), "compte": compte, "fiches": fiches}


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", action="append", default=[], help="URL (repetable)")
    ap.add_argument("--question", default="", help="question de controle (test decisif)")
    ap.add_argument("--db", default=None)
    ap.add_argument("--depuis-veille", type=int, default=0,
                    help="auditer les N dernieres sources du domaine watch_veille")
    a = ap.parse_args()

    sources = list(a.source)
    if a.depuis_veille:
        conn = _conn(a.db)
        if conn is None:
            print(json.dumps({"verdict": "INDETERMINE",
                              "motif": "base absente ou illisible"}, ensure_ascii=False))
            return 2
        sources += [r[0] for r in conn.execute(
            "SELECT DISTINCT source FROM rag_chunks WHERE domain='watch_veille' "
            "ORDER BY rowid DESC LIMIT ?", (a.depuis_veille,)).fetchall()]
        conn.close()
    if not sources:
        print("aucune source demandee (--source ou --depuis-veille)")
        return 2

    bilan = auditer(sources, db_path=a.db, question=a.question or None)
    print(json.dumps(bilan, ensure_ascii=False, indent=1))
    return 0 if bilan["compte"]["NON_SERVABLE"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_main())
