"""Completude et indexation des depots de veille — un verdict PAR DEPOT.

__FORGE_COLOR__ = "memoire/audit : completude et indexation des depots de veille"

POURQUOI UN MODULE DE PLUS (anti-dup, verifie le 2026-09-08). Deux audits
existent et aucun ne descend au depot : `forge_veille_audit` rapproche
`watch_jobs`, `biblio_raw` et le journal git (« ce qui a ete demande a-t-il ete
code ? ») ; `forge_rag_coverage_audit` mesure la couverture GLOBALE des trois
mecanismes declares (dense, hash, decay). La question ouverte reste : pour CE
depot precis, le contenu est-il entier, indexe, et faut-il le refaire ?

CE QU'IL NE FAIT PAS. Aucune jointure sur `rag_fts` : cette table virtuelle n'a
pas de B-tree, une jointure la rescanne PAR LIGNE (41 min, 2 195 Go mesures le
2026-09-03). On lit ses `chunk_id` en un ensemble (~80 Mo pour 2 M), puis on
streame la table principale avec un test d'appartenance O(1). Le texte n'est
jamais rapatrie : `length(text)` suffit a reperer une troncature.

CE QU'IL NE CROIT PAS. La date d'ingestion ne dit PAS quand une veille a ete
demandee : mesure du 2026-09-08, 2 248 chunks tires au hasard ne portent que 29
jours distincts et un seul jour (2026-07-04) en concentre 31,8 % — c'est une
reindexation. La fenetre est donc publiee comme telle, jamais comme une date de
collecte.

CE QU'IL DIT QUAND IL NE SAIT PAS. Une tranche illisible est COMPTEE, jamais
confondue avec une absence ; si l'index lexical ne se lit pas, le verdict qui en
depend est declare NON EVALUE au lieu d'etre rendu faussement bon.

Usage : run action=run_job script=tools/forge_veille_completude.py lane=inventaire
Sortie : sandbox/veille_completude.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_db_path import db_path  # noqa: E402
from nokido_agent.app.forge_memory_availability import VECTORISABLES, tier  # noqa: E402
from nokido_agent.tools.forge_veille_inventaire import depot  # noqa: E402

SORTIE = ROOT / "sandbox" / "veille_completude.json"
PROGRES = ROOT / "sandbox" / "veille_completude.progress.json"
TRANCHE = 50_000

# Longueurs de decoupe du chunker. ATTENTION : un chunk A cette longueur est le
# fonctionnement NORMAL d'un decoupage a taille fixe, PAS une amputation. Mesure
# 2026-09-08 : un premier jet en tirait un verdict TRONQUE pour 206 depots, dont
# scalesim a 97 % — c'etait le chunker qui travaillait. Le compteur est CONSERVE
# comme information brute, il ne produit plus de verdict. Le seul cas qui reste
# suspect est un fichier rendu par UN SEUL chunk pile a la coupe : la, le reste
# du document a pu etre jete en silence (motif `borne_trop_serree`).
CAPS = (3000, 2000, 1500, 1000, 800)
MINCE_FICHIERS = 2       # depot resume a <= 2 fichiers = README seul, a refaire
SEUIL_LEXICAL = 0.99     # le lexical PRIME : sous ce taux, l'index ment


def _dire(msg: str) -> None:
    print("[completude] %s" % msg, flush=True)


def ids_lexicaux(con: sqlite3.Connection) -> set | None:
    """Identifiants presents dans l'index lexical. None = ILLISIBLE, pas vide."""
    t0 = time.time()
    vus = set()
    try:
        for (cid,) in con.execute("SELECT chunk_id FROM rag_fts"):
            if cid is not None:
                vus.add(cid)
    except sqlite3.Error as exc:
        _dire("index lexical ILLISIBLE : %s" % str(exc)[:140])
        return None
    _dire("index lexical : %d identifiants en %.1fs" % (len(vus), time.time() - t0))
    return vus


def verdict(d: dict, lexical_lisible: bool) -> tuple:
    """Verdict + raison.

    L'ordre nomme la CAUSE, pas le symptome : un depot froid n'a pas de vecteur
    PARCE QUE la politique les refuse, le declarer SANS_VECTEUR enverrait
    reparer une decision. Le premier jet mettait A_REFAIRE en tete et masquait
    ainsi les defauts structurels de 678 depots.
    """
    froid = [t for t in d["tiers"] if t not in VECTORISABLES]
    if froid:
        return "MAL_CLASSE", "palier %s : vectorisation refusee par politique" % (
            ",".join(sorted(froid)[:2]))
    if lexical_lisible and d["chunks"] and d["lexical"] / d["chunks"] < SEUIL_LEXICAL:
        return "LEXICAL_INCOMPLET", "%d/%d chunks indexes" % (d["lexical"], d["chunks"])
    if d["fichiers"] <= MINCE_FICHIERS and d["chunks"] < 40:
        return "A_REFAIRE", "seulement %d fichier(s) pour %d chunks" % (
            d["fichiers"], d["chunks"])
    if d["vecteurs"] == 0:
        return "SANS_VECTEUR", "palier chaud, eligible, jamais vectorise"
    if d["vecteurs"] < d["chunks"]:
        return "PARTIEL", "%d/%d vectorises" % (d["vecteurs"], d["chunks"])
    return "COMPLET", "%d chunks, %d fichiers" % (d["chunks"], d["fichiers"])


