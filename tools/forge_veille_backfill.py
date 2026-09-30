"""
tools/forge_veille_backfill.py — rattrapage du corpus de veille DEJA ingere
(owner 2026-07-25 : « reverifie les veilles passees si elles sont incompletes »).

CONSTAT MESURE : 1377 sources pour 1429 chunks dans `watch_veille`, soit 1,04 chunk
par source -- l'ancien `_step_ingest` gardait UN chunk tronque a 3000 caracteres par
source (474 collent au plafond, signature de la troncature). Le contenu etait donc
disponible et jete. Depuis les correctifs du jour, `crawl_url` route les notices
academiques vers le texte integral et `_step_ingest` chunke le corps : ce script
rejoue le meme chemin sur l'ANCIEN corpus.

REUTILISE, ne reecrit rien : `forge_crawl_tool.crawl_url` (routage texte-integral +
tier PDF) et `forge_watch_agent._step_ingest` (gardes 1-4, chunking, embed, rag_fts).

PRUDENCE (dans cet ordre) :
  - dry-run par DEFAUT ; il faut `--apply` pour ecrire ;
  - borne `--limit` (defaut 10) : un backfill massif = des centaines de crawls ;
  - on ne remplace QUE si le nouveau contenu est nettement plus riche
    (`--min-gain`, defaut x3) -- sinon on ne touche pas a l'existant ;
  - l'ancien chunk unique est supprime APRES insertion des nouveaux, et seulement
    si des nouveaux ont bien ete ecrits (jamais de fenetre sans donnee) ;
  - `--source-like` pour cibler (defaut : arxiv.org/abs = gain garanti mesure x53).

Doit tourner en run_job online : le crawl exige internet, l'embed exige le loopback.
"""
from __future__ import annotations

__FORGE_COLOR__ = "digestif/veille : rattrapage du corpus de veille deja ingere"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import re
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "app",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_THEME_RE = re.compile(r"Th[eè]me:\s*(.+)")


def _candidates(conn, source_like: str, max_len: int, redo: bool = False) -> list[dict]:
    """Sources eligibles au rattrapage.

    Par defaut : celles a UN SEUL chunk (jamais chunkees) et sous `max_len`
    (signature de la troncature a 3000). Avec `redo` : toute source du filtre, y
    compris deja chunkee -- utile quand l'EXTRACTION s'ameliore et qu'il faut
    repasser (cas mesure : les 12 premieres sources ont ete traitees avant le
    correctif x_tolerance de pdfplumber, donc avec des mots colles).
    """
    having = "" if redo else " HAVING n = 1 AND maxlen <= ?"
    params: tuple = (source_like,) if redo else (source_like, max_len)
    rows = conn.execute(
        "SELECT source, COUNT(*) AS n, MAX(LENGTH(text)) AS maxlen,"
        "       SUM(LENGTH(text)) AS totlen,"
        "       MIN(id) AS one_id, MIN(text) AS one_text"
        "  FROM rag_chunks WHERE domain='watch_veille' AND source LIKE ?"
        "  GROUP BY source" + having +
        "  ORDER BY totlen ASC", params).fetchall()
    out = []
    for r in rows:
        m = _THEME_RE.search(r["one_text"] or "")
        # En redo, l'en-tete a pu etre retiree (chunks depollues) : on retombe alors
        # sur le role_hint, seule source restante du theme.
        theme = m.group(1).strip() if m else ""
        if not theme:
            rh = conn.execute(
                "SELECT role_hint FROM rag_chunks WHERE source=? AND role_hint IS NOT NULL"
                " LIMIT 1", (r["source"],)).fetchone()
            if rh and (rh["role_hint"] or "").startswith("veille:"):
                theme = rh["role_hint"][len("veille:"):].strip()
        out.append({"url": r["source"], "chunk_id": r["one_id"], "n": r["n"],
                    "len": r["maxlen"], "total_len": r["totlen"] or r["maxlen"],
                    "theme": theme})
    return out


