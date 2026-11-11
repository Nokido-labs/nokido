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

import asyncio
import contextlib
import inspect
import json
import os
import re
import statistics
import time
from pathlib import Path

try:
    from tools.forge_retrieval_baseline import MARGE_RAM_GO, _dense_vivant, _ram_libre_go
except ImportError:
    try:
        from forge_retrieval_baseline import MARGE_RAM_GO, _dense_vivant, _ram_libre_go
    except ImportError:
        MARGE_RAM_GO = 6.0

        def _dense_vivant():
            return False, "forge_retrieval_baseline introuvable"

        def _ram_libre_go():
            return None

try:
    from filelock import FileLock
except ImportError:
    FileLock = None

__FORGE_COLOR__ = "memoire/rappel_golden : instrument rappel@k du jeu de reference RAG (VALIDE seules, INCONNU a part)"

_SEP_SOURCE = re.compile(r"[#:]")


def ecrire_sortie(chemin: Path | str, r: dict) -> Path:
    """Ecrit le rapport JSON sous FileLock via un fichier .tmp renomme : exclusion inter-processus."""
    dest = Path(chemin)
    dest.parent.mkdir(parents=True, exist_ok=True)
    lock_file = dest.with_suffix(dest.suffix + ".lock")
    lock = FileLock(str(lock_file), timeout=10) if FileLock is not None else contextlib.nullcontext()
    tmp = dest.with_name(f".{dest.name}.tmp.{os.getpid()}_{time.time_ns()}")
    with lock:
        tmp.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(dest)
    return dest


def source_de(identifiant) -> str:
    """Le document d'un id de chunk : ce qui precede le premier « # » ou « : ».
    Pour les fiches memoire (`memory:<stem>`), preserve le prefixe `memory:<stem>` sans couper au deux-points."""
    s = str(identifiant)
    if s.startswith("memory:"):
        return s.split("#", 1)[0]
    return _SEP_SOURCE.split(s, 1)[0]


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


@contextlib.contextmanager
def _env_places_memoire(valeur: str):
    """Bascule temporaire de LAFORGE_RAG_PLACES_MEMOIRE avec restauration garantie (y compris sur exception)."""
    anc = os.environ.get("LAFORGE_RAG_PLACES_MEMOIRE")
    os.environ["LAFORGE_RAG_PLACES_MEMOIRE"] = str(valeur)
    try:
        yield
    finally:
        if anc is not None:
            os.environ["LAFORGE_RAG_PLACES_MEMOIRE"] = anc
        else:
            os.environ.pop("LAFORGE_RAG_PLACES_MEMOIRE", None)


def _chercher_avec_engine(engine, k: int = 10):
    """Enveloppe synchrone/asynchrone appelant engine.search(query, k=k)."""
    def chercher(query: str):
        res = engine.search(query, k=k)
        if inspect.iscoroutine(res):
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, res).result()
            else:
                return asyncio.run(res)
        return res
    return chercher


def _instancier_engine():
    """Instancie RAGEngine du corps sans balayage prealable."""
    try:
        from nokido_agent.app.forge_rag_engine import RAGEngine
    except ImportError:
        from forge_rag_engine import RAGEngine
    return RAGEngine()


def _formater_bilan_bras(nom: str, r: dict, k: int) -> str:
    fmt_2 = lambda x: "None" if x is None else "%.2f" % x  # noqa: E731
    gagnees = r.get("gagnees") or []
    perdues = r.get("perdues") or []
    return (
        f"BILAN bras={nom} places_memoire={r.get('places_memoire')} k={k} "
        f"rappel_source@{k}={fmt_2(r.get('rappel_source'))} "
        f"mrr={fmt_2(r.get('mrr'))} "
        f"gagnees={len(gagnees)} "
        f"perdues={perdues} "
        f"latence_mediane_ms={fmt_2(r.get('latence_mediane_ms'))} "
        f"part_memory_top10={fmt_2(r.get('part_memoire_top10'))}"
    )


