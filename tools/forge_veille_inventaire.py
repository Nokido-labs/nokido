"""Inventaire du PATRIMOINE de veille — une passe, deportee, sans jointure.

__FORGE_COLOR__ = "memoire/inventaire"

POURQUOI CE MODULE. Le snapshot de `forge_memory_availability` publie un
`by_domain`, alors que la politique de paliers decide sur `(source, domain)`
(cf. `tier()`, copie fidele du trigger `forge_tier_guard`). Un `GROUP BY domain`
ne peut donc PAS dire combien de chaud et de froid vit dans un domaine : un meme
domaine porte du `http` (web-crawl, CHAUD) et du `gitingest` (external-lib,
froid). Ce module retablit l'axe reel.

CE QU'IL NE FAIT PAS. Aucune jointure sur une table FTS virtuelle (balayage par
ligne, 41 min et 2 195 Go mesures le 2026-09-03). Aucune lecture de `text` ni du
blob `embedding` : `typeof(embedding)` suffit et n'ouvre pas les pages overflow.
Aucune ecriture : connexion `mode=ro`.

DENOMINATEURS. Chaque compteur est publie avec ce qui a ete LU et ce qui a ete
ILLISIBLE. Une source absente d'un compteur n'est jamais presumee inexistante.

Usage : run action=run_job script=tools/forge_veille_inventaire.py lane=inventaire
Sortie : sandbox/inventaire_veille.json (+ progression dans le meme dossier)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_db_path import db_path  # noqa: E402

try:
    from nokido_agent.app.forge_memory_availability import VECTORISABLES, tier
except Exception:  # le module doit exister ; sans lui on ne classe pas a l'aveugle
    VECTORISABLES, tier = set(), None

SORTIE = ROOT / "sandbox" / "inventaire_veille.json"
PROGRES = ROOT / "sandbox" / "inventaire_veille.progress.json"
TRANCHE = 50_000
# Un catalogue de sources non borne peut faire enfler la RAM du job. La borne DIT
# combien elle ecarte, sinon le catalogue paraitrait complet (motif borne_trop_serree).
MAX_SOURCES = 400_000


def famille(source: str) -> str:
    """Regroupe une source par son EMETTEUR, pas par son chemin."""
    s = source or ""
    if s.startswith("http"):
        bouts = s.split("/")
        return bouts[2] if len(bouts) > 2 else "http:???"
    if ":" in s:
        return s.split(":", 1)[0]
    if "\\" in s or "/" in s:
        return s.replace("\\", "/").split("/", 1)[0]
    return s[:40] or "(vide)"


# Prefixes qui ne designent JAMAIS un depot : documentation, conversations,
# memoire interne, code du depot local. Sans cette liste, `docset` (912 809
# chunks) passerait pour le plus gros depot GitHub de la base.
# Suffixes qui trahissent un FICHIER, jamais un depot. Un nom de depot peut
# contenir un point (`OBOFoundry.github.io`, `llama.cpp`) : on ne rejette donc
# que sur une extension connue, pas sur la presence d'un point.
EXTENSIONS_FICHIER = {
    "py", "md", "json", "ts", "tsx", "js", "jsx", "txt", "yaml", "yml", "toml",
    "cfg", "ini", "sh", "ps1", "bat", "rs", "go", "java", "c", "h", "cpp", "hpp",
    "html", "css", "sql", "pdf", "csv", "lock", "log", "xml", "rb", "php",
}

NON_DEPOT = {
    "docset", "https", "http", "claude_docs", "qdrant_docs", "openrouter_docs",
    "deno_docs", "session", "anchor", "conv", "conv_claude", "conv_agy",
    "conv_claude_desktop", "mcp_result", "app", "tools", "ctf", "proxy_deno",
    "gitingest", "rfc", "memory", "sandbox", "docs", "tests", "(vide)",
}


def depot(source: str, domain: str) -> str | None:
    """Identite du DEPOT, quelle que soit la convention d'ecriture de la source.

    Deux conventions coexistent en base, et aucune vue ne les reunissait :
      `github:owner/repo/fichier`   -> famille "github", owner perdu dans la masse
      `owner_repo/chemin/fichier`   -> une famille PAR depot
    Les compter separement fait croire a deux patrimoines distincts.
    """
    s = source or ""
    if s.startswith("github:") or s.startswith("gh:"):
        reste = s.split(":", 1)[1].replace("\\", "/").split("/")
        if len(reste) >= 2:
            return "%s/%s" % (reste[0], reste[1])
        return reste[0] if reste and reste[0] else None
    if domain not in ("veille_code", "sdk_gitingest", "ext_repo"):
        return None
    tete = s.replace("\\", "/").split("/", 1)[0]
    tete = tete.split("#", 1)[0]

    # Les dumps `gitingest_veille_<depot>.txt` sont le SEUL cas ou un suffixe
    # `.txt` designe un depot : on le retire ICI, avant le filtre d'extension.
    # Le faire pour tout `.txt` faisait echapper n'importe quel fichier texte au
    # filtre -- `notes.txt` devenait un depot nomme `notes` (trouve par le NR
    # `test_un_fichier_du_code_local_n_est_pas_un_depot`, 2026-09-08).
    if tete.startswith("gitingest_veille_"):
        if tete.endswith(".txt"):
            tete = tete[:-4]
        tete = tete[len("gitingest_veille_"):]
        return tete or None

    # Un FICHIER n'est pas un depot. Mesure 2026-09-08 : sans ce filtre, 678 des
    # 899 "depots" etaient des modules du code local (`forge_rag_warmup.py` ...),
    # chacun compte comme un depot a un seul fichier, donc classe A_REFAIRE.
    # L'owner l'a dit : la veille EXTERNE, pas l'ingestion du code de Nokido.
    if "." in tete:
        queue = tete.rsplit(".", 1)[1].lower()
        if queue in EXTENSIONS_FICHIER:
            return None
    return tete or None if tete not in NON_DEPOT else None


def _dire(msg: str) -> None:
    print("[inventaire] %s" % msg, flush=True)


def parcourir(con: sqlite3.Connection, table: str, avec_date: bool) -> dict:
    """Une passe par tranches de rowid. Reprend sur erreur de tranche."""
    cols = "rowid, source, domain, typeof(embedding)"
    if avec_date:
        cols += ", substr(ingested_at,1,7)"
    borne = con.execute("SELECT max(rowid) FROM %s" % table).fetchone()[0] or 0

    par_tier = defaultdict(lambda: {"n": 0, "vec": 0})
    par_famille = defaultdict(lambda: {"n": 0, "vec": 0, "domaines": Counter()})
    par_domaine = defaultdict(lambda: {"n": 0, "vec": 0})
    par_mois = Counter()
    par_depot = defaultdict(lambda: {"n": 0, "vec": 0, "fichiers": 0})
    sources = defaultdict(lambda: {"n": 0, "vec": 0})
    lus = illisibles = tranches_ko = 0
    sources_ecartees = 0
    t0 = time.time()

    bas = 0
    while bas <= borne:
        haut = bas + TRANCHE
        try:
            curseur = con.execute(
                "SELECT %s FROM %s WHERE rowid >= ? AND rowid < ?" % (cols, table),
                (bas, haut),
            )
            lignes = curseur.fetchall()
        except sqlite3.Error as exc:
            # Une tranche illisible est COMPTEE, jamais avalee : sans cela la
            # couverture serait surestimee en silence.
            tranches_ko += 1
            _dire("tranche %d-%d ILLISIBLE : %s" % (bas, haut, str(exc)[:120]))
            bas = haut
            continue

        for ligne in lignes:
            src = ligne[1] or ""
            dom = ligne[2] or ""
            a_vec = 1 if (ligne[3] or "null") != "null" else 0
            if tier is None:
                illisibles += 1
                continue
            t = tier(src, dom)
            lus += 1

            par_tier[t]["n"] += 1
            par_tier[t]["vec"] += a_vec
            fam = famille(src)
            par_famille[fam]["n"] += 1
            par_famille[fam]["vec"] += a_vec
            par_famille[fam]["domaines"][dom] += 1
            par_domaine[dom]["n"] += 1
            par_domaine[dom]["vec"] += a_vec
            d_id = depot(src, dom)
            if d_id:
                par_depot[d_id]["n"] += 1
                par_depot[d_id]["vec"] += a_vec
                par_depot[d_id]["fichiers"] += 1
            if avec_date and len(ligne) > 4 and ligne[4]:
                par_mois[ligne[4]] += 1
            if len(sources) < MAX_SOURCES:
                sources[src]["n"] += 1
                sources[src]["vec"] += a_vec
            elif src not in sources:
                sources_ecartees += 1

        bas = haut
        if (bas // TRANCHE) % 10 == 0:
            avance = {"table": table, "rowid": bas, "borne": borne, "lus": lus,
                      "sources": len(sources), "s": round(time.time() - t0, 1)}
            PROGRES.write_text(json.dumps(avance), encoding="utf-8")
            _dire("%(table)s rowid %(rowid)d/%(borne)d lus=%(lus)d" % avance)

    return {
        "table": table,
        "borne_rowid": borne,
        "lus": lus,
        "illisibles": illisibles,
        "tranches_illisibles": tranches_ko,
        "duree_s": round(time.time() - t0, 1),
        "par_tier": {k: dict(v) for k, v in par_tier.items()},
        "par_domaine": {k: dict(v) for k, v in sorted(
            par_domaine.items(), key=lambda x: -x[1]["n"])},
        "par_famille": {k: {"n": v["n"], "vec": v["vec"],
                            "domaines": dict(v["domaines"].most_common(6))}
                        for k, v in sorted(par_famille.items(),
                                           key=lambda x: -x[1]["n"])},
        "familles_total": len(par_famille),
        "depots_total": len(par_depot),
        "depots": {k: dict(v) for k, v in sorted(
            par_depot.items(), key=lambda x: -x[1]["n"])},
        "par_mois": dict(sorted(par_mois.items())),
        "sources_distinctes": len(sources),
        "sources_ecartees_par_la_borne": sources_ecartees,
        "sources": {k: dict(v) for k, v in sorted(
            sources.items(), key=lambda x: -x[1]["n"])[:8000]},
    }


def colonnes(con: sqlite3.Connection, table: str) -> list:
    try:
        return [r[1] for r in con.execute("PRAGMA table_info(%s)" % table)]
    except sqlite3.Error:
        return []


def main() -> int:
    if tier is None:
        _dire("ABANDON : forge_memory_availability.tier illisible, "
              "classer sans lui fabriquerait une seconde verite")
        return 2

    chemin = str(db_path())
    _dire("base %s" % chemin)
    con = sqlite3.connect("file:%s?mode=ro" % chemin.replace("\\", "/"), uri=True,
                          timeout=60)
    con.execute("PRAGMA query_only = ON")
    con.execute("PRAGMA cache_size = -32000")  # 32 Mo, on streame

    rapport = {"genere_le": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "base": chemin,
               "vectorisables": sorted(VECTORISABLES),
               "tables": {}}

    presentes = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    cibles = ["rag_chunks", "rag_chunks_cold_storage", "rag_chunks_dedup_archive"]
    for table in cibles:
        if table not in presentes:
            rapport["tables"][table] = {"etat": "ABSENTE"}
            _dire("%s ABSENTE" % table)
            continue
        cols = colonnes(con, table)
        _dire("=== %s (colonnes: %s) ===" % (table, ",".join(cols[:8])))
        rapport["tables"][table] = parcourir(con, table, "ingested_at" in cols)

    con.close()
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(rapport, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    _dire("ecrit %s" % SORTIE)

    for table, bloc in rapport["tables"].items():
        if bloc.get("etat") == "ABSENTE":
            continue
        _dire("%s : lus=%d sources=%d familles=%d tranches_illisibles=%d en %ss"
              % (table, bloc["lus"], bloc["sources_distinctes"],
                 bloc["familles_total"], bloc["tranches_illisibles"],
                 bloc["duree_s"]))
        for t, v in sorted(bloc["par_tier"].items(), key=lambda x: -x[1]["n"]):
            _dire("   %-16s n=%-9d vec=%-9d %s"
                  % (t, v["n"], v["vec"],
                     "CHAUD" if t in VECTORISABLES else "froid"))
        _dire("   DEPOTS distincts : %d" % bloc.get("depots_total", 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