def _maybe_reexec_free_threaded(argv: list[str]) -> None:
    """Se relancer sous `${PY314T}` (free-threaded) quand c'est utile ET possible.

    Ce workload est massivement parallelisable : chaque source = un crawl (I/O, donc
    beaucoup d'attente reseau) + un chunking (CPU pur). Le bench maison du 2026-05-29
    donne **6,3x @ 8 threads** en pur Python pour le free-threaded, la ou `${PYTHON}` et
    `${PY314}` plafonnent sur le GIL (`${PY314}` REGRESSE meme sur mix a 4+ threads).
    Cf. `[vars]` de `services.toml`.

    On ne re-exec PAS a l'aveugle. DEUX conditions sont verifiees, pas supposees :

    1. PY314T est un env SEPARE : ses roues doivent etre installees (mesure : il a
       longtemps eu `psutil` mais NI `trafilatura` NI `pdfplumber`).
    2. **Le GIL doit RESTER desactive apres l'import des dependances.** C'est le point
       decisif, mesure le 2026-07-25 : `lxml.etree` (dont depend trafilatura) n'est pas
       declare sur sans GIL, donc CPython **reactive le GIL a son chargement** --
       `sys._is_gil_enabled()` passe de False a True. Le free-threaded ne rapporte alors
       RIEN pour ce workload : re-exec ou pas, on retombe sur un interpreteur a GIL.

    On NE force PAS `PYTHON_GIL=0` pour passer outre : cela ferait tourner lxml sans le
    verrou qu'il exige, au risque d'une corruption ou d'un segfault silencieux au milieu
    d'un rattrapage de plusieurs heures -- un gain nul ne justifie pas ce risque.
    Opt-in explicite pour qui veut l'assumer : `LAFORGE_BACKFILL_FORCE_FT=1`.

    Le parallelisme reste acquis dans tous les cas via le pool de threads : ce workload
    est domine par l'attente reseau du crawl et par pdfium (code C qui relache le GIL),
    pas par du Python CPU-bound.
    """
    import os
    import subprocess
    import sysconfig

    if os.environ.get("LAFORGE_BACKFILL_NO_REEXEC") == "1":
        return
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        return  # deja free-threaded
    py = Path(os.path.expanduser(r"~/miniforge3/envs/laforge_py314t/python.exe"))
    if not py.is_file():
        return
    force = os.environ.get("LAFORGE_BACKFILL_FORCE_FT") == "1"
    probe = subprocess.run(
        [str(py), "-c",
         "import trafilatura, pdfplumber, psutil, sys; print(int(sys._is_gil_enabled()))"],
        capture_output=True, text=True, errors="replace", timeout=120)
    if probe.returncode != 0:
        print(f"[backfill] PY314T present mais deps manquantes -> on reste sur "
              f"{sys.executable} (parallelisme I/O conserve). Detail: "
              f"{(probe.stderr or '').strip().splitlines()[-1][:120] if probe.stderr else '?'}",
              flush=True)
        return
    gil_reactive = (probe.stdout or "").strip().endswith("1")
    if gil_reactive and not force:
        print("[backfill] PY314T dispo mais le GIL est REACTIVE par lxml (dependance de "
              "trafilatura) : aucun gain CPU a attendre. On reste sur l'interpreteur "
              "courant plutot que de forcer PYTHON_GIL=0 (lxml n'est pas declare sur "
              "sans GIL). Opt-in : LAFORGE_BACKFILL_FORCE_FT=1.", flush=True)
        return
    print(f"[backfill] re-exec FREE-THREADED sous {py}"
          f"{' (FORCE, GIL=0 assume)' if force else ''}", flush=True)
    env = dict(os.environ, LAFORGE_BACKFILL_NO_REEXEC="1")
    if force:
        env["PYTHON_GIL"] = "0"
    r = subprocess.run([str(py), str(Path(__file__).resolve())] + argv, env=env)
    raise SystemExit(r.returncode)


_IGNOREES_PATH = Path(__file__).resolve().parent.parent / "sandbox" / "veille_backfill_ignorees.json"
_IGNOREES_TTL_S = float(os.environ.get("LAFORGE_VEILLE_IGNOREES_TTL_S", str(7 * 86400)))


