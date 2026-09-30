"""Moisson de la veille par AXE d'organe — extraits bruts, aucun jugement.

__FORGE_COLOR__ = "memoire/moisson : extraction de la veille par axe d'organe"

POURQUOI UN MODULE DE PLUS (anti-dup verifie le 2026-09-08, 45 modules de veille
lus). `forge_knowledge_harvester` extrait du RAISONNEMENT depuis les taches
REUSSIES (`harvest_on_success`) et en fait des gabarits ; `forge_veille_variete_organe`
QUALIFIE un document entrant en le comparant au centroide d'un organe ;
`forge_veille_digest` resume un lot frais. Aucun n'interroge le corpus DEJA
INGERE par une question d'ingenierie pour en ressortir ce qui sert un chantier.

CE QU'IL NE FAIT PAS. Il n'evalue pas et ne classe pas : le tri est un travail de
lecture. Un script qui trancherait ici serait un juge LLM de plus dans la voie
critique, ce que le manifeste interdit.

PRECAUTIONS. Le canal dense peut etre eteint : son absence est DITE par axe
(`INDISPONIBLE`), jamais rendue comme « aucun resultat ». Les sources internes
(`conv_*`, `session:*`, `mcp_result:*`) sont ecartees : les inclure ferait lire a
l'instrument son propre vocabulaire, motif paye six fois en trois jours.

Usage : run action=run_job script=tools/forge_veille_moisson.py lane=inventaire
Sortie : sandbox/veille_moisson.json + sandbox/veille_moisson.md

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `extrait_porteur` — Le texte A PARTIR de la premiere vraie phrase (liens retires).
- `porteur` — Le morceau contient-il au moins UNE vraie phrase hors liens de navigation ?
- `source_propre` — Source appartenant a l'owner (depot ou page) — a ne pas moissonner comme veille.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.request as _u
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_db_path import db_path  # noqa: E402

SORTIE = ROOT / "sandbox" / "veille_moisson.json"
LISIBLE = ROOT / "sandbox" / "veille_moisson.md"
PAR_DEPOT_JSON = ROOT / "sandbox" / "veille_par_depot.json"
PAR_DEPOT_MD = ROOT / "sandbox" / "veille_par_depot.md"

# Fichiers qui portent l'INTENTION d'un depot (pourquoi, comment, quels choix),
# par opposition a son code. Un depot rend ses enseignements par ceux-la.
DOCS_STRUCTURANTS = re.compile(
    r"(readme|architecture|design|spec|adr|rfc|decision|cheatsheet|"
    r"best[_-]?practice|contributing|principle|concept|overview|"
    r"guide|tutorial|whitepaper|manifest)", re.I)
TRANCHE_DEPOT = 50_000
EXTRAITS_PAR_DEPOT = 3
EMBED = "http://127.0.0.1:8099/v1/embeddings"
QDRANT = "http://127.0.0.1:6333/collections/nokido_sovereign_rag/points/search"
EXTRAIT = 900
PREFIXES_EXCLUS = ("conv_", "session:", "anchor", "mcp_result:", "memory:")
# Comptes de l'OWNER : ses depots publics (La-Forge...) portent la doctrine de Nokido.
# Les moissonner comme veille EXTERNE fait relire au corps son propre vocabulaire
# (mesure veille lot_C_05, 2026-09-24). Ecartes ET comptes (`ecartes_sources_propres`).
COMPTES_OWNER = ("user",)
_LIEN_MD = re.compile(r"\[[^\]]*\]\([^)]*\)")
_PHRASE = re.compile(r"[A-Za-zÀ-ÿ][^.!?]{60,}[.!?]")


_FIN_REELLE = re.compile(r"(?<=[.!?])\s+")
_MOT = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
_MOTS_MIN = 10


def _premiere_phrase(texte: str) -> tuple[str, int | None]:
    """(texte sans liens, position de la premiere VRAIE phrase ou None).

    Une vraie phrase : >= 10 mots, se termine par . ! ? SUIVI d'un blanc ou de la fin
    (le point de `Huggingface.js` ou de `v1.2` n'en est pas une), sans separateur de menu
    (`·`, `|`). MESURE du 2026-09-24 apres le 1er correctif : l'ancien motif (60 caracteres
    jusqu'au premier point, quel qu'il soit) acceptait les menus -- 4,3 % de pages HF
    « sans corps » au compteur, ~37 % a un critere de vraie phrase.
    """
    t = _LIEN_MD.sub(" ", texte or "")
    pos = 0
    for morceau in _FIN_REELLE.split(t):
        debut = t.find(morceau, pos)
        pos = debut + len(morceau)
        m = morceau.strip()
        if (m[-1:] in ".!?" and len(_MOT.findall(m)) >= _MOTS_MIN
                and "·" not in m and "|" not in m):
            return t, debut + (len(morceau) - len(morceau.lstrip()))
    return t, None


def porteur(texte: str) -> bool:
    """Le morceau contient-il au moins UNE vraie phrase hors liens de navigation ?

    MESURE du 2026-09-24 (13 lots, 2 728 pages) : le premier morceau d'une page de
    documentation est son MENU pour 73,2 % des pages huggingface.co/docs, contre
    4,2 % pour arXiv. Critere resserre le meme jour : voir `_premiere_phrase`.
    """
    return _premiere_phrase(texte)[1] is not None


def extrait_porteur(texte: str) -> str:
    """Le texte A PARTIR de la premiere vraie phrase (liens retires) : le lecteur de la
    fiche voit le corps, plus le menu qui le precedait dans le meme morceau."""
    t, i = _premiere_phrase(texte)
    return t[i:] if i is not None else texte


def source_propre(source: str, depot_id: str = "") -> bool:
    """Source appartenant a l'owner (depot ou page) — a ne pas moissonner comme veille."""
    s = (source or "").lower()
    d = (depot_id or "").lower()
    for c in COMPTES_OWNER:
        if ("github.com/%s/" % c) in s or s.startswith(("github:%s/" % c, "%s_" % c)) \
                or d.startswith(c + "/"):
            return True
    return False

