"""forge_health_diagnostic.py — Diagnostic de santé Nokido (lacunes + métriques).

Audite :
- rag_chunks : total, vectorisés/non-vectorisés (%), dim cohérence, hash dups
- biblio_raw / biblio_topics / biblio_link : peuplement par status
- agent_messages : volume cross-agents, % unread, % du jour
- network_log / conversation_log / shared_prompt_log : taille, ratio jour/total
- Tables critiques vides ou orphelines
- Taille DB (main + WAL)
- Heartbeats workers (biblio_worker, gemini_poll, skill_enricher, rss_watcher)
- Services NSSM (parsing status sans admin)
- Constantes critiques (paths, ENV vars, ports)
- Score global 0-100 + lacunes prioritaires + recommandations actionnables

Sortie :
- sandbox/health_diagnostic.json (machine-readable)
- sandbox/health_report_<date>.md (lisible humain)
- anchor RAG si score < 70 ou nouvelle lacune detectee

Hook circadien : phase 0.5 (avant nettoyage) du forge_circadian_loop.
Standalone : LAFORGE_PYTHON app/forge_health_diagnostic.py [--once|--daemon]

Version 1.0 — 2026-04-30

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `audit_examens` — Etat de CHAQUE examen du corps : FRAIS · PERIME · SANS_ORDONNANCEUR · ABSENT · ILLISIBLE.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
SANDBOX = ROOT / "sandbox"
OUT_JSON = SANDBOX / "health_diagnostic.json"
HEARTBEAT = SANDBOX / "health_diagnostic.heartbeat"

DEFAULT_INTERVAL_S = int(os.environ.get("LAFORGE_HEALTH_INTERVAL_S", "21600"))  # 6h


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


# ============================================================================
# AUDITS
# ============================================================================


# Cache du bloc RAG. Mesure 2026-09-04 : ce diagnostic declare un intervalle de
# 6 h (DEFAULT_INTERVAL_S = 21600) mais tourne toutes les 6,7 min en mediane —
# 124 passages entre 00h06 et 14h25, facteur 54. La cause n'est pas ici : c'est
# `forge_homeostasis_orchestrator` qui appelle `run_cycle` a CHAQUE tick, alors
# que ses autres consommateurs sont amortis (immune 1/12, hebbian 1/72,
# tool_efficiency 1/24). Le diagnostic est le SEUL non amorti, et le plus cher.
#
# L'amortissement est place ICI plutot que chez l'appelant, a dessein : le reste
# du diagnostic (services, heartbeats, ports, hormones) doit rester FRAIS a
# chaque tick pour que l'orchestrateur decide sur du reel. Seul le bloc RAG,
# couteux et lent a bouger, se met en cache.
#
# Le cache DIT son age : une valeur servie sans son anciennete se lit comme une
# mesure de l'instant, et c'est ainsi qu'on decide sur du perime sans le savoir.
_RAG_CACHE: dict = {}
_RAG_TTL_S = int(os.environ.get("LAFORGE_HEALTH_RAG_TTL_S", "1800"))  # 30 min
# SECOND LECTEUR LONG DU 23/09 (derogation owner). Doublons et qualite etaient calcules par
# `SCAN rag_chunks` (38 Go, EXPLAIN reel) a chaque recalcul ; la phase `health` depassait son
# delai de 90 s, etait « abandonnee », et le cache — ecrit en FIN de mesure — n'etait jamais
# rafraichi : le tick suivant relancait une mesure complete. Aucun controle profond n'existe
# vers lequel les deplacer (le CLI appelle le meme `run_cycle`) : ces deux grandeurs deviennent
# un ECHANTILLON DECLARE (les N dernieres lignes par rowid), sous des noms qui le disent.
# NR : tests/nr/test_health_audit_rag_sans_scan_nr.py
_RAG_ECHANTILLON_N = int(os.environ.get("LAFORGE_HEALTH_RAG_ECHANTILLON", "10000"))
import threading as _threading  # noqa: E402 - verrou de mesure, voisin du cache qu'il protege

_MESURE_VERROU = _threading.Lock()


def audit_rag_chunks(conn, force: bool = False) -> dict:
    """Qualité RAG : vectorisation, dim, dups, distribution domaine.

    Le résultat est mis en cache `_RAG_TTL_S` secondes et porte son âge dans
    `mesure_age_s`. `force=True` recalcule (outil en ligne de commande, test).
    """
    _maintenant = time.time()
    if not force and _RAG_CACHE.get("ts") and (_maintenant - _RAG_CACHE["ts"]) < _RAG_TTL_S:
        _cache = dict(_RAG_CACHE["valeur"])
        _cache["mesure_age_s"] = round(_maintenant - _RAG_CACHE["ts"], 1)
        _cache["depuis_cache"] = True
        return _cache
    # PAS DE RELANCE pendant une mesure en cours : on rend la derniere valeur connue, DITE
    # comme telle ; sans valeur connue on attend au plus 60 s, puis on echoue EN LE DISANT
    # (phase `health` KO nommee) plutot que d'empiler une seconde mesure ou de rendre un zero.
    if not _MESURE_VERROU.acquire(blocking=False):
        if _RAG_CACHE.get("valeur") is not None:
            _cache = dict(_RAG_CACHE["valeur"])
            _cache["mesure_age_s"] = round(_maintenant - _RAG_CACHE.get("ts", _maintenant), 1)
            _cache["depuis_cache"] = True
            _cache["mesure_en_cours"] = True
            return _cache
        if not _MESURE_VERROU.acquire(timeout=60):
            raise RuntimeError("audit RAG : mesure precedente toujours en cours depuis > 60 s — pas de relance")
    try:
        resultat = _audit_rag_chunks_mesure(conn)
    finally:
        _MESURE_VERROU.release()
    _ventiler_la_dette(resultat)
    return resultat


def _ventiler_la_dette(resultat: dict) -> None:
    """Separe ce qui ATTEND un vecteur de ce qui n'en aura JAMAIS.

    `embedding IS NULL` n'est pas un backlog. Le trigger `forge_tier_guard` fait
    RAISE(IGNORE) sur les paliers froids : ces chunks sont refuses PAR CONCEPTION
    et aucun `forge_rag_warmup` ne les vectorisera. Mesure du 2026-09-04 sur
    736 272 « sans embedding » :

        109 053  PENDING            le deficit reellement actionnable (5,4 %)
        626 646  REFUSED_BY_POLICY  n'aura jamais de vecteur (30,8 %)
      2 032 604  lexical_available  100 % : RIEN n'est invisible a la recherche

    Ce diagnostic etait le SEUL organe reste sur l'ancienne lecture :
    `forge_organ_pulse`, `forge_rag_engine`, `forge_retrieval_router` et
    `forge_resource_manager` consomment tous `forge_memory_availability` depuis
    que la meme confusion y a ete corrigee (« ~146k = embolie chronique »).
    Il recommandait donc de relancer un remede impuissant sur 85 % du chiffre.

    La ventilation est AJOUTEE, jamais substituee : `non_vectorized` garde son
    sens brut pour qui le lisait deja, et les nouveaux champs disent ce qu'il
    recouvre. En cas d'echec, les champs valent None — « je n'ai pas pu ventiler »
    n'est pas « tout est en attente ».
    """
    resultat["vector_pending"] = None
    resultat["vector_refused"] = None
    resultat["lexical_available"] = None
    resultat["ventilation"] = "indisponible"
    try:
        from nokido_agent.app.forge_memory_availability import snapshot as _snapshot
        snap = _snapshot()
    except Exception as exc:
        resultat["ventilation"] = "%s: %s" % (type(exc).__name__, exc)
        return
    if not isinstance(snap, dict) or snap.get("vector_pending") is None:
        resultat["ventilation"] = "snapshot sans ventilation"
        return
    resultat["vector_pending"] = snap.get("vector_pending")
    resultat["vector_refused"] = snap.get("vector_refused")
    resultat["lexical_available"] = snap.get("lexical_available")
    resultat["ventilation_age_s"] = round(snap.get("age_s") or 0, 1)
    resultat["ventilation"] = "frais" if snap.get("frais") else "perime"


def _audit_rag_chunks_mesure(conn) -> dict:
    """La mesure elle-meme, toujours fraiche. Alimente le cache."""
    # Compte des NON-vectorises par l'index PARTIEL `idx_embedding_null`
    # (WHERE embedding IS NULL), et non par sa negation.
    #
    # Mesure 2026-09-04, sur une base de 24,9 Go :
    #   COUNT(*) WHERE embedding IS NULL        SCAN USING INDEX      0,031 s
    #   COUNT(*)                                SCAN COVERING INDEX   0,039 s
    #   COUNT(*) WHERE ... length(embedding)>0  SCAN rag_chunks       ~70 s
    #
    # La forme precedente appelait `length(embedding)` sur chaque ligne, ce qui
    # force la lecture du BLOB de ~4 Ko : 11 s mesurees pour 200 000 lignes,
    # donc ~70 s pour les 1,3 M vectorises. Ce rapport tourne toutes les ~7 min
    # (121 passages le 2026-09-04) : environ 2 h 20 de lecture disque par jour
    # pour un chiffre obtenu ici en 70 ms. L'instrument de SANTE etait une cause
    # majeure de la pression I/O qui throttlait le reste du corps.
    #
    # Le SENS est preserve, verifie et non suppose : sur un echantillon de
    # 200 000 lignes non-NULL, ZERO blob de longueur nulle. `IS NULL` et
    # `NOT NULL AND length>0` comptent donc la meme chose ici.
    #
    # Les deux comptes sont pris dans la MEME transaction : en autocommit ce
    # sont deux instantanes, et `total - vec` melangeait alors deux moments —
    # c'est ce qui faisait varier le chiffre d'un rapport a l'autre sans qu'aucun
    # chunk n'ait change d'etat.
    conn.execute("BEGIN")
    try:
        total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        no_vec = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL"
        ).fetchone()[0]
    finally:
        conn.execute("COMMIT")
    vec = total - no_vec
    pct_vec = round(vec * 100 / max(total, 1), 1)

    # Dim moyenne (échantillon)
    sample = conn.execute(
        "SELECT length(embedding) FROM rag_chunks WHERE embedding IS NOT NULL AND length(embedding) > 0 LIMIT 50"
    ).fetchall()
    dims = [int(r[0]) for r in sample if r[0]]
    avg_bytes = round(sum(dims) / max(len(dims), 1)) if dims else 0
    # f32 = 4 bytes/float → dim = bytes/4
    dim_f32 = avg_bytes // 4

    # ECHANTILLON DECLARE (voir `_RAG_ECHANTILLON_N`) : les N dernieres lignes par rowid —
    # recherche par cle, la ou les doublons naissent (ingestions recentes). NON exhaustif.
    _borne = conn.execute("SELECT MAX(rowid) FROM rag_chunks").fetchone()[0] or 0
    _debut = max(0, _borne - _RAG_ECHANTILLON_N)
    _statut_ech = ("ECHANTILLON_%d_DERNIERES_LIGNES (rowid > %d) — NON exhaustif"
                   % (_RAG_ECHANTILLON_N, _debut))
    # Hash dupes (même text), DANS L'ECHANTILLON
    dups = conn.execute(
        "SELECT hash, COUNT(*) FROM rag_chunks WHERE rowid > ? AND hash IS NOT NULL AND hash != '' "
        "GROUP BY hash HAVING COUNT(*) > 1", (_debut,)
    ).fetchall()

    # Top domains
    by_dom = conn.execute(
        "SELECT COALESCE(domain,'(null)'), COUNT(*) FROM rag_chunks GROUP BY domain ORDER BY 2 DESC LIMIT 10"
    ).fetchall()

    # Quality score moyen
    qsa = conn.execute(
        "SELECT AVG(quality_score), MIN(quality_score), MAX(quality_score), COUNT(quality_score) "
        "FROM rag_chunks WHERE rowid > ? AND quality_score IS NOT NULL", (_debut,)
    ).fetchone()
    # AUCUNE valeur n'est pas une qualite NULLE : `round(None or 0)` rendait 0 (mesure du
    # 23/09 : les 10 000 derniers chunks n'ont pas de quality_score). On rend None, et on le dit.
    _n_q = qsa[3] or 0
    _resultat = {
        "total": total,
        "vectorized": vec,
        "non_vectorized": no_vec,
        "pct_vectorized": pct_vec,
        "mesure_age_s": 0.0,
        "depuis_cache": False,
        "embedding_dim_f32": dim_f32,
        "embedding_avg_bytes": avg_bytes,
        "duplicate_hashes_echantillon": len(dups),
        "duplicate_rows_echantillon": sum(c - 1 for _, c in dups),
        "doublons_statut": _statut_ech,
        "top_domains": [{"domain": d, "count": n} for d, n in by_dom],
        "quality_score_echantillon": {
            "avg": round(qsa[0], 3) if _n_q else None,
            "min": round(qsa[1], 3) if _n_q else None,
            "max": round(qsa[2], 3) if _n_q else None,
            "n": _n_q,
            "statut": _statut_ech + ("" if _n_q else " ; 0 valeur de quality_score : NON MESURE, pas nul"),
        },
    }
    _RAG_CACHE["ts"] = time.time()
    _RAG_CACHE["valeur"] = _resultat
    return _resultat


def audit_biblio(conn) -> dict:
    """Pipeline biblio : peuplement status + topics + links."""
    by_status = dict(conn.execute("SELECT status, COUNT(*) FROM biblio_raw GROUP BY status").fetchall())
    topics_total = conn.execute("SELECT COUNT(*) FROM biblio_topics").fetchone()[0]
    topics_distinct = conn.execute("SELECT COUNT(DISTINCT topic) FROM biblio_topics").fetchone()[0]
    topics_auto = conn.execute("SELECT COUNT(*) FROM biblio_topics WHERE source LIKE 'auto_%'").fetchone()[0]
    links_total = conn.execute("SELECT COUNT(*) FROM biblio_link").fetchone()[0]
    return {
        "raw_by_status": by_status,
        "topics_total": topics_total,
        "topics_distinct": topics_distinct,
        "topics_auto_extracted": topics_auto,
        "cross_links": links_total,
    }


def audit_messages(conn) -> dict:
    """Mailbox + conversation_log : volume + freshness."""
    from datetime import timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    # Exclure la TELEMETRIE (pas des messages inter-agents a lire) : firehose EventBus
    # (to_agent='EVENTBUS_ARCHIVE'/method 'tool.%') ET captures de conversation
    # (to_agent='cli_capture'/method 'conversation.turn'). Les compter donnait 99% de
    # faux "unread", saturait LEPTIN_MAILBOX_FULL (TTL 4h) -> daemons ralentis pour rien.
    _REAL = (
        " AND to_agent NOT IN ('EVENTBUS_ARCHIVE','cli_capture') "
        "AND (method IS NULL OR (method NOT LIKE 'tool.%' AND method != 'conversation.turn'))"
    )
    # Scission M2M : la table vit dans la base M2M (interrupteur sandbox/m2m.switch) ;
    # `conn` (base du RAG) garde conversation_log et le reste de l'audit.
    import sqlite3 as _sq3
    from nokido_agent.app.forge_db_path import m2m_path as _m2m_path
    _m = _sq3.connect(_m2m_path(), timeout=5)
    am_total = _m.execute("SELECT COUNT(*) FROM agent_messages WHERE 1=1" + _REAL).fetchone()[0]
    am_today = _m.execute("SELECT COUNT(*) FROM agent_messages WHERE created_at >= ?" + _REAL, (today,)).fetchone()[0]
    # unread PERTINENT = vrais messages inter-agents NON LUS et RECENTS (<7j). Un message
    # non lu de plusieurs semaines = backlog historique a archiver (le status 'unread'
    # n'est jamais nettoye), PAS une pression de mailbox actuelle : ne doit pas saturer
    # la leptine en permanence.
    am_unread = _m.execute(
        "SELECT COUNT(*) FROM agent_messages WHERE status='unread' AND created_at >= ?" + _REAL,
        (week_ago,),
    ).fetchone()[0]
    by_from = _m.execute(
        "SELECT from_agent, COUNT(*) FROM agent_messages GROUP BY from_agent ORDER BY 2 DESC LIMIT 10"
    ).fetchall()
    _m.close()
    # `conversation_log` est un JOURNAL qui suit `sandbox/journaux.switch` ;
    # `network_log` et `shared_prompt_log` restent dans la base du RAG. Les trois
    # etaient comptees par la MEME connexion : le jour de la bascule, ce
    # diagnostic aurait rendu un total FIGE en le presentant comme courant, sans
    # la moindre erreur. Ce module ouvre deja des connexions dediees (`_m` pour la
    # base M2M) : on suit ce patron plutot que d'en inventer un autre.
    import sqlite3 as _sq3

    try:
        from nokido_agent.app.forge_db_path import journal_path as _jp
        _base_cv = _jp("conversation_log")
    except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
        _base_cv = None
    if _base_cv and _base_cv != str(DB):
        _c_cv = _sq3.connect("file:%s?mode=ro" % _base_cv.replace("\\", "/"),
                             uri=True, timeout=10)
        try:
            cv_total = _c_cv.execute("SELECT COUNT(*) FROM conversation_log").fetchone()[0]
        finally:
            _c_cv.close()
    else:
        cv_total = conn.execute("SELECT COUNT(*) FROM conversation_log").fetchone()[0]
    nl_total = conn.execute("SELECT COUNT(*) FROM network_log").fetchone()[0]
    spl_total = conn.execute("SELECT COUNT(*) FROM shared_prompt_log").fetchone()[0]
    return {
        "agent_messages_total": am_total,
        "agent_messages_today": am_today,
        "agent_messages_unread": am_unread,
        "agent_messages_pct_unread": round(am_unread * 100 / max(am_total, 1), 1),
        "agent_messages_by_from": [{"agent": a, "count": n} for a, n in by_from],
        "conversation_log_total": cv_total,
        "network_log_total": nl_total,
        "shared_prompt_log_total": spl_total,
    }


def audit_tables_empty(conn) -> dict:
    """Détecte tables existantes mais vides ou sous-peuplées."""
    tbls = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%' "
            "AND name NOT LIKE '%_data' AND name NOT LIKE '%_idx' "
            "AND name NOT LIKE '%_docsize' AND name NOT LIKE '%_content' "
            "AND name NOT LIKE '%_config'"
        ).fetchall()
    ]
    empty = []
    low = []
    for t in tbls:
        try:
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        except Exception:
            continue
        if n == 0:
            empty.append(t)
        elif n < 5:
            low.append({"table": t, "rows": n})
    return {"empty_tables": empty, "low_population_tables": low, "total_tables_audited": len(tbls)}


def audit_db_size() -> dict:
    """Taille DB main + WAL + SHM."""
    out = {}
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DB) + suffix)
        if p.exists():
            out[f"size_bytes{suffix or '_main'}"] = p.stat().st_size
            out[f"size_mb{suffix or '_main'}"] = round(p.stat().st_size / 1024 / 1024, 1)
    return out


# SOURCE UNIQUE des heartbeats de workers : l'audit les mesure, l'exemption les
# apparie a `services.toml` par le NOM DE FICHIER. Deux listes auraient diverge.
_WORKER_HEARTBEATS = {
    "biblio_worker": "biblio_worker.heartbeat",
    "gemini_poll": "gemini_poll_daemon.heartbeat",
    "skill_enricher": "skill_enricher.heartbeat",
    # Fichier d'ETAT et non heartbeat : c'est son mtime qui prouve l'activite.
    "rss_watcher": "rss_watcher_state.json",
    "health_diagnostic": "health_diagnostic.heartbeat",
    # Ajoute le 2026-07-28 : ce daemon etait MORT depuis 13 h sans que rien ne le
    # signale — il ne figurait dans AUCUNE liste de surveillance. Un organe absent du
    # capteur ne peut pas mourir bruyamment : sa mort n'est pas silencieuse par
    # hasard, elle l'est par construction.
    "epistemic_daemon": "epistemic_daemon.heartbeat",
    # Ajoutes le 2026-08-25 : ces deux keepers publient DEJA, dans leur propre
    # battement, l'etat de l'organe qu'ils servent — et personne ne le lisait.
    # Mesure du jour : `docker_keeper` bat depuis 11 s avec `health: "idle"` et
    # `stats.daemon_up: false` ; `llama_keeper` bat depuis 31 s avec `gemma_up: false`.
    # La cellule vit, l'organe est mort, et le corps voyait vert.
    "docker_keeper": "docker_keeper.heartbeat",
    "llama_keeper": "llama_keeper.heartbeat",
}

# Le drapeau d'intention `sandbox/<organe>.wanted` porte un TTL declare de 900 s
# (`forge_resource_manager`). Il decide si un organe eteint est une PANNE ou un
# REPOS conforme.
_INTENTION_TTL_S = float(os.environ.get("LAFORGE_WANTED_TTL_S", "900"))

# Le nom du worker et celui de l'organe qu'il sert ne coincident pas.
_ORGANE_DE_WORKER = {"docker_keeper": "docker", "llama_keeper": "llama"}


def _intention_fraiche(organe: str):
    """Quelqu'un RECLAME-t-il cet organe ? True / False / None si illisible.

    On juge sur le MTIME, jamais sur le contenu : mesure 2026-08-25, les quatre
    drapeaux presents portent QUATRE formats — float nu (`docker.wanted`), JSON
    (`llama.wanted`), fichier VIDE (`rerank.wanted`), prose (`snn.wanted`). Un
    parseur de contenu casserait sur trois d'entre eux.
    """
    p = SANDBOX / f"{organe}.wanted"
    try:
        if not p.exists():
            return False
        return (datetime.now().timestamp() - p.stat().st_mtime) <= _INTENTION_TTL_S
    except Exception:  # noqa: BLE001 — illisible n'est pas « pas voulu »
        return None


def _hb_declares_par_services_toml() -> dict:
    """{service: chemin heartbeat} DECLARE dans services.toml.

    DELEGUE a `forge_sensor_fusion_probe._declared_heartbeats()` : ce registre existe
    deja, il est teste, et il porte la lecon qui justifie son existence (deviner par
    convention de nom ramasse des heartbeats orphelins d'anciens services). On ne le
    reimplemente pas — on l'interroge. Rend {} si le module est indisponible : une
    provenance INCONNUE vaut mieux qu'une provenance inventee.
    """
    try:
        from nokido_agent.app.forge_sensor_fusion_probe import _declared_heartbeats  # noqa: PLC0415

        return _declared_heartbeats() or {}
    except Exception:  # noqa: BLE001
        return {}


_SERVICES_DESACTIVES: dict | None = None


def _service_desactive(nom_fichier_hb: str):
    """Ce heartbeat appartient-il a un service `disabled = true` ? True/False/None.

    None = on n'a pas pu lire le registre. NE JAMAIS rendre False dans ce cas : ce
    serait affirmer « ce service est actif » sans l'avoir verifie, et transformer
    cinq extinctions VOULUES en cinq pannes. Mesure 2026-09-04 : les embedders
    (EmbedTrigger, LlamaEmbed, BrainWorker, BrainWorkerRust, EmbedWorkerIsolated)
    sont tous `disabled = true` depuis la directive owner du 01/09 qui route
    l'embedding vers Modal — leur heartbeat est stale PAR CONSTRUCTION.
    """
    global _SERVICES_DESACTIVES
    if _SERVICES_DESACTIVES is None:
        import re as _re  # noqa: PLC0415

        table: dict = {}
        try:
            _toml = ROOT / "proxy_deno" / "core" / "services.toml"
            _txt = _toml.read_text(encoding="utf-8", errors="replace")
            for _bloc in _txt.split("[[service]]")[1:]:
                _hb = _re.search(r'^\s*heartbeat\s*=\s*"([^"]+)"', _bloc, _re.M)
                if not _hb:
                    continue
                _off = _re.search(r'^\s*disabled\s*=\s*(\w+)', _bloc, _re.M)
                table[Path(_hb.group(1)).name] = bool(
                    _off and _off.group(1).strip().lower() == "true")
        except Exception as _e:  # noqa: BLE001
            # PAS de silence ici. Mesure 2026-09-04 : la premiere version utilisait
            # `re` sans l'importer — ce module ne l'importe pas au niveau global — et
            # le NameError, avale par cet `except`, rendait une table VIDE. Resultat :
            # `eteint_par_decision` valait None pour les 50 workers, et la distinction
            # entre « eteint par decision » et « en panne » disparaissait EXACTEMENT
            # dans la fonction ecrite pour l'etablir. Quatrieme import manquant de la
            # session, invisible a la validation AST, masque par un except. Un
            # capteur qui echoue doit le DIRE, avec sa consequence.
            import logging as _lg  # noqa: PLC0415

            _lg.getLogger(__name__).warning(
                "[health] registre des services ILLISIBLE (%s: %s) | consequence : "
                "impossible de distinguer un organe eteint PAR DECISION d'un organe "
                "en panne — les extinctions voulues risquent d'etre rapportees comme "
                "des morts", type(_e).__name__, str(_e)[:120])
            table = {}
        _SERVICES_DESACTIVES = table
    if not _SERVICES_DESACTIVES:
        return None
    return _SERVICES_DESACTIVES.get(nom_fichier_hb)


def _verdict_fonctionnel(data) -> tuple:
    """L'organe que ce worker sert REPOND-il ? (True|False|None, motif).

    On lit le payload que le keeper publie DEJA, un niveau d'imbrication compris —
    on n'invente aucun protocole et on ne demande rien de neuf aux keepers. Mesure
    2026-08-25 : `docker_keeper` porte `stats.daemon_up` + `stats.error`,
    `llama_keeper` porte `gemma_up`.

    Un payload sans champ d'etat rend None, JAMAIS False : « je n'ai pas pu voir »
    n'est pas « l'organe est mort ». C'est toute la difference entre un capteur et
    une accusation, et c'est ce qui evite de desarmer le garde a force de faux cris.
    """
    if not isinstance(data, dict):
        return None, "payload illisible"
    portees = [data] + [v for v in data.values() if isinstance(v, dict)]
    for src in portees:
        for cle, val in src.items():
            if isinstance(val, bool) and cle.lower().endswith("_up"):
                if val:
                    return True, f"{cle}=true"
                _err = str(src.get("error") or "").strip()
                return False, (f"{cle}=false" + (f" — {_err[:110]}" if _err else ""))
    return None, "aucun etat d'organe publie dans le payload"


def _daemons_au_repos_declare() -> tuple:
    """Workers dont le silence est VOULU. Rend (cles_exemptes, raison lisible).

    Apparie par le FICHIER DE HEARTBEAT et non par un nom code en dur : c'est la
    seule cle que `services.toml` et cet audit partagent deja, donc la seule qui ne
    derive pas au premier renommage. Une table de correspondance manuelle serait un
    seconde verite a maintenir, et elle mentirait le jour ou personne ne la met a jour.

    En cas d'illisibilite on n'exempte PERSONNE : mieux vaut un faux positif visible
    qu'une exemption silencieuse qui masquerait une vraie mort.
    """
    exempts: set = set()
    raisons: list = []
    try:
        import tomllib

        with open(ROOT / "proxy_deno" / "core" / "services.toml", "rb") as fh:
            services = tomllib.load(fh).get("service", [])
    except Exception as exc:  # noqa: BLE001
        return set(), f"etat declare ILLISIBLE ({type(exc).__name__}) — aucune exemption"

    # statut vivant (sleeping) : best-effort, son absence ne doit pas exempter a tort
    statuts: dict = {}
    try:
        import json as _js
        import urllib.request as _ur

        with _ur.urlopen("http://127.0.0.1:8765/supervisor/status", timeout=4) as r:
            statuts = {n: (s or {}).get("status")
                       for n, s in (_js.loads(r.read()).get("services") or {}).items()}
    except Exception:  # noqa: BLE001 - muet-ok : sans registre, seul `disabled` exempte
        statuts = {}

    par_hb = {}
    for s in services:
        hb = s.get("heartbeat")
        if hb:
            par_hb[Path(hb).name] = s
    for cle, chemin in _WORKER_HEARTBEATS.items():
        svc = par_hb.get(Path(chemin).name)
        if svc is None:
            # SECONDE CLE D'APPARIEMENT. Mesure 2026-08-25 : `rss_watcher` est audite
            # via `rss_watcher_state.json` alors que son service declare
            # `rss_watcher.heartbeat` — deux fichiers pour un meme organe, donc aucun
            # appariement par nom de fichier, donc un service `sleeping` accuse de
            # mort. On retombe sur le radical du worker, present dans l'un ou l'autre.
            for s in services:
                _hb = str(s.get("heartbeat") or "")
                _args = " ".join(s.get("args") or [])
                if cle in _hb or cle in _args:
                    svc = s
                    break
        if svc is None:
            continue
        nom = svc.get("name", "?")
        if svc.get("disabled") is True:
            exempts.add(cle)
            raisons.append(f"{nom}: disabled=true")
        elif statuts.get(nom) in ("sleeping", "stopped"):
            exempts.add(cle)
            raisons.append(f"{nom}: {statuts.get(nom)}")
    return exempts, ("; ".join(raisons) if raisons else "aucun etat de repos declare")


def audit_workers_heartbeat() -> dict:
    """Heartbeats fraîcheur des workers daemon."""
    files = {cle: SANDBOX / nom for cle, nom in _WORKER_HEARTBEATS.items()}
    # ZONE D'OMBRE FERMEE (2026-09-04). Mesure : 48 fichiers `*.heartbeat` sur le
    # disque, 8 dans `_WORKER_HEARTBEATS` — QUARANTE organes battaient sans qu'aucun
    # audit ne les regarde, et le score de sante portait donc sur 17 % de la flotte
    # qui bat. Le commentaire de la liste enonce DEJA le defaut (« un organe absent du
    # capteur ne peut pas mourir bruyamment : sa mort n'est pas silencieuse par
    # hasard, elle l'est par construction ») — et il a ete soigne DEUX fois, le 28/07
    # et le 25/08, en ajoutant une entree A LA MAIN. La cause structurelle restait.
    #
    # On enumere donc le disque. La liste garde ses deux roles : ALIAS (le fichier de
    # `gemini_poll` s'appelle `gemini_poll_daemon.heartbeat`, celui de `rss_watcher`
    # est un fichier d'ETAT) et DECLARATION. Les organes DECOUVERTS sont audites et
    # rapportes, mais ne pesent pas encore sur le score : faire basculer quarante
    # organes d'un coup dans `-8 * len(dead)` ferait crier le garde a faux et le
    # ferait desarmer. Voir n'est pas punir — on ouvre les yeux d'abord.
    #
    # ON DEMANDE AU REGISTRE, ON NE DEVINE PAS PAR LE NOM. Second raffinement, impose
    # par la mesure : `forge_sensor_fusion_probe._declared_heartbeats()` lit quel
    # fichier chaque service DECLARE dans `services.toml`, et son commentaire porte le
    # prix de l'erreur inverse — deviner `<service>.heartbeat` faisait ramasser des
    # fichiers ORPHELINS d'anciens services (24-07 : `NokidoWebHub`, qui ne declare
    # AUCUN heartbeat, se voyait attribuer un residu de 20,6 jours et etait rapporte
    # « capteur gele »). On croise donc l'enumeration du disque avec la declaration :
    # 40 des 43 fichiers decouverts le 2026-09-04 sont bien adosses a un service
    # declare — ce ne sont PAS des residus, c'est un vrai trou d'audit. Les 3 autres
    # (`modal_campagne`, `remediation`, `service_crash_watcher`) sont a instruire, et
    # l'un d'eux est precisement le watcher de crash que personne ne surveillait.
    _deja = {p.name for p in files.values()}
    _decouverts: set = set()
    try:
        _noms_declares = {Path(v).name
                          for v in _hb_declares_par_services_toml().values()}
    except Exception:  # noqa: BLE001
        _noms_declares = set()   # illisible -> on n'affirme AUCUNE provenance
    try:
        for _p in sorted(SANDBOX.glob("*.heartbeat")):
            if _p.name not in _deja:
                files[_p.stem] = _p
                _decouverts.add(_p.stem)
    except OSError as _e:
        # muet-ok explicite : sandbox illisible. On garde les declares, et on ne
        # pretend PAS avoir enumere — l'absence de decouverts sera alors un « pas vu ».
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[health] enumeration des heartbeats impossible (%s) | consequence : "
            "seuls les %d workers declares sont audités, la couverture est SOUS-estimee",
            type(_e).__name__, len(files))
    out = {}
    now = datetime.now()
    for name, p in files.items():
        if not p.exists():
            out[name] = {"present": False, "alive": False,
                         "declare": name not in _decouverts}
            continue
        # CONSTATER la lecture. Depuis l'enumeration du disque (2026-09-04) ce
        # diagnostic est le lecteur UNIVERSEL des pouls, mais rien ne le mesurait :
        # l'atlas du cablage ne comptait comme lecteurs que `services.toml` et les
        # sites AST, et rapportait donc 21 pouls « sans consommateur » alors qu'ils
        # etaient lus ici. VOIR n'est pas SUPERVISER — la distinction reste entiere,
        # elle se joue sur l'autorite, pas sur la lecture.
        try:
            from nokido_agent.app.forge_signal_coupling import observe_signal

            observe_signal(p.name,
                           consumer="forge_health_diagnostic.audit_workers_heartbeat")
        except Exception:  # noqa: BLE001 - muet-ok : sonde, jamais un capteur
            pass
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ts = data.get("ts") or data.get("last_run")
            age_s = None
            age_src = "ts"
            if ts:
                # EPOCH OU ISO, DECIDE PAR L'ESSAI ET NON PAR `.isdigit()`.
                # Mesure 2026-08-25 : `epistemic_daemon` ecrit `{"ts": 1787671164.4189937}`
                # — un epoch FLOTTANT. `.isdigit()` rend False a cause du point, donc
                # l'ancien code tentait `fromisoformat("1787671164")` sur un daemon qui
                # battait depuis 22 secondes, et le declarait MORT. Meme famille que le
                # piege ISO/epoch paye ailleurs le meme jour : on ne devine pas un
                # format, on l'ESSAIE, du plus specifique au plus general.
                _brut = str(ts).strip()
                try:
                    t = datetime.fromtimestamp(float(_brut))
                except (TypeError, ValueError):
                    t = datetime.fromisoformat(_brut.split(".")[0])
                age_s = int((now - t).total_seconds())
            else:
                # Fichier d'ÉTAT, pas de heartbeat : le mtime PROUVE l'écriture, donc
                # l'activité. Mesuré le 2026-07-28 : rss_watcher_state.json ne porte
                # que {"seen": [...]} ; le lire comme un heartbeat rendait age=None,
                # donc « mort », donc -8 au score — sur un fichier écrit le jour même.
                # « Pas de champ date » n'est pas « pas d'activité » : on mesure ce
                # qu'on peut mesurer au lieu de conclure faute de champ.
                try:
                    age_s = int(now.timestamp() - p.stat().st_mtime)
                    age_src = "mtime"
                except OSError:
                    age_s = None
                    age_src = "illisible"
            _fonc, _motif = _verdict_fonctionnel(data)
            out[name] = {
                "present": True,
                "alive": age_s is not None and age_s < 21600,  # < 6h
                "age_s": age_s,
                "age_source": age_src,
                "interval_s": data.get("interval_s"),
                # `alive` dit que la CELLULE bat. `fonctionnel` dit que l'ORGANE
                # repond. Les confondre fait passer pour sain un keeper qui publie
                # lui-meme la mort de sa dependance.
                "fonctionnel": _fonc,
                "fonctionnel_motif": _motif,
                "intention_fraiche": _intention_fraiche(
                    _ORGANE_DE_WORKER.get(name, name)),
                # DECLARE : ce worker figure-t-il dans `_WORKER_HEARTBEATS` ? Les
                # decouverts sont VUS (c'est tout l'objet du changement) mais ne
                # pesent pas sur le score tant qu'ils n'ont pas ete instruits un par
                # un — certains sont des vestiges, d'autres des organes vivants.
                "declare": name not in _decouverts,
                # PROVENANCE, distincte de la presence : ce heartbeat est-il adosse a
                # un service qui le DECLARE dans services.toml ? Un fichier sans
                # declaration peut etre un residu d'ancien service comme un organe
                # reel hors registre — on NOMME l'incertitude au lieu de trancher.
                "adosse_registre": (p.name in _noms_declares) if _noms_declares else None,
                # ETEINT PAR DECISION : `disabled = true` dans services.toml. Mesure
                # 2026-09-04 : les cinq embedders (EmbedTrigger, LlamaEmbed,
                # BrainWorker, BrainWorkerRust, EmbedWorkerIsolated) le sont, suite a
                # la directive owner du 01/09 qui route l'embedding vers Modal. Sans
                # ce champ, leur silence se lit « stale » et fabrique cinq fausses
                # pannes — le faux positif exact que ce fichier combat partout.
                "eteint_par_decision": _service_desactive(p.name),
            }
        except Exception as e:
            # `alive: None` et non False : un heartbeat ILLISIBLE n'est pas un worker
            # mort. Mesure 2026-08-25 : six heartbeats du bac a sable ne sont pas du
            # JSON — deux portent une date ISO nue (`harness_worker`, `task_executor`)
            # et `lmstudio_server` n'est que des octets NUL, vieux de 37 jours. Les
            # declarer morts, c'est fabriquer des pannes a partir d'un defaut de FORMAT.
            # Un heartbeat ILLISIBLE porte lui aussi sa provenance et son etat de
            # decision : c'est le cas le PLUS ambigu, donc celui ou l'absence de
            # qualificateur coute le plus cher. Un fichier corrompu adosse a un
            # service `disabled = true` ne pose pas la meme question qu'un fichier
            # corrompu adosse a un service cense tourner.
            out[name] = {"present": True, "alive": None, "err": str(e)[:80],
                         "declare": name not in _decouverts,
                         "adosse_registre": ((p.name in _noms_declares)
                                             if _noms_declares else None),
                         "eteint_par_decision": _service_desactive(p.name)}
    return out


# Une sonde unique ne decide pas (2026-09-25) : « ❌ CRITIQUES DOWN : ['web_hub'] » (-15) etait ecrit
# sur UNE sonde de 2 s prise pendant un rechargement du superviseur, alors que la fusion de capteurs
# du MEME rapport rangeait NokidoWebHub en « sain ». Un critique qui echoue se re-sonde une fois.
_CRITIQUES_HTTP = ("hub_mcp", "ollama", "web_hub")
_RESONDE_DELAI_S = 3.0


def audit_services_http() -> dict:
    """Smoke HTTP des services attendus (sans admin)."""
    targets = {
        "hub_mcp": "http://127.0.0.1:8766/health",
        "web_hub": "http://127.0.0.1:7400/health",
        "llamacpp_native": "http://127.0.0.1:8091/v1/models",
        "llamacpp_python": "http://127.0.0.1:8090/v1/models",
        # 7420, pas 7474 : 7474 est le port par defaut de Neo4j, que Nokido
        # n'installe pas. Le Graph Explorer (FastAPI + Cytoscape) ecoute sur
        # LAFORGE_GRAPH_PORT, defaut 7420 -- cf tools/nokido_graph_server.py et
        # le proxy /graph/ du web hub. Mesure du 2026-08-15 : le service
        # repondait 200 sur 7420 pendant que le demon repetait « SOIN requis,
        # graph_explorer DOWN » depuis onze cycles. La sonde regardait ailleurs.
        "graph_explorer": "http://127.0.0.1:7420/",
        "ollama": "http://127.0.0.1:11434/api/tags",
        "netcfg_mcp": "http://127.0.0.1:8767/mcp",  # 401 attendu = vivant
        "searxng": "http://127.0.0.1:8080/search?q=ping&format=json",
    }
    def _sonder(url: str, timeout: float = 2) -> dict:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Nokido-health/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return {"up": True, "status": r.status}
        except urllib.error.HTTPError as e:
            # 401/403 = vivant (juste auth-protected)
            return {"up": True, "status": e.code, "auth_protected": True}
        except Exception as e:
            return {"up": False, "err": f"{type(e).__name__}"}

    # En PARALLELE : mesure 2026-09-24, 8,10 s sur 44,9 s de phase health, chaque
    # service endormi consommant son delai de 2 s avant la cible suivante. Les
    # issues ne changent pas ; l'ordre declare des cibles est conserve.
    from concurrent.futures import ThreadPoolExecutor

    def _sonder_deux_fois_si_critique(nom_url) -> dict:
        nom, url = nom_url
        r = _sonder(url)
        if r.get("up") or nom not in _CRITIQUES_HTTP:
            return r
        time.sleep(_RESONDE_DELAI_S)
        r2 = _sonder(url, timeout=5)
        if r2.get("up"):
            r2["premiere_sonde"] = r.get("err")   # le rattrapage se DIT, il ne s'efface pas
        else:
            r2["sondes"] = 2
        return r2

    with ThreadPoolExecutor(max_workers=len(targets), thread_name_prefix="health_http") as ex:
        return dict(zip(targets, ex.map(_sonder_deux_fois_si_critique, targets.items())))


def audit_supervised_fleet() -> dict:
    """Perception TEMPS RÉEL de la flotte : croise ce que le corps DÉCLARE, ce qui ÉCOUTE,
    et qui possède quoi. Aucune liste à tenir à jour.

    Pourquoi ça ne pouvait PAS être `audit_services_http` : celui-ci sonde une liste EN DUR
    de 8 cibles, écrite une fois et jamais resynchronisée avec l'anatomie. `:8099` (embed),
    `:8100` (rerank), `:8098` (qdrant) n'y sont pas — l'organe de santé ne regardait même
    pas l'embedder dont dépend TOUT le RAG dense, quand le superviseur déclare ~100 services
    avec leurs ports. Et « le port répond-il ? » ne dit RIEN de la propriété : un orphelin
    RÉPOND, donc il passe `up`, donc sain. Invisible PAR CONSTRUCTION — rien n'avait été
    « perdu », rien n'avait jamais été conçu pour le voir (mesuré 2026-07-16, cf 974d439f).

    Ici on ne demande pas au corps s'il va bien : on lui demande CE QU'IL EST, et on croise
    trois sources qui ne peuvent pas mentir ensemble — le registre du superviseur (l'organe
    qui a lancé), les sockets (la seule preuve d'écoute), et la propriété des pid.

    Trois pathologies, sans liste à maintenir :
      - `dead`    : déclaré `running`, mais RIEN n'écoute son port.
      - `orphans` : un process ÉCOUTE un port déclaré, aucune entrée du registre ne le
                    revendique, ET c'est un ENFANT du superviseur -> lancé puis sorti du
                    registre. Mesuré le 2026-07-16 : pid 7712 sur :8099 (registre = 4716).
      - `drift`   : le registre annonce un pid, et AUCUN process à l'écoute n'est ce pid NI
                    un de ses DESCENDANTS. La filiation est obligatoire : un service lancé
                    `runAs=interactive` passe par un LAUNCHER, donc le registre note le pid du
                    launcher pendant que le serveur qui bind le port est son enfant.
                    ⚠️ CORRECTION 2026-07-16 — la 1re version comparait les pid à l'ÉGALITÉ et
                    a produit DEUX faux positifs : NokidoWebHub (registre 22768, écoute 3704)
                    et NokidoQdrantServer (19756 / 19924). Dans les DEUX cas l'écoutant descend
                    du pid déclaré : `python(3704) -> python(22768) -> deno(14276)` et
                    `qdrant(19924) -> python(19756) -> deno(14276)`. Rien n'avait dérivé. Sur
                    la foi de ce faux positif j'ai arrêté un WebHub SAIN, et le gate ressources
                    a ensuite refusé son respawn 11 fois en 3 min 30. **Un capteur qui accuse à
                    tort coûte le service qu'il prétend protéger** — d'où la règle : filiation
                    illisible => on s'ABSTIENT, on n'accuse pas. Le gotcha « web_hub FLAKY
                    stale-PID » n'est PAS confirmé par cet audit ; il ne l'a jamais été.

    DISCRIMINANT `ppid` — sans lui l'audit crie au loup et finit ignoré : le superviseur
    DÉCLARE des services dont il n'engendre PAS le process (SearXNG vit dans Docker -> le
    listener est le proxy Docker ; LMStudio est une app externe). « Déclaré par » n'est pas
    « lancé par ». On ne retient donc comme orphelin qu'un process dont le PARENT est le
    superviseur lui-même : lui seul aurait dû figurer au registre. Un capteur qu'on ignore
    ne vaut pas mieux que pas de capteur.

    Ni le RSS ni le heartbeat ne servent ici : le RSS ne dit pas qui est légitime
    (l'orphelin pesait 665Mo, le vrai service 303Mo) et l'orphelin n'a AUCUN heartbeat tout
    en servant. Seul le registre de l'organe lanceur fait foi.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from nokido_agent.app.forge_lifecycle_tool import _supervisor_call  # helper EXISTANT, ne pas refaire
    except Exception as e:
        return {"skipped": f"forge_lifecycle_tool indisponible: {type(e).__name__}"}

    r = _supervisor_call("GET", "/supervisor/status")
    if not r.get("ok"):
        return {"skipped": r.get("error", "superviseur injoignable")}
    svcs = (r.get("data") or {}).get("services") or {}
    if not isinstance(svcs, dict) or not svcs:
        return {"skipped": "registre superviseur vide"}

    # La socket PROUVE l'écoute ; la config ne fait que la DÉCLARER.
    listening: dict = {}
    try:
        import psutil

        for c in psutil.net_connections("tcp"):
            if c.status == "LISTEN" and c.laddr and c.pid:
                listening.setdefault(c.laddr.port, set()).add(c.pid)
    except Exception as e:
        return {"skipped": f"sockets illisibles: {type(e).__name__}"}

    # Le superviseur = parent des process qu'il engendre. Tout ce qui ecoute un port
    # declare SANS descendre de lui (Docker, app externe) n'est pas un orphelin : il n'a
    # jamais eu vocation a figurer au registre.
    sup_pids: set = set()
    try:
        import psutil as _ps

        for _p in _ps.process_iter(["pid", "name"]):
            if (_p.info["name"] or "").lower() == "deno.exe":
                sup_pids.add(_p.info["pid"])
    except Exception:
        sup_pids = set()

    _anc_cache: dict = {}

    def _ancestors(pid: int):
        """Ascendants d'un pid (8 niveaux). Retourne None si la filiation est ILLISIBLE
        (droits, process disparu) : l'appelant doit alors s'ABSTENIR, jamais conclure."""
        if pid in _anc_cache:
            return _anc_cache[pid]
        out = set()
        try:
            import psutil as _ps3

            p = _ps3.Process(pid)
            for _ in range(8):
                p = p.parent()
                if p is None:
                    break
                out.add(p.pid)
        except Exception:
            out = None
        _anc_cache[pid] = out
        return out

    def _bound_by(pid: int, pids_on_port: set) -> bool:
        """Le pid déclaré tient-il le port — lui-même, ou via un descendant (launcher) ?

        Filiation illisible -> True : on s'abstient d'accuser. Le coût des deux erreurs
        n'est PAS symétrique — rater une vraie dérive laisse un capteur muet, accuser à
        tort fait ARRÊTER un service sain (mesuré sur NokidoWebHub le 2026-07-16).
        """
        for p in pids_on_port:
            if p == pid:
                return True
            anc = _ancestors(p)
            if anc is None or pid in anc:
                return True
        return False

    def _is_sup_child(pid: int) -> bool:
        try:
            import psutil as _ps2

            return _ps2.Process(pid).ppid() in sup_pids
        except Exception:
            return False  # prudence : filiation inconnue -> pas d'accusation

    claimed = {s.get("pid") for s in svcs.values() if isinstance(s, dict) and s.get("pid")}
    by_port: dict = {}
    for name, s in svcs.items():
        if isinstance(s, dict) and s.get("port"):
            by_port.setdefault(s["port"], []).append((name, s))

    dead, drift, orphans = [], [], {}
    for port, entries in by_port.items():
        pids_on_port = listening.get(port, set())
        for name, s in entries:
            pid, status = s.get("pid"), s.get("status")
            if status == "running" and not pids_on_port:
                dead.append({"service": name, "port": port, "registry_pid": pid})
            elif pid and pids_on_port and not _bound_by(pid, pids_on_port):
                drift.append({"service": name, "port": port,
                              "registry_pid": pid, "listening_pids": sorted(pids_on_port)})
        for p in pids_on_port - claimed:
            anc = _ancestors(p)
            if anc is None:
                continue  # filiation illisible -> on s'abstient
            if anc & claimed:
                continue  # descendant d'un service declare = SON serveur, pas un orphelin
            if not _is_sup_child(p):
                continue  # Docker / app externe : declare, mais pas engendre ici
            orphans[p] = {"pid": p, "port": port, "declared_by": [n for n, _ in entries]}

    return {
        "declared_with_port": len(by_port),
        "dead": dead,
        "drift": drift,
        "orphans": list(orphans.values()),
    }


def audit_lessons_recent(conn) -> dict:
    """Leçons récentes (anchor_solution / anchor_error)."""
    # GLOB et non LIKE sur un motif de PREFIXE : `LIKE` est insensible a la casse par
    # defaut, donc SQLite ne peut pas s'appuyer sur l'index de la cle primaire et
    # parcourt l'integralite de rag_chunks. Mesure 2026-09-04 : plan `SCAN` avant,
    # `SEARCH ... USING COVERING INDEX` apres. Ce diagnostic tourne periodiquement --
    # c'etait donc un balayage recurrent, pas un cout ponctuel.
    sol = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE id GLOB 'lesson_sol_*'").fetchone()[0]
    err = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE id GLOB 'lesson_err_*'").fetchone()[0]
    last_24h = conn.execute(
        "SELECT COUNT(*) FROM rag_chunks WHERE (id GLOB 'lesson_sol_*' OR id GLOB 'lesson_err_*') "
        "AND ingested_at >= datetime('now', '-24 hours')"
    ).fetchone()[0]
    return {
        "solutions_total": sol,
        "errors_total": err,
        "lessons_last_24h": last_24h,
    }


def _interpreteur_laforge_present(declare: str | None = None) -> bool | None:
    """LAFORGE_PYTHON est-il present ? True / False / None si INDETERMINE.

    Temoignage d'abord, palpation ensuite. `sys.executable` est le seul temoin qui ne
    peut pas se tromper sur ce point : si cette ligne s'execute, l'interpreteur qui la
    porte existe. On en deduit la racine `miniforge3` au lieu de la DEVINER depuis un
    HOME que le compte de service resout a cote. Le disque n'est interroge qu'apres, et
    un refus d'acces rend None -- « je n'ai pas pu regarder » n'est pas « ca n'existe
    pas ». Un parent ABSENT, lui, est une reponse nette : ce candidat-la n'existe pas.
    """
    courant = Path(sys.executable)

    # Une declaration explicite fait AUTORITE : on repond sur ELLE, jamais sur un
    # candidat de repli. Enchainer sur la racine derivee rendrait True pour un
    # `LAFORGE_PYTHON_BIN` qui pointe dans le vide — le diagnostic masquerait
    # exactement le defaut de configuration qu'il est cense lever.
    if declare:
        return _chemin_interprete(Path(declare), courant)

    candidats: list[Path] = []
    for parent in courant.parents:
        if parent.name.lower() == "miniforge3":
            candidats.append(parent / "python.exe")
            break
    candidats.append(Path.home() / "miniforge3" / "python.exe")

    indetermine = False
    for c in candidats:
        try:
            if c == courant or c.exists():
                return True
        except Exception:  # noqa: BLE001 — ACL : on ne SAIT pas, on ne conclut pas
            indetermine = True
            continue
        try:
            next(iter(c.parent.iterdir()), None)
        except (FileNotFoundError, NotADirectoryError):  # muet-ok : l'absence EST la reponse
            continue
        except Exception:  # noqa: BLE001 — parent illisible : indetermine, pas absent
            indetermine = True
    return None if indetermine else False


def _chemin_interprete(candidat: Path, courant: Path) -> bool | None:
    """Un chemin d'interpreteur : present / absent / ILLISIBLE.

    Meme discipline a trois etats que l'appelant. Le parent tranche entre les deux
    facons dont `exists()` rend False : parent listable et fichier absent = ABSENT
    (verdict net) ; parent illisible = INDETERMINE, et on n'accuse pas.
    """
    try:
        if candidat == courant or candidat.exists():
            return True
    except Exception:  # noqa: BLE001
        return None
    try:
        next(iter(candidat.parent.iterdir()), None)
    except (FileNotFoundError, NotADirectoryError):
        return False  # le dossier parent n'existe pas : reponse nette
    except Exception:  # noqa: BLE001
        return None
    return False


def audit_constants() -> dict:
    """Constantes critiques (env vars + paths Nokido)."""
    nokido_python = ROOT / "app" / "forge_python_bin.py"
    # `Path.home()` MENT sous un compte de service, et il ment DIFFEREMMENT selon le
    # compte. Le garde a trois etats existait deja ici, mais il ne reconnaissait qu'UN
    # profil non-owner (`name == "default"`) : tout autre compte de service retombait
    # sur False = « introuvable », pour -20 au score EN PERMANENCE. Mesure 2026-08-25 :
    # `%USERPROFILE%\miniforge3\python.exe` est LISIBLE depuis le sandbox et son
    # parent est listable -- ce n'etait donc meme pas une ACL, c'etait la racine devinee
    # qui etait fausse. Le remede vivait une branche plus bas que le defaut.
    _py_ok = _interpreteur_laforge_present(os.environ.get("LAFORGE_PYTHON_BIN"))
    # MESURE 2026-08-25 : ces deux lignes appelaient `get_secret` sans que le nom soit
    # dans la portee — l'import vit dans une AUTRE fonction de ce fichier. `run_cycle()`
    # levait donc `NameError` SYSTEMATIQUEMENT, et le bilan de sante consolide que la
    # doctrine prescrit pour tout diagnostic systeme n'a jamais pu s'executer. Un
    # appareil de diagnostic inerte est pire qu'absent : on croit disposer d'un bilan.
    # Et l'echec de lecture rend None, pas False : « je n'ai pas pu regarder » n'est
    # pas « le secret est absent », et le scoring en aval doit pouvoir les distinguer.
    try:
        from nokido_agent.app.forge_secrets import get_secret as _lire_secret

        _admin = bool(_lire_secret("LAFORGE_ADMIN_TOKEN"))
        _mcp = bool(_lire_secret("FORGE_MCP_TOKEN"))
    except Exception:  # noqa: BLE001
        _admin = _mcp = None
    return {
        "LAFORGE_PYTHON_path_exists": _py_ok,
        "Nokido_env_present": (ROOT / "Nokido.env").exists(),
        "LAFORGE_ADMIN_TOKEN_set": _admin,
        "FORGE_MCP_TOKEN_set": _mcp,
        "data_litellm_snapshot": (ROOT / "data" / "litellm_snapshot.json").exists(),
        "forge_python_bin_module": nokido_python.exists(),
    }


def validate_provider_keys() -> dict:
    """Verifie que chaque cle API provider resout une valeur REELLE — ni
    absente, ni placeholder `<ENCRYPTED...>`. Bug 2026-05-22 : la migration
    coffre avait stocke le texte du placeholder a la place de la vraie cle
    -> les providers repondaient 401 silencieusement. Ce check l'attrape."""
    keys = [
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "MISTRAL_API_KEY",
        "COHERE_API_KEY",
        "CEREBRAS_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "HF_TOKEN",
        "OPENROUTER_API_KEY",
        "GITHUB_TOKEN",
    ]
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as e:  # noqa: BLE001
        return {
            "error": f"forge_secrets indisponible: {e}",
            "ok": [],
            "broken": [{"key": k, "reason": "no_resolver"} for k in keys],
            "total": len(keys),
        }
    ok: list = []
    broken: list = []
    for k in keys:
        try:
            v = get_secret(k)
        except Exception:  # noqa: BLE001
            v = None
        if not v:
            broken.append({"key": k, "reason": "absente"})
        elif str(v).startswith("<ENC") or not str(v).strip():
            broken.append({"key": k, "reason": "placeholder"})
        else:
            ok.append(k)
    return {"ok": ok, "broken": broken, "total": len(keys)}


def audit_import_resolvability() -> dict:
    """Scan AST de tous les forge_*.py (app/ + tools/) : vérifie que chaque
    import d'un module Nokido (forge_*) résout. Une réf morte — module
    renommé/supprimé, un autre fichier l'importe encore — = régression,
    souvent introduite par un agent. Pur stdlib.

    Résolution robuste (évite les faux positifs) : connu si .py OU package
    (dossier avec __init__.py) dans app/tools, OU trouvable via find_spec
    (ex: forge_bm25 = rust ext installée en pip)."""
    import ast as _ast
    import importlib.util as _ilu
    import sys as _sys

    # find_spec = autorité unique : résout .py, packages-dossiers, pip installs.
    # On garantit que les emplacements Nokido sont sur sys.path — y compris
    # les sous-dossiers de tools/ et app/ (tools/research, tools/intel, ...).
    _roots = [ROOT, ROOT / "app", ROOT / "tools"]
    for _base in (ROOT / "app", ROOT / "tools"):
        if _base.is_dir():
            _roots += [p for p in _base.iterdir() if p.is_dir()]
    for d in _roots:
        if str(d) not in _sys.path:
            _sys.path.insert(0, str(d))
    files: list = []
    for d in (ROOT / "app", ROOT / "tools"):
        if d.is_dir():
            files += list(d.glob("*.py"))
    broken: list = []
    optionnels: list = []
    for p in files:
        try:
            tree = _ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue  # erreur de syntaxe -> couverte par le hook AST PostToolUse
        mods: set = set()
        gardes: set = set()
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for n in node.names:
                    mods.add(n.name.split(".")[0])
            elif isinstance(node, _ast.ImportFrom):
                if node.module and node.level == 0:
                    mods.add(node.module.split(".")[0])
            # Un import place DANS un `try` muni d'un handler n'est pas une reference
            # morte : c'est une capacite OPTIONNELLE, dont l'appelant a prevu
            # l'absence. Mesure 2026-08-25 : `forge_mcp_registry` importe
            # `forge_exegol_supervisor` sous `try`, avec un repli explicite
            # (« capacite DEPORTEE vers le depot redteam »). Le scanner le comptait
            # comme une REGRESSION, ❌ et -points, a chaque cycle — un garde qui
            # accuse un choix d'architecture finit desarme.
            elif isinstance(node, _ast.Try) and node.handlers:
                for sous in node.body:
                    for n2 in _ast.walk(sous):
                        if isinstance(n2, _ast.Import):
                            for a in n2.names:
                                gardes.add(a.name.split(".")[0])
                        elif isinstance(n2, _ast.ImportFrom):
                            if n2.module and n2.level == 0:
                                gardes.add(n2.module.split(".")[0])
        for m in mods:
            if not m.startswith("forge_"):
                continue
            try:
                spec = _ilu.find_spec(m)
            except Exception:
                spec = True  # find_spec plante -> prudence, on ne flag pas
            if spec is None:
                # On ne SUPPRIME pas l'information, on la CLASSE : un module garde
                # qui a disparu reste visible, sans etre compte comme une panne. Le
                # taire completement rendrait invisible la suppression d'un module
                # que tout le monde importerait sous `try`.
                (optionnels if m in gardes else broken).append(
                    {"file": p.name, "missing": m})
    return {"scanned": len(files), "broken": broken, "optionnels": optionnels}


# ============================================================================
# SCORING + RECOMMANDATIONS
# ============================================================================


# Journaux dont l'absence de date par ligne n'est PAS un défaut : la date est
# dans le NOM du fichier (un fichier par démarrage/exécution) ou dans un en-tête
# unique. Mesuré le 2026-07-26 : sans cette liste, un détecteur qui échantillonne
# la FIN du fichier signale 116 fautifs au lieu de 8 — et un chiffre faux décrédibilise
# le garde qui le produit.
_JOURNAL_DATE_IN_NAME = ("nokido_start_", "laforge-master-", "_sbx_", "watchdog.std")


def audit_journal_timestamps(root: Path | None = None) -> dict:
    """Journaux actifs SANS horodatage exploitable.

    Mandat owner 2026-07-26 : tout organe qui a besoin d'un horodatage s'y inscrit
    via un système fiable (`forge_timecode`). Ce garde rend la non-adoption
    VISIBLE : sans lui la convention serait déclarative, et un journal ajouté
    demain sans date passerait inaperçu jusqu'au prochain post-mortem — c'est
    exactement ce qui est arrivé avec `loop_lag.log` (22 Mo de stacks non datées)
    et `organ_pulse.log` (l'alarme du corps, non datable).

    Un fait temporel ne se réfute que par un LOG : un journal sans date ne réfute
    rien.
    """
    import re as _re
    import time as _time

    pats = [
        _re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"),   # ISO (avec ou sans ms)
        _re.compile(r'"ts"\s*:\s*("?\d{4}-\d{2}-\d{2}|\d{9,})'),  # JSONL ts ISO ou epoch
    ]
    root = root or Path(__file__).resolve().parent.parent
    undated, scanned, elagues, illisibles = [], 0, 0, 0
    for sub in ("logs", "sandbox"):
        d = root / sub
        if not d.is_dir():
            continue
        # ELAGAGE DES COPIES DE DEPOT (2026-09-24, mesure). `rglob` parcourait 487 889 fichiers
        # (106 s ; 87 s dans la phase health, qui depasse ses 90 s a CHAQUE tick) dont 380 529
        # dans les worktrees de preuve de la CI (`sandbox/workspace/tmp/nokido_proof`), et 1 793
        # des 1 879 journaux retenus y etaient des COPIES (`worktree/logs/a2a.log`...) -- pas des
        # journaux actifs d'organes, qui polluaient la liste « sans date ». Un journal ACTIF
        # n'est jamais dans une copie de depot : tout dossier portant un `.git` est elague, et
        # le NOMBRE d'elagues est rendu (un filtre qui ecarte le DIT).
        for racine, dirs, fichiers in os.walk(d):
            if ".git" in dirs or ".git" in fichiers:
                elagues += 1
                dirs[:] = []
                continue
            for nom in fichiers:
                p = Path(racine) / nom
                if p.suffix not in (".log", ".jsonl", ".err"):
                    continue
                if any(k in p.name for k in _JOURNAL_DATE_IN_NAME):
                    continue
                try:
                    st = p.stat()
                    if st.st_size == 0 or _time.time() - st.st_mtime > 7 * 86400:
                        continue
                    with p.open("rb") as f:
                        if st.st_size > 120_000:
                            f.seek(st.st_size - 120_000)
                            f.readline()
                        lines = [x for x in f.read().decode("utf-8", "replace").splitlines() if x.strip()][-20:]
                except OSError:
                    illisibles += 1   # un journal qu'on n'a pas pu lire n'est ni date ni sain : COMPTE
                    continue
                if not lines:
                    continue
                scanned += 1
                hit = sum(1 for l in lines if any(rx.search(l) for rx in pats))
                if hit < max(1, len(lines) // 2):
                    undated.append({"path": str(p.relative_to(root)).replace("\\", "/"),
                                    "size_mb": round(st.st_size / 1e6, 2)})
    undated.sort(key=lambda r: -r["size_mb"])
    return {"scanned": scanned, "undated": undated[:20], "undated_count": len(undated),
            "copies_de_depot_elaguees": elagues, "illisibles": illisibles}


def audit_host_vitals() -> dict:
    """Vitaux de la MACHINE qui porte Nokido (RAM/CPU/disque/GPU) + tendance 1 h.

    Trou MESURE le 2026-07-26 : a 11:37:34, soixante-dix secondes avant que la
    machine s'arrete SALE (Kernel-Power 41, BugcheckCode=0, aucun dump ecrit),
    ce diagnostic a produit « Score global : 50/100 » sans une seule ligne sur la
    RAM, le CPU ou le disque. L'organisme se surveillait lui-meme — RAG, tables,
    heartbeats, HTTP — mais pas l'hote qui le porte. Un rapport de sante muet sur
    son support se lit rassurant a l'instant precis ou il ne devrait pas.

    On DEMANDE au proprietaire du capteur (forge_resource_manager, SSoT du
    sampler) au lieu de re-sonder : dupliquer la mesure, c'est se preparer deux
    verites divergentes.
    """
    import time as _time

    out: dict = {"ok": False}
    try:
        import sys as _s

        _app = str(Path(__file__).resolve().parent)
        if _app not in _s.path:
            _s.path.insert(0, _app)
        # NE PAS appeler get_snapshot() : il LAZY-START un sampler (3 s) dans le
        # process appelant (forge_resource_manager.get_snapshot -> start_sampler), et
        # ce sampler spawne un PowerShell par tick pour la sonde GPU.
        # MESURE 2026-07-26 : en ajoutant cet audit j'ai cree un SECOND echantillonneur.
        # Constate dans le journal PowerShell apres restart — les sondes GPU *et* TDR,
        # throttlees a 60 s chacune, sont passees de 1,0/min a ~2,0/min a l'echelle
        # machine : deux processus, deux horloges. La serie de vitaux le disait aussi,
        # avec un ecart NEGATIF entre deux points consecutifs (deux ecrivains).
        # On lit donc l'ETAT PUBLIE par le proprietaire du capteur au lieu d'instancier
        # un rival. read_vitals_history reste sur : c'est une lecture de fichier pure.
        from nokido_agent.app.forge_resource_manager import read_vitals_history

        _state = Path(__file__).resolve().parent.parent / "sandbox" / "resource_state.json"
        snap = {}
        if _state.exists():
            try:
                snap = json.loads(_state.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                snap = {}
        if snap.get("ts"):
            # Un instantane PERIME doit se voir : sinon on lit des vitaux morts comme
            # des vitaux sains — exactement le piege que cet audit existe pour fermer.
            out["snapshot_age_s"] = round(_time.time() - float(snap["ts"]), 1)
        for k in ("ram_pct", "ram_used_gb", "ram_free_gb", "ram_total_gb",
                  "cpu_pct", "disk_pct", "gpu_pct", "tdr_recent", "gpu_sample_ms"):
            out[k] = snap.get(k)
        out["top_procs"] = (snap.get("top_procs") or [])[:5]
        hist = read_vitals_history(since_ts=_time.time() - 3600.0, limit=400)
        out["history_points_1h"] = len(hist)
        rams = [float(r["ram_pct"]) for r in hist if r.get("ram_pct") is not None]
        if rams:
            out["ram_pct_1h"] = {"min": round(min(rams), 1),
                                 "max": round(max(rams), 1),
                                 "avg": round(sum(rams) / len(rams), 1)}
        out["ok"] = True
    except Exception as exc:  # noqa: BLE001
        out["err"] = f"{type(exc).__name__}: {exc}"[:150]
    return out


# Services ON-DEMAND : éteints tant que personne ne les réclame. L'intention se
# pose en déposant `sandbox/<flag>` (TTL WANT_TTL_S) — patron DÉJÀ en place, lu par
# `forge_docker_keeper` et par l'échelle d'éviction de `forge_resource_manager`.
# On ne mappe QUE ce qui est mesuré : llamacpp_python et graph_explorer n'ont pas
# d'intention connue, ils restent donc comptés DOWN (une étiquette inventée se
# propage, et plus rien ne la distingue d'une mesure).
_ON_DEMAND_FLAG = {
    "searxng": "docker.wanted",  # searxng vit dans Docker : pas de moteur, pas de service
    "llamacpp_native": "llama.wanted",
}
_WANT_TTL_S = 900


def _on_demand_idle(name: str) -> bool:
    """Le service est-il éteint PAR DESSEIN, faute de demande fraîche ?

    Mesuré le 2026-07-28 : `docker.wanted` avait expiré à 00:16, le keeper a
    relâché Docker à 00:31 (`relache Docker ... rc=0`), et searxng est resté
    compté DOWN pendant 11 h — 12 alertes en inbox pour un état NOMINAL. Le bruit
    d'une fausse panne finit par masquer les vraies : « au repos » n'est pas
    « en panne ».
    """
    flag = _ON_DEMAND_FLAG.get(name)
    if not flag:
        return False
    p = SANDBOX / flag
    try:
        return (not p.exists()) or (time.time() - p.stat().st_mtime) >= _WANT_TTL_S
    except OSError:
        return False  # illisible : on s'abstient, on n'excuse pas une vraie panne


def audit_identification(fenetre_h: int = 1) -> dict:
    """Qui appelle le hub, et combien d'appelants restent ANONYMES.

    Mesure du 2026-08-04 : 114 406 rejets `ERR:401` sur 257 278 evenements, soit
    44 % de tout le trafic, avec `agent = no_auth` -- des appels a /mcp sans le
    moindre Bearer. Le journal savait les compter depuis toujours ; personne ne les
    LISAIT, donc l'anomalie a vecu des semaines. Instruit le 2026-08-05 : les deux
    emetteurs etaient `forge_organ_pulse` et `forge_coagulation`, daemons internes.

    Ce controle rend l'anonymat IMPOSSIBLE A IGNORER : il alimente les lacunes du
    rapport de sante, donc les faits `self_care` du demon epistemique, donc l'inbox
    d'ouverture de session. Trois etats : lisible / illisible (avec la raison) --
    ne jamais lire un journal muet comme un journal propre.
    """
    from pathlib import Path as _P

    anonymes = {"no_auth", "bad_token", "no_token",
                "expired_or_invalid_capability_token"}
    db = _P(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
    out: dict = {"lisible": False, "fenetre_h": fenetre_h}
    if not db.exists():
        out["raison"] = "journal absent : %s" % db
        return out
    try:
        c = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True, timeout=5)
    except Exception as e:  # noqa: BLE001
        out["raison"] = "ouverture refusee (%s)" % type(e).__name__
        return out
    # FUSEAU : `network_log.ts` est ecrit en heure LOCALE (datetime.now().isoformat())
    # alors que `datetime('now')` de SQLite est en UTC. Sans 'localtime', une fenetre
    # demandee a 1 h en couvrait 3 ici (UTC+2) -- mesure du 2026-08-05 : les bornes
    # -5 minutes et -1 heure rendaient le MEME compte, 1572 contre 1573. Un decalage
    # de fuseau ne fait pas planter une requete, il elargit la fenetre en silence et
    # melange des evenements d'avant un correctif avec ceux d'apres.
    try:
        borne = "-%d hours" % fenetre_h
        par_agent = dict(c.execute(
            "SELECT COALESCE(agent,'<null>'), COUNT(*) FROM network_log "
            "WHERE ts > datetime('now', 'localtime', ?) GROUP BY 1", (borne,)).fetchall())
        total = sum(par_agent.values())
        n_anon = sum(v for k, v in par_agent.items() if k in anonymes)
        # QUI, pas seulement COMBIEN : le journal resout port -> pid a l'instant du
        # rejet (connexion encore ouverte), seule attribution fiable -- une sonde
        # posterieure croise deux fenetres temporelles et accuse a tort.
        emetteurs: dict = {}
        for (meta,) in c.execute(
                "SELECT meta FROM network_log WHERE ts > datetime('now', 'localtime', ?) "
                "AND agent IN (%s) AND meta IS NOT NULL LIMIT 200"
                % ",".join("?" * len(anonymes)), (borne, *sorted(anonymes))):
            try:
                cm = (json.loads(meta) or {}).get("channel_meta") or {}
            except Exception:  # noqa: BLE001
                continue
            if cm.get("origine") == "resolue":
                cle = (cm.get("cmdline") or cm.get("process") or "?")[:120]
                emetteurs[cle] = emetteurs.get(cle, 0) + 1
        out.update({
            "lisible": True,
            "total_1h": total,
            "anonymes_1h": n_anon,
            "part_pct": round(100.0 * n_anon / total, 1) if total else 0.0,
            "agents": dict(sorted(par_agent.items(), key=lambda kv: -kv[1])[:10]),
            "emetteurs": ["%s (x%d)" % (k, v) for k, v in
                          sorted(emetteurs.items(), key=lambda kv: -kv[1])[:5]],
        })
    except Exception as e:  # noqa: BLE001
        out["raison"] = "lecture impossible (%s: %s)" % (type(e).__name__, str(e)[:80])
    finally:
        c.close()
    return out


# Examens que d'AUTRES organes produisent (2026-09-25, epreuve owner « comme un vrai medecin
# qui fait toutes les analyses »). Mesure du jour : la soif ne lisait QUE ce rapport-ci, et a cote
# `capability_freshness.json` disait `ratchet_check=REGRESSION` sans qu'aucun organe l'entende.
# Le diagnostic ne REFAIT aucun de ces examens : il les LIT et dit leur age.
# (nom, chemin sous sandbox/, cadence declaree en h ou None, producteur)
# 48 h : phase circadienne NREM1, quotidienne (supervisor.ts, bloc NREM1), et le circadien tient
# lui-meme sa dette a 48 h. None : AUCUN ordonnanceur trouve (mesure du 25/09) -- on rend l'age,
# on ne fabrique pas un verdict de peremption sur une cadence que personne n'a declaree.
_EXAMENS = (
    ("capacites", "capability_freshness.json", 48, "tools/forge_capability_freshness.py (circadien NREM1)"),
    ("innervation", "workspace/body_regulation.json", 48, "tools/forge_body_regulation_audit.py (circadien NREM1)"),
    ("atteignabilite", "reachability.json", 48, "tools/forge_reachability_ledger.py (via capability_freshness)"),
    ("anatomie", "workspace/organ_map_full.json", None, "tools/forge_module_census.py"),
    ("fournisseurs", "provider_reachability.json", None, "tools/forge_provider_reachability.py"),
)


def _constats_examen(nom: str, data) -> list:
    """Ce que dit un examen, dans SES termes -- jamais un recalcul."""
    if not isinstance(data, dict):
        return []
    if nom == "capacites":
        # INDETERMINE n'est ni PASS ni FAIL : il est NOMME tel quel, pas compte en echec.
        return sorted("%s=%s" % (k, v) for k, v in (data.get("resume") or {}).items() if v != "PASS")
    if nom == "innervation":
        compte: dict = {}
        for v in data.values():
            s = v.get("statut") if isinstance(v, dict) else None
            if s in ("ZONE_MORTE", "NON_CABLE", "INDETERMINE"):
                compte[s] = compte.get(s, 0) + 1
        return ["%s=%d" % kv for kv in sorted(compte.items())]
    if nom == "atteignabilite":
        r = data.get("resume") or {}
        return ["%s=%s" % (k, r[k]) for k in ("LOST", "ORPHELIN") if r.get(k)]
    return []


def _cablages_declares_manquants() -> list:
    from nokido_agent.app.forge_organ_agents import gaps as _gaps

    return list(_gaps())


def audit_examens(sandbox: Path | None = None, maintenant: float | None = None) -> dict:
    """Etat de CHAQUE examen du corps : FRAIS · PERIME · SANS_ORDONNANCEUR · ABSENT · ILLISIBLE.

    Un examen absent ou illisible n'est ni sain ni vide : il est nomme, et le medecin
    sait qu'une analyse lui manque au lieu de conclure d'un silence.
    """
    base = sandbox or SANDBOX
    t = time.time() if maintenant is None else maintenant
    out: dict = {}
    for nom, rel, cadence_h, producteur in _EXAMENS:
        fiche = {"fichier": rel, "cadence_h": cadence_h, "producteur": producteur, "constats": []}
        p = base / rel
        try:
            if not p.exists():
                fiche["etat"] = "ABSENT"
                out[nom] = fiche
                continue
            age = round((t - p.stat().st_mtime) / 3600, 1)
            fiche["age_h"] = age
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as e:
            fiche["etat"] = "ILLISIBLE"
            fiche["raison"] = ("%s: %s" % (type(e).__name__, e))[:120]
            out[nom] = fiche
            continue
        fiche["etat"] = ("SANS_ORDONNANCEUR" if cadence_h is None
                         else "PERIME" if age > cadence_h else "FRAIS")
        fiche["constats"] = _constats_examen(nom, data)
        out[nom] = fiche
    try:
        out["cablages_manquants"] = {"etat": "FRAIS", "producteur": "forge_organ_agents.gaps()",
                                     "constats": ["%s — %s" % (g.get("family"), g.get("missing_wiring"))
                                                  for g in _cablages_declares_manquants()]}
    except Exception as e:  # noqa: BLE001 - illisible se DIT, il ne devient pas « aucun manque »
        out["cablages_manquants"] = {"etat": "ILLISIBLE", "constats": [],
                                     "raison": ("%s: %s" % (type(e).__name__, e))[:120]}
    return out


def _lignes_examens(examens: dict) -> list:
    """Lignes de diagnostic des examens -- NON BLOQUANTES : aucune ne retire de point tant que
    leur bruit n'a pas ete mesure sur plusieurs cycles. Une ligne qui demande un soin porte un
    marqueur que la soif entend (PÉRIMÉ, REGRESSION, ERREUR_OUTIL) : sinon elle n'arriverait
    jamais au medecin."""
    lignes = []
    for nom, f in (examens or {}).items():
        etat, age, prod = f.get("etat"), f.get("age_h"), f.get("producteur", "?")
        if etat == "ABSENT":
            lignes.append(f"~ Examen PÉRIMÉ : {nom} ABSENT (jamais produit ou efface) — remede : rejouer {prod}")
        elif etat == "ILLISIBLE":
            lignes.append(f"~ Examen ILLISIBLE : {nom} ({f.get('raison', '?')}) — ni sain ni malade, non lu")
        elif etat == "PERIME":
            # PAS d'age exact ici (2026-09-25) : la soif hache le TEXTE d'une lesion pour la suivre ;
            # un age qui avance chaque cycle en faisait une lesion neuve a chaque passage (jamais
            # chronique, un fait de plus au tableau noir par cycle). L'age reste dans `examens`.
            lignes.append(f"~ Examen PÉRIMÉ : {nom} au-dela des {f.get('cadence_h')} h declarees "
                          f"— remede : rejouer {prod}")
        elif etat == "SANS_ORDONNANCEUR":
            lignes.append(f"· Examen SANS ORDONNANCEUR : {nom} a {age} h — aucune cadence declaree ({prod})")
        constats = f.get("constats") or []
        if not constats:
            continue
        quand = f" (examen de {age} h)" if age is not None else ""
        if nom == "capacites":
            lignes.append(f"⚠ Capacites : {', '.join(constats)}")   # sans age : ligne de SOIN, cf. PERIME
        elif nom == "cablages_manquants":
            lignes.extend(f"· Cablage essentiel MANQUANT (declare) : {c}" for c in constats)
        else:
            lignes.append(f"· {nom.capitalize()}{quand} : {', '.join(constats)} "
                          "— signal a instruire, jamais une suppression")
    return lignes


def audit_meta_sante() -> dict:
    """Le diagnostic est-il en etat de diagnostiquer ?

    Question posee frontalement le 2026-08-25 : « si le diagnostic est malade, Nokido
    sait-il le savoir ? ». Reponse mesuree ce jour-la : NON. Trois de ses dix lacunes
    etaient ses propres angles morts -- un HOME devine, un import garde lu comme mort,
    un service ENDORMI accuse de panne -- et rien dans le corps ne pouvait le lever.
    Un appareil de mesure qui ignore sa propre portee rend des verdicts qu'on ne peut
    pas ponderer.

    `forge_sensor_fusion_probe.coverage()` repond deja a cela et n'avait AUCUN
    appelant. On ne reecrit donc rien : on branche. Cout mesure 5,6 s pour 55 services,
    soit 1,9 % d'un tick de 300 s.

    La confiance est le PRODUIT de deux parts qui n'ont aucun sens l'une sans l'autre :
    ce qu'on VOIT (un capteur absent ne se compense pas par un capteur d'accord) et ce
    sur quoi les capteurs S'ACCORDENT (tout voir en se contredisant ne tranche rien).
    Elle ne modifie JAMAIS le score : elle dit avec quelle reserve le lire. Un score
    qui absorberait sa propre incertitude deviendrait illisible dans les deux sens.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from nokido_agent.app.forge_sensor_fusion_probe import coverage as _couverture

        c = _couverture()
    except Exception as e:  # noqa: BLE001
        # Illisible n'est pas « tout va bien » : l'appelant doit pouvoir le distinguer.
        return {"lisible": False, "raison": type(e).__name__}

    sondes = int(c.get("services_sondes") or 0)
    observables = int(c.get("observables") or 0)
    desaccords = list(c.get("en_desaccord") or [])
    part_vue = round(observables / sondes, 3) if sondes else None
    part_accord = round(1.0 - len(desaccords) / sondes, 3) if sondes else None
    confiance = (round(part_vue * part_accord, 3)
                 if part_vue is not None and part_accord is not None else None)
    return {
        "lisible": True,
        "services_sondes": sondes,
        "observables": observables,
        "zones_non_observables": int(c.get("zones_non_observables") or 0),
        "par_verdict": c.get("par_verdict") or {},
        "en_desaccord": desaccords,
        "part_observable": part_vue,
        "part_en_accord": part_accord,
        "confiance": confiance,
    }


def organes_morts(workers: dict) -> list[dict]:
    """CELLULE VIVANTE, ORGANE MORT : le keeper bat, l'organe ne repond pas, et
    quelqu'un le RECLAME (intention fraiche).

    Extrait ici pour que le PREDICAT vive a UN seul endroit : `compute_score_and_gaps`
    le lit pour scorer, `run_cycle` l'expose pour que l'etat PROPAGE au lieu de finir
    en phrase dans un rapport. Un seuil qui vit a deux endroits derive -- c'est la
    raison donnee par `_algedonic_signals` pour ne pas recalculer la severite du
    world_model_drift chez le consommateur.

    L'`intention_fraiche` reste la condition : un organe eteint n'est une panne que si
    quelqu'un le reclame (mesure 2026-08-25, `docker.wanted` perime depuis 44 h).
    """
    return [{"organe": n, "motif": h.get("fonctionnel_motif")}
            for n, h in (workers or {}).items()
            if h.get("alive") and h.get("fonctionnel") is False
            and h.get("intention_fraiche") is True]


def compute_score_and_gaps(audit: dict) -> tuple[int, list[str]]:
    """Score 0-100 + lacunes prioritaires."""
    gaps: list[str] = []
    score = 100

    # RAG vectorisation
    rag = audit["rag_chunks"]
    # Le deficit se juge sur ce qui ATTEND, pas sur `embedding IS NULL` : le
    # trigger `forge_tier_guard` refuse les paliers froids par conception, et
    # les compter en dette faisait annoncer 736 272 manquants la ou 109 053
    # etaient actionnables — puis recommander un remede impuissant sur le reste.
    _pending = rag.get("vector_pending")
    _refuse = rag.get("vector_refused")
    _lexical = rag.get("lexical_available")
    if _pending is None:
        # Ventilation indisponible : on ne sait pas ce que recouvre le brut, donc
        # on le DIT au lieu de le lire comme une dette entiere.
        score -= 5
        gaps.append(
            f"~ {rag['non_vectorized']} chunks sans embedding, ventilation PENDING/REFUSED "
            f"indisponible ({rag.get('ventilation')}) — deficit reel non mesurable ici"
        )
    elif _pending > 200_000:
        score -= 20
        gaps.append(
            f"⚠ {_pending} chunks EN ATTENTE de vecteur — relancer forge_rag_warmup "
            f"(sur {rag['non_vectorized']} sans embedding, {_refuse} sont refuses "
            f"par forge_tier_guard et n'en auront jamais)"
        )
    elif _pending > 20_000:
        score -= 5
        gaps.append(
            f"~ {_pending} chunks en attente de vecteur (rebuild partiel souhaitable) ; "
            f"{_refuse} refuses par politique, {_lexical} couverts en lexical"
        )
    if (rag.get("duplicate_hashes_echantillon") or 0) > 0:
        score -= 5
        gaps.append(f"⚠ {rag['duplicate_hashes_echantillon']} hash dupliqués dans l'échantillon "
                    f"({rag.get('doublons_statut', 'échantillon')})")

    # Biblio populated
    biblio = audit["biblio"]
    if biblio["topics_total"] == 0:
        score -= 10
        gaps.append("⚠ biblio_topics vide — biblio_worker hook topic-extractor inactif ?")
    _bq = biblio["raw_by_status"].get("queued", 0) + biblio["raw_by_status"].get("unverified", 0)
    if _bq > 50:
        score -= 5
        gaps.append(f"~ {_bq} biblio_raw queued/unverified (worker en retard ou vocab mismatch ?)")

    # Tables vides critiques
    empty_critical = [
        t for t in audit["tables_empty"]["empty_tables"] if t in ("forge_entities", "biblio_raw", "rag_chunks")
    ]
    if empty_critical:
        score -= 30
        gaps.append(f"❌ Tables critiques VIDES : {empty_critical}")

    # Workers heartbeat morts — MAIS un daemon ETEINT VOLONTAIREMENT n'est pas mort.
    # Mesure 2026-08-25 : les quatre « workers morts » signales etaient
    # `gemini_poll` et `gemini_autonomous` (`disabled = true` dans services.toml,
    # decision owner : mode autonome coupe par defaut), `rss_watcher` (`sleeping`,
    # on-demand) et `health_diagnostic` (perime parce que CE module levait). Soit
    # ZERO panne reelle, pour -32 points de score. Un garde qui crie a faux se fait
    # desarmer : c'est la doctrine du corps, et elle vaut d'abord pour ses propres
    # capteurs. On consulte donc l'etat DECLARE avant d'accuser.
    workers = audit["workers_heartbeat"]
    _exempts, _pourquoi_exempt = _daemons_au_repos_declare()
    # `declare` : voir le commentaire de `audit_workers_heartbeat`. Les organes
    # DECOUVERTS par enumeration du disque sont audites mais n'entrent pas dans le
    # calcul du score tant qu'ils n'ont pas ete instruits — ils sont rapportes a part.
    dead = [n for n, h in workers.items()
            if h.get("present") and h.get("alive") is False and n not in _exempts
            and h.get("declare", True)]
    repos = [n for n, h in workers.items()
             if h.get("present") and h.get("alive") is False and n in _exempts]
    _hb_illisibles = [n for n, h in workers.items()
                      if h.get("present") and h.get("alive") is None
                      and h.get("declare", True)]
    # LA ZONE D'OMBRE, NOMMEE. Tant que ces organes n'etaient pas enumeres, leur mort
    # etait silencieuse PAR CONSTRUCTION. On les montre desormais, avec leur etat, et
    # on dit explicitement qu'ils ne comptent pas encore : un chiffre de couverture
    # honnete vaut mieux qu'un score flatteur calcule sur une fraction de la flotte.
    _hors_liste = {n: h for n, h in workers.items() if not h.get("declare", True)}
    if _hors_liste:
        _hl_morts = sorted(n for n, h in _hors_liste.items() if h.get("alive") is False)
        _hl_vivants = sorted(n for n, h in _hors_liste.items() if h.get("alive") is True)
        _hl_flous = sorted(n for n, h in _hors_liste.items() if h.get("alive") is None)
        gaps.append(
            "~ COUVERTURE : %d organe(s) battent HORS de la liste de surveillance "
            "(%d declares sur %d heartbeats presents) — audites depuis le 2026-09-04 "
            "mais NON comptes au score tant qu'ils ne sont pas instruits un par un. "
            "stale=%s | frais=%s | illisibles=%s"
            % (len(_hors_liste), len(workers) - len(_hors_liste), len(workers),
               _hl_morts[:12], _hl_vivants[:12], _hl_flous[:12]))

    # UN SILENCE VOULU N'EST PAS UNE PANNE — et la moitie des silences le sont.
    # Mesure 2026-09-04 : sur 8 organes stale, 4 portent `disabled = true` dans
    # services.toml (embed_auto_trigger, gemini_autonomous, handoff_worker,
    # pyexec_server) — dont les embedders eteints par la directive owner du 01/09 qui
    # route l'embedding vers Modal. Les rapporter comme morts, c'est fabriquer quatre
    # pannes et noyer les vraies. On separe donc les deux populations, et on NOMME
    # celles dont la provenance reste inconnue plutot que de les ranger d'office.
    _tus = sorted(n for n, h in workers.items()
                  if h.get("alive") is False and h.get("eteint_par_decision") is True)
    _muets = sorted(n for n, h in workers.items()
                    if h.get("alive") is False and h.get("eteint_par_decision") is not True)
    if _tus:
        gaps.append("· Silence VOULU (disabled=true dans services.toml, pas une "
                    "panne) : %s" % _tus[:12])
    if _muets:
        _sans_provenance = sorted(n for n in _muets
                                  if workers[n].get("eteint_par_decision") is None)
        gaps.append(
            "⚠ Organes silencieux CENSES TOURNER : %s%s"
            % (_muets[:12],
               (" | provenance INCONNUE pour %s — registre illisible ou heartbeat "
                "hors services.toml, a instruire avant d'accuser" % _sans_provenance[:8])
               if _sans_provenance else ""))
    if dead:
        score -= 8 * len(dead)
        gaps.append(f"⚠ Workers daemon morts (heartbeat stale) : {dead}")
    if repos:
        gaps.append("· Workers au repos DECLARE (pas une panne) : "
                    f"{repos} — {_pourquoi_exempt}")
    if _hb_illisibles:
        gaps.append(
            f"~ {len(_hb_illisibles)} heartbeat(s) ILLISIBLE(S) — défaut de FORMAT, "
            f"pas de mort constatée : {_hb_illisibles}"
        )

    # CELLULE VIVANTE, ORGANE MORT. Un keeper qui bat frais tout en publiant que sa
    # dépendance est down passait pour sain : le corps mesurait la disponibilité de la
    # cellule, jamais le témoignage fonctionnel de l'organe.
    #
    # Mais un organe éteint n'est une PANNE que si quelqu'un le réclame. Mesure
    # 2026-08-25 : `docker.wanted` a 159 731 s pour un TTL déclaré de 900 s — périmé
    # depuis 44 heures. `daemon_up: false` y est donc l'état VOULU, et l'accuser
    # aurait fabriqué un faux positif de plus.
    _organe_mort = organes_morts(workers)
    _organe_au_repos = [n for n, h in workers.items()
                        if h.get("alive") and h.get("fonctionnel") is False
                        and h.get("intention_fraiche") is False]
    _intention_illisible = [n for n, h in workers.items()
                            if h.get("alive") and h.get("fonctionnel") is False
                            and h.get("intention_fraiche") is None]
    if _organe_mort:
        score -= min(18, 6 * len(_organe_mort))
        gaps.append(
            "❌ CELLULE VIVANTE, ORGANE MORT — le keeper bat et quelqu'un RÉCLAME "
            f"l'organe, mais il ne répond pas : "
            f"{[(d['organe'], d['motif']) for d in _organe_mort]}"
        )
    if _organe_au_repos:
        gaps.append(
            "· Organe au repos, conforme à l'intention (aucun `.wanted` frais — "
            f"pas une panne) : {_organe_au_repos}"
        )
    if _intention_illisible:
        gaps.append(
            "~ Organe down mais INTENTION ILLISIBLE (ni panne ni repos établis) : "
            f"{_intention_illisible}"
        )

    # Services HTTP DOWN
    svcs = audit["services_http"]
    _off = [n for n, s in svcs.items() if not s.get("up")]
    idle = [n for n in _off if _on_demand_idle(n)]
    down = [n for n in _off if n not in idle]
    critical_down = [n for n in down if n in _CRITIQUES_HTTP]
    if critical_down:
        score -= 15 * len(critical_down)
        gaps.append(f"❌ Services CRITIQUES DOWN : {critical_down}")
    elif down:
        score -= 3 * len(down)
        gaps.append(f"~ Services DOWN (non-critiques) : {down}")
    if idle:
        gaps.append(
            f"· Services au repos (on-demand, aucune intention fraîche) : {idle} "
            "— état voulu, pas une panne"
        )

    # Flotte supervisée : ce que le corps DÉCLARE vs ce qui ÉCOUTE vs qui possède.
    # Couvre tout ce que la liste en dur de `services_http` ne voit pas (embed :8099,
    # rerank :8100, qdrant :8098... ~100 services declares).
    fleet = audit.get("supervised_fleet", {})
    if not fleet.get("skipped"):
        _dead = fleet.get("dead", [])
        if _dead:
            # « RIEN n'écoute son port » est un CONSTAT, pas un diagnostic. Un launcher
            # terminé, un démarrage en cours, un service endormi et un vrai fantôme
            # produisent EXACTEMENT le même silence, et n'appellent pas la même réponse.
            # `forge_sensor_fusion_probe` sait déjà les distinguer : il croise registre,
            # port, pid et heartbeat, et il nomme explicitement « je n'ai pas pu voir ».
            # Mesure 2026-08-25 : il n'avait AUCUN appelant hors son propre CLI, un audit
            # et ses tests — le meilleur organe sensoriel du corps ne commandait aucun
            # réflexe. Il ne manquait que le câble.
            _grave: list = []
            _tiede: list = []
            _capteur: list = []
            _explique: list = []
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                from nokido_agent.app.forge_sensor_fusion_probe import probe as _fusion

                for _d in _dead:
                    _v = (_fusion(_d["service"], port=_d.get("port")) or {}).get("verdict")
                    if _v == "fantome":
                        _grave.append((_d["service"], _v))
                    elif _v == "revendique_mais_sourd":
                        _tiede.append((_d["service"], _v))
                    elif _v in ("indeterminable", "heartbeat_gele"):
                        _capteur.append((_d["service"], _v))
                    else:
                        _explique.append((_d["service"], _v))
            except Exception as e:  # noqa: BLE001
                # Dégradation DITE. Sans le capteur on retombe sur le constat brut, et on
                # le signale : un repli silencieux ferait passer « je n'ai pas pu
                # qualifier » pour « c'est bien un défaut ».
                _grave = _tiede = _capteur = _explique = []
                score -= min(20, 5 * len(_dead))
                gaps.append(
                    f"❌ Déclarés running mais RIEN n'écoute : {[d['service'] for d in _dead]}"
                    f" — NON QUALIFIÉ (fusion de capteurs indisponible : {type(e).__name__})"
                )
            if _grave:
                score -= min(20, 5 * len(_grave))
                gaps.append(
                    f"❌ FANTÔMES — pid disparu, personne ne les relancera : {_grave}"
                )
            if _tiede:
                score -= min(10, 3 * len(_tiede))
                gaps.append(
                    f"⚠ Revendiqués mais SOURDS — liveness sans readiness : {_tiede}"
                )
            if _capteur:
                # Ni pénalité, ni silence : c'est la SONDE qui manque, pas l'organe qui
                # faute. Confondre les deux fait accuser un service sain.
                gaps.append(
                    "~ Verdict IMPOSSIBLE ou capteur gelé (la sonde manque, l'organe "
                    f"n'est pas mis en cause) : {_capteur}"
                )
            if _explique:
                gaps.append(
                    "· Port muet EXPLIQUÉ par la fusion de capteurs (pas une panne) : "
                    f"{_explique}"
                )
        _orph = fleet.get("orphans", [])
        if _orph:
            score -= min(10, 3 * len(_orph))
            gaps.append(
                f"⚠ {len(_orph)} process ORPHELIN(S) — écoutent un port déclaré, revendiqués par "
                f"aucun service : {[(o['pid'], o['port']) for o in _orph]} "
                "— enfant hors registre du superviseur (ne PAS tuer a l'aveugle : verifier qui sert)"
            )
        _drift = fleet.get("drift", [])
        if _drift:
            score -= min(10, 3 * len(_drift))
            gaps.append(
                f"⚠ Dérive registre/socket : {[(d['service'], d['registry_pid'], d['listening_pids']) for d in _drift]}"
            )

    # Examens des AUTRES organes (2026-09-25) : lus, dates, NON BLOQUANTS (cf. _lignes_examens).
    gaps.extend(_lignes_examens(audit.get("examens")))

    # Méta-santé : ce que le diagnostic sait de sa PROPRE portée. Aucune de ces lignes
    # ne retire de point — elles qualifient le score, elles ne le remplacent pas. Un
    # capteur absent n'est pas une pathologie de l'organe : c'est une limite de la
    # mesure, et la confondre avec une panne fait accuser un service sain.
    _meta = audit.get("meta_sante") or {}
    if _meta.get("lisible") is False:
        gaps.append(
            f"~ MÉTA-SANTÉ ILLISIBLE ({_meta.get('raison')}) — le score ci-dessus n'est "
            "assorti d'AUCUNE confiance mesurée : le lire comme tel"
        )
    elif _meta.get("lisible"):
        _nz = _meta.get("zones_non_observables") or 0
        if _nz:
            gaps.append(
                f"~ {_nz} zone(s) NON OBSERVABLE(S) sur {_meta.get('services_sondes')} "
                "— ni port ni heartbeat : « pas vu » n'est pas « rien à signaler »"
            )
        if _meta.get("en_desaccord"):
            gaps.append(
                "~ Capteurs en DÉSACCORD (verdict fragile — ne pas déclencher d'action "
                f"automatique dessus) : {_meta['en_desaccord']}"
            )
        _conf = _meta.get("confiance")
        if _conf is not None and _conf < 0.9:
            gaps.append(
                f"~ CONFIANCE du diagnostic : {_conf:.0%} (vu {_meta['part_observable']:.0%}, "
                f"accord {_meta['part_en_accord']:.0%}) — le score est une estimation "
                "sous cette réserve"
            )

    # Constantes critiques
    cst = audit["constants"]
    # `is False` et NON `not` : None signifie INDETERMINE (HOME non-owner, cf
    # audit_constants). Un capteur qui n'a pas pu regarder ne doit pas faire perdre 20
    # points -- c'est la difference entre « absent » et « invisible d'ici ».
    if cst["LAFORGE_PYTHON_path_exists"] is False:
        score -= 20
        gaps.append("❌ LAFORGE_PYTHON path miniforge3 introuvable")
    elif cst["LAFORGE_PYTHON_path_exists"] is None:
        gaps.append(
            "~ Interpreteur LaForge NON EVALUE (HOME non-owner : profil invisible d'ici) "
            "— indetermine, pas un defaut"
        )
    if not cst["LAFORGE_ADMIN_TOKEN_set"] and not cst["FORGE_MCP_TOKEN_set"]:
        gaps.append("~ Aucun break-glass token dans env (lu seulement depuis Nokido.env)")

    # Cles provider cassees (placeholder <ENCRYPTED...> ou absentes)
    pk = audit.get("provider_keys", {})
    broken_pk = pk.get("broken", [])
    if broken_pk:
        score -= min(20, 4 * len(broken_pk))
        gaps.append(
            f"⚠ {len(broken_pk)} cle(s) provider cassee(s) : "
            f"{[b['key'] for b in broken_pk]} — placeholder/absente, 401 garanti"
        )

    # Imports Nokido morts (module forge_* renommé/supprimé, réf non résolue)
    imp = audit.get("imports", {})
    broken_imp = imp.get("broken", [])
    if broken_imp:
        score -= min(30, 6 * len(broken_imp))
        gaps.append(
            f"❌ {len(broken_imp)} import(s) Nokido mort(s) : "
            f"{[(b['file'], b['missing']) for b in broken_imp[:6]]} "
            "— module renomme/supprime, regression"
        )
    # Capacite OPTIONNELLE absente : l'import est garde par un `try` avec repli, donc
    # l'appelant a prevu ce cas. Visible sans penalite — la taire rendrait invisible
    # la suppression d'un module que tout le monde importerait sous `try`.
    _imp_opt = imp.get("optionnels", [])
    if _imp_opt:
        gaps.append(
            f"· {len(_imp_opt)} capacité(s) OPTIONNELLE(S) absente(s) — import gardé "
            f"avec repli, pas une régression : "
            f"{[(b['file'], b['missing']) for b in _imp_opt[:6]]}"
        )

    # Mailbox saturée
    am = audit["messages"]
    if am["agent_messages_total"] > 5000 and am["agent_messages_pct_unread"] > 30:
        score -= 5
        gaps.append(
            f"~ Mailbox surchargée : {am['agent_messages_total']} msgs, "
            f"{am['agent_messages_pct_unread']}% unread — purge/archive recommandé"
        )

    # Horodatage des journaux. Une convention non mesurée est une convention
    # déclarative : c'est le garde, pas le document, qui la rend fiable.
    jt = audit.get("journal_timestamps") or {}
    if jt.get("undated_count"):
        worst = ", ".join(u["path"] for u in (jt.get("undated") or [])[:3])
        gaps.append(f"⚠ {jt['undated_count']} journal(aux) actif(s) SANS horodatage : {worst}")
        score -= min(10, 2 * jt["undated_count"])

    # Vitaux de l'hote. Un score de sante qui ignore la machine porteuse peut
    # rester a 50/100 pendant que la RAM sature — c'est arrive le 2026-07-26.
    hv = audit.get("host_vitals") or {}
    if hv.get("ok"):
        _ram = hv.get("ram_pct") or 0
        if _ram >= 90:
            gaps.append(f"❌ RAM hôte à {_ram}% — au-delà du seuil où le gate P1 refuse tout spawn (85%)")
            score -= 15
        elif _ram >= 85:
            gaps.append(f"⚠ RAM hôte à {_ram}% — au seuil de blocage P1")
            score -= 5
        if not hv.get("history_points_1h"):
            gaps.append("~ aucune série de vitaux hôte sur 1 h — un arrêt brutal resterait indiagnosticable")
            score -= 3
    else:
        gaps.append("⚠ vitaux hôte illisibles — « je ne peux pas voir » n'est pas « tout va bien »")
        score -= 3
    # IDENTIFICATION DES CLIENTS. Directive owner 2026-08-05 : « je ne veux plus
    # aucun manque d'identification des clients du hub ». Un correctif ponctuel ne
    # garantit rien -- le prochain daemon ecrit sans jeton et l'anonymat revient en
    # silence. Ce controle-ci est la garantie DURABLE.
    ident = audit.get("identification") or {}
    if ident.get("lisible"):
        _anon = ident.get("anonymes_1h") or 0
        if _anon:
            _part = ident.get("part_pct") or 0
            _qui = ident.get("emetteurs") or ["origine non resolue"]
            _marque = "❌" if _part >= 10 else "⚠"
            gaps.append(
                f"{_marque} {_anon} requete(s) NON IDENTIFIEE(S) sur 1 h "
                f"({_part}% du trafic hub) — emetteur(s) : {'; '.join(_qui[:3])} "
                f"| un appelant sans Bearer est compte `no_auth` par _resolve_ring "
                f"| remede : le faire passer par forge_hub_client(agent=<NOM>) et "
                f"declarer l'identite dans config/agent_identities.json")
            score -= 15 if _part >= 10 else 5
    else:
        gaps.append(
            "⚠ identification des clients ILLISIBLE (%s) — impossible de dire s'il "
            "reste des appelants anonymes ; « je ne peux pas voir » n'est pas "
            "« tout va bien »" % (ident.get("raison") or "raison inconnue"))
        score -= 3
    score = max(0, min(100, score))
    return score, gaps


# ============================================================================
# REPORTING
# ============================================================================


def write_report(audit: dict, score: int, gaps: list[str]) -> Path:
    """Markdown lisible humain dans sandbox/health_report_<date>.md."""
    date = datetime.now().strftime("%Y-%m-%d_%H%M")
    path = SANDBOX / f"health_report_{date}.md"
    rag = audit["rag_chunks"]
    biblio = audit["biblio"]
    db = audit["db_size"]
    am = audit["messages"]

    md = [
        f"# Diagnostic santé Nokido — {date}",
        "",
        f"## Score global : **{score}/100**",
        "",
        "### Lacunes prioritaires",
    ]
    if gaps:
        for g in gaps:
            md.append(f"- {g}")
    else:
        md.append("- (aucune — système nominal)")
    md += [
        "",
        "## RAG",
        f"- {rag['total']:,} chunks total — **{rag['pct_vectorized']}% vectorisés** ({rag['vectorized']:,}/{rag['total']:,})",
        f"- Embedding dim : {rag['embedding_dim_f32']} (f32, {rag['embedding_avg_bytes']} bytes)",
        f"- Hash duplicates (ÉCHANTILLON) : {rag.get('duplicate_hashes_echantillon', '?')} "
        f"({rag.get('duplicate_rows_echantillon', '?')} rows) — {rag.get('doublons_statut', '?')}",
        "- Quality score (ÉCHANTILLON) : avg={avg} min={min} max={max}".format(
            **{k: (rag.get('quality_score_echantillon') or {}).get(k, '?') for k in ('avg', 'min', 'max')}),
        "- Top domaines : " + ", ".join(f"`{d['domain']}`({d['count']})" for d in rag["top_domains"][:5]),
        "",
        "## Biblio",
        "- biblio_raw status : " + ", ".join(f"{k}={v}" for k, v in biblio["raw_by_status"].items()),
        f"- biblio_topics : {biblio['topics_total']} ({biblio['topics_distinct']} distincts, "
        f"{biblio['topics_auto_extracted']} auto-extraits laforge-qwen)",
        f"- biblio_link cross-entries : {biblio['cross_links']}",
        "",
        "## Mailbox + logs",
        f"- agent_messages : {am['agent_messages_total']:,} total, {am['agent_messages_today']} aujourd'hui, "
        f"{am['agent_messages_unread']} unread ({am['agent_messages_pct_unread']}%)",
        f"- network_log : {am['network_log_total']:,}",
        f"- conversation_log : {am['conversation_log_total']:,}",
        f"- shared_prompt_log : {am['shared_prompt_log_total']:,}",
        "",
        "## Tables peuplement",
        f"- {audit['tables_empty']['total_tables_audited']} tables auditées",
        f"- Vides : {audit['tables_empty']['empty_tables']}",
        f"- Faiblement peuplées (<5 rows) : {audit['tables_empty']['low_population_tables']}",
        "",
        "## DB taille",
        f"- main : {db.get('size_mb_main', '?')} MB",
        f"- WAL : {db.get('size_mb-wal', '?')} MB",
        "",
        "## Horodatage des journaux",
    ]
    _jt = audit.get("journal_timestamps") or {}
    md.append(f"- {_jt.get('scanned', 0)} journaux actifs scannés — **{_jt.get('undated_count', 0)} sans date exploitable**")
    for _u in (_jt.get("undated") or [])[:8]:
        md.append(f"  - `{_u['path']}` ({_u['size_mb']} Mo)")
    md += [
        "",
        "## Vitaux hôte (la machine qui porte Nokido)",
    ]
    hv = audit.get("host_vitals") or {}
    if hv.get("ok"):
        md.append(f"- RAM : **{hv.get('ram_pct')}%** ({hv.get('ram_used_gb')}/{hv.get('ram_total_gb')} Go, libre {hv.get('ram_free_gb')} Go)")
        md.append(f"- CPU : {hv.get('cpu_pct')}% · disque : {hv.get('disk_pct')}% · GPU : {hv.get('gpu_pct')} (coût sonde {hv.get('gpu_sample_ms')} ms) · TDR récents : {hv.get('tdr_recent')}")
        r1h = hv.get("ram_pct_1h")
        if r1h:
            md.append(f"- RAM sur 1 h : min={r1h['min']}% avg={r1h['avg']}% max={r1h['max']}% ({hv.get('history_points_1h')} points)")
        else:
            md.append(f"- Série de vitaux : {hv.get('history_points_1h', 0)} point(s) sur 1 h — sans série, un arrêt brutal reste indiagnosticable")
        if hv.get("top_procs"):
            md.append("- Top RAM : " + ", ".join(f"{t.get('name')} {t.get('ram_gb')} Go" for t in hv["top_procs"]))
    else:
        md.append(f"- ⚠ vitaux hôte ILLISIBLES : {hv.get('err', 'capteur muet')}")
    md += [
        "",
        "## Workers daemon (heartbeats)",
    ]
    for n, h in audit["workers_heartbeat"].items():
        if h.get("present"):
            tag = "🟢" if h.get("alive") else "🔴"
            md.append(f"- {tag} **{n}** : age={h.get('age_s', '?')}s")
        else:
            md.append(f"- ⚪ {n} : pas de heartbeat (jamais lancé ?)")
    md += [
        "",
        "## Services HTTP",
    ]
    for n, s in audit["services_http"].items():
        if s.get("up"):
            tag = "🟢"
        else:
            tag = "😴" if _on_demand_idle(n) else "🔴"
        md.append(f"- {tag} **{n}** : status={s.get('status', s.get('err', '?'))}")
    md += [
        "",
        "## Leçons (capitalisation)",
        f"- {audit['lessons']['solutions_total']} solutions, {audit['lessons']['errors_total']} erreurs ancrées",
        f"- {audit['lessons']['lessons_last_24h']} ancrages dernières 24h",
        "",
        "## Constantes",
    ]
    for k, v in audit["constants"].items():
        tag = "✓" if v else "✗"
        md.append(f"- {tag} {k}")
    md += [
        "",
        "---",
        "_Généré par forge_health_diagnostic — JSON brut : sandbox/health_diagnostic.json_",
    ]
    path.write_text("\n".join(md), encoding="utf-8")
    return path


def _heartbeat(stats: dict) -> None:
    try:
        SANDBOX.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(
            json.dumps(
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "pid": os.getpid(),
                    "interval_s": DEFAULT_INTERVAL_S,
                    "last_score": stats.get("score"),
                    "last_gaps_count": len(stats.get("gaps", [])),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


# ============================================================================
# ENTRYPOINT
# ============================================================================


def _release_hormones_from_audit(audit: dict) -> list[dict]:
    """Hypothalamus : convertit l'audit en signaux hormonaux (forge_endocrine).
    Système biomimétique de régulation transverse — les récepteurs distants
    (forge_llm_router, forge_rag_warmup, forge_*_daemon) lisent les hormones
    et adaptent leur comportement sans couplage direct.
    """
    try:
        from nokido_agent.app.forge_endocrine import release
    except ImportError:
        return []

    released = []
    rag = audit["rag_chunks"]
    am = audit["messages"]

    # 1. Vectorisation : déficit ou saturation
    #
    # MESURE 2026-08-25 — l'accélérateur était INATTEIGNABLE par construction. Son
    # niveau valait `(80 - pct) / 80`, soit 0,0125 à pct=79 % : le récepteur
    # (`forge_rag_warmup`, `TSH > 0.4 -> batch ×2`) ne pouvait donc réagir qu'en
    # dessous de **48 %** de corpus vectorisé. Entre 80 % et 95 %, RIEN n'était émis
    # du tout — c'est-à-dire sur toute la plage de fonctionnement normale. Relevé du
    # jour : pct=86,7 %, 176 467 chunks en attente, `read_full("TSH_VECTORIZATION")`
    # ne rend AUCUNE ligne en base, tandis que l'antagoniste `INSULIN_VECTORIZATION`
    # tient 0,477 (au-dessus de son seuil de frein) et se renouvelle 144 fois en
    # 4 h 05. Une régulation avec un frein permanent et un accélérateur hors
    # d'atteinte n'est pas une régulation : c'est un frein.
    #
    # Le niveau est désormais gradué sur la distance à la cible, entre les DEUX
    # bornes que cette fonction publiait déjà (80 % et 95 %) — on ne choisit aucun
    # chiffre neuf, c'est le motif `seuil_invente` de RULES_SHARED. La courbe devient
    # continue et monotone : 1,0 sous 80 %, 0,55 à 86,7 %, 0,07 à 94 %, 0 à 95 %.
    # L'antagoniste continue de s'opposer au MÊME site : quand la RAM est haute, le
    # frein annule le boost, et la demande ne l'emporte que si les ressources suivent.
    pct = rag["pct_vectorized"]
    _CIBLE, _ALARME = 95.0, 80.0
    if pct < _CIBLE:
        level = max(0.0, min(1.0, (_CIBLE - pct) / (_CIBLE - _ALARME)))
        released.append(
            release(
                "TSH_VECTORIZATION",
                level=level,
                source="health_diagnostic",
                reason=(f"pct_vectorized={pct}% < {_CIBLE:.0f}% cible "
                        f"({rag['non_vectorized']} non-vec)"),
            )
        )
    elif pct > 95:
        # Saturation : signal de "ralenti"
        level = min(1.0, (pct - 95) / 5)
        released.append(
            release(
                "INSULIN_VECTORIZATION",
                level=level,
                source="health_diagnostic",
                reason=f"pct_vectorized={pct}% > 95% (saturation OK)",
            )
        )

    # 2. Mailbox saturée
    unread_pct = am["agent_messages_pct_unread"]
    if unread_pct > 50 and am["agent_messages_total"] > 100:
        level = min(1.0, (unread_pct - 50) / 50)
        released.append(
            release(
                "LEPTIN_MAILBOX_FULL",
                level=level,
                source="health_diagnostic",
                reason=f"unread={unread_pct}% / total={am['agent_messages_total']}",
            )
        )

    # 3. Cortisol cloud — délégation à forge_token_monitor (a accès au daily_cost)
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_token_monitor import daily_report, ALERT_DAILY_BUDGET_USD

        rep = daily_report()
        cost = rep.get("daily_cost_usd", 0)
        ratio = cost / max(ALERT_DAILY_BUDGET_USD, 1.0)
        if ratio > 0.6:
            released.append(
                release(
                    "CORTISOL_QUOTA_CLOUD",
                    level=min(1.5, ratio),
                    source="health_diagnostic+token_monitor",
                    reason=f"daily_cost ${cost} / ${ALERT_DAILY_BUDGET_USD} = {ratio:.2f}",
                )
            )
    except Exception:
        pass

    return released


def run_cycle() -> dict:
    """Un cycle complet de diagnostic."""
    conn = _conn()
    audit = {
        "ts": datetime.now().isoformat(),
        "rag_chunks": audit_rag_chunks(conn),
        "biblio": audit_biblio(conn),
        "messages": audit_messages(conn),
        "tables_empty": audit_tables_empty(conn),
        "lessons": audit_lessons_recent(conn),
        "db_size": audit_db_size(),
        "workers_heartbeat": audit_workers_heartbeat(),
        "services_http": audit_services_http(),
        "supervised_fleet": audit_supervised_fleet(),
        "constants": audit_constants(),
        "provider_keys": validate_provider_keys(),
        "imports": audit_import_resolvability(),
        "host_vitals": audit_host_vitals(),
        "journal_timestamps": audit_journal_timestamps(),
        "identification": audit_identification(),
        "meta_sante": audit_meta_sante(),
        "examens": audit_examens(),
    }
    conn.close()

    score, gaps = compute_score_and_gaps(audit)
    audit["score"] = score
    # Le score et sa confiance voyagent ENSEMBLE : un consommateur qui lit l'un sans
    # l'autre traite une estimation comme une mesure.
    audit["confiance"] = (audit.get("meta_sante") or {}).get("confiance")
    audit["gaps"] = gaps

    # Hypothalamus : émet les hormones selon les lacunes détectées
    audit["hormones_released"] = _release_hormones_from_audit(audit)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path = write_report(audit, score, gaps)
    _heartbeat({"score": score, "gaps": gaps, "hormones": [h["hormone"] for h in audit["hormones_released"]]})

    return {
        "score": score,
        "gaps_count": len(gaps),
        # L'ETAT, pas seulement son resume. Sans cette clef le verdict « cellule
        # vivante, organe mort » restait un point de score et une phrase : aucun
        # consommateur ne pouvait agir dessus. Lu par
        # `forge_homeostasis_orchestrator._algedonic_signals`.
        "organes_morts": organes_morts(audit["workers_heartbeat"]),
        "hormones_released": [h["hormone"] for h in audit["hormones_released"]],
        "json": str(OUT_JSON),
        "report": str(report_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido health diagnostic")
    ap.add_argument("--once", action="store_true", help="1 cycle puis exit (default)")
    ap.add_argument("--daemon", action="store_true", help="cycle 6h")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S)
    ap.add_argument(
        "--import-check",
        action="store_true",
        help="scan des imports Nokido morts seulement (rapide — hook git pre-push)",
    )
    args = ap.parse_args()

    if args.import_check:
        r = audit_import_resolvability()
        print(f"BROKEN_IMPORTS={len(r['broken'])}", flush=True)
        for b in r["broken"]:
            print(f"  {b['file']} -> {b['missing']}", flush=True)
        return 0

    if args.daemon:
        try:
            (SANDBOX / "health_diagnostic.pid").write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass

    while True:
        out = run_cycle()
        print(f"[health] score={out['score']}/100 gaps={out['gaps_count']}", flush=True)
        print(f"  -> JSON   : {out['json']}", flush=True)
        print(f"  -> Report : {out['report']}", flush=True)
        if not args.daemon:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