def _charger_ignorees(chemin: Path = _IGNOREES_PATH) -> dict:
    """{url: {"raison", "ts"}} — vide si absent ; un fichier ILLISIBLE est dit."""
    if not chemin.exists():
        return {}
    try:
        import json as _j
        d = _j.loads(chemin.read_text(encoding="utf-8") or "{}")
        return d if isinstance(d, dict) else {}
    except Exception as e:  # noqa: BLE001
        print(f"[backfill] memoire des ignorees ILLISIBLE ({type(e).__name__}) : on repart sans",
              flush=True)
        return {}


def _filtrer_ignorees(cands: list[dict], ignorees: dict, ttl_s: float = _IGNOREES_TTL_S,
                      now: float | None = None) -> tuple[list[dict], int]:
    """Retire les candidats ignores il y a moins de ttl_s. Rend (retenus, n_ecartes).

    Mesure 2026-09-05 (lots GitHub) : 12 sources ignorees (gain insuffisant, depot
    trop gros, fetch KO) revenaient en TETE de chaque lot de 40 — l'ordre `totlen
    ASC` est stable — et un « depot trop gros » coute 13 min de telechargement
    avant son refus. Une memoire par url, avec date : une ignoree redevient
    candidate apres le TTL (l'extraction peut s'ameliorer), ou tout de suite
    avec --redo.
    """
    import time as _t
    now = _t.time() if now is None else now
    out, n = [], 0
    for c in cands:
        e = ignorees.get(c.get("url", ""))
        if e and (now - float(e.get("ts", 0) or 0)) < ttl_s:
            n += 1
            continue
        out.append(c)
    return out, n