AXES = [
    ("retrieval_hybride",
     "fusionner un classement lexical et un classement vectoriel puis reranker",
     '"reciprocal rank fusion" OR "hybrid search" OR "late interaction"'),
    ("evaluation_retrieval",
     "mesurer la qualite d un systeme de recuperation recall precision",
     '"recall@k" OR ndcg OR "mean reciprocal rank" OR "retrieval evaluation"'),
    ("incertitude",
     "estimer la confiance d un modele et detecter une hallucination",
     '"semantic entropy" OR "uncertainty quantification" OR "confidence calibration"'),
    ("memoire_agent",
     "memoire persistante d un agent consolidation et oubli entre sessions",
     '"memory consolidation" OR "episodic memory" OR "catastrophic forgetting"'),
    ("orchestration",
     "orchestrer plusieurs agents delegation handoff et contrat de tache",
     '"multi-agent" AND (handoff OR orchestration OR "task decomposition")'),
    ("tests",
     "ecrire des tests qui ne peuvent pas reussir a tort doublures et simulation",
     '"deterministic simulation" OR "property-based" OR "flaky test" OR "test double"'),
    ("regulation",
     "reguler la charge backpressure hysteresis et file bornee",
     'backpressure OR hysteresis OR "circuit breaker" OR "rate limit"'),
    ("observabilite",
     "observer un systeme vivant heartbeat liveness et trace distribuee",
     '"health check" OR liveness OR "distributed tracing" OR "structured logging"'),
    ("securite",
     "confiner l execution capacites permissions et bac a sable",
     'sandbox AND (capability OR "least privilege" OR seccomp OR "trust boundary")'),
    ("auto_amelioration",
     "un systeme qui modifie son propre code et evalue ses variantes",
     '"self-improving" OR "genetic programming" OR "evolutionary search"'),
    ("ingestion",
     "decouper un document en chunks et conserver la provenance",
     '"chunking strategy" OR "semantic chunking" OR "document provenance"'),
    ("cout_llm",
     "reduire le cout d appel d un modele cache de prompt et cascade",
     '"prompt caching" OR "model cascade" OR "token budget"'),
]