def comparer_canal_memoire(
    questions,
    verdicts=None,
    engine=None,
    k: int = 10,
    source_attendue=None,
    verifier_gardes: bool = True,
    no_rag_scan: bool = False,
) -> dict:
    """Compare RAGEngine.search avec LAFORGE_RAG_PLACES_MEMOIRE=0 (baseline) vs 40 (canal memoire actif).

    Contrat :
    - Deux passes off puis on sur le meme moteur, meme processus, memes questions.
    - Gardes de ressources (RAM et canal dense vivant) : refus avec NO_VERDICT si non satisfaites.
    - Restauration garantie de la variable d'environnement, y compris sur exception.
    - Rapport JSON detaillant rappel_source@k, MRR, latence mediane, part memory:*, et questions perdues (nommees).
    - Recherche qui leve = INCONNUE, jamais ratee.
    """
    if no_rag_scan and engine is None:
        return {
            "ok": False,
            "verdict": "NO_VERDICT",
            "refus": "instanciation de RAGEngine = balayage de rag_chunks",
            "pourquoi": "le flag no_rag_scan empeche l'instanciation du moteur",
        }

    if verifier_gardes:
        libre = _ram_libre_go()
        if libre is not None and libre < MARGE_RAM_GO:
            return {
                "ok": False,
                "verdict": "NO_VERDICT",
                "refus": "marge RAM insuffisante",
                "libre_go": round(libre, 2),
                "plancher_go": MARGE_RAM_GO,
                "pourquoi": "charger le corpus sous ce plancher risque de saturer la machine",
            }
        dense_ok, motif = _dense_vivant()
        if not dense_ok:
            return {
                "ok": False,
                "verdict": "NO_VERDICT",
                "refus": "canal dense muet",
                "detail": motif,
                "pourquoi": "comparer avec un canal dense muet rendrait toute conclusion fausse",
            }

    if engine is None:
        # RAGEngine() parcourt toute rag_chunks (_load_embeddings) : balayage interdit (owner 24/10).
        # Paye le 6/11 : deux jobs tues a 6,5 et 12,1 Go avant toute sortie. Rouvrir par une voie par requete.
        # 9/11 : une livraison remplacait ce refus par une instanciation sous verrou -- un verrou serialise le
        # balayage, il ne l'empeche pas. Refus maintenu, quel que soit no_rag_scan.
        return {
            "ok": False,
            "verdict": "NO_VERDICT",
            "refus": "instanciation de RAGEngine = balayage de rag_chunks",
            "pourquoi": "aucune voie de mesure par requete n'est encore prouvee sans balayage",
        }

    # Bras 1 : OFF (baseline temoin, LAFORGE_RAG_PLACES_MEMOIRE=0)
    with _env_places_memoire("0"):
        chercher_off = _chercher_avec_engine(engine, k=k)
        r_off = mesurer_rappel(questions, verdicts, chercher_off, k=k, source_attendue=source_attendue)

    # Bras 2 : ON (canal memoire actif, LAFORGE_RAG_PLACES_MEMOIRE=40)
    with _env_places_memoire("40"):
        chercher_on = _chercher_avec_engine(engine, k=k)
        r_on = mesurer_rappel(questions, verdicts, chercher_on, k=k, source_attendue=source_attendue)

    trouvees_off = set(r_off.get("trouvees_source_ids") or [])
    trouvees_on = set(r_on.get("trouvees_source_ids") or [])
    gagnees = sorted(list(trouvees_on - trouvees_off))
    perdues = sorted(list(trouvees_off - trouvees_on))

    r_off["places_memoire"] = 0
    r_off["gagnees"] = []
    r_off["perdues"] = []

    r_on["places_memoire"] = 40
    r_on["gagnees"] = gagnees
    r_on["perdues"] = perdues

    return {
        "ok": True,
        "verdict": "VALIDE",
        "k": k,
        "questions_gagnees": gagnees,
        "questions_perdues": perdues,
        "bras_off": r_off,
        "bras_on": r_on,
    }


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
    ap.add_argument("--comparer-canal-memoire", action="store_true",
                    help="compare RAGEngine.search avec LAFORGE_RAG_PLACES_MEMOIRE=0 vs 40")
    ap.add_argument("--no-rag-scan", action="store_true",
                    help="desactive l'instanciation de RAGEngine et l'acces a la base RAG pour eviter le balayage de rag_chunks")
    a = ap.parse_args(argv)
    questions = json.loads(Path(a.jeu).read_text(encoding="utf-8")).get("questions") or []
    chemin_v = Path(a.verdicts) if a.verdicts else _racine_donnees() / "sandbox" / "golden_relecture_owner.json"
    verdicts = json.loads(chemin_v.read_text(encoding="utf-8")) if chemin_v.exists() else None
    attendus = sorted({str(s) for q in questions for s in q.get("sources_attendues") or []})
    sources = {} if a.no_rag_scan else (_sources_attendues(attendus) if attendus else {})

    if a.comparer_canal_memoire:
        r = comparer_canal_memoire(
            questions,
            verdicts=verdicts,
            k=a.k,
            source_attendue=sources.get,
            verifier_gardes=True,
            no_rag_scan=a.no_rag_scan,
        )
        if r.get("verdict") == "NO_VERDICT":
            sortie = Path(a.sortie) if a.sortie else (_racine_donnees() / "sandbox" / "workspace"
                                                      / ("golden_memoire_refus_%s.json" % time.strftime("%Y%m%d_%H%M%S")))
            ecrire_sortie(sortie, r)
            print(json.dumps(r, ensure_ascii=False, indent=2))
            print("REFUS NO_VERDICT : %s -> %s" % (r.get("refus"), sortie))
            return 3

        r.update(jeu=str(a.jeu), mesure_le=time.strftime("%Y-%m-%dT%H:%M:%S"))
        sortie = Path(a.sortie) if a.sortie else (_racine_donnees() / "sandbox" / "workspace"
                                                  / ("golden_memoire_comparaison_%s.json" % time.strftime("%Y%m%d_%H%M%S")))
        ecrire_sortie(sortie, r)

        print(_formater_bilan_bras("off", r["bras_off"], a.k))
        print(_formater_bilan_bras("on", r["bras_on"], a.k))
        print("RAPPORT -> %s" % sortie)
        return 0

    r = mesurer_rappel(questions, verdicts, chercher_corps(_preflight(), a.k), k=a.k, source_attendue=sources.get)
    r.update(retriever=RETRIEVER, jeu=str(a.jeu), mesure_le=time.strftime("%Y-%m-%dT%H:%M:%S"),
             sources_attendues=len(attendus), sources_attendues_resolues=len(sources))
    sortie = Path(a.sortie) if a.sortie else (_racine_donnees() / "sandbox" / "workspace"
                                              / ("golden_rappel_%s.json" % time.strftime("%Y%m%d_%H%M%S")))
    ecrire_sortie(sortie, r)
    fmt = lambda x: "None" if x is None else "%.2f" % x  # noqa: E731
    print("BILAN k=%d mesurees=%d inconnues=%d rappel_id=%s rappel_source=%s retriever=%s -> %s" % (
        a.k, r["mesurees"], r["inconnues"], fmt(r["rappel_id"]), fmt(r["rappel_source"]), RETRIEVER, sortie))
    return 0