def _noter_ignoree(ignorees: dict, url: str, raison: str, chemin: Path = _IGNOREES_PATH) -> None:
    import json as _j
    import time as _t
    ignorees[url] = {"raison": (raison or "")[:160], "ts": _t.time()}
    try:
        tmp = chemin.with_suffix(".tmp")
        tmp.write_text(_j.dumps(ignorees, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(chemin)
    except Exception as e:  # noqa: BLE001
        print(f"[backfill] memoire des ignorees NON ecrite ({type(e).__name__}: {e})", flush=True)


def _est_depot_github(url: str) -> bool:
    """`https://github.com/owner/repo[...]` — et rien d'autre (pas gist, pas raw)."""
    import re as _re
    return bool(_re.search(r"^https?://(www\.)?github\.com/[^/\s]+/[^/\s#?]+", url or ""))


# Suffixes de DONNEES/config que l'ingesteur de depot garde : utiles petits (un
# pyproject, un package.json), du bruit lexical gros (un modele JSON de 43 Ko).
_GH_DATA_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
_GH_DATA_MAX_CHARS = int(os.environ.get("LAFORGE_VEILLE_GH_DATA_MAX", "8000"))
# ~700 chars par chunk dans l'ingesteur : le budget aligne le depot sur le cap
# veille (LAFORGE_VEILLE_MAX_CHUNKS, 400 par source) -- approximatif, et il le DIT.
_GH_CHARS_PAR_CHUNK = 700


def _selection_github(fichiers: list[tuple[str, str]],
                      max_chunks: int | None = None) -> tuple[list[tuple[str, str]], dict]:
    """Ce qu'on garde d'un depot pour la VEILLE, et ce qu'on ecarte, compte.

    Mesure 2026-09-05 (job_3ed9b031e735) : `open-physiology/apinatomy-models`,
    22 fichiers de ~43 Ko en moyenne -> 1 353 chunks de JSON ; `hxtorch`, 114 .py
    -> 917 chunks. L'ingesteur de depot (`forge_ingest_github_repo.index`) ne
    connait ni le cap veille (400 chunks/source, `_INGEST_MAX_CHUNKS`) ni la
    difference prose/donnees : sur 186 depots, 100 k+ chunks dans une base gelee.
    Regles, dans l'ordre : README et .md/.txt d'abord, puis le code par taille
    croissante ; un fichier de donnees > _GH_DATA_MAX_CHARS est ecarte ; le budget
    total = max_chunks x ~700 chars. Fonction PURE (testable sans reseau ni base).
    """
    if max_chunks is None:
        max_chunks = int(os.environ.get("LAFORGE_VEILLE_MAX_CHUNKS", "400"))
    budget = max(1, max_chunks) * _GH_CHARS_PAR_CHUNK
    ecartes = {"donnees_volumineuses": 0, "cap_depot": 0}

    def _cle(f):
        nom = f[0].replace("\\", "/").lower()
        base = nom.rsplit("/", 1)[-1]
        rang = 0 if base.startswith("readme") else (1 if base.endswith((".md", ".txt")) else 2)
        return (rang, len(f[1]))

    gardes: list[tuple[str, str]] = []
    for nom, texte in sorted(fichiers, key=_cle):
        sfx = Path(nom).suffix.lower()
        if sfx in _GH_DATA_SUFFIXES and len(texte) > _GH_DATA_MAX_CHARS:
            ecartes["donnees_volumineuses"] += 1
            continue
        if len(texte) > budget:
            ecartes["cap_depot"] += 1
            continue
        gardes.append((nom, texte))
        budget -= len(texte)
    return gardes, ecartes


def _retirer_chunk(conn, cid: str, log: list | None = None) -> None:
    """Retire un chunk ET sa ligne lexicale, sans balayer `rag_fts`.

    L'ancien texte est lu par cle primaire AVANT la suppression : c'est lui que
    `forge_db_path.purger_fts` cherche par MATCH. `DELETE FROM rag_fts WHERE chunk_id=?`
    balayait tout l'index lexical sous verrou d'ecriture (`chunk_id` est UNINDEXED) --
    une fois PAR morceau en --redo (2026-09-27). Une erreur sur `rag_chunks` remonte ;
    une purge lexicale ratee est DITE dans le journal, pas avalee.
    """
    from nokido_agent.app.forge_db_path import purger_fts

    ancien = conn.execute("SELECT text FROM rag_chunks WHERE id=?", (cid,)).fetchone()
    conn.execute("DELETE FROM rag_chunks WHERE id=?", (cid,))
    if ancien is None:
        return
    try:
        _n, laissees = purger_fts(conn, [(cid, ancien[0])])
        if laissees and log is not None:
            log.append(f"    ({cid} : ligne FTS laissee a purge_rag_fts_fantomes)")
    except sqlite3.Error as e:
        if log is not None:
            log.append(f"    (rag_fts non purge pour {cid} : {type(e).__name__})")


def _process_github(c: dict, args) -> dict:
    """Un depot GitHub tronque ne se rattrape PAS par le crawl HTML de sa page
    (demande owner 2026-09-05 : « les depots github, j'entends ») : on passe par
    l'ingesteur de depot existant — tar.gz de la branche, filtre `_garder`,
    chunks `github:<owner>/<repo>/<chemin>` en domaine `ext_repo`, ids = hash
    (source + chunk) donc idempotent — puis on retire l'ancien chunk tronque, comme
    le chemin arxiv. `fetch` rend un RAPPORT des fichiers ecartes : on le journalise,
    un depot « vide » n'est pas un depot sans acces.
    """
    log: list[str] = []
    try:
        from nokido_agent.tools import forge_ingest_github_repo as G
    except ImportError as e:
        return {"status": "skip", "n": 0,
                "log": [f"  SKIP {c['url']} : ingesteur GitHub indisponible ({e})"]}
    try:
        owner, repo = G.parse_slug(c["url"])
    except (SystemExit, Exception) as e:  # noqa: BLE001 - parse_slug leve SystemExit
        return {"status": "skip", "n": 0, "log": [f"  SKIP {c['url']} : slug GitHub illisible ({e})"]}
    slug = f"{owner}/{repo}"
    # `fetch` signale ses refus par `raise SystemExit(...)` (c'est un CLI reutilise
    # en bibliotheque) : `except Exception` ne l'attrape PAS, et le 2026-09-05 le
    # lot job_3ed9b031e735 est MORT (rc=1) sur « 20000440 chars > cap 20000000 —
    # depot trop gros », apres 13 min de telechargement. Un depot trop gros pour
    # etre avale entier a presque toujours une doc qui tient : on la retente seule.
    fichiers, rapport = [], {}
    essais = ((None, "depot entier"), ("docs", "doc seule (prefixe docs/)"))
    for prefixe, libelle in essais:
        try:
            fichiers, rapport = G.fetch(owner, repo, None, prefixe=prefixe)
            if prefixe:
                log.append(f"    (repli {libelle})")
            break
        except (SystemExit, Exception) as e:  # noqa: BLE001 - SystemExit = refus du CLI
            msg = str(e)
            log.append(f"    fetch {libelle} KO : {type(e).__name__}: {msg[:140]}")
            if "trop gros" not in msg or prefixe is not None:
                return {"status": "skip", "n": 0,
                        "log": [f"  SKIP {c['url']} : fetch KO {type(e).__name__}: {msg[:140]}"] + log}
    n_fetch = len(fichiers)
    fichiers, ecartes_veille = _selection_github(fichiers)
    total_chars = sum(len(t) for _, t in fichiers)
    log.append(f"  {c['url']}\n    {c['len']} -> {total_chars} chars sur {len(fichiers)} fichier(s)"
               f" (fetch {n_fetch}, ecartes veille {ecartes_veille}, cap ~{_GH_CHARS_PAR_CHUNK} c/chunk)"
               f" | ecartes fetch: {str(rapport.get('ecartes', rapport))[:120]}")
    if not fichiers:
        log.append("    -> aucun fichier retenu : ancien chunk CONSERVE")
        return {"status": "skip", "n": 0, "log": log}
    if not args.apply:
        return {"status": "done", "n": 0, "log": log}
    try:
        res = G.index(fichiers, slug, G.DEFAULT_DOMAIN)
    except (SystemExit, Exception) as e:  # noqa: BLE001 - meme convention CLI que fetch
        log.append(f"    ECHEC index ({type(e).__name__}: {e}) — ancien chunk INTACT")
        return {"status": "skip", "n": 0, "log": log}
    n = int((res or {}).get("inserted", 0) or 0) if isinstance(res, dict) else 0
    deja = int((res or {}).get("skipped", 0) or 0) if isinstance(res, dict) else 0
    if n <= 0 and deja <= 0:
        log.append(f"    -> index sans chunk ({res!r}) : ancien chunk CONSERVE")
        return {"status": "skip", "n": 0, "log": log}
    from nokido_agent.app.forge_db_path import open_writer
    conn = open_writer(timeout=60.0)
    try:
        _retirer_chunk(conn, c["chunk_id"], log)
    finally:
        conn.close()
    log.append(f"    -> depot {slug} : {n} chunk(s) inseres, {deja} deja presents ;"
               f" ancien chunk tronque retire")
    return {"status": "done", "n": n, "log": log}


def _process_one(c: dict, args, run_started: str) -> dict:
    """Traite UNE source de bout en bout, avec sa PROPRE connexion writer.

    Une connexion par THREAD (et non partagee) : c'est ce qui rend le pool possible
    sans « database is locked », combine a l'autocommit de `open_writer`. Retourne un
    dict {status, log[]} plutot que d'imprimer : l'affichage est fait par le thread
    principal, sinon les lignes de plusieurs sources s'entrelacent et le journal
    devient illisible.
    """
    import hashlib as _h

    from nokido_agent.app.forge_crawl_tool import crawl_url
    from nokido_agent.app.forge_db_path import open_writer
    from nokido_agent.app import forge_watch_agent as W

    log: list[str] = []
    # La source EN COURS est annoncee par le thread PRINCIPAL (voir main) : un emit
    # depuis ce worker etait ecrase aussitot par le resultat de la source precedente
    # (1 worker : N+1 demarre avant que N soit publie). Mesure 2026-09-05, lot
    # job_18467ae0f9a1 : jamais visible, 10 min « muettes » sur un candidat.
    if _est_depot_github(c["url"]):
        return _process_github(c, args)   # le theme n'est pas requis : domaine ext_repo
    if not c["theme"]:
        return {"status": "skip", "n": 0,
                "log": [f"  SKIP {c['url']} : theme illisible dans le chunk existant"]}
    try:
        content = crawl_url(c["url"], timeout=60) or ""
    except Exception as e:  # noqa: BLE001
        return {"status": "skip", "n": 0,
                "log": [f"  SKIP {c['url']} : crawl KO {type(e).__name__}: {e}"]}
    # En redo la reference est la SOMME des chunks existants (sinon une source
    # deja chunkee afficherait un faux gain de x1 et serait ignoree a tort).
    ref_len = c["total_len"] if args.redo else c["len"]
    gain = len(content) / max(1, ref_len)
    verdict = "OK" if gain >= args.min_gain else "gain insuffisant"
    log.append(f"  {c['url']}\n    {c['len']} -> {len(content)} chars (x{gain:.1f}) {verdict}")
    if gain < args.min_gain:
        return {"status": "skip", "n": 0, "log": log}
    if not args.apply:
        return {"status": "done", "n": 0, "log": log}

    # base_id RECALCULE depuis l'URL, comme le fait `_step_ingest`. Le prendre dans
    # MIN(id) etait faux en --redo : sur une source deja chunkee, MIN(id) vaut deja un
    # id SUFFIXE, donc le LIKE de controle ne matchait rien (mesure 2026-07-25).
    base_id = "watch_" + _h.md5(c["url"].encode()).hexdigest()[:10]
    refined = [{"url": c["url"], "title": c["url"].rsplit("/", 1)[-1],
                "content": content, "relevance": 8, "keyword": "backfill"}]
    conn = open_writer(timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        # RETRY sur verrou (mesure 2026-07-25) : `busy_timeout` ne couvre PAS le cas ou
        # un AUTRE PROCESSUS tient une transaction longue -- ici deux files lancees avant
        # le passage a `open_writer` gardaient encore le mode transaction implicite. A
        # 6 workers, la moitie des sources repartaient en « database is locked » et
        # etaient PERDUES pour la passe. Une file intelligente REESSAIE : le travail
        # couteux (le crawl) est deja fait, l'abandonner pour un verrou transitoire est
        # du gaspillage. Backoff croissant, 4 essais, puis on rend la main proprement.
        import time as _t

        # Texte AVANT `_step_ingest`, lu par cle primaire : la resynchro FTS d'une reecriture
        # en place purge par MATCH (forge_db_path.purger_fts), il lui faut l'ANCIEN texte --
        # apres l'INSERT OR REPLACE, rag_chunks ne porte plus que le nouveau.
        _avant = conn.execute("SELECT text FROM rag_chunks WHERE id=?", (base_id,)).fetchone()
        n = None
        for _att in range(4):
            try:
                n = W._step_ingest(conn, "job_backfill", c["theme"], refined)
                break
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower() or _att == 3:
                    log.append(f"    ECHEC ingest ({type(e).__name__}: {e}) — ancien chunk INTACT")
                    return {"status": "skip", "n": 0, "log": log}
                _t.sleep(1.5 * (_att + 1))
            except Exception as e:  # noqa: BLE001
                log.append(f"    ECHEC ingest ({type(e).__name__}: {e}) — ancien chunk INTACT")
                return {"status": "skip", "n": 0, "log": log}
        if n is None:
            log.append("    ECHEC ingest (verrou persistant) — ancien chunk INTACT")
            return {"status": "skip", "n": 0, "log": log}
        fresh = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE source=? AND id LIKE ?",
            (c["url"], base_id + "_%")).fetchone()[0]
        if n > 0 and fresh == 0 and c["chunk_id"] == base_id:
            # UN SEUL chunk : `_step_ingest` reprend l'id de base, sans suffixe,
            # c'est-a-dire l'id de l'ancien chunk tronque -> INSERT OR REPLACE l'a
            # REECRIT en place. Mesure 2026-09-05 (doi.org, job_8c8196a16a4b) :
            # « 298 -> 3961 chars (x13.3) OK » puis « ancien chunk CONSERVE », compte
            # ignore ET memorise comme tel pendant 7 j, alors que la base portait
            # deja le nouveau texte. On tranche sur la LONGUEUR relue (PK) : si
            # elle a grandi, c'est un rattrapage — rien a retirer, rien a memoriser.
            nouvelle = conn.execute("SELECT LENGTH(text) FROM rag_chunks WHERE id=?",
                                    (base_id,)).fetchone()
            nouvelle = int(nouvelle[0] or 0) if nouvelle else 0
            if nouvelle > c["len"]:
                try:
                    from nokido_agent.app.forge_db_path import purger_fts

                    actuel = conn.execute("SELECT text FROM rag_chunks WHERE id=?",
                                          (base_id,)).fetchone()
                    # l'ANCIEN texte (ligne laissee si `_step_ingest` n'a pas resynchronise) ET
                    # le nouveau (ligne deja posee par lui) : une seule ligne apres l'INSERT
                    purger_fts(conn, [(base_id, t[0] or "") for t in (_avant, actuel) if t])
                    conn.execute(
                        "INSERT INTO rag_fts (chunk_id, text, source, domain) "
                        "SELECT id, text, source, domain FROM rag_chunks WHERE id=?", (base_id,))
                except Exception as e:  # noqa: BLE001
                    log.append(f"    (rag_fts non resynchronise : {type(e).__name__})")
                log.append(f"    -> 1 chunk REECRIT en place ({c['len']} -> {nouvelle} chars),"
                           f" meme id")
                return {"status": "done", "n": 1, "log": log}
        if not (n > 0 and fresh > 0):
            log.append(f"    -> ingest sans nouveau chunk (n={n}, fresh={fresh}) :"
                       f" ancien chunk CONSERVE")
            return {"status": "skip", "n": 0, "log": log}
        _retirer_chunk(conn, c["chunk_id"], log)
        if args.redo:
            stale = conn.execute(
                "SELECT id FROM rag_chunks WHERE source=? AND id LIKE ?"
                " AND (ingested_at IS NULL OR ingested_at < ?)",
                (c["url"], base_id + "_%", run_started)).fetchall()
            for s in stale:
                _retirer_chunk(conn, s["id"], log)
            if stale:
                log.append(f"    {len(stale)} morceau(x) obsolete(s) retire(s) (redo)")
        log.append(f"    -> {n} chunks ecrits ({fresh} suffixes), ancien chunk unique retire")
        # AUDIT QUALITE : OPT-IN (--audit), desarme depuis la mesure du 2026-07-25 (un
        # seuil global a supprime 35 chunks sur 67 d'une source homogene). Il reste
        # actif dans le pipeline VIVANT, ou le theme est cadre par la veille.
        if args.audit:
            try:
                audit = W._audit_chunks_quality(conn, c["theme"], threshold=0.55)
                if isinstance(audit, dict) and audit.get("dropped"):
                    log.append(f"    audit qualite: {audit.get('dropped')} elague(s) sur "
                               f"{audit.get('checked')} (cut {audit.get('cut')})")
            except Exception as e:  # noqa: BLE001
                log.append(f"    audit qualite indisponible: {type(e).__name__}: {e}")
        return {"status": "done", "n": n, "log": log}
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut: dry-run)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--min-gain", type=float, default=3.0)
    ap.add_argument("--source-like", default="%arxiv.org/abs/%")
    ap.add_argument("--max-len", type=int, default=3100,
                    help="ne cible que les chunks <= cette taille (troncature)")
    ap.add_argument("--redo", action="store_true",
                    help="re-traiter meme les sources DEJA chunkees (extraction amelioree)")
    ap.add_argument("--audit", action="store_true",
                    help="lancer l'audit qualite apres chaque source (OFF par defaut, cf. plus bas)")
    ap.add_argument("--workers", type=int, default=6,
                    help="sources traitees EN PARALLELE (crawl I/O + chunking CPU)")
    args = ap.parse_args()

    if args.workers > 1:
        _maybe_reexec_free_threaded(sys.argv[1:])

    from datetime import datetime, timezone

    from nokido_agent.app.forge_crawl_tool import crawl_url
    from nokido_agent.app import forge_watch_agent as W

    # Borne temporelle du run : sert a distinguer, en redo, les morceaux reecrits
    # a l'instant de ceux laisses par un decoupage precedent.
    _run_started = datetime.now(tz=timezone.utc).isoformat()

    # Pattern d'ecriture concurrente DEJA RESOLU dans la maison (decision archi
    # 2026-06-04, cf. forge_swarm_blackboard) : autocommit + WAL + busy_timeout.
    # Un `sqlite3.connect()` nu ouvre une transaction implicite qui tient le verrou
    # pendant les 80 INSERT d'une source -> « database is locked » chez le voisin.
    # Avec ce writer, plusieurs rattrapages peuvent tourner EN PARALLELE.
    from nokido_agent.app.forge_db_path import open_writer

    conn = open_writer(timeout=60.0)
    conn.row_factory = sqlite3.Row

    cands = _candidates(conn, args.source_like, args.max_len, redo=args.redo)
    print(f"[backfill] {len(cands)} source(s) eligible(s) (filtre {args.source_like!r},"
          f" <= {args.max_len} chars) — traitement de {min(len(cands), args.limit)}",
          flush=True)
    # Progression publiee dans sandbox/jobs/<job>.progress.json (lue par
    # progress_watch / job_status). L'id vient de LAFORGE_JOB_ID, injecte par le
    # wrapper de run_job ; hors job, emit rend False et c'est normal. Un import
    # qui echoue le DIT : une progression muette se lit comme un job bloque.
    try:
        from nokido_agent.tools.forge_job_progress import emit as _emit_progress
    except ImportError as _e_prog:  # noqa: BLE001
        print(f"[backfill] progression NON publiee (forge_job_progress: {_e_prog})", flush=True)

        def _emit_progress(*_a, **_k):
            return False
    _n_todo = min(len(cands), args.limit)
    _emit_progress("backfill veilles", index=0, total=_n_todo,
                   message=f"{len(cands)} eligibles, {_n_todo} a traiter, {max(1, args.workers)} worker(s)")
    if not args.apply:
        print("[backfill] DRY-RUN : rien ne sera ecrit (--apply pour agir)", flush=True)

    conn.close()   # la liste des candidats est lue, chaque worker ouvre SA connexion

    import sysconfig
    from concurrent.futures import ThreadPoolExecutor, as_completed

    _ft = "free-threaded" if sysconfig.get_config_var("Py_GIL_DISABLED") else "GIL actif"
    workers = max(1, args.workers)
    print(f"[backfill] {workers} worker(s) en parallele — {sys.version.split()[0]} ({_ft})",
          flush=True)

    done = skipped = written = 0
    ignorees = {} if args.redo else _charger_ignorees()
    cands, n_memo = _filtrer_ignorees(cands, ignorees) if not args.redo else (cands, 0)
    if n_memo:
        print(f"[backfill] {n_memo} source(s) ecartee(s) par la memoire des ignorees"
              f" ({_IGNOREES_PATH.name}, TTL {int(_IGNOREES_TTL_S // 3600)} h ; --redo pour forcer)",
              flush=True)
    todo = cands[:args.limit]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_process_one, c, args, _run_started): c for c in todo}
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                res = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  SKIP {c['url']} : worker KO {type(e).__name__}: {e}", flush=True)
                skipped += 1
                continue
            for line in res.get("log", []):
                print(line, flush=True)
            if res.get("status") == "done":
                done += 1
                written += res.get("n", 0)
            else:
                skipped += 1
                if args.apply:
                    _noter_ignoree(ignorees, c.get("url", ""),
                                   next((l.strip() for l in reversed(res.get("log", [])) if l.strip()), "?"))
            # Avec 1 worker l'ordre de traitement est l'ordre de soumission : la
            # source en cours est la prochaine de `todo`. A plusieurs workers c'est
            # approximatif, et le message le dit.
            _suiv = todo[done + skipped] if done + skipped < len(todo) else None
            _en_cours = (f" | en cours{'~' if workers > 1 else ''}: {_suiv.get('url', '?')[:80]}"
                         if _suiv else "")
            _emit_progress("backfill veilles", index=done + skipped, total=len(todo),
                           message=f"{done} ok / {skipped} ignorees / {written} chunks"
                                   f" | derniere: {c.get('url', '?')[:80]}{_en_cours}")
    print(f"[backfill] termine : {done} source(s) traitee(s), {written} chunk(s) ecrit(s),"
          f" {skipped} ignoree(s)", flush=True)
    _emit_progress("backfill veilles", index=len(todo), total=len(todo),
                   message=f"termine : {done} ok / {skipped} ignorees / {written} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