def _dire(m: str) -> None:
    print("[moisson] %s" % m, flush=True)


def _post(url: str, charge: dict, delai: int = 45):
    req = _u.Request(url, data=json.dumps(charge).encode(),
                     headers={"Content-Type": "application/json"})
    return json.loads(_u.urlopen(req, timeout=delai).read())


def embed(texte: str):
    """Vecteur de la question, ou None si le canal est eteint (DIT, pas devine)."""
    try:
        return _post(EMBED, {"input": [texte], "model": "bge-m3"})["data"][0]["embedding"]
    except Exception as exc:
        _dire("canal dense indisponible : %s" % str(exc)[:100])
        return None


def interne(source: str) -> bool:
    s = (source or "").lower()
    return any(s.startswith(p) for p in PREFIXES_EXCLUS)


def dense(question: str, con: sqlite3.Connection, k: int = 6):
    vec = embed(question)
    if vec is None:
        return None                       # None = INDISPONIBLE, [] = aucun resultat
    try:
        res = _post(QDRANT, {"vector": {"name": "dense", "vector": vec},
                             "limit": k * 4, "with_payload": True})["result"]
    except Exception as exc:
        _dire("qdrant indisponible : %s" % str(exc)[:100])
        return None
    sortie = []
    for h in res:
        cid = (h.get("payload") or {}).get("chunk_id")
        if not cid:
            continue
        ligne = con.execute(
            "SELECT source, substr(text,1,%d) FROM rag_chunks WHERE id=?" % EXTRAIT,
            (cid,)).fetchone()
        if not ligne or interne(ligne[0]) or len(ligne[1] or "") < 200:
            continue
        sortie.append({"score": round(h["score"], 4), "source": ligne[0],
                       "texte": ligne[1]})
        if len(sortie) >= k:
            break
    return sortie


def lexical(expr: str, con: sqlite3.Connection, k: int = 6):
    try:
        lignes = con.execute(
            "SELECT source, substr(text,1,%d) FROM rag_fts WHERE rag_fts MATCH ? "
            "ORDER BY bm25(rag_fts) LIMIT ?" % EXTRAIT, (expr, k * 5)).fetchall()
    except sqlite3.Error as exc:
        _dire("lexical illisible sur '%s' : %s" % (expr[:40], str(exc)[:90]))
        return None
    return [{"source": s, "texte": t} for s, t in lignes
            if not interne(s) and len(t or "") >= 200][:k]


def hote(source: str) -> str | None:
    """Hote d'une source web, ou None si ce n'est pas une page."""
    s = source or ""
    if not s.startswith("http"):
        return None
    bouts = s.split("/")
    return bouts[2] if len(bouts) > 2 else None