def mesurer_rappel(questions, verdicts, chercher, k: int = 10, source_attendue=None) -> dict:
    """rappel@k par id et par source sur les questions VALIDE ; une recherche qui leve = INCONNUE (a part).
    `source_attendue(id)` donne la source d'un id attendu (sinon source_de) ; un chemin qui ne rend aucun id rend
    rappel_id None et rappel_id_mesurable False -- jamais 0."""
    trouvees_id = trouvees_source = mesurees = ecartees = 0
    somme_rr = 0.0   # 4/11 : rang reciproque du 1er id attendu (MRR) -- DEPARTAGE d'une metrique en escalier
    somme_rr_src = 0.0
    ratees, inconnues_ids = [], []
    trouvees_source_ids, ratees_source_ids = [], []
    latences_ms = []
    total_memory_hits = 0
    total_rendus_hits = 0
    id_mesurable = False
    for q in questions or []:
        qid = q.get("id")
        if verdicts is not None and ((verdicts.get(qid) or {}).get("verdict") != "VALIDE"):
            ecartees += 1
            continue
        try:
            t0 = time.perf_counter()
            resultats = list(chercher(q.get("question", "")) or [])[:k]
            latences_ms.append((time.perf_counter() - t0) * 1000.0)
        except Exception:  # noqa: BLE001 - recherche illisible : INCONNUE, ni succes ni echec
            inconnues_ids.append(qid)
            continue
        mesurees += 1
        rendus = [r for r in resultats if isinstance(r, dict)]
        ids = [str(r["id"]) for r in rendus if r.get("id") is not None]
        id_mesurable = id_mesurable or bool(ids)
        rendues = {str(r["source"]) if r.get("source") else source_de(r.get("id")) for r in rendus}
        attendues = [str(s) for s in q.get("sources_attendues") or []]
        attendues_sources = {(source_attendue(s) if source_attendue else None) or source_de(s) for s in attendues}

        for r in rendus:
            src = str(r.get("source") or "")
            cid = str(r.get("id") or "")
            if src.startswith("memory:") or cid.startswith("memory:"):
                total_memory_hits += 1
        total_rendus_hits += len(rendus)

        rang = next((j + 1 for j, x in enumerate(ids) if x in attendues), None)
        somme_rr += (1.0 / rang) if rang else 0.0

        rang_src = next((j + 1 for j, r in enumerate(rendus)
                         if ((str(r["source"]) if r.get("source") else source_de(r.get("id"))) in attendues_sources)), None)
        somme_rr_src += (1.0 / rang_src) if rang_src else 0.0

        if any(s in ids for s in attendues):
            trouvees_id += 1
        else:
            ratees.append(qid)
        if attendues_sources & rendues:
            trouvees_source += 1
            trouvees_source_ids.append(qid)
        else:
            ratees_source_ids.append(qid)

    mrr_val = (somme_rr / mesurees) if (mesurees and id_mesurable) else None
    if mrr_val is None and mesurees and somme_rr_src > 0.0:
        mrr_val = somme_rr_src / mesurees

    latence_med = float(statistics.median(latences_ms)) if latences_ms else None
    part_mem = (total_memory_hits / total_rendus_hits) if total_rendus_hits else 0.0

    return {
        "k": k, "mesurees": mesurees, "inconnues": len(inconnues_ids), "ecartees_non_valides": ecartees,
        "rappel_id": (trouvees_id / mesurees) if (mesurees and id_mesurable) else None,
        "rappel_id_mesurable": id_mesurable,
        "mrr": mrr_val,
        "rappel_source": (trouvees_source / mesurees) if mesurees else None,
        "ratees": ratees, "inconnues_ids": inconnues_ids,
        "trouvees_source_ids": trouvees_source_ids, "ratees_source": ratees_source_ids,
        "latence_mediane_ms": latence_med, "part_memoire_top10": part_mem,
    }


if __name__ == "__main__":
    raise SystemExit(main())
