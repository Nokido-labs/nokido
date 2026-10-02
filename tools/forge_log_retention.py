"""forge_log_retention.py — Rétention + sanitisation tiers des logs Nokido.

Mesuré 2026-05-30 : execution_traces.db = 62.8 MB, +4.7 MB/jour (≈1.7 GB/an),
non borné (aucune rétention). 3 KB/trace = les 2 embeddings (state_t/state_t1).

Stratégie en tiers (borne le poids SANS perdre le signal utile) :
  CHAUD  0-WARM_DAYS   : trace complète (embeddings + action) -> offline_trainer
                         + debug + réversibilité opt-in (<7j).
  TIÈDE  WARM..COLD    : DROP les 2 embeddings (le bulk 3 KB/row), garde
                         action_json + cost + success (trace_mining + audit).
                         offline_trainer a déjà appris dessus.
  FROID  > COLD_DAYS   : DELETE les lignes brutes (le trainer + le miner ne
                         regardent plus aussi loin).
Puis : purge audit.db (>COLD), prune redaction_vault (>WARM, cf. réversibilité),
VACUUM pour réclamer l'espace.

Usage :
  LAFORGE_PYTHON tools/forge_log_retention.py --once
  LAFORGE_PYTHON tools/forge_log_retention.py --daemon   (boucle INTERVAL_S)
  LAFORGE_PYTHON tools/forge_log_retention.py --once --dry-run
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _chemin_tmp_sandbox() -> str:
    """Le point unique `chemin_tmp_sandbox()`, importable QUEL QUE SOIT le lanceur.

    Mesure en production (2026-09-24, relance de 21:15) : le service est lance sur ce fichier,
    donc `sys.path[0]` = tools/ et la RACINE est absente -- `app.forge_sandbox_exec` comme
    `nokido_agent.app...` levent ModuleNotFoundError. La purge des preuves (1re etape) le rendait
    ILLISIBLE ; celle du tmp (plus loin) ne marchait que parce qu'une etape intermediaire avait
    ajoute la racine entre-temps. Meme famille que les 6 services morts au boot le matin meme.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from app.forge_sandbox_exec import chemin_tmp_sandbox
    except ImportError:  # depot lance avec app/ dans sys.path
        from nokido_agent.app.forge_sandbox_exec import chemin_tmp_sandbox  # type: ignore[no-redef]
    return chemin_tmp_sandbox()
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [log_retention] %(levelname)s %(message)s", stream=sys.stdout
)
log = logging.getLogger("log_retention")

TRACES_DB = ROOT / "RAG" / "execution_traces.db"
VAULT_DB = ROOT / "sandbox" / "redaction_vault.db"
HEARTBEAT = ROOT / "sandbox" / "log_retention.heartbeat"

import os

WARM_DAYS = float(os.environ.get("LOG_RETENTION_WARM_DAYS", "7"))  # drop embeddings après
COLD_DAYS = float(os.environ.get("LOG_RETENTION_COLD_DAYS", "30"))  # delete après
MAIL_DAYS = float(os.environ.get("MAIL_RETENTION_DAYS", "2"))  # courrier TRAITÉ = éphémère, archive courte
MORTE_DAYS = float(os.environ.get("VEILLE_URL_MORTE_DAYS", "180"))  # marque 404 re-essayée après
INTERVAL_S = 86400  # daemon : 1×/jour
CORE_MEMORY_DAYS = float(os.environ.get("CORE_MEMORY_RETENTION_DAYS", "180"))  # agent sans archive depuis
CORE_MEMORY_FACTS_MAX = int(os.environ.get("CORE_MEMORY_FACTS_MAX", "16000"))  # SIGNALE, jamais tronque


def _retention_traces(dry: bool) -> dict:
    """Tier-down execution_traces : drop embeddings tièdes, delete froids."""
    if not TRACES_DB.exists():
        return {"skipped": "no traces db"}
    now = time.time()
    warm_cut = now - WARM_DAYS * 86400
    cold_cut = now - COLD_DAYS * 86400
    con = sqlite3.connect(str(TRACES_DB))
    try:
        warm_n = con.execute(
            "SELECT COUNT(*) FROM traces WHERE ts < ? AND ts >= ? AND state_t_emb IS NOT NULL",
            (warm_cut, cold_cut),
        ).fetchone()[0]
        cold_n = con.execute("SELECT COUNT(*) FROM traces WHERE ts < ?", (cold_cut,)).fetchone()[0]
        # alignment_events (capteur P1 d'alignement, meme db) : retention FROIDE
        try:
            ae_n = con.execute(
                "SELECT COUNT(*) FROM alignment_events WHERE ts < ?", (cold_cut,)
            ).fetchone()[0]
        except sqlite3.OperationalError:
            ae_n = 0  # table pas encore creee
        if not dry:
            # TIÈDE : libère les embeddings (≈3 KB/row récupérés au VACUUM)
            con.execute(
                "UPDATE traces SET state_t_emb=NULL, state_t1_emb=NULL "
                "WHERE ts < ? AND ts >= ? AND state_t_emb IS NOT NULL",
                (warm_cut, cold_cut),
            )
            # FROID : suppression sèche
            con.execute("DELETE FROM traces WHERE ts < ?", (cold_cut,))
            if ae_n:
                con.execute("DELETE FROM alignment_events WHERE ts < ?", (cold_cut,))
            con.commit()
        return {"embeddings_dropped": warm_n, "rows_deleted": cold_n,
                "alignment_events_deleted": ae_n, "dry_run": dry}
    finally:
        con.close()


def _prune_vault(dry: bool) -> dict:
    """Prune la map de réversibilité (tag->valeur) > WARM_DAYS : au-delà, les
    traces deviennent irréversibles-au-repos (le tag reste, la valeur disparaît)."""
    if not VAULT_DB.exists():
        return {"skipped": "no vault"}
    now = time.time()
    cut = now - WARM_DAYS * 86400
    con = sqlite3.connect(str(VAULT_DB))
    try:
        n = con.execute("SELECT COUNT(*) FROM redaction_vault WHERE ts < ?", (cut,)).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM redaction_vault WHERE ts < ?", (cut,))
            con.commit()
        return {"vault_pruned": n, "dry_run": dry}
    except sqlite3.OperationalError:
        return {"skipped": "no redaction_vault table"}
    finally:
        con.close()


# Retention de la zone TEMP du sandbox. Mesure 2026-09-08 : 4112 fichiers,
# 0,55 Go accumules dans <depot>/sandbox/workspace/tmp, que PERSONNE ne purgeait
# — `cleanup_workdir` audite des dossiers parents (node_modules, venv), pas ce
# tmp. On etend le purgeur du corps plutot que d'ecrire un treizieme outil.
TMP_DAYS = int(os.environ.get("LAFORGE_TMP_RETENTION_DAYS", "7") or 7)


def _purge_workspace_tmp(dry: bool) -> dict:
    """Purge les fichiers temporaires du sandbox plus vieux que TMP_DAYS.

    Le chemin est DEMANDE au point unique (`chemin_tmp_sandbox`), jamais
    reconstruit : deux notions du chemin tmp, c'est une purge qui rate sa cible —
    le meme defaut que le poseur a deux sites, vu depuis l'autre bout.

    La borne DIT COMBIEN : on rend les vus, les retenus, les gardes parce que
    recents, et les ILLISIBLES comptes a part. Un fichier qu'on n'a pas pu lire
    n'est ni purge ni sain, et le taire surestimerait la couverture.
    """
    try:
        base = Path(_chemin_tmp_sandbox())
        if not base.is_dir():
            return {"tmp_zone": "absente", "tmp_chemin": str(base)}

        limite = time.time() - TMP_DAYS * 86400
        vus = retenus = recents = illisibles = 0
        octets = 0
        for chemin in base.rglob("*"):
            try:
                if not chemin.is_file():
                    continue
                vus += 1
                stat = chemin.stat()
                if stat.st_mtime >= limite:
                    recents += 1
                    continue
                retenus += 1
                octets += stat.st_size
                if not dry:
                    chemin.unlink()
            except OSError:
                illisibles += 1

        return {
            "tmp_chemin": str(base),
            "tmp_ttl_jours": TMP_DAYS,
            "tmp_fichiers_vus": vus,
            "tmp_fichiers_purges": 0 if dry else retenus,
            "tmp_fichiers_eligibles": retenus,
            "tmp_gardes_recents": recents,
            "tmp_illisibles": illisibles,
            "tmp_octets_liberes": 0 if dry else octets,
            "tmp_octets_eligibles": octets,
            "tmp_mode": "dry-run" if dry else "applique",
        }
    except Exception as e:
        return {"tmp_error": str(e)[:120]}


def _purge_audit(dry: bool) -> dict:
    """Réutilise forge_audit_log.purge_older_than (audit.db http-level)."""
    if dry:
        return {"audit_purge": "dry-run skip"}
    try:
        from nokido_agent.app.forge_audit_log import purge_older_than

        n = purge_older_than(int(COLD_DAYS))
        return {"audit_rows_purged": n}
    except Exception as e:
        return {"audit_error": str(e)[:120]}


