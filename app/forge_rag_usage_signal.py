# -*- coding: utf-8 -*-
"""forge_rag_usage_signal.py — le journal d'USAGE du RAG, hors de la base RAG.

POURQUOI (chantier owner « LoRA retrieval », cause etablie le 2026-10-02 :
bb:lora_signal_usage_cause_2026-10-02). Un retrieval ne s'affine que sur ce que les
recherches ont TROUVE et sur ce qui a SERVI. Or :
  * l'unique ecrivain de `query_log`, `_log_query` (forge_mcp_registry), n'insere jamais
    `selected_chunk_id` -- aucune recherche ne dit quel morceau a servi ;
  * `synaptic_feedback_log` n'est ecrit par AUCUN agent ;
  * `introspect` ne passe pas par `_log_query`.
Et la base RAG principale (45 Go) doit CESSER de recevoir des ecritures (chantier P0) :
le signal ne peut donc pas y naitre.

CE QUE FAIT CE MODULE
  noter(...)       une recherche : requete (expurgee DLP), ids retrouves dans l'ordre,
                   scores du reranker, et le top-1 marque positif FAIBLE ;
  marquer_cite(...) un morceau effectivement CITE par une reponse : positif FORT (pour un
                   futur extracteur de citations) ;
  triplets(...)    (requete, positif, negatifs durs) depuis le journal.
Le journal est un fichier APPEND-ONLY (`logs/rag_usage_signal.jsonl`) a rotation BORNEE.
Aucune ecriture SQLite, nulle part.

ANTI-DUP. `forge_synaptic_plasticity` porte deja un « feedback » -- mais il ECRIT dans la
base RAG (`rag_chunks.meta`, tables synaptic_*), ce que le chantier P0 interdit.
`tools/forge_jepa_dataset` construit des triplets HORS LIGNE depuis d'autres sources
(execution_traces.db, success_oplog) : il pourra consommer `triplets()`, il n'est pas un
journal d'usage. Aucun des deux ne journalise une recherche au moment ou elle a lieu.

GARDES
  * `noter` ne leve JAMAIS : un journal non inscriptible ne casse pas la recherche, et le
    DIT (avertissement au premier echec puis tous les 200, compteur `PERTES`, retour ok=False) ;
  * un positif FAIBLE n'engendre de negatifs que si les scores sont CONNUS et l'ecart
    franc (`MARGE_NEGATIF`) : sans score, un voisin de rang 2 peut etre aussi pertinent que
    le rang 1, et l'appeler negatif apprendrait une erreur (liste blanche) ;
  * une ligne illisible est COMPTEE, jamais fatale.
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/journal-usage : signal d usage du RAG, hors base, pour le LoRA retrieval"

import hashlib
import json
import logging
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = Path(os.environ.get("LAFORGE_RAG_USAGE_JOURNAL",
                              str(ROOT / "logs" / "rag_usage_signal.jsonl")))
MAX_OCTETS = int(os.environ.get("LAFORGE_RAG_USAGE_MAX_MO", "20")) * 1024 * 1024
ARCHIVES = int(os.environ.get("LAFORGE_RAG_USAGE_ARCHIVES", "3"))
MAX_IDS = 20
MARGE_NEGATIF = float(os.environ.get("LAFORGE_RAG_USAGE_MARGE", "2.0"))
FAIBLE, FORT = "FAIBLE", "FORT"
PERTES = {"n": 0}

log = logging.getLogger("Nokido.RagUsage")


def _expurger(texte: str) -> tuple[str, str]:
    """(texte, etat_dlp). La requete peut porter un secret ou une donnee personnelle."""
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_for_log
        return str(redact_for_log(texte)), "APPLIQUE"
    except Exception as e:  # noqa: BLE001 - DLP indisponible : on le DIT dans la ligne
        return texte, "NON_APPLIQUE (%s)" % type(e).__name__


def _pivoter(chemin: Path) -> None:
    """Rotation bornee : journal -> .1 -> .2 ... -> .ARCHIVES (la plus vieille sort)."""
    if not chemin.exists() or chemin.stat().st_size < MAX_OCTETS:
        return
    for i in range(ARCHIVES, 0, -1):
        src = chemin.with_name(chemin.name + (".%d" % (i - 1) if i > 1 else ""))
        if src.exists():
            os.replace(src, chemin.with_name(chemin.name + ".%d" % i))


def _ecrire(entree: dict) -> dict:
    chemin = Path(JOURNAL)
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        _pivoter(chemin)
        with open(chemin, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entree, ensure_ascii=False, sort_keys=True) + "\n")
        return {"ok": True, "id": entree.get("id")}
    except Exception as e:  # noqa: BLE001 - jamais propage : la recherche ne paie pas le journal
        PERTES["n"] += 1
        if PERTES["n"] == 1 or PERTES["n"] % 200 == 0:
            log.warning("[rag_usage] journal d'usage NON ECRIT (%s: %s) -- %d perte(s) | "
                        "consequence : ce signal d'usage manquera au LoRA retrieval",
                        type(e).__name__, str(e)[:80], PERTES["n"])
        return {"ok": False, "raison": "%s: %s" % (type(e).__name__, str(e)[:120]),
                "pertes": PERTES["n"]}


def noter(requete: str, ids: list, scores: list | None = None, source: str = "",
          mode: str = "") -> dict:
    """Journalise une recherche. Top-1 = positif FAIBLE. Ne leve jamais.

    `scores` : scores du reranker DANS L'ORDRE de `ids` (None si pas de rerank)."""
    try:
        ids = [str(i) for i in (ids or [])][:MAX_IDS]
        sc = None
        if scores is not None:
            sc = [float(s) if s is not None else None for s in list(scores)[:len(ids)]]
            if len(sc) != len(ids):
                sc = None  # des scores qui ne s'alignent pas ne s'attribuent a personne
        texte, dlp = _expurger(str(requete or "")[:500])
        ts = time.time()
        rid = hashlib.sha256(("%r|%s|%s" % (ts, texte, ",".join(ids))).encode()).hexdigest()[:16]
        return _ecrire({"type": "recherche", "id": rid, "ts": round(ts, 3), "requete": texte,
                        "dlp": dlp, "ids": ids, "scores": sc, "source": source, "mode": mode,
                        "positif": ids[0] if ids else None, "force": FAIBLE if ids else None})
    except Exception as e:  # noqa: BLE001 - meme regle : le dire, ne pas casser
        PERTES["n"] += 1
        return {"ok": False, "raison": "entree non formable (%s)" % type(e).__name__}


