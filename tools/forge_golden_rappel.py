"""forge_golden_rappel -- instrument rappel@k du jeu de reference RAG (couche 3, roadmap_p1_methode_dev_par_couches).

Jeu : docs/rapports/golden_dataset_retrieval_20261019.json (liste de questions : id, question, sources_attendues =
ids de chunks). Verdicts : sandbox/golden_relecture_owner.json ({id: {"verdict": ...}}). Aucun instrument de RAPPEL
n'existait : tools/bench_rag.py mesure la latence, tools/forge_bench_beir.py est BEIR.

Contrat (tests/nr/test_golden_rappel_nr.py) : seules les questions VALIDE sont mesurees ; rappel par ID de chunk ET par
SOURCE (document : prefixe avant « # » ou « : ») ; une recherche qui leve est INCONNUE, comptee a part, jamais un echec
ni un succes (UNKNOWN != NO) ; rien de mesurable -> None, jamais 0. Le branchement sur le retriever REEL est l'etape
suivante : `chercher` est injecte.
"""
from __future__ import annotations

import re
from pathlib import Path

__FORGE_COLOR__ = "memoire/rappel_golden : instrument rappel@k du jeu de reference RAG (VALIDE seules, INCONNU a part)"

_SEP_SOURCE = re.compile(r"[#:]")


def source_de(identifiant) -> str:
    """Le document d'un id de chunk : ce qui precede le premier « # » ou « : »."""
    return _SEP_SOURCE.split(str(identifiant), 1)[0]


def chercher_corps(preflight, k: int = 10):
    """Le chemin REEL du corps (preflight_check_verbose, 10 appelants) rendu en `[{"source": ...}]` borne a k.
    Tier « illisible » (tous les niveaux en panne) : RuntimeError -> question INCONNUE, jamais ratee."""
    def chercher(question):
        v = preflight(question, "", limit=k) or {}
        if v.get("tier") == "illisible":
            raise RuntimeError("recherche illisible : %s" % "; ".join(map(str, v.get("pannes") or []))[:200])
        return [{"source": r.get("source")} for r in (v.get("results") or [])[:k] if isinstance(r, dict)]
    return chercher


def sources_des_ids(ids, db) -> dict:
    """{id: source} des chunks attendus, par CLE PRIMAIRE (jamais de LIKE sur rag_chunks : 45 Go). Absent = absent."""
    import sqlite3

    ids = [str(i) for i in ids or []]
    if not ids:
        return {}
    con = sqlite3.connect("file:%s?mode=ro" % Path(db).as_posix(), uri=True)
    try:
        trous = ",".join("?" * len(ids))
        return {i: s for i, s in con.execute("SELECT id, source FROM rag_chunks WHERE id IN (%s)" % trous, ids)}
    finally:
        con.close()


RETRIEVER = "forge_self_correction.preflight_check_verbose"
_RACINE_CODE = Path(__file__).resolve().parents[1]
JEU = _RACINE_CODE / "docs" / "rapports" / "golden_dataset_retrieval_20261019.json"


def _racine_donnees() -> Path:
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
        from forge_db_path import racine_donnees
    return Path(racine_donnees())


def _preflight():
    """Le chemin REEL du corps (10 appelants), importe a l'appel : la fonction reste testable sans base."""
    try:
        from nokido_agent.app.forge_self_correction import preflight_check_verbose
    except ImportError:  # repli checkout
        from forge_self_correction import preflight_check_verbose
    return preflight_check_verbose


def _sources_attendues(ids) -> dict:
    try:
        from nokido_agent.app.forge_db_path import db_path
    except ImportError:  # repli checkout
        from forge_db_path import db_path
    return sources_des_ids(ids, db_path())


def main(argv=None) -> int:
    """Mesure le rappel@k du golden sur le retriever du corps ; rapport JSON + ligne BILAN."""
    import argparse
    import json
    import time

    ap = argparse.ArgumentParser(description="rappel@k du jeu de reference RAG sur le retriever du corps")
    ap.add_argument("--jeu", default=str(JEU))
    ap.add_argument("--verdicts", default=None, help="defaut : <racine_donnees>/sandbox/golden_relecture_owner.json")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    questions = json.loads(Path(a.jeu).read_text(encoding="utf-8")).get("questions") or []
    chemin_v = Path(a.verdicts) if a.verdicts else _racine_donnees() / "sandbox" / "golden_relecture_owner.json"
    verdicts = json.loads(chemin_v.read_text(encoding="utf-8"))
    attendus = sorted({str(s) for q in questions for s in q.get("sources_attendues") or []})
    sources = _sources_attendues(attendus)
    r = mesurer_rappel(questions, verdicts, chercher_corps(_preflight(), a.k), k=a.k, source_attendue=sources.get)
    r.update(retriever=RETRIEVER, jeu=str(a.jeu), mesure_le=time.strftime("%Y-%m-%dT%H:%M:%S"),
             sources_attendues=len(attendus), sources_attendues_resolues=len(sources))
    sortie = Path(a.sortie) if a.sortie else (_racine_donnees() / "sandbox" / "workspace"
                                              / ("golden_rappel_%s.json" % time.strftime("%Y%m%d_%H%M%S")))
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    fmt = lambda x: "None" if x is None else "%.2f" % x  # noqa: E731
    print("BILAN k=%d mesurees=%d inconnues=%d rappel_id=%s rappel_source=%s retriever=%s -> %s" % (
        a.k, r["mesurees"], r["inconnues"], fmt(r["rappel_id"]), fmt(r["rappel_source"]), RETRIEVER, sortie))
    return 0


def mesurer_rappel(questions, verdicts, chercher, k: int = 10, source_attendue=None) -> dict:
    """rappel@k par id et par source sur les questions VALIDE ; une recherche qui leve = INCONNUE (a part).
    `source_attendue(id)` donne la source d'un id attendu (sinon source_de) ; un chemin qui ne rend aucun id rend
    rappel_id None et rappel_id_mesurable False -- jamais 0."""
    trouvees_id = trouvees_source = mesurees = ecartees = 0
    ratees, inconnues_ids = [], []
    id_mesurable = False
    for q in questions or []:
        qid = q.get("id")
        if ((verdicts or {}).get(qid) or {}).get("verdict") != "VALIDE":
            ecartees += 1
            continue
        try:
            resultats = list(chercher(q.get("question", "")) or [])[:k]
        except Exception:  # noqa: BLE001 - recherche illisible : INCONNUE, ni succes ni echec
            inconnues_ids.append(qid)
            continue
        mesurees += 1
        rendus = [r for r in resultats if isinstance(r, dict)]
        ids = [str(r["id"]) for r in rendus if r.get("id") is not None]
        id_mesurable = id_mesurable or bool(ids)
        rendues = {str(r["source"]) if r.get("source") else source_de(r.get("id")) for r in rendus}
        attendues = [str(s) for s in q.get("sources_attendues") or []]
        if any(s in ids for s in attendues):
            trouvees_id += 1
        else:
            ratees.append(qid)
        if {(source_attendue(s) if source_attendue else None) or source_de(s) for s in attendues} & rendues:
            trouvees_source += 1
    return {"k": k, "mesurees": mesurees, "inconnues": len(inconnues_ids), "ecartees_non_valides": ecartees,
            "rappel_id": (trouvees_id / mesurees) if (mesurees and id_mesurable) else None,
            "rappel_id_mesurable": id_mesurable,
            "rappel_source": (trouvees_source / mesurees) if mesurees else None,
            "ratees": ratees, "inconnues_ids": inconnues_ids}


if __name__ == "__main__":
    raise SystemExit(main())
