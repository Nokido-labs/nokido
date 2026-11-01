"""JUGE du banc d'amelioration `rappel_lexical` (organe memoire) : rappel@10 du canal LEXICAL du RAG, mesure sur un
MINI-INDEX FIGE, avec la fonction `requete_fts` (app/forge_rag_engine.py) de la RACINE donnee (copie du candidat).

DETERMINISTE : aucun reseau, aucun LLM, aucune lecture de %NOKIDO_DATA%\embeddings.db. Le mini-index (FTS5 local, HORS git car il
porte du texte RAG) est construit une fois par C:/tmp/laforge_jobs/construire_mini_index_rag.py : fragments attendus des
54 questions validees (docs/rapports/golden_dataset_retrieval_20261019.json) lus par cle primaire, plus des distracteurs
tires par FTS. Son empreinte est verifiee contre le manifeste : un index qui a bouge = juge refuse, jamais un chiffre.

Metrique = rappel_id@k (un id attendu parmi les k premiers), via tools/forge_golden_rappel.mesurer_rappel. Une requete
que FTS5 refuse (syntaxe) compte comme RATEE, jamais INCONNUE : sinon un candidat ecarterait les questions dures en
levant. Les questions dont aucun fragment attendu n'est dans l'index sont ecartees (comptees a part).
La fonction est extraite par AST et chargee SEULE (sans importer le moteur, ses index et ses embedders).
Usage : banc_rappel_lexical.py [--racine DIR] [--index FICHIER] [--k 10]   -> une ligne JSON {"metrique": ..., ...}
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/meta-evaluation"

import argparse
import ast
import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[2]


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return _RACINE
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
GOLDEN = _RACINE / "docs" / "rapports" / "golden_dataset_retrieval_20261019.json"
INDEX = _RACINE_DONNEES / "sandbox" / "workspace" / "bancs" / "rag_mini_index.sqlite"


def charger_requete_fts(racine: Path):
    """`requete_fts` de la racine donnee, extraite par AST et chargee seule (module temporaire)."""
    src = Path(racine) / "app" / "forge_rag_engine.py"
    arbre = ast.parse(src.read_text(encoding="utf-8"))
    noeud = next((n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "requete_fts"), None)
    if noeud is None:
        raise SystemExit("requete_fts absente de %s" % src)
    with tempfile.TemporaryDirectory(prefix="banc_rappel_") as d:
        seule = Path(d) / "requete_fts_banc.py"
        seule.write_text(ast.unparse(noeud) + "\n", encoding="utf-8")
        spec = importlib.util.spec_from_file_location("requete_fts_banc", seule)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod.requete_fts


def verifier_index(index: Path) -> str:
    """Empreinte du mini-index, refusee si elle differe du manifeste (index non fige = pas de verdict)."""
    manifeste = json.loads(Path(index).with_suffix(".json").read_text(encoding="utf-8"))
    h = hashlib.sha256(Path(index).read_bytes()).hexdigest()
    if h != manifeste.get("sha256"):
        raise SystemExit("mini-index MODIFIE depuis sa construction (%s != %s) : juge refuse" % (h[:12],
                                                                                          str(manifeste.get("sha256"))[:12]))
    return h


def mesurer(racine: Path = _RACINE, index: Path = INDEX, golden: Path = GOLDEN, k: int = 10) -> dict:
    sys.path.insert(0, str(_RACINE / "tools"))
    from forge_golden_rappel import mesurer_rappel

    h = verifier_index(index)
    requete_fts = charger_requete_fts(racine)
    questions = json.loads(Path(golden).read_text(encoding="utf-8"))["questions"]
    con = sqlite3.connect("file:%s?mode=ro" % Path(index).as_posix(), uri=True)
    # source d'un id attendu = celle de l'index : un id hache ne la porte pas dans sa forme (source_de rendait 0,0)
    sources = dict(con.execute("SELECT id, source FROM mini"))
    verdicts = {q["id"]: {"verdict": "VALIDE" if set(q.get("sources_attendues") or []) & sources.keys() else "HORS_INDEX"}
                for q in questions}
    erreurs = []

    def chercher(question):
        expr = requete_fts(question)
        if not expr:
            return []
        try:
            return [{"id": i, "source": s} for i, s in
                    con.execute("SELECT id, source FROM mini WHERE mini MATCH ? ORDER BY rank LIMIT ?", (expr, k))]
        except sqlite3.OperationalError as e:
            erreurs.append(str(e)[:80])
            return []

    try:
        r = mesurer_rappel(questions, verdicts, chercher, k=k, source_attendue=sources.get)
    finally:
        con.close()
    return {"metrique": r["rappel_id"] or 0.0, "rappel_source": r["rappel_source"], "k": k,
            "mesurees": r["mesurees"], "hors_index": r["ecartees_non_valides"], "erreurs_fts": len(erreurs),
            "ratees": r["ratees"], "index_sha": h[:12]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--racine", default=str(_RACINE))
    ap.add_argument("--index", default=str(INDEX))
    ap.add_argument("--k", type=int, default=10)
    a = ap.parse_args(argv)
    print(json.dumps(mesurer(Path(a.racine), Path(a.index), k=a.k), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