def marquer_cite(recherche_id: str, chunk_id: str, par: str = "") -> dict:
    """Un morceau CITE par une reponse : positif FORT de la recherche `recherche_id`."""
    if not recherche_id or not chunk_id:
        return {"ok": False, "raison": "recherche_id et chunk_id requis"}
    return _ecrire({"type": "citation", "ref": str(recherche_id), "chunk_id": str(chunk_id),
                    "force": FORT, "par": par, "ts": round(time.time(), 3)})


def _lignes(chemin: Path):
    """Journal + archives, du plus ancien au plus recent."""
    fichiers = [chemin.with_name(chemin.name + ".%d" % i) for i in range(ARCHIVES, 0, -1)]
    for f in fichiers + [chemin]:
        try:
            with open(f, encoding="utf-8") as fh:
                yield from fh
        except FileNotFoundError:  # muet-ok : archive pas encore nee, rien a lire
            continue


def triplets(chemin=None, n_negatifs: int = 3, force_min: str = FAIBLE) -> dict:
    """(requete, positif, negatifs durs) depuis le journal.

    Positif FORT = morceau CITE ; sinon positif FAIBLE = top-1 (si `force_min` le permet).
    Negatifs DURS = retrouves par la meme recherche (donc proches) mais non positifs :
      * positif FORT  -> les autres retrouves, dans l'ordre du reranker ;
      * positif FAIBLE -> seulement ceux dont le score est connu et inferieur au positif d'au
        moins MARGE_NEGATIF ; sans scores, AUCUN negatif (et la recherche est comptee).
    """
    chemin = Path(chemin) if chemin is not None else Path(JOURNAL)
    recherches: dict = {}
    citations: dict = {}
    stats = {"lignes_illisibles": 0, "recherches": 0, "citations": 0,
             "citations_orphelines": 0, "faibles_sans_scores": 0, "sans_negatif": 0}
    for ligne in _lignes(chemin):
        if not ligne.strip():
            continue
        try:
            e = json.loads(ligne)
        except ValueError:
            stats["lignes_illisibles"] += 1
            continue
        if e.get("type") == "recherche" and e.get("id"):
            recherches[e["id"]] = e
        elif e.get("type") == "citation" and e.get("ref"):
            citations.setdefault(e["ref"], []).append(str(e.get("chunk_id")))
    stats["recherches"] = len(recherches)
    out = []
    for ref, cites in citations.items():
        stats["citations"] += len(cites)
        if ref not in recherches:
            stats["citations_orphelines"] += len(cites)
    for rid, r in recherches.items():
        ids, scores = list(r.get("ids") or []), r.get("scores")
        cites = [c for c in citations.get(rid, []) if c in ids]
        if cites:
            for pos in dict.fromkeys(cites):
                negs = [i for i in ids if i not in cites][:n_negatifs]
                if not negs:
                    stats["sans_negatif"] += 1
                    continue
                out.append({"requete": r.get("requete"), "positif": pos, "force": FORT,
                            "negatifs": negs, "recherche": rid})
            continue
        if force_min == FORT or not ids:
            continue
        if not isinstance(scores, list) or len(scores) != len(ids) or scores[0] is None:
            stats["faibles_sans_scores"] += 1
            continue
        negs = [i for i, s in zip(ids[1:], scores[1:])
                if s is not None and scores[0] - s >= MARGE_NEGATIF][:n_negatifs]
        if not negs:
            stats["sans_negatif"] += 1
            continue
        out.append({"requete": r.get("requete"), "positif": ids[0], "force": FAIBLE,
                    "negatifs": negs, "recherche": rid})
    return {"triplets": out, "stats": stats}


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Journal d'usage du RAG (hors base)")
    ap.add_argument("--triplets", action="store_true")
    ap.add_argument("--fort-seulement", action="store_true")
    a = ap.parse_args(argv)
    r = triplets(force_min=FORT if a.fort_seulement else FAIBLE)
    print(json.dumps(r["stats"] if not a.triplets else r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