def par_depot(con: sqlite3.Connection) -> dict:
    """Une passe : ce que chaque VEILLE enseigne, depot ou page.

    Deux natures, deux regles, et c'est le point : un depot s'enseigne par ses
    fichiers d'INTENTION (README, architecture, ADR) et pas par son code ; une
    PAGE n'a pas de fichiers, son premier morceau porte le titre et le resume.
    Appliquer le filtre des depots aux pages les aurait toutes ecartees — c'est
    ce que faisait la premiere version, qui laissait 51 494 chunks web et 157
    hotes hors de l'inventaire (releve par l'owner le 2026-09-08).

    Les bornes disent ce qu'elles ecartent : un resultat borne en silence
    paraitrait exhaustif (motif `borne_trop_serree`).
    """
    from nokido_agent.tools.forge_veille_inventaire import depot as _depot

    borne = con.execute("SELECT max(rowid) FROM rag_chunks").fetchone()[0] or 0
    retenus: dict[str, list] = defaultdict(list)
    ecartes: dict[str, int] = defaultdict(int)
    pages: dict[str, dict] = {}
    pages_par_hote: dict[str, int] = defaultdict(int)
    lus = candidats = tranches_ko = propres = 0
    t0 = time.time()

    bas = 0
    while bas <= borne:
        haut = bas + TRANCHE_DEPOT
        try:
            lignes = con.execute(
                "SELECT source, domain, substr(text,1,%d) FROM rag_chunks "
                "WHERE rowid >= ? AND rowid < ?" % EXTRAIT, (bas, haut)).fetchall()
        except sqlite3.Error as exc:
            tranches_ko += 1
            _dire("tranche %d-%d ILLISIBLE : %s" % (bas, haut, str(exc)[:100]))
            bas = haut
            continue
        for src, dom, txt in lignes:
            lus += 1
            src = src or ""
            if len(txt or "") < 300:
                continue
            h = hote(src)
            if h:
                if source_propre(src):
                    propres += 1
                    continue
                # Une page = une source. On retient le PREMIER morceau PORTEUR
                # (une phrase hors liens) et on DIT lequel. L'ancienne regle
                # (« le premier morceau porte le titre et le resume ») est vraie
                # pour un article, fausse pour une page de documentation, dont le
                # premier morceau est le MENU (73,2 % des pages HF, 24/09).
                p = pages.get(src)
                if p is None:
                    _porte = porteur(txt)
                    pages[src] = {"hote": h, "texte": extrait_porteur(txt) if _porte else txt,
                                  "porteur": _porte, "morceaux_vus": 1, "morceau_retenu": 1}
                    pages_par_hote[h] += 1
                else:
                    p["morceaux_vus"] += 1
                    if not p["porteur"] and porteur(txt):
                        p.update(texte=extrait_porteur(txt), porteur=True,
                                 morceau_retenu=p["morceaux_vus"])
                continue
            d_id = _depot(src, dom or "")
            if d_id and source_propre(src, d_id):
                propres += 1
                continue
            if not d_id or not DOCS_STRUCTURANTS.search(src):
                continue
            candidats += 1
            if len(retenus[d_id]) < EXTRAITS_PAR_DEPOT:
                retenus[d_id].append({"source": src, "texte": txt})
            else:
                ecartes[d_id] += 1
        bas = haut
        if (bas // TRANCHE_DEPOT) % 20 == 0:
            _dire("par-source rowid %d/%d depots=%d pages=%d"
                  % (bas, borne, len(retenus), len(pages)))

    return {"depots": {k: {"extraits": v, "ecartes": ecartes.get(k, 0)}
                       for k, v in retenus.items()},
            "pages": pages,
            "pages_par_hote": dict(sorted(pages_par_hote.items(),
                                          key=lambda x: -x[1])),
            "chunks_lus": lus, "candidats_structurants": candidats,
            "tranches_illisibles": tranches_ko,
            # Ce qui est ecarte ou degrade est COMPTE, jamais tu.
            "pages_sans_corps": sum(1 for p in pages.values() if not p.get("porteur")),
            "ecartes_sources_propres": propres,
            "borne_par_depot": EXTRAITS_PAR_DEPOT,
            "duree_s": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Moisson de la veille")
    ap.add_argument("--par-depot", action="store_true",
                    help="extrait les documents structurants de CHAQUE depot")
    args = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % str(db_path()).replace("\\", "/"),
                          uri=True, timeout=45)
    con.execute("PRAGMA query_only = ON")

    if args.par_depot:
        con.execute("PRAGMA cache_size = -48000")
        r = par_depot(con)
        con.close()
        PAR_DEPOT_JSON.write_text(json.dumps(r, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        lignes = ["# Ce que chaque veille enseigne — depots ET pages", "",
                  "%d depots et %d pages sur %d hotes ; %d chunks lus, "
                  "%d documents structurants, %d tranches illisibles, %ss."
                  % (len(r["depots"]), len(r["pages"]), len(r["pages_par_hote"]),
                     r["chunks_lus"], r["candidats_structurants"],
                     r["tranches_illisibles"], r["duree_s"]),
                  "", "Borne : %d extraits par depot ; le nombre d'ecartes est donne "
                  "pour chacun. Une page rend son premier morceau PORTEUR (une phrase "
                  "hors liens) ; %d page(s) n'en ont aucun (menu seul) ; %d morceau(x) "
                  "de sources de l'owner ecartes."
                  % (r["borne_par_depot"], r["pages_sans_corps"],
                     r["ecartes_sources_propres"]), "",
                  "## Pages par hote", ""]
        for h, n in list(r["pages_par_hote"].items())[:60]:
            lignes.append("- **%s** — %d page(s)" % (h, n))
        lignes.append("")
        lignes.append("## Pages")
        lignes.append("")
        for src, p in sorted(r["pages"].items(), key=lambda x: x[1]["hote"]):
            lignes.append("- `%s`" % src)
            lignes.append("  > %s" % p["texte"].replace("\n", " ")[:600])
        lignes.append("")
        lignes.append("## Depots")
        lignes.append("")
        for d_id, bloc in sorted(r["depots"].items(),
                                 key=lambda x: -len(x[1]["extraits"])):
            lignes.append("## %s" % d_id)
            if bloc["ecartes"]:
                lignes.append("_%d autre(s) document(s) structurant(s) non montre(s)._"
                              % bloc["ecartes"])
            for e in bloc["extraits"]:
                lignes.append("- `%s`" % e["source"])
                lignes.append("  > %s" % e["texte"].replace("\n", " ")[:800])
            lignes.append("")
        PAR_DEPOT_MD.write_text("\n".join(lignes), encoding="utf-8")
        _dire("par-depot : %d depots, %d candidats, %ss -> %s"
              % (len(r["depots"]), r["candidats_structurants"], r["duree_s"],
                 PAR_DEPOT_MD.name))
        return 0

    rapport = {"genere_le": time.strftime("%Y-%m-%dT%H:%M:%S"), "axes": {}}
    t0 = time.time()

    for nom, question, expr in AXES:
        _dire("axe %s" % nom)
        d = dense(question, con)
        lx = lexical(expr, con)
        rapport["axes"][nom] = {
            "question": question, "expression_lexicale": expr,
            "dense": "INDISPONIBLE" if d is None else d,
            "lexical": "ILLISIBLE" if lx is None else lx,
        }
        _dire("   dense=%s lexical=%s"
              % ("INDISPO" if d is None else len(d),
                 "ILLISIBLE" if lx is None else len(lx)))
    con.close()

    rapport["duree_s"] = round(time.time() - t0, 1)
    SORTIE.write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")

    lignes = ["# Moisson de la veille par axe", "",
              "Genere le %s en %ss." % (rapport["genere_le"], rapport["duree_s"]), ""]
    for nom, bloc in rapport["axes"].items():
        lignes += ["## %s" % nom, "_%s_" % bloc["question"]]
        for canal in ("dense", "lexical"):
            items = bloc[canal]
            lignes.append("")
            if isinstance(items, str):
                lignes.append("**%s : %s**" % (canal, items))
                continue
            lignes.append("**%s** (%d)" % (canal, len(items)))
            for it in items:
                lignes.append("- `%s`" % it["source"])
                lignes.append("  > %s" % it["texte"].replace("\n", " ")[:700])
        lignes.append("")
    LISIBLE.write_text("\n".join(lignes), encoding="utf-8")
    _dire("ecrit %s et %s (%ss)" % (SORTIE.name, LISIBLE.name, rapport["duree_s"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