def main() -> int:
    chemin = str(db_path())
    con = sqlite3.connect("file:%s?mode=ro" % chemin.replace("\\", "/"), uri=True,
                          timeout=60)
    con.execute("PRAGMA query_only = ON")
    con.execute("PRAGMA cache_size = -48000")
    _dire("base %s" % chemin)

    lex = ids_lexicaux(con)
    lexical_lisible = lex is not None
    if lex is None:
        lex = set()

    borne = con.execute("SELECT max(rowid) FROM rag_chunks").fetchone()[0] or 0
    fiches = defaultdict(lambda: {
        "chunks": 0, "vecteurs": 0, "lexical": 0, "tronques": 0,
        "fichiers": 0, "_srcs": set(), "tiers": set(),
        "premier": None, "dernier": None, "len_min": None, "len_max": 0,
    })
    lus = tranches_ko = 0
    t0 = time.time()

    bas = 0
    while bas <= borne:
        haut = bas + TRANCHE
        try:
            lignes = con.execute(
                "SELECT id, source, domain, typeof(embedding), length(text), "
                "substr(ingested_at,1,10) FROM rag_chunks "
                "WHERE rowid >= ? AND rowid < ?", (bas, haut)).fetchall()
        except sqlite3.Error as exc:
            tranches_ko += 1
            _dire("tranche %d-%d ILLISIBLE : %s" % (bas, haut, str(exc)[:110]))
            bas = haut
            continue

        for cid, src, dom, typ, lg, jour in lignes:
            src = src or ""
            dom = dom or ""
            d_id = depot(src, dom)
            if not d_id:
                continue
            lus += 1
            f = fiches[d_id]
            f["chunks"] += 1
            if (typ or "null") != "null":
                f["vecteurs"] += 1
            if lexical_lisible and cid in lex:
                f["lexical"] += 1
            if lg in CAPS:
                f["tronques"] += 1
            f["_srcs"].add(src)
            f["tiers"].add(tier(src, dom))
            if lg is not None:
                f["len_min"] = lg if f["len_min"] is None else min(f["len_min"], lg)
                f["len_max"] = max(f["len_max"], lg)
            if jour:
                f["premier"] = jour if not f["premier"] else min(f["premier"], jour)
                f["dernier"] = jour if not f["dernier"] else max(f["dernier"], jour)

        bas = haut
        if (bas // TRANCHE) % 10 == 0:
            PROGRES.write_text(json.dumps(
                {"rowid": bas, "borne": borne, "lus": lus,
                 "depots": len(fiches), "s": round(time.time() - t0, 1)}),
                encoding="utf-8")
            _dire("rowid %d/%d  lus=%d  depots=%d" % (bas, borne, lus, len(fiches)))
    con.close()

    rapport = {"genere_le": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "base": chemin,
               "index_lexical_lisible": lexical_lisible,
               "chunks_rattaches_a_un_depot": lus,
               "tranches_illisibles": tranches_ko,
               "duree_s": round(time.time() - t0, 1),
               "avertissement_dates": ("la fenetre premier/dernier est une date "
                                       "d'ecriture, pas une date de collecte"),
               "depots": {}}
    compte = defaultdict(int)
    for d_id, f in fiches.items():
        f["fichiers"] = len(f["_srcs"])
        del f["_srcs"]
        f["tiers"] = sorted(f["tiers"])
        v, raison = verdict(f, lexical_lisible)
        f["verdict"], f["raison"] = v, raison
        compte[v] += 1
        rapport["depots"][d_id] = f
    rapport["par_verdict"] = dict(compte)

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    _dire("ecrit %s" % SORTIE)
    _dire("depots audites : %d (chunks rattaches %d, tranches illisibles %d, %.1fs)"
          % (len(fiches), lus, tranches_ko, rapport["duree_s"]))
    for v, n in sorted(compte.items(), key=lambda x: -x[1]):
        _dire("   %-20s %d" % (v, n))
    if not lexical_lisible:
        _dire("ATTENTION : index lexical illisible -> verdict LEXICAL_INCOMPLET "
              "NON EVALUE (aucun depot n'est declare sain sur ce critere)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