def _purge_network_log(dry: bool) -> dict:
    """network_log (RAG/embeddings.db) : INSERT-only par requête, AUCUNE purge — les DB
    sœurs SONT purgées (traces/audit/vault), PAS elle -> croissance illimitée (307k+ rows,
    audit workflow 2026-06-11). DELETE > COLD_DAYS. ⚠️ ts = string ISO (datetime.isoformat),
    comparaison LEXICO valide ISO-8601 (PAS epoch). Pas de VACUUM full sur les 8GB (lock
    exclusif) -> la glymphatic GC réclame les pages."""
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    from datetime import datetime, timedelta

    cut = (datetime.now() - timedelta(days=COLD_DAYS)).isoformat()
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM network_log WHERE ts < ?", (cut,)).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM network_log WHERE ts < ?", (cut,))
            con.commit()
        return {"network_log_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_query_log(dry: bool) -> dict:
    """query_log (RAG/embeddings.db) : log PAR requête RAG, INSERT-only, sans purge — même
    classe que network_log (flaggé par forge_firehose_guard 2026-06-11). ts = ISO string."""
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    from datetime import datetime, timedelta

    cut = (datetime.now() - timedelta(days=COLD_DAYS)).isoformat()
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM query_log WHERE timestamp < ?", (cut,)).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM query_log WHERE timestamp < ?", (cut,))
            con.commit()
        return {"query_log_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_canary_alerts(dry: bool) -> dict:
    """canary_alerts (RAG/embeddings.db) : alertes de fuite canari (forge_prompt_guard),
    INSERT-only, table séparée non chaînée -> croissance illimitée. DELETE > COLD_DAYS.
    ts = ISO string. Audit 2026-06-15 (gate firehose)."""
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    from datetime import datetime, timedelta

    cut = (datetime.now() - timedelta(days=COLD_DAYS)).isoformat()
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM canary_alerts WHERE ts < ?", (cut,)).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM canary_alerts WHERE ts < ?", (cut,))
            con.commit()
        return {"canary_alerts_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_membrane_aliases(dry: bool) -> dict:
    """alias_map (recon_silo/recon_data/membrane.db) : map de réversibilité par mission
    (forge_sovereign_membrane) -> croissance illimitée (gate firehose). DELETE les alias
    > COLD_DAYS (mission expirée = irréversible au-delà, conforme au design). created_ts =
    CURRENT_TIMESTAMP SQLite -> comparaison via datetime('now','-Nd'). Audit 2026-06-15."""
    DB = ROOT / "recon_silo" / "recon_data" / "membrane.db"
    if not DB.exists():
        return {"skipped": "no membrane db"}
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        cutexpr = "datetime('now','-%d days')" % int(COLD_DAYS)
        n = con.execute(f"SELECT COUNT(*) FROM alias_map WHERE created_ts < {cutexpr}").fetchone()[0]
        if not dry and n:
            con.execute(f"DELETE FROM alias_map WHERE created_ts < {cutexpr}")
            con.commit()
        return {"membrane_aliases_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_tasks(dry: bool) -> dict:
    """tasks (sandbox/tasks.db) : tâches TERMINÉES > COLD_DAYS (garde pending/running).
    created_at = ISO string."""
    DB = ROOT / "sandbox" / "tasks.db"
    if not DB.exists():
        return {"skipped": "no tasks db"}
    from datetime import datetime, timedelta

    cut = (datetime.now() - timedelta(days=COLD_DAYS)).isoformat()
    term = ("done", "error", "completed", "failed", "cancelled")
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        ph = ",".join("?" * len(term))
        n = con.execute(
            f"SELECT COUNT(*) FROM tasks WHERE created_at < ? AND status IN ({ph})", (cut, *term)
        ).fetchone()[0]
        if not dry and n:
            con.execute(f"DELETE FROM tasks WHERE created_at < ? AND status IN ({ph})", (cut, *term))
            con.commit()
        return {"tasks_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_watch_chains(dry: bool) -> dict:
    """veille (RAG/embeddings.db) : watch_jobs + agent_chain_nodes + agent_chain_context.

    INSERT-only, aucune purge cablee -> croissance illimitee (flagge par le gate firehose
    a chaque commit, anti-regression incident 47GB). Chaque veille ecrit 1 job + 1 contexte
    + 7 nodes, et le `result_json` d'un node porte les resultats de recherche ENTIERS.

    Purge par CHAINE, jamais node par node : le ChainExecutor relit les nodes de sa chaine
    pour avancer, en amputer une encore vivante la casserait. Une chaine part si AUCUN de
    ses nodes n'est pending/running ET que sa creation depasse COLD_DAYS.

    PIEGE DATES : deux formats coexistent -- '2026-07-16T12:00:00+00:00' (create_job, ISO-T)
    et '2026-07-16 12:00:00' (DEFAULT datetime('now')). En comparaison binaire ' ' < 'T',
    donc un cut au format ISO-T matcherait TOUTES les lignes au format espace = purge totale.
    `datetime(col)` normalise les deux (meme parade que _purge_network_log).
    """
    # LISTE BLANCHE (2026-09-23, decision owner : « la purge ne doit pas tuer les
    # veilles ratees »). L'ancien critere purgeait tout ce qui n'etait ni pending ni
    # running : `failed`, `stalled`, `degraded`, `completed_partial`, `completed_empty`
    # partaient avec les reussies, et une veille ratee disparaissait avant d'avoir ete
    # rattrapee (mesure : 24 watch_jobs pour MAX(rowid)=281). N'est purgeable QUE ce qui
    # est PROUVE reussi : job dans REUSSIES ET tous ses nodes `completed`.
    reussies = "('completed','completed_dedup')"
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    cutexpr = "datetime('now','-%d days')" % int(COLD_DAYS)
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        chains = [
            r[0]
            for r in con.execute(
                "SELECT n.chain_id FROM agent_chain_nodes n "
                f"JOIN watch_jobs w ON w.id = n.chain_id AND w.status IN {reussies} "
                "GROUP BY n.chain_id "
                "HAVING SUM(CASE WHEN n.status = 'completed' THEN 0 ELSE 1 END) = 0 "
                f"AND MAX(datetime(n.created_at)) < {cutexpr}"
            ).fetchall()
        ]
        # Contextes orphelins : plus aucun node ne les reference (chaine deja purgee, ou
        # create_job interrompu entre l'insert du contexte et celui des nodes).
        orphans = [
            r[0]
            for r in con.execute(
                "SELECT chain_id FROM agent_chain_context WHERE chain_id NOT IN "
                "(SELECT DISTINCT chain_id FROM agent_chain_nodes) "
                f"AND datetime(updated_at) < {cutexpr}"
            ).fetchall()
        ]
        # Un job ne part QUE si sa chaine part aussi (meme preuve de reussite).
        n_jobs = len(chains)
        res = {
            "chains_purged": len(chains),
            "ctx_orphans_purged": len(orphans),
            "watch_jobs_purged": n_jobs,
            "dry_run": dry,
        }
        if dry:
            return res
        for cid in chains:
            con.execute("DELETE FROM agent_chain_nodes WHERE chain_id = ?", (cid,))
            con.execute("DELETE FROM agent_chain_context WHERE chain_id = ?", (cid,))
            con.execute("DELETE FROM watch_jobs WHERE id = ?", (cid,))
        for cid in orphans:
            con.execute("DELETE FROM agent_chain_context WHERE chain_id = ?", (cid,))
        con.commit()
        return res
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_endocrine_signals(dry: bool) -> dict:
    """Clairance du sang (RAG/embeddings.db : endocrine_signals).

    Flaggee par le gate firehose a CHAQUE commit ("CREATE TABLE endocrine_signals
    non referencee dans forge_log_retention.py -> croissance illimitee"). La cause
    n'etait pas une purge manquante : forge_endocrine.purge_expired() EXISTE depuis
    l'origine -- elle n'a simplement JAMAIS ete appelee. Mesure le 2026-07-16 :
    9 des 13 lignes etaient eteintes depuis 2 a 50 jours (`adrenaline` level=0.000,
    age 50j ; residus `src=pytest` vieux de 9 jours).

    La politique de clairance appartient a l'ORGANE endocrine : on APPELLE
    purge_expired(dry), on ne redirive pas son critere ici. La retention est
    l'eboueur RESIDENT qui la declenche -- la fonction de clairance existait, il
    manquait la microglie qui l'invoque. Corollaire : purge_expired filtre sur
    released_at (dernier pic), donc une hormone CHRONIQUE, qui est renouvelee, est
    protegee. On ne ramasse jamais un signal vivant.
    """
    try:
        import sys as _sys

        app_dir = str(ROOT / "app")
        if app_dir not in _sys.path:
            _sys.path.insert(0, app_dir)
        from nokido_agent.app import forge_endocrine as fe

        # On DEMANDE a l'organe ou vit son sang -- on ne redirive pas le chemin ici.
        # Coder `ROOT/"RAG"/"embeddings.db"` (ce que faisait la 1re version de cette
        # fonction) rate le SSoT forge_db_path.db_path() et vise le SYMLINK C:->V:.
        if not fe.DB.exists():
            return {"skipped": "no embeddings db"}
        return {"hormones_purged": int(fe.purge_expired(dry=dry)), "dry_run": dry}
    except Exception as e:
        return {"skipped": str(e)[:80]}


def _purge_mail(dry: bool) -> dict:
    """mail (RAG/postal.db, forge_postal) : courriers TERMINÉS (acked/dead) > COLD_DAYS.
    ts_queued = epoch float (time.time), PAS ISO. Garde les queued/delivered en cours."""
    DB = ROOT / "RAG" / "postal.db"
    if not DB.exists():
        return {"skipped": "no postal db"}
    cut = time.time() - MAIL_DAYS * 86400  # mail traité = éphémère -> archive COURTE (pas COLD_DAYS=30)
    # SEULEMENT LE TRAITE (decision owner 2026-10-01) : 'acked'. 'dead' (jamais livre) etait
    # supprime SANS export ; il ne l'est plus. La liste vit dans le postal.
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_postal import ETATS_COURRIER_TRAITES
    _traites = sorted(ETATS_COURRIER_TRAITES)
    _ph = ",".join("?" * len(_traites))
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM mail WHERE ts_queued < ? AND status IN (%s)" % _ph,
                        (cut, *_traites)).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM mail WHERE ts_queued < ? AND status IN (%s)" % _ph, (cut, *_traites))
            con.commit()
        return {"mail_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_inspector_log(dry: bool) -> dict:
    """inspector_log (RAG/embeddings.db) : une ligne par cycle d'inspecteur (30 s).

    MESURE 2026-07-26 : la table contenait EXACTEMENT 2000 lignes. Le plafond inline
    de `forge_inspector` (DELETE ... id NOT IN (SELECT ... LIMIT 2000), exécuté après
    chaque INSERT) fonctionne donc — l'avertissement « croissance illimitée » du gate
    firehose était un FAUX POSITIF sur ce point, et il faut le dire.

    Ce qui manquait réellement : ce plafond vit chez l'ÉCRIVAIN. Il ne s'applique que
    tant que l'inspecteur tourne, il disparaît si ce chemin d'écriture change, et un
    auditeur qui lit CE module concluait que la table n'était pas gérée. On l'y
    enregistre donc : même politique (garder les N dernières), défense en profondeur,
    et visibilité centrale de la rétention.
    """
    keep = int(os.environ.get("LOG_RETENTION_INSPECTOR_KEEP", "2000"))
    # `inspector_log` a DEUX ecrivains : `forge_inspector` insere, et CETTE
    # fonction SUPPRIME. L'ecart entre COUNT=2000 et MAX(rowid)=176072 vient
    # entierement d'ici — la rotation prend le verrou d'ecriture aussi souvent
    # que l'insertion. Migrer l'inserteur sans le rotateur laisserait la MOITIE
    # des prises sur la base de 26 Go, tout en se relisant comme une migration
    # faite. Meme patron que `tasks_path` et `m2m_path` plus bas dans ce fichier.
    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_db_path import journal_path  # suit sandbox/journaux.switch
        DB = Path(journal_path("inspector_log"))
    except (ImportError, ValueError):  # muet-ok: repli EXPLICITE sur le chemin historique
        DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        total = con.execute("SELECT COUNT(*) FROM inspector_log").fetchone()[0]
        excess = max(0, total - keep)
        if not dry and excess:
            con.execute(
                "DELETE FROM inspector_log WHERE id NOT IN "
                "(SELECT id FROM inspector_log ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
            con.commit()
        return {"inspector_log_rows": total, "keep": keep,
                "inspector_log_purged": excess, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _vacuum(dry: bool) -> dict:
    """VACUUM execution_traces pour réclamer l'espace des embeddings droppés."""
    if dry or not TRACES_DB.exists():
        return {"vacuum": "skip"}
    before = TRACES_DB.stat().st_size
    con = sqlite3.connect(str(TRACES_DB))
    try:
        con.execute("VACUUM")
        con.commit()
    finally:
        con.close()
    after = TRACES_DB.stat().st_size
    return {"vacuum_mb_before": round(before / 1e6, 1), "vacuum_mb_after": round(after / 1e6, 1)}


def _purge_runtime_lanes(dry: bool) -> dict:
    """Runtime WAL (laforge_lanes.db) : baux d'admission + mutex OAuth EXPIRÉS, et frames de
    progression vieux. Ces tables s'auto-nettoient (TTL/overwrite) mais on borne (anti incident 47GB)."""
    DB = Path(os.environ.get("LAFORGE_RUNTIME_DB", os.environ.get("LAFORGE_LANES_DB", "C:/tmp/laforge_lanes.db")))
    if not DB.exists():
        return {"skipped": "no runtime db"}
    now = time.time()
    out: dict = {"dry_run": dry}
    con = sqlite3.connect(str(DB), timeout=20)
    try:
        for tbl, where, args in (
            ("lane_leases", "expiry <= ?", (now,)),
            ("oauth_mutex", "expiry <= ?", (now,)),
            ("job_progress", "updated < ?", (now - COLD_DAYS * 86400,)),
        ):
            try:
                n = con.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {where}", args).fetchone()[0]
                if not dry and n:
                    con.execute(f"DELETE FROM {tbl} WHERE {where}", args)
                out[tbl] = n
            except sqlite3.OperationalError as e:
                out[tbl] = f"skip: {str(e)[:40]}"
        if not dry:
            con.commit()
        return out
    finally:
        con.close()


def _purge_bridge_logs(dry: bool) -> dict:
    """bridge_logs (data/network_log.db, mcp_stdio_bridge) : INSERT-only par appel MCP ->
    croissance illimitée (flaggé firehose 2026-06-16). DELETE > COLD_DAYS. ts = datetime('now')
    SQLite ('YYYY-MM-DD HH:MM:SS') -> coupe SQL-side. bridge_status = 1 ligne heartbeat, non purgée."""
    DB = ROOT / "data" / "network_log.db"
    if not DB.exists():
        return {"skipped": "no network_log.db"}
    cutexpr = "datetime('now','-%d days')" % int(COLD_DAYS)
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute(f"SELECT COUNT(*) FROM bridge_logs WHERE ts < {cutexpr}").fetchone()[0]
        if not dry and n:
            con.execute(f"DELETE FROM bridge_logs WHERE ts < {cutexpr}")
            con.commit()
        return {"bridge_logs_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_edges(dry: bool) -> dict:
    """edges (forge_edge_fleet) : noeuds STALE (last_seen > COLD_DAYS = morts). Table
    d'ENREGISTREMENT bornee par # de noeuds vivants (PAS un firehose de logs) -> referencee
    ici pour la garde anti-incident-47GB + nettoie les noeuds disparus."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_edge_fleet import DB as _EDB
    except Exception as e:  # noqa: BLE001
        return {"skipped": f"no edge_fleet: {str(e)[:60]}"}
    if not Path(str(_EDB)).exists():
        return {"skipped": "no edges db"}
    from datetime import datetime, timedelta
    cut = (datetime.now() - timedelta(days=COLD_DAYS)).isoformat()
    con = sqlite3.connect(str(_EDB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM edges WHERE last_seen < ?", (cut,)).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM edges WHERE last_seen < ?", (cut,))
            con.commit()
        return {"edges_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _archive_event_sourced(dry: bool) -> dict:
    """Tables EVENT-SOURCED (event_log = journal d'intentions/events ; swarm_blackboard) :
    on N'EFFACE PAS (audit-trail immuable) -> COLD-TIER les lignes > 365j vers
    event_log_archive (preserve l'historique ; replay = union hot+archive). Reference ici
    pour la garde firehose : event-sourcing = ARCHIVE, jamais purge."""
    from datetime import datetime, timedelta
    out = {}
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_timecode import get_timecode_engine
        eng = get_timecode_engine()
        con0 = eng._conn()
        db = con0.execute("PRAGMA database_list").fetchone()[2]
        con0.close()
        cut = (datetime.now() - timedelta(days=365)).isoformat()
        con = sqlite3.connect(str(db), timeout=30)
        con.execute("CREATE TABLE IF NOT EXISTS event_log_archive AS SELECT * FROM event_log WHERE 0")
        n = con.execute("SELECT COUNT(*) FROM event_log WHERE timecode < ?", (cut,)).fetchone()[0]
        if not dry and n:
            con.execute("INSERT INTO event_log_archive SELECT * FROM event_log WHERE timecode < ?", (cut,))
            con.execute("DELETE FROM event_log WHERE timecode < ?", (cut,))
            con.commit()
        con.close()
        out["event_log"] = {"archived": n, "dry_run": dry}
    except Exception as e:  # noqa: BLE001
        out["event_log"] = {"skipped": str(e)[:80]}
    # swarm_blackboard : borne PAR ZONE via _prune (apply_fact, mono-writer) ; event-sourced
    # -> pas de purge globale (reference ici pour la garde).
    out["swarm_blackboard"] = {"note": "borne par _prune per-zone ; archive-not-purge"}
    return out


def _purge_agent_tasks(dry: bool) -> dict:
    """agent_tasks (bus de taches multi-agents, forge_task_bus) : TERMINEES > COLD_DAYS.

    Signale par le garde anti-regression de l'incident 47 Go au moment ou la
    revue a gagne son identite (2026-09-18) : la table existait depuis longtemps
    et n'avait AUCUNE politique de retention. Meme famille que `task_queue`,
    meme remede.

    Perimetre STRICT : `done`, `failed` et `cancelled` plus vieux que COLD_DAYS.
    Une tache `pending`, `assigned`, `running` ou `review` n'est JAMAIS touchee.
    Et comme pour la file, une tache tres vieille restee `running` est un BAIL
    ORPHELIN a instruire -- on la COMPTE, on ne la supprime pas.

    Export jsonl.gz rejouable AVANT tout DELETE : on archive, on ne perd pas.
    """
    sys.path.insert(0, str(ROOT))
    import gzip

    # ON DEMANDE LE CHEMIN A L'ORGANE, on ne le devine pas. Un premier jet
    # supposait `DB_PATH` : le bus le nomme `_DB_PATH`, et la purge se sautait
    # elle-meme en silence -- un `skipped` se lit « rien a faire ».
    #
    # ⚠️ CE QUE CETTE LECTURE REVELE : `agent_tasks` vit dans
    # `RAG/embeddings.db`, la base de 25 Go, ouverte par un `sqlite3.connect`
    # nu. C'est le MEME defaut que `task_queue`, corrige le meme jour par le
    # patron d'interrupteur -- le bus de taches multi-agents dispute lui aussi
    # le verrou d'ecriture du RAG. La scission reste a faire ; elle est
    # mecanique maintenant que le patron et l'outil existent.
    try:
        from nokido_agent.app.forge_task_bus import _DB_PATH as _BUS
    except Exception:  # noqa: BLE001 — le bus nomme sa base ; sans lui on ne devine pas
        return {"skipped": "forge_task_bus ne publie pas sa base"}
    DB = Path(str(_BUS))
    if not DB.exists():
        return {"skipped": "no agent_tasks db"}
    cut = f"-{COLD_DAYS} days"
    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_tasks'").fetchone():
            return {"skipped": "no agent_tasks table"}
        cols = [r[1] for r in con.execute("PRAGMA table_info(agent_tasks)")]
        sel = ",".join(cols)
        rows = con.execute(
            f"SELECT {sel} FROM agent_tasks WHERE status IN ('done','failed','cancelled') "
            "AND COALESCE(updated_at, created_at) < datetime('now', ?)", (cut,)).fetchall()
        baux = con.execute(
            "SELECT COUNT(*) FROM agent_tasks WHERE status IN ('running','assigned','review') "
            "AND COALESCE(updated_at, created_at) < datetime('now', ?)", (cut,)).fetchone()[0]
        if dry:
            return {"deletable": len(rows), "baux_orphelins_non_touches": baux, "dry_run": True}
        arch = ROOT / "logs" / "archive"
        try:
            arch.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            arch = ROOT / "sandbox" / "archive"
            arch.mkdir(parents=True, exist_ok=True)
        out = arch / f"agent_tasks_{time.strftime('%Y%m')}.jsonl.gz"
        with gzip.open(out, "at", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(dict(zip(cols, r)), ensure_ascii=False, default=str) + "\n")
        ids = [r[0] for r in rows]
        for i in range(0, len(ids), 5000):
            b = ids[i:i + 5000]
            con.execute("DELETE FROM agent_tasks WHERE id IN (%s)" % ",".join("?" * len(b)), b)
            con.commit()
        return {"exported": len(rows), "deleted": len(ids), "archive": str(out),
                "baux_orphelins_non_touches": baux, "dry_run": False}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_task_queue(dry: bool) -> dict:
    """task_queue (base de la file, forge_db_path.tasks_path) : taches TERMINEES > COLD_DAYS.

    Pose le 2026-09-18, le jour ou la table a quitte la base du RAG. Le garde
    anti-regression de l'incident 47 Go l'a exige a l'instant meme du commit :
    une table neuve sans politique de retention est une croissance illimitee, et
    ce n'est pas parce qu'elle est petite aujourd'hui qu'elle le restera.

    Perimetre STRICT : uniquement DONE et ERROR, plus vieux que COLD_DAYS. Une
    tache PENDING n'est jamais touchee -- c'est du travail qui attend. Une tache
    RUNNING non plus, meme tres vieille : une reclamation perimee est un BAIL
    ORPHELIN a instruire, pas un dechet a supprimer (mesure du 2026-09-18 : la
    file portait un RUNNING du 27 avril, cinq mois de bail mort).

    Comme pour `agent_messages` : EXPORT jsonl.gz rejouable AVANT tout DELETE.
    On archive, on ne perd pas.
    """
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_db_path import tasks_path  # suit l'interrupteur sandbox/task_queue.switch

    DB = Path(tasks_path())
    if not DB.exists():
        return {"skipped": "no task queue db"}
    import gzip

    cut = f"-{COLD_DAYS} days"
    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_queue'").fetchone():
            return {"skipped": "no task_queue table"}
        cols = ("id", "ts", "title", "role", "priority", "status", "context",
                "result", "started_at", "done_at")
        rows = con.execute(
            "SELECT " + ",".join(cols) + " FROM task_queue "
            "WHERE status IN ('DONE','ERROR') AND COALESCE(done_at, ts) < datetime('now', ?)",
            (cut,),
        ).fetchall()
        # Ce que la purge NE touche PAS, et qui doit rester visible dans le rapport :
        # un RUNNING tres vieux est un bail orphelin, pas un dechet.
        baux = con.execute(
            "SELECT COUNT(*) FROM task_queue WHERE status='RUNNING' "
            "AND COALESCE(started_at, ts) < datetime('now', ?)", (cut,)
        ).fetchone()[0]
        if dry:
            return {"deletable": len(rows), "baux_orphelins_non_touches": baux, "dry_run": True}
        arch = ROOT / "logs" / "archive"
        try:
            arch.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            arch = ROOT / "sandbox" / "archive"
            arch.mkdir(parents=True, exist_ok=True)
        out = arch / f"task_queue_{time.strftime('%Y%m')}.jsonl.gz"
        with gzip.open(out, "at", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(dict(zip(cols, r)), ensure_ascii=False, default=str) + "\n")
        ids = [r[0] for r in rows]
        for i in range(0, len(ids), 5000):
            b = ids[i:i + 5000]
            con.execute("DELETE FROM task_queue WHERE id IN (%s)" % ",".join("?" * len(b)), b)
            con.commit()
        return {"exported": len(rows), "deleted": len(ids), "archive": str(out),
                "baux_orphelins_non_touches": baux, "dry_run": False}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_agent_messages(dry: bool) -> dict:
    """agent_messages (base M2M, forge_db_path.m2m_path) : TELEMETRIE + courrier TRAITE > COLD_DAYS.
    Directive user 2026-07-05 : TRAITE avant suppression = EXPORT jsonl.gz
    rejouable (logs/archive/agent_messages_YYYYMM.jsonl.gz) AVANT tout DELETE.
    Perimetre delete : cli_capture (boite noire telemetrique jamais lue) +
    status read/archived, plus vieux que COLD_DAYS. Le courrier unread d'agents
    REELS n'est JAMAIS supprime ; l'heritage agt_gemini (agent mort) est
    exporte puis marque archived (contenu conserve en DB, purgeable au cycle
    suivant). Deletes par lots (contention drain backfill sur la meme DB)."""
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : la table suit l'interrupteur sandbox/m2m.switch
    DB = Path(m2m_path())
    if not DB.exists():
        return {"skipped": "no m2m db"}
    import gzip
    cut = f"-{COLD_DAYS} days"
    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        cols = ("id", "from_agent", "to_agent", "correlation_id", "method",
                "payload", "status", "created_at")
        base = "SELECT " + ",".join(cols) + " FROM agent_messages WHERE created_at < datetime('now', ?) AND "
        # SEULEMENT LE TRAITE (decision owner 2026-10-01) : la liste vit dans le postal, qui
        # sait ce qui est traite. Avant : 'read' (lu, pas traite) et 'archived' (courrier NON lu
        # d'un agent mort) etaient supprimes. cli_capture = telemetrie, jamais du courrier.
        # Toujours EXPORTE (jsonl.gz rejouable) AVANT le DELETE, comme avant.
        from nokido_agent.app.forge_postal import ETATS_M2M_TRAITES
        _traites = sorted(ETATS_M2M_TRAITES)
        rows = con.execute(base + "(to_agent='cli_capture' OR status IN (%s))"
                           % ",".join("?" * len(_traites)), (cut, *_traites)).fetchall()
        gem = con.execute(base + "to_agent='agt_gemini' AND status='unread'", (cut,)).fetchall()
        if dry:
            return {"deletable": len(rows), "gemini_to_archive": len(gem), "dry_run": True}
        # logs/ = zone owner (mkdir refuse au user sandbox) -> fallback sandbox/archive
        # quand la passe tourne en run_job sandboxe ; le service supervise (SYSTEM)
        # garde logs/archive.
        arch = ROOT / "logs" / "archive"
        try:
            arch.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            arch = ROOT / "sandbox" / "archive"
            arch.mkdir(parents=True, exist_ok=True)
        out = arch / f"agent_messages_{time.strftime('%Y%m')}.jsonl.gz"
        with gzip.open(out, "at", encoding="utf-8") as fh:
            for r in list(rows) + list(gem):
                fh.write(json.dumps(dict(zip(cols, r)), ensure_ascii=False, default=str) + "\n")
        ids = [r[0] for r in rows]
        for i in range(0, len(ids), 5000):
            b = ids[i:i + 5000]
            con.execute("DELETE FROM agent_messages WHERE id IN (%s)" % ",".join("?" * len(b)), b)
            con.commit()
        gids = [r[0] for r in gem]
        for i in range(0, len(gids), 5000):
            b = gids[i:i + 5000]
            con.execute("UPDATE agent_messages SET status='archived' WHERE id IN (%s)" % ",".join("?" * len(b)), b)
            con.commit()
        return {"exported": len(rows) + len(gem), "deleted": len(ids),
                "gemini_archived": len(gids), "archive": str(out), "dry_run": False}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_conv_archives(dry: bool) -> dict:
    """conv_archives (memoire Letta agents, RAG/embeddings.db) : borne la croissance
    en gardant les CONV_ARCHIVE_KEEP tours les PLUS RECENTS par agent — memoire recente
    preservee (borne par COUNT, pas par age = pas d'amnesie). Nettoie l'index FTS et le
    mirror rag_chunks associes. Anti-incident 47GB (croissance illimitee interdite)."""
    mem_db = ROOT / "RAG" / "embeddings.db"
    if not mem_db.exists():
        return {"skipped": "no embeddings.db"}
    keep = int(os.environ.get("CONV_ARCHIVE_KEEP", "5000"))
    con = sqlite3.connect(str(mem_db), timeout=30)
    try:
        if not con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conv_archives'"
        ).fetchone():
            return {"skipped": "no conv_archives"}
        to_del = []
        for (aid,) in con.execute("SELECT DISTINCT agent_id FROM conv_archives").fetchall():
            to_del.extend(
                con.execute(
                    "SELECT id, rag_chunk_id FROM conv_archives WHERE agent_id=? "
                    "ORDER BY archived_at DESC LIMIT -1 OFFSET ?",
                    (aid, keep),
                ).fetchall()
            )
        n = len(to_del)
        if not dry and n:
            arch = [(r[0],) for r in to_del]
            chunks = [(r[1],) for r in to_del if r[1]]
            con.executemany("DELETE FROM conv_archives WHERE id=?", arch)
            try:
                con.executemany("DELETE FROM conv_archives_fts WHERE arch_id=?", arch)
            except sqlite3.Error:
                pass
            con.executemany("DELETE FROM rag_chunks WHERE id=?", chunks)
            con.commit()
        return {"conv_archives_pruned": n, "keep_per_agent": keep, "dry_run": dry}
    except Exception as e:  # noqa: BLE001
        return {"conv_archives_error": str(e)[:120]}
    finally:
        con.close()


def _purge_veille_digest(dry: bool) -> dict:
    """veille_digest_suggestions (RAG/embeddings.db, forge_veille_digest) : suggestions
    de l'organe digest->suggest, INSERT-only dedup par hash -> borne par COUNT (keep les
    VEILLE_DIGEST_KEEP plus recentes ; une suggestion vieille non promue a expire).
    Reference ici pour la garde firehose (flag au commit 755a80fd)."""
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    keep = int(os.environ.get("VEILLE_DIGEST_KEEP", "2000"))
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM veille_digest_suggestions").fetchone()[0]
        excess = max(0, n - keep)
        if not dry and excess:
            con.execute(
                "DELETE FROM veille_digest_suggestions WHERE id IN ("
                "SELECT id FROM veille_digest_suggestions "
                "ORDER BY created_at ASC LIMIT ?)",
                (excess,),
            )
            con.commit()
        return {"digest_suggestions_pruned": excess, "keep": keep, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_safety_organs(dry: bool) -> dict:
    """red_team_results + metric_integrity_findings (RAG/embeddings.db, organes safety
    2026-07-22) : bornes par COUNT (garde les plus recents). Reference ici pour la garde
    firehose (flag au commit dc28dd21). metric_integrity_findings = upsert par cle donc
    petit ; red_team_results = 1 ligne/run, borne a VEILLE_DIGEST_KEEP-like."""
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    keep = int(os.environ.get("SAFETY_ORGAN_KEEP", "2000"))
    # PLAFONDS DEDIES (2026-08-23). `promcp_tool_metrics` n'est PAS un organe de
    # surete : il ecrit UNE LIGNE PAR APPEL D'OUTIL (~1 150/jour mesures), quand les
    # autres tables de ce lot ecrivent une ligne par RUN (`red_team_results`) ou font
    # de l'upsert par cle (`metric_integrity_findings`). Range dans leur seau de 2000,
    # il ne conservait que 43 HEURES -- et c'est exactement ce qui a fait echouer la
    # mesure du signal evenementiel du jour, faute d'incidents en nombre suffisant.
    # 50 000 lignes = environ six semaines pour ~5 Mo. Le defaut commun reste 2000 :
    # relever SAFETY_ORGAN_KEEP aurait gonfle cinq tables sans raison.
    keep_par_table = {
        "promcp_tool_metrics": int(os.environ.get("PROMCP_METRICS_KEEP", "50000")),
    }
    con = sqlite3.connect(str(DB), timeout=30)
    out = {"dry_run": dry}
    try:
        for tbl, order_col in (("red_team_results", "created_at"),
                               ("metric_integrity_findings", "created_at"),
                               ("delivery_integrity_findings", "created_at"),
                               ("promcp_tool_metrics", "ts"),
                               ("oversight_audits", "created_at"),
                               ("corrigibility_state", "ts")):
            try:
                n = con.execute("SELECT COUNT(*) FROM %s" % tbl).fetchone()[0]
                excess = max(0, n - keep_par_table.get(tbl, keep))
                if not dry and excess:
                    con.execute(
                        "DELETE FROM %s WHERE id IN (SELECT id FROM %s "
                        "ORDER BY %s ASC LIMIT ?)" % (tbl, tbl, order_col), (excess,))
                out[tbl] = excess
            except sqlite3.OperationalError as e:
                out[tbl] = "skip: %s" % str(e)[:40]
        if not dry:
            con.commit()
        return out
    finally:
        con.close()


def _purge_goap_plans(dry: bool) -> dict:
    """goap_plans (RAG/embeddings.db, forge_goap.persist_plan) : 1 ligne/plan GOAP,
    INSERT-only par plan_id -> croissance illimitée (flag firehose au commit 86b9a414).
    created_at = epoch REAL (time.time). DELETE > COLD_DAYS."""
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    cut = time.time() - COLD_DAYS * 86400
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM goap_plans WHERE created_at < ?", (cut,)).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM goap_plans WHERE created_at < ?", (cut,))
            con.commit()
        return {"goap_plans_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_active_inference(dry: bool) -> dict:
    """Clairance du moteur Active Inference (RAG/embeddings.db).

    Flaggee par le gate firehose depuis que le 2026-07-24 a rendu la table
    LOAD-BEARING : FlowRegulator.get_dynamic_threshold() lit desormais
    recent_surprise() a chaque tick homeostatique.

    Les deux tables ne se purgent PAS de la meme facon, et confondre les deux
    donnerait une amnesie :

    - `active_inference_surprises` = journal BRUT des observations. Purgeable :
      l'apprentissage n'y vit pas, il a deja ete agrege dans les priors par la
      mise a jour Welford de observe(). On garde une fenetre longue + un plancher
      en nombre, parce que le debit mesure est faible (~0.6 obs/jour) et qu'une
      purge purement calendaire viderait le signal que la regulation consomme.

    - `active_inference_priors` = le modele generatif LUI-MEME. Le purger par
      age serait detruire la memoire de l'organe. On ne ramasse que le bruit
      jamais reconfirme (une methode vue une seule fois, il y a des mois) ; tout
      prior substantiel est sanctuarise, quel que soit son age.
    """
    try:
        import sys as _sys

        app_dir = str(ROOT / "app")
        if app_dir not in _sys.path:
            _sys.path.insert(0, app_dir)
        from nokido_agent.app import forge_active_inference as ai

        # On DEMANDE a l'organe ou vit sa base (cf. _purge_endocrine_signals).
        db = Path(str(ai.DEFAULT_DB))
        if not db.exists():
            return {"skipped": "no embeddings db"}

        keep_last = 500
        max_age_s = 90 * 86400
        prior_noise_age_s = 180 * 86400
        now = time.time()

        conn = sqlite3.connect(str(db))
        try:
            floor_row = conn.execute(
                "SELECT ts FROM active_inference_surprises ORDER BY ts DESC LIMIT 1 OFFSET ?",
                (keep_last - 1,),
            ).fetchone()
            # Plancher anti-amnesie : on ne descend jamais sous les N plus recentes.
            cutoff = now - max_age_s
            if floor_row and floor_row[0] is not None:
                cutoff = min(cutoff, float(floor_row[0]))

            n_surp = conn.execute(
                "SELECT COUNT(*) FROM active_inference_surprises WHERE ts < ?", (cutoff,)
            ).fetchone()[0]
            n_priors = conn.execute(
                "SELECT COUNT(*) FROM active_inference_priors "
                "WHERE n_observations <= 1 AND COALESCE(last_updated, 0) < ?",
                (now - prior_noise_age_s,),
            ).fetchone()[0]

            if not dry and (n_surp or n_priors):
                conn.execute("DELETE FROM active_inference_surprises WHERE ts < ?", (cutoff,))
                conn.execute(
                    "DELETE FROM active_inference_priors "
                    "WHERE n_observations <= 1 AND COALESCE(last_updated, 0) < ?",
                    (now - prior_noise_age_s,),
                )
                conn.commit()
        finally:
            conn.close()

        return {
            "surprises_purged": int(n_surp),
            "priors_noise_purged": int(n_priors),
            "kept_last": keep_last,
            "dry_run": dry,
        }
    except Exception as e:
        return {"skipped": str(e)[:80]}


def _purge_qdrant_sync_pending(dry: bool) -> dict:
    """qdrant_sync_pending (RAG/embeddings.db, forge_qdrant_sync_daemon) : file outbox
    SQLite->Qdrant. Bornee en regime normal (chunk_id PRIMARY KEY <= |rag_chunks|, et
    le daemon la vide en secondes), mais si le daemon meurt longtemps elle stagne ->
    filet firehose. queued_at = epoch. Une entree > COLD_DAYS = daemon mort/orpheline :
    purge sure (un fill de rattrapage recupere un chunk non synce). DELETE > COLD_DAYS."""
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    cut = time.time() - COLD_DAYS * 86400
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM qdrant_sync_pending WHERE queued_at < ?", (cut,)).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM qdrant_sync_pending WHERE queued_at < ?", (cut,))
            con.commit()
        return {"qdrant_sync_pending_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_loop_lag(dry: bool) -> dict:
    """logs/loop_lag.log (LoopSentinel) : dumps de stacks a chaque blocage de
    l'event-loop du hub. Chaque entree fait des DIZAINES de lignes (toutes les
    piles de tous les threads) ; mesure du 2026-08-17 : **49 Mo**, sans aucune
    politique de purge — le meme angle mort que le gate firehose reproche aux
    tables neuves. Or ce fichier est un outil de DIAGNOSTIC : au-dela des
    derniers incidents il n'apprend plus rien, et sa taille rend sa lecture
    couteuse (un `Get-Content -Tail` dessus bloque justement le hub qu'on
    diagnostique). On garde la QUEUE, la seule partie utile.
    """
    p = ROOT / "logs" / "loop_lag.log"
    if not p.exists():
        return {"skipped": "pas de loop_lag.log"}
    cap = int(os.environ.get("LOOP_LAG_KEEP_BYTES", str(8 * 1024 * 1024)))
    taille = p.stat().st_size
    if taille <= cap:
        return {"loop_lag_mb": round(taille / 1048576, 1), "sous_plafond": True}
    if dry:
        return {"loop_lag_mb": round(taille / 1048576, 1), "a_tronquer_mb":
                round((taille - cap) / 1048576, 1), "dry_run": True}
    try:
        with open(p, "rb") as f:
            f.seek(-cap, 2)
            queue = f.read()
        # On repart a la premiere borne d'entree pour ne pas laisser une pile
        # tronquee en tete, illisible et trompeuse.
        marque = queue.find(b"\n=== ")
        if marque > 0:
            queue = queue[marque + 1:]
        p.write_bytes(queue)
        return {"loop_lag_tronque_mb": round((taille - len(queue)) / 1048576, 1),
                "restant_mb": round(len(queue) / 1048576, 1)}
    except OSError as e:
        return {"skipped": str(e)[:80]}


def _purge_veille_url_morte(dry: bool) -> dict:
    """veille_url_morte (RAG/embeddings.db, forge_veille_gap_recover) : URLs dont
    le serveur a repondu 404/410. Bornee par l'univers des URLs de biblio, mais on
    RE-ESSAYE volontairement les vieilles marques : une page morte aujourd'hui peut
    reapparaitre (refonte de doc, URL restauree). Purger la marque > MORTE_DAYS rend
    l'URL au perimetre de rattrapage. vu_le = ISO 8601 UTC, comparable en texte."""
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    from datetime import datetime, timedelta, timezone

    cut = (datetime.now(timezone.utc) - timedelta(days=MORTE_DAYS)).isoformat()
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM veille_url_morte WHERE vu_le < ?", (cut,)).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM veille_url_morte WHERE vu_le < ?", (cut,))
            con.commit()
        return {"veille_url_morte_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_epistemic_seen(dry: bool) -> dict:
    """epistemic_seen (RAG/embeddings.db, forge_epistemic_daemon) : requetes deja
    jugees pour la soif de connaissance. Bornee (query_hash PRIMARY KEY <= queries
    distinctes) mais on RE-EVALUE volontairement les vieilles entrees : une query
    jugee 'gap' il y a longtemps a pu etre comblee (ou l'inverse). Purger > COLD_DAYS
    force la re-mesure ET satisfait le filet firehose. seen_at = epoch."""
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    cut = time.time() - COLD_DAYS * 86400
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM epistemic_seen WHERE seen_at < ?", (cut,)).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM epistemic_seen WHERE seen_at < ?", (cut,))
            con.commit()
        return {"epistemic_seen_purged": n, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_proprioception_snapshots(dry: bool) -> dict:
    """proprioception_snapshots (RAG/embeddings.db, app/forge_proprioception.py) :
    un instantane des 6 axes + atlas a chaque cycle (daemon 6 h). Chaque ligne porte
    deux JSON plafonnes a 8 Ko : la table etait la SEULE ecrite sans retention.

    PLANCHER de MIN_KEEP lignes en plus de la fenetre : ces snapshots servent a
    calculer une tendance (delta T-7j). Purger sur la seule date effacerait l'
    historique apres une periode d'inactivite -- soit exactement quand la tendance
    redevient interessante. ts = ISO-8601, d'ou la comparaison textuelle.
    """
    from datetime import datetime, timedelta  # importe localement, comme ses voisines

    MIN_KEEP = 60  # ~15 jours de cycles 6 h, conserves quoi qu'il arrive
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    cut = (datetime.now() - timedelta(days=COLD_DAYS)).isoformat()
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM proprioception_snapshots WHERE ts < ? AND id NOT IN "
            "(SELECT id FROM proprioception_snapshots ORDER BY id DESC LIMIT ?)",
            (cut, MIN_KEEP),
        ).fetchone()[0]
        if not dry and n:
            con.execute(
                "DELETE FROM proprioception_snapshots WHERE ts < ? AND id NOT IN "
                "(SELECT id FROM proprioception_snapshots ORDER BY id DESC LIMIT ?)",
                (cut, MIN_KEEP),
            )
            con.commit()
        return {"proprioception_snapshots_purged": n, "min_keep": MIN_KEEP, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_autonomous_loops(dry: bool) -> dict:
    """autonomous_loop_audit (RAG/embeddings.db, forge_autonomous_loops) : une ligne
    par execution de pattern, `id` AUTOINCREMENT + `ts` epoch -> croissance ILLIMITEE.
    Mesure 2026-07-28 : 8683 lignes, daemon a tick 60 s. Au-dela de COLD_DAYS l'audit
    ne sert plus qu'a peser.

    `autonomous_loop_state` n'est PAS purgee et ne DOIT pas l'etre : sa clef primaire
    est `pattern`, donc elle est BORNEE par construction — 14 lignes pour 14 patterns,
    mesure le meme jour. Le filet firehose la signalait faute de la voir referencee
    ici ; c'est son DIAGNOSTIC qui etait faux, pas la table. On corrige le diagnostic,
    on ne contourne pas le garde.
    """
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    cut = time.time() - COLD_DAYS * 86400
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM autonomous_loop_audit WHERE ts < ?", (cut,)
        ).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM autonomous_loop_audit WHERE ts < ?", (cut,))
            con.commit()
        rest = con.execute("SELECT COUNT(*) FROM autonomous_loop_audit").fetchone()[0]
        return {
            "autonomous_loop_audit_purged": n,
            "rows_after": rest,
            "autonomous_loop_state": "bornee par PK pattern — purge volontairement absente",
            "dry_run": dry,
        }
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_signal_emissions(dry: bool) -> dict:
    """signal_emissions.db (forge_signal_coupling) : BORNEE, et volontairement SANS purge.

    Flaggee par le gate firehose ("CREATE TABLE emissions non referencee -> croissance
    illimitee"). Le garde a raison de demander ; la reponse est qu'il n'y a rien a
    purger, et il faut le DIRE plutot que l'ignorer.

    Couvre les TROIS tables du module -- `emissions`, `lectures`, `transductions` --
    qui partagent la meme forme et la meme raison.

    Pourquoi bornees : `PRIMARY KEY (signal, <pair>)` + UPSERT. Une ligne par COUPLE
    distinct, pas par evenement -- meme raisonnement que `autonomous_loop_state`
    ci-dessus. Mille emissions du meme emetteur = une ligne, avec un compteur.

    Pourquoi AUCUNE suppression : cette table porte la seule trace qui rende une voie
    DEGENERESCENTE visible. Supprimer une emission ancienne ferait repasser le signal
    de « emis jadis, plus stimule » a « jamais mesure » -- de l'amnesie deguisee en
    elagage, et la perte exacte de l'information qu'on cherchait. En biologie l'elagage
    retire la SYNAPSE, pas le souvenir qu'elle a existe.
    """
    db = ROOT / "sandbox" / "signal_emissions.db"
    if not db.exists():
        return {"signal_emissions": "absente (aucune emission encore constatee)"}
    try:
        con = sqlite3.connect(str(db), timeout=10)
        con.execute("PRAGMA busy_timeout=5000")
        out = {}
        for t in ("emissions", "lectures", "transductions"):
            try:
                out["%s_couples" % t] = con.execute(
                    "SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                out["%s_total" % t] = con.execute(
                    "SELECT COALESCE(SUM(n), 0) FROM %s" % t).fetchone()[0]
            except sqlite3.OperationalError:
                out["%s_couples" % t] = "table absente (module pas encore sollicite)"
        con.close()
    except Exception as exc:
        return {"signal_emissions_error": "%s: %s" % (type(exc).__name__, str(exc)[:90])}
    out["purge"] = ("aucune — bornees par UPSERT ; la trace fait le diagnostic "
                    "(degenerescence, et lectures vs transductions pour le leurre)")
    return out


def _purge_organ_demandes(dry: bool) -> dict:
    """organ_demandes / organ_demandes_journal (forge_organ_demand) : PURGE REELLE.

    Meme base que ci-dessus, raisonnement OPPOSE, et c'est la difference qui
    compte. Les trois tables de `forge_signal_coupling` sont bornees par un
    UPSERT sur une clef ; celles-ci grossissent d'une ligne PAR EVENEMENT --
    un bail est ouvert a chaque inference qui traverse
    `forge_llamacpp._server_call`. Sans purge, le journal suit le trafic
    d'inference indefiniment. Le gate firehose a eu raison de le signaler des
    l'ecriture du module (2026-09-02).

    `organ_etats` reste EXCLUE : une ligne par organe, PRIMARY KEY + UPSERT --
    bornee comme les emissions.

    Ce qu'on garde, et pourquoi ce n'est pas un reglage arbitraire : la phase de
    coexistence doit repondre a « qui demande llama, combien de temps, a quelle
    frequence » AVANT qu'on retire le faux emetteur du keeper. Effacer trop tot
    detruirait la preuve qu'on est en train de constituer -- et c'est cette
    preuve qui evitera de rejouer juillet (73 arrets, 312,94 Go rechargees).
    Les baux FERMES et le journal partent apres la fenetre ; un bail OUVERT
    n'est jamais supprime, quel que soit son age : il decrit le present.
    """
    jours = float(os.environ.get("ORGAN_DEMAND_RETENTION_DAYS", "30"))
    db = ROOT / "sandbox" / "signal_emissions.db"
    if not db.exists():
        return {"organ_demandes": "base absente (module pas encore sollicite)"}
    cut = time.time() - jours * 86400.0
    try:
        con = sqlite3.connect(str(db), timeout=10)
        con.execute("PRAGMA busy_timeout=5000")
        out: dict = {"fenetre_jours": jours}
        try:
            out["demandes_ouvertes"] = con.execute(
                "SELECT COUNT(*) FROM organ_demandes WHERE released_at IS NULL"
            ).fetchone()[0]
            # Un bail OUVERT decrit le present : jamais purge, meme tres vieux.
            # Un bail vieux et toujours ouvert est d'ailleurs un signal en soi.
            vieux = con.execute(
                "SELECT COUNT(*) FROM organ_demandes WHERE released_at IS NOT NULL"
                " AND released_at < ?", (cut,)).fetchone()[0]
            journal = con.execute(
                "SELECT COUNT(*) FROM organ_demandes_journal WHERE ts < ?",
                (cut,)).fetchone()[0]
            out["demandes_fermees_a_purger"] = vieux
            out["journal_a_purger"] = journal
            if not dry:
                con.execute("DELETE FROM organ_demandes WHERE released_at IS NOT NULL"
                            " AND released_at < ?", (cut,))
                con.execute("DELETE FROM organ_demandes_journal WHERE ts < ?", (cut,))
                con.commit()
                out["purge"] = "%d bail(s) ferme(s) + %d evenement(s)" % (vieux, journal)
            else:
                out["purge"] = "dry-run"
        except sqlite3.OperationalError:
            out["organ_demandes"] = "tables absentes (module pas encore sollicite)"
        con.close()
    except Exception as exc:  # noqa: BLE001
        return {"organ_demandes_error": "%s: %s" % (type(exc).__name__, str(exc)[:90])}
    return out


def _purge_rag_snapshots(dry: bool) -> dict:
    """rag_snapshots (RAG/embeddings.db) : instantanés pris avant chaque écriture
    RAG (forge_timecode) pour `rag_rollback(before=T)`. INSERT-only, et chaque
    ligne porte le TEXTE COMPLET du chunk -> croissance illimitée en OCTETS, pas
    seulement en lignes. Mesuré 2026-07-26 : 70 168 lignes, table non référencée
    ici, signalée par le gate anti-régression « incident 47 Go ».

    On garde RAG_SNAPSHOTS_KEEP_DAYS (défaut COLD_DAYS) : au-delà, la profondeur
    de rollback n'a plus de valeur opérationnelle alors que son coût, lui, reste.

    `timecode` est de l'ISO UTC suffixé Z. La borne DOIT être écrite dans la même
    forme : une comparaison lexicographique entre deux formats hétérogènes ne
    coupe rien et rendrait la purge silencieusement inopérante.
    """
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    from datetime import datetime, timedelta, timezone

    days = float(os.environ.get("RAG_SNAPSHOTS_KEEP_DAYS", str(COLD_DAYS)))
    cut = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM rag_snapshots WHERE timecode < ?", (cut,)).fetchone()[0]
        if not dry and n:
            con.execute("DELETE FROM rag_snapshots WHERE timecode < ?", (cut,))
            con.commit()
        return {"rag_snapshots_purged": n, "keep_days": days, "cut": cut, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _check_global_sequence(dry: bool) -> dict:
    """global_sequence (RAG/embeddings.db) : compteur de la séquence monotone de
    forge_timecode — colonnes (id, last_seq, last_tick), UNE seule ligne.

    Référencée ICI volontairement. Le gate anti-régression exige que toute table
    créée soit citée dans ce module, et il l'avait signalée au même titre que
    rag_snapshots. Mais la vérification dit autre chose : ce n'est pas un journal,
    c'est un compteur. Le purger détruirait la séquence et casserait l'ordre des
    événements — le remède serait pire que le mal supposé.

    On MESURE donc au lieu de purger, et on lève une anomalie si l'hypothèse
    « une seule ligne » cesse d'être vraie. Un garde-fou peut être bon et son
    diagnostic faux : on corrige le diagnostic, pas le garde.
    """
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        n = con.execute("SELECT COUNT(*) FROM global_sequence").fetchone()[0]
        return {"global_sequence_rows": n,
                "purge": "aucune — compteur, pas un journal",
                "anomalie": bool(n > 1), "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


# Plafond du journal d'audit opsec, en LIGNES. Mesure 2026-09-13 : 21 lignes
# accumulees sur plusieurs mois. Le plafond borne un emballement sans jamais
# mordre sur le regime normal -- il faudrait ~200x le rythme observe pour
# l'atteindre.
OPSEC_AUDIT_MAX_LIGNES = 5000


def _purge_journaux_securite(dry: bool) -> dict:
    """Journaux de securite INSERT-only, signales par le garde anti-firehose.

    MESURE 2026-08-19 : `forge_firehose_guard` nommait cinq tables creees sans
    aucune purge cablee ici. Trois sont de vrais JOURNAUX, et ils sont traites :
      * `db_access_log`  (logs/db_access.db)      -- ts REAL, epoch
      * `token_events`   (sandbox/token_usage.db) -- ts TEXT, ISO
      * `vault_audit`    (vault.db)               -- journal d'acces au coffre

    ⚠️ DEUX SONT EXEMPTEES, et ce n'est pas un oubli :
    `vault_entries` et `vault_meta` ne sont PAS des journaux -- ce sont les
    SECRETS eux-memes (payload chiffre, categorie, libelle). Les purger par
    anciennete detruirait des donnees que rien ne regenere. Un garde qui compte
    les tables sans distinguer JOURNAL et DONNEE pousse a effacer le coffre.
    Leur peremption legitime passe par `expires_at`, decision separee et non
    prise ici.

    Les tables n'existent pas encore (CREATE IF NOT EXISTS jamais execute) : la
    purge est donc tolerante, et le dira plutot que d'echouer.
    """
    from datetime import datetime, timedelta

    epoch_cut = time.time() - COLD_DAYS * 86400
    iso_cut = (datetime.now() - timedelta(days=COLD_DAYS)).isoformat()
    # (base, table, colonne, borne) -- ts REAL et ts TEXT ne se comparent pas
    # de la meme facon : melanger les deux effacerait tout, ou rien.
    plan = (
        (ROOT / "logs" / "db_access.db", "db_access_log", "ts", epoch_cut),
        (ROOT / "sandbox" / "token_usage.db", "token_events", "ts", iso_cut),
        (ROOT / "vault.db", "vault_audit", "ts", iso_cut),
    )
    out: dict = {"dry_run": dry, "exemptees": ["vault_entries", "vault_meta"]}
    for chemin, table, col, borne in plan:
        if not chemin.exists():
            out[table] = "base absente"
            continue
        con = sqlite3.connect(str(chemin), timeout=30)
        try:
            n = con.execute("SELECT COUNT(*) FROM %s WHERE %s < ?" % (table, col),
                            (borne,)).fetchone()[0]
            if not dry and n:
                con.execute("DELETE FROM %s WHERE %s < ?" % (table, col), (borne,))
                con.commit()
            out[table] = n
        except sqlite3.OperationalError as e:
            # Table pas encore creee, ou colonne differente : on le DIT.
            out[table] = "non purgeable (%s)" % str(e)[:60]
        finally:
            con.close()

    # --- Journaux d'AUTORITE (opsec) ------------------------------------
    # MESURE 2026-09-13, apres signalement du garde anti-firehose au commit
    # `cffd0fb05`. Deux tables etaient nommees ; elles ne se traitent PAS pareil,
    # et c'est exactement la distinction JOURNAL / DONNEE ci-dessus :
    #
    #   * `opsec_audit_log` EST un journal (21 lignes, `ts` REAL epoch) -- mais
    #     ces 21 lignes couvrent PLUSIEURS MOIS. A COLD_DAYS=30, une purge par
    #     anciennete en effacerait 21 sur 21 : tout l'historique du kill-switch,
    #     pour gagner quelques kilo-octets. Le risque que nomme le garde est la
    #     CROISSANCE, pas l'age. On la borne donc par un PLAFOND DE LIGNES, qui
    #     ne detruit rien tant que le journal reste petit et qui coupe net s'il
    #     s'emballe.
    #   * `opsec_state` est EXEMPTEE : 3 lignes cle/valeur qui portent le
    #     kill-switch humain lui-meme. La purger n'effacerait pas un journal,
    #     elle effacerait l'AUTORITE.
    #
    # Le chemin passe par `authority_path()` : il suit la bascule de la base
    # d'autorite hors du RAG au lieu de la figer ici.
    out["exemptees"] = list(out.get("exemptees", [])) + ["opsec_state"]
    try:
        from nokido_agent.app.forge_db_path import authority_path as _autorite

        _base = _autorite()
    except Exception as e:  # noqa: BLE001 - l'illisible se DIT, il ne s'avale pas
        out["opsec_audit_log"] = "base d'autorite irresolue (%s)" % type(e).__name__
        _base = None
    # SYMETRIE (2026-09-13) : le plan ci-dessus teste `exists()` avant de se
    # connecter, pas ce bloc -- et `connect` sur un dossier absent LEVE. La
    # fonction explosait au lieu de le DIRE. Detail : message de commit.
    from pathlib import Path as _Chemin

    if _base and not _Chemin(str(_base)).exists():
        out["opsec_audit_log"] = "base d'autorite absente (%s)" % str(_base)[:80]
        _base = None
    if _base:
        con = None
        try:
            con = sqlite3.connect(str(_base), timeout=30)
            total = con.execute("SELECT COUNT(*) FROM opsec_audit_log").fetchone()[0]
            trop = max(0, total - OPSEC_AUDIT_MAX_LIGNES)
            if not dry and trop:
                con.execute(
                    "DELETE FROM opsec_audit_log WHERE id NOT IN "
                    "(SELECT id FROM opsec_audit_log ORDER BY id DESC LIMIT ?)",
                    (OPSEC_AUDIT_MAX_LIGNES,),
                )
                con.commit()
            out["opsec_audit_log"] = {
                "lignes": total,
                "plafond": OPSEC_AUDIT_MAX_LIGNES,
                "supprimees": trop,
                "mode": "volume (pas anciennete)",
            }
        except sqlite3.OperationalError as e:
            out["opsec_audit_log"] = "non purgeable (%s)" % str(e)[:60]
        finally:
            if con is not None:
                con.close()
    return out


def _purge_core_memory(dry: bool) -> dict:
    """core_memory (RAG/embeddings.db, forge_memory_archival) : persona + facts par agent.

    SIGNALE par le gate au commit d5df30950 : `CREATE TABLE core_memory` sans purge.
    MESURE 2026-08-26 : 2 lignes, `facts` max 34 octets — la table est bornee par le
    NOMBRE D'AGENTS (agent_id PRIMARY KEY, INSERT OR REPLACE), pas par le temps. Le
    risque reel n'est donc pas le nombre de lignes mais (a) un agent disparu dont les
    facts survivent indefiniment et sont injectes AVANT le reste du contexte, et (b)
    un `facts` qui enfle chez un agent vivant. Retention DECLAREE :
      (a) agent sans aucune archive depuis CORE_MEMORY_DAYS ET dont la ligne n'a pas
          bouge depuis autant -> supprime (index idx_archives_agent, pas de balayage) ;
      (b) `facts` au-dela de CORE_MEMORY_FACTS_MAX -> SIGNALE, jamais tronque : couper
          des facts en silence fabriquerait une memoire fausse, pire qu'une lourde.
    """
    from datetime import datetime, timedelta, timezone

    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    cut = (datetime.now(timezone.utc) - timedelta(days=CORE_MEMORY_DAYS)).isoformat()
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        morts = [r[0] for r in con.execute(
            "SELECT agent_id FROM core_memory m WHERE m.updated_at < ? AND NOT EXISTS "
            "(SELECT 1 FROM conv_archives a WHERE a.agent_id = m.agent_id AND a.archived_at >= ?)",
            (cut, cut))]
        gros = [(r[0], r[1]) for r in con.execute(
            "SELECT agent_id, length(facts) FROM core_memory WHERE length(facts) > ?",
            (CORE_MEMORY_FACTS_MAX,))]
        if not dry and morts:
            con.executemany("DELETE FROM core_memory WHERE agent_id = ?", [(a,) for a in morts])
            con.commit()
        total = con.execute("SELECT COUNT(*) FROM core_memory").fetchone()[0]
        if gros:
            log.warning("core_memory: facts au-dela de %d octets chez %s — a reduire a la main",
                        CORE_MEMORY_FACTS_MAX, gros)
        return {"core_memory_purged": len(morts), "agents": morts[:10], "restants": total,
                "facts_sur_borne": gros, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_epistemic_vue(dry: bool) -> dict:
    """epistemic_extraction_vue (RAG/embeddings.db, forge_epistemic_extract_claims) :
    journal des chunks deja soumis a l'extraction d'assertions. Bornee par |rag_chunks|
    (chunk_id PRIMARY KEY) mais ORPHELINABLE : un chunk purge laisse sa marque. On
    retire les marques sans chunk (PK lookup, pas de balayage) et les marques `muet`
    plus vieilles que COLD_DAYS — un LLM muet ce jour-la n'etait pas un verdict."""
    from datetime import datetime, timedelta, timezone

    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    cut = (datetime.now(timezone.utc) - timedelta(days=COLD_DAYS)).isoformat()
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        orph = con.execute(
            "SELECT COUNT(*) FROM epistemic_extraction_vue v WHERE NOT EXISTS "
            "(SELECT 1 FROM rag_chunks c WHERE c.id = v.chunk_id)").fetchone()[0]
        muets = con.execute(
            "SELECT COUNT(*) FROM epistemic_extraction_vue WHERE statut = 'muet' AND vu_at < ?",
            (cut,)).fetchone()[0]
        if not dry and (orph or muets):
            con.execute("DELETE FROM epistemic_extraction_vue WHERE NOT EXISTS "
                        "(SELECT 1 FROM rag_chunks c WHERE c.id = epistemic_extraction_vue.chunk_id)")
            con.execute("DELETE FROM epistemic_extraction_vue WHERE statut = 'muet' AND vu_at < ?", (cut,))
            con.commit()
        return {"orphelines": orph, "muets_reouverts": muets, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def _purge_epistemic_claims(dry: bool) -> dict:
    """chunk_claims / claim_reevaluations (RAG/embeddings.db, forge_epistemic_extract_claims).
    Bornees par construction (<= 3 assertions par chunk, une reevaluation par paire)
    mais ORPHELINABLES : le schema declare `ON DELETE CASCADE`, or aucune purge de ce
    fichier n'active `PRAGMA foreign_keys`, donc la cascade ne joue jamais. Signale par
    le gate firehose au commit 738651e6f. On retire les assertions sans chunk et les
    reevaluations sans assertion — PK lookups, jamais de balayage de rag_chunks."""
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        claims = con.execute(
            "SELECT COUNT(*) FROM chunk_claims k WHERE NOT EXISTS "
            "(SELECT 1 FROM rag_chunks c WHERE c.id = k.chunk_id)").fetchone()[0]
        reevals = con.execute(
            "SELECT COUNT(*) FROM claim_reevaluations r WHERE NOT EXISTS "
            "(SELECT 1 FROM chunk_claims k WHERE k.id = r.older_claim_id) OR NOT EXISTS "
            "(SELECT 1 FROM chunk_claims k WHERE k.id = r.newer_claim_id)").fetchone()[0]
        if not dry and (claims or reevals):
            con.execute("DELETE FROM chunk_claims WHERE NOT EXISTS "
                        "(SELECT 1 FROM rag_chunks c WHERE c.id = chunk_claims.chunk_id)")
            con.execute("DELETE FROM claim_reevaluations WHERE NOT EXISTS "
                        "(SELECT 1 FROM chunk_claims k WHERE k.id = claim_reevaluations.older_claim_id) "
                        "OR NOT EXISTS (SELECT 1 FROM chunk_claims k WHERE k.id = claim_reevaluations.newer_claim_id)")
            con.commit()
        return {"claims_orphelines": claims, "reevaluations_orphelines": reevals, "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


PROOF_DAYS = float(os.environ.get("PROOF_RETENTION_DAYS", "7"))   # worktrees de CI plus vieux
PROOF_KEEP = int(os.environ.get("PROOF_RETENTION_KEEP", "3"))     # ... sauf les N plus recents


def _purge_worktrees_de_preuve(dry: bool) -> dict:
    """sandbox/workspace/tmp/nokido_proof : worktrees git DETACHES + artefacts de chaque CI.

    Question owner du 2026-09-24 (« y a pas une purge auto a mettre en place ? ») ; mesure :
    126 entrees du 11/09 au 22/09. `ci_local` cree un worktree de reference PAR execution
    (identifiant unique) et ne le retire JAMAIS ; `forge_worktree.remove_proof` existait,
    appele par personne. On ne reinvente rien : le chemin est DEMANDE au proprietaire
    (`forge_worktree.PROOF_ROOT`), le retrait passe par SA fonction (`git worktree remove`,
    le depot n'est jamais touche) -- supprimer le dossier a la main laisserait des
    references orphelines dans .git/worktrees.
    Garde : les PROOF_KEEP plus recents ET tout ce qui a moins de PROOF_DAYS (une CI en
    cours n'est jamais visee). Le reste : worktree retire par git, puis artefacts.
    """
    try:
        import forge_worktree as fw
    except ImportError:
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            import forge_worktree as fw
        except ImportError as e:
            return {"skipped": "forge_worktree illisible (%s)" % type(e).__name__}
    uniques, illisibles = _racines_de_preuve(fw)
    par_racine = [_purger_une_racine_de_preuve(fw, rac, dry) for rac in uniques]
    if not dry and any(r.get("eligibles") for r in par_racine):
        fw._git(["worktree", "prune"], cwd=ROOT)
    return {"racines": par_racine, "illisibles": illisibles,
            "retirees": sum(r.get("retirees", 0) for r in par_racine),
            "regle": "garde %d plus recentes + < %.0f j, par racine" % (PROOF_KEEP, PROOF_DAYS),
            "dry_run": dry}


def _racines_de_preuve(fw) -> tuple:
    """Racines ou la CI ECRIT reellement ses preuves -- (racines uniques, illisibles).

    Mesure en production (2026-09-24) : `fw.PROOF_ROOT` vaut le TEMP du compte qui l'evalue.
    Le service de retention obtenait `C:\\WINDOWS\\TEMP\\nokido_proof` (« zone absente ») pendant
    que 126 preuves s'accumulaient la ou la CI les ecrit : `chemin_tmp_sandbox()/nokido_proof`,
    le point unique des comptes de job. Les deux sont parcourues ; une racine illisible est DITE.
    """
    racines, illisibles = [Path(fw.PROOF_ROOT)], []
    try:
        racines.append(Path(_chemin_tmp_sandbox()) / "nokido_proof")
    except Exception as e:  # noqa: BLE001
        illisibles.append("chemin_tmp_sandbox illisible (%s)" % type(e).__name__)
    uniques = []
    for rac in racines:
        if all(os.path.normcase(str(rac)) != os.path.normcase(str(u)) for u in uniques):
            uniques.append(rac)
    return uniques, illisibles


def _supprimer_arbre(chemin: Path) -> None:
    """`shutil.rmtree` qui leve l'attribut LECTURE SEULE avant de reessayer (Windows).

    Mesure en production (2026-09-24, relance de 22:13) : 24 entrees sur 63 refusees en
    PermissionError ; dans l'une d'elles, les 137 fichiers restants etaient TOUS en lecture seule --
    des objets git crees par des fixtures pytest (`pytest_basetemp/.../depot/.git/objects`).
    Le compte a le droit de supprimer ; seul l'attribut bloquait. Un refus qui PERSISTE (ACL
    d'un autre compte) remonte tel quel, avec le chemin. `onexc` : Python >= 3.12 (les deux
    interpreteurs du corps, miniforge 3.12 et py314).
    """
    import shutil
    import stat

    def _forcer(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    shutil.rmtree(chemin, onexc=_forcer)


def _purger_une_racine_de_preuve(fw, base: Path, dry: bool) -> dict:
    import shutil

    if not base.is_dir():
        return {"proof_zone": "absente", "proof_chemin": str(base)}
    entrees = sorted((e for e in base.iterdir() if e.is_dir() and not e.is_symlink()),
                     key=lambda e: e.stat().st_mtime, reverse=True)
    limite = time.time() - PROOF_DAYS * 86400
    gardes = [e for i, e in enumerate(entrees) if i < PROOF_KEEP or e.stat().st_mtime >= limite]
    visees = [e for e in entrees if e not in gardes]
    retires, erreurs = [], []
    # Worktrees que GIT connait encore : un dossier sans `.git` n'est supprime a la main que s'il
    # n'y figure PAS (preuve, pas deduction, qu'aucune reference ne devient orpheline -- owner 24/09).
    try:
        connus = {os.path.normcase(os.path.normpath(w["path"])) for w in fw.list_wt()} if visees and not dry else set()
        liste_lisible = True
    except Exception as ex:  # noqa: BLE001
        connus, liste_lisible = set(), False
        erreurs.append({"entree": "*", "msg": "git worktree list illisible (%s) : aucun dossier sans .git "
                                               "supprime" % type(ex).__name__})
    for e in visees:
        if dry:
            continue
        # Deux formes : <execution_id>/worktree (+ artefacts) ou <sha12> (le worktree lui-meme).
        # Retrait par CHEMIN : la racine vient d'ici, pas de fw.PROOF_ROOT.
        # SANS `.git` (mesure 2026-09-24 : 64 entrees sur 121) = plus un worktree git, un dossier
        # ordinaire : `git worktree remove` le refuse (« validation failed ») et la regle « pas de
        # suppression a la main apres un refus de git » le gardait POUR TOUJOURS. Aucun worktree
        # vivant ne le reference ; les metadonnees pointant vers un .git absent sont celles que
        # `git worktree prune` nettoie en fin de passage -- supprimer ne cree aucune reference orpheline.
        if (e / "worktree" / ".git").exists():
            r = fw.retirer_worktree(e / "worktree")
        elif (e / ".git").exists():
            r = fw.retirer_worktree(e)
        else:
            cibles = {os.path.normcase(os.path.normpath(str(p))) for p in (e, e / "worktree")}
            if not liste_lisible or cibles & connus:
                erreurs.append({"entree": e.name, "msg": "sans .git mais encore REFERENCE par git worktree list "
                                "(ou liste illisible) : non supprime, `git worktree prune` d'abord"})
                continue
            r = {"status": "sans_worktree_git"}
        if r.get("status") == "erreur":
            msg = r.get("msg", "")
            erreurs.append({"entree": e.name, "msg": msg[:500] + (" (tronque)" if len(msg) > 500 else "")})
            continue   # worktree git VIVANT non retire par git : on ne supprime PAS le dossier a la main
        try:
            _supprimer_arbre(e)
        except OSError as ex:
            erreurs.append({"entree": e.name, "msg": "suppression refusee (%s: %s)" % (type(ex).__name__, str(ex)[:400])})
            continue
        retires.append(e.name)
    return {"proof_chemin": str(base), "vues": len(entrees), "gardees": len(gardes),
            "eligibles": len(visees), "retirees": len(retires), "noms_retires": retires[:80],
            "erreurs": erreurs[:10], "erreurs_total": len(erreurs), "dry_run": dry}


CONV_LOG_SIGNAL_MO = float(os.environ.get("CONV_LOG_SIGNAL_MO", "100"))  # SIGNALE, jamais purge


def _surveiller_conversation_log(dry: bool) -> dict:
    """conversation_log (RAG/embeddings.db, forge_conversation_logger) : SURVEILLE, JAMAIS PURGE.

    Decision owner du 2026-09-24 : « purge intelligente SI TRAITE, ou compacte, apres en
    avoir tire la substantifique moelle ». MESURE du jour : 31 906 lignes, 8 Mo de contenu
    sur six mois (~4 Mo/mois) dans une base de ~45 Go -- 0,02 % ; AUCUN distillateur ne
    consomme la table (seuls le logger, pour son rappel, et le diagnostic, pour la
    compter) ; 0 session recouverte par `conv_archives`. Aucune ligne n'est donc
    « traitee » : purger detruirait de la matiere jamais distillee, pour rien.
    Retention DECLAREE : on MESURE a chaque passage ; au-dela de CONV_LOG_SIGNAL_MO, on
    SIGNALE qu'il faut distiller AVANT de purger. Le jour ou un distillateur marque ses
    sessions, la purge des sessions marquees s'ecrit ICI -- export jsonl.gz rejouable
    d'abord, comme pour agent_messages.
    """
    DB = ROOT / "RAG" / "embeddings.db"
    if not DB.exists():
        return {"skipped": "no embeddings db"}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB.as_posix(), uri=True, timeout=30)
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    try:
        n, mo, plus_ancien = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(length(content)), 0) / 1048576.0, MIN(ts) "
            "FROM conversation_log").fetchone()
        sur_seuil = mo > CONV_LOG_SIGNAL_MO
        if sur_seuil:
            log.warning("conversation_log: %.1f Mo > %.0f Mo -- DISTILLER avant toute purge "
                        "(aucune ligne n'est marquee traitee)", mo, CONV_LOG_SIGNAL_MO)
        return {"lignes": n, "mo": round(mo, 2), "plus_ancien": plus_ancien,
                "seuil_mo": CONV_LOG_SIGNAL_MO, "sur_seuil": sur_seuil,
                "purgees": 0, "raison": "aucune ligne traitee : rien n'est eligible",
                "dry_run": dry}
    except sqlite3.OperationalError as e:
        return {"skipped": str(e)[:80]}
    finally:
        con.close()


def run_retention(dry: bool = False) -> dict:
    t0 = time.monotonic()
    res = {
        "traces": _retention_traces(dry),
        "conversation_log": _surveiller_conversation_log(dry),
        "worktrees_de_preuve": _purge_worktrees_de_preuve(dry),
        "journaux_securite": _purge_journaux_securite(dry),
        "qdrant_sync_pending": _purge_qdrant_sync_pending(dry),
        "epistemic_seen": _purge_epistemic_seen(dry),
        "epistemic_vue": _purge_epistemic_vue(dry),
        "epistemic_claims": _purge_epistemic_claims(dry),
        "core_memory": _purge_core_memory(dry),
        "veille_url_morte": _purge_veille_url_morte(dry),
        "loop_lag": _purge_loop_lag(dry),
        "autonomous_loops": _purge_autonomous_loops(dry),
        "proprioception_snapshots": _purge_proprioception_snapshots(dry),
        "edges": _purge_edges(dry),
        "rag_snapshots": _purge_rag_snapshots(dry),
        "global_sequence": _check_global_sequence(dry),
        "archive_event_sourced": _archive_event_sourced(dry),
        "vault": _prune_vault(dry),
        "audit": _purge_audit(dry),
        "network_log": _purge_network_log(dry),
        "conv_archives": _purge_conv_archives(dry),
        "query_log": _purge_query_log(dry),
        "tasks": _purge_tasks(dry),
        "watch_chains": _purge_watch_chains(dry),
        "endocrine": _purge_endocrine_signals(dry),
        "signal_emissions": _purge_signal_emissions(dry),
        "organ_demandes": _purge_organ_demandes(dry),
        "agent_messages": _purge_agent_messages(dry),
        "task_queue": _purge_task_queue(dry),
        "agent_tasks": _purge_agent_tasks(dry),
        "mail": _purge_mail(dry),
        "runtime_lanes": _purge_runtime_lanes(dry),
        "canary_alerts": _purge_canary_alerts(dry),
        "veille_digest": _purge_veille_digest(dry),
        "safety_organs": _purge_safety_organs(dry),
        "goap_plans": _purge_goap_plans(dry),
        "active_inference": _purge_active_inference(dry),
        "membrane_aliases": _purge_membrane_aliases(dry),
        "bridge_logs": _purge_bridge_logs(dry),
        "inspector_log": _purge_inspector_log(dry),
        "workspace_tmp": _purge_workspace_tmp(dry),
        "vacuum": _vacuum(dry),
        "elapsed_s": None,
    }
    res["elapsed_s"] = round(time.monotonic() - t0, 1)
    log.info("retention: %s", json.dumps(res, default=str))
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il ajoute le `pid`.
    from nokido_agent.app.forge_heartbeat import beat_daemon

    beat_daemon("log_retention", health="ok", last=res)
    return res


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Nokido log retention + sanitisation tiers")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.once and not args.daemon:
        ap.error("--once or --daemon required")

    if args.once:
        print(json.dumps(run_retention(dry=args.dry_run), indent=2, default=str))
        return 0

    log.info("log_retention daemon — interval=%ds", INTERVAL_S)
    while True:
        try:
            run_retention(dry=False)
        except Exception as e:
            log.error("retention cycle error: %s", e)
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())
