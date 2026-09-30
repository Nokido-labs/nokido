"""
tools/forge_embed_auto_trigger.py — Daemon: watches for NULL-embedding RAG chunks,
auto-embeds via forge_embed_router (:8099 BGE-M3 GGUF + cascade), heartbeat sandbox/.
Migré 2026-06-09 : ZMQ brain_worker :5557 (DISABLED OOM 2026-06-03) -> embed_batch_fast.
"""

import json
import logging
import sqlite3
import struct as _struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nokido_agent.tools.forge_tier_policy import HOT_TIER_SQL, hot_tier_clause  # noqa: F401 (HOT_TIER_SQL = repli)
from nokido_agent.app.forge_embed_router import embed_batch_fast

try:
    import zmq  # legacy _zmq_embed_batch (fallback historique, non appelé)
except ImportError:
    zmq = None

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = LAFORGE_ROOT / "RAG" / "embeddings.db"
HEARTBEAT_PATH = LAFORGE_ROOT / "sandbox" / "embed_auto_trigger.heartbeat"
ZMQ_ADDR = "tcp://localhost:5557"
POLL_INTERVAL = 5
BATCH_SIZE = 512

# GARDE RAM AVEC HYSTERESIS (2026-09-06). Le drain n'en avait AUCUNE : il vectorisait
# a plein regime quelle que soit la charge, et c'est ce qui a fait ecarter le pilier
# local le 2026-09-01 (machine a 98 %). Mesure du jour, embedder borne : 15,6 chunks/s
# et un RSS qui plafonne a ~2,5 Go -- le drain PEUT donc tourner, a condition de se
# taire quand la machine est chargee. Deux seuils, jamais un seul : avec un seuil
# unique, le drain repart des qu'il repasse d'un dixieme de point sous la barre et
# pompe. Les valeurs viennent de `forge_physiology` (HIGH 85 / RELEASE 75), la meme
# echelle que les episodes de stress mesures ailleurs -- ne pas en inventer d'autres.
try:  # les seuils du corps priment ; le repli est DIT, jamais silencieux
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from nokido_agent.tools.forge_physiology import HIGH as RAM_PAUSE, RELEASE as RAM_REPRISE  # type: ignore
except Exception as _e_seuils:  # noqa: BLE001
    RAM_PAUSE, RAM_REPRISE = 85.0, 75.0
    print(f"[embed_auto_trigger] seuils forge_physiology illisibles ({_e_seuils!r}) "
          f"-> repli 85/75", flush=True)


def _secondes_avant_reset_quota() -> float:
    """Secondes avant le prochain rechargement du quota Cloudflare (00:00 UTC).

    Mesure 2026-09-06 : le quota gratuit vaut **27 100 chunks** quand on appelle EN LOT
    de 50 (812 caracteres par chunk en moyenne, 72 chunks/s) -- contre 3 631 mesures le
    2026-08-03 en appels unitaires. Ce n'est donc pas le quota qui avait change, c'est
    la FORME de l'appel. Une fois epuise, marteler l'API ne sert a rien : on dort
    jusqu'au rechargement plutot que de bruler des requetes en pure perte.
    """
    import datetime as _dt

    maintenant = _dt.datetime.now(_dt.timezone.utc)
    demain = (maintenant + _dt.timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return max(60.0, (demain - maintenant).total_seconds())


def _quota_epuise(stats: dict) -> bool:
    """La passe a-t-elle echoue faute de quota (et non pour une autre raison) ?

    On ne devine pas : la cascade journalise la cause exacte, et seule une passe qui
    n'ecrit RIEN en ayant des erreurs est candidate. Une passe partielle continue.
    """
    if stats.get("embedded"):
        return False
    return bool(stats.get("errors")) and _DERNIER_MOTIF_QUOTA[0]


_DERNIER_MOTIF_QUOTA = [False]


class _EcouteQuota(logging.Handler):
    """Ecoute les avertissements du routeur pour reconnaitre un quota epuise."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            m = record.getMessage().lower()
        except Exception:  # noqa: BLE001
            return
        if "neuron" in m or "quota" in m or " 429" in m:
            _DERNIER_MOTIF_QUOTA[0] = True


def _ram_pct() -> float:
    """RAM machine, ou -1.0 si ILLISIBLE (jamais 0 : un capteur muet ne doit pas se
    lire comme « machine au repos », ce serait un feu vert fabrique)."""
    try:
        import psutil

        return float(psutil.virtual_memory().percent)
    except Exception as e:  # noqa: BLE001
        print(f"[embed_auto_trigger] RAM illisible ({e!r})", flush=True)
        return -1.0
SUB_BATCH = 64  # texts per brain_worker submit — 64 optimal DIRECTML unified memory


def _zmq_embed_batch(texts: list) -> list:
    """Submit texts in sub-batches — socket ZMQ REQ FRAIS par sub-batch.

    Un socket REQ reutilise se wedge irreversiblement sur timeout (lockstep
    strict : send doit etre suivi de recv). Le drain ne restaure pas l'etat ;
    pire, le cascade finit par wedger aussi le REP de brain_worker. Socket
    frais + close() par sub-batch = robuste (pattern valide en test direct)."""
    import msgpack

    all_vecs = []
    for i in range(0, len(texts), SUB_BATCH):
        chunk = texts[i : i + SUB_BATCH]
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(ZMQ_ADDR)
        try:
            sock.send(
                msgpack.packb({"cmd": "submit", "type": "embed", "texts": chunk}, use_bin_type=True)
            )
            if not sock.poll(20_000):
                raise TimeoutError(f"submit timeout on sub-batch {i // SUB_BATCH}")
            rep = msgpack.unpackb(sock.recv(), raw=False)
            if not rep.get("ok"):
                raise RuntimeError(rep.get("error", "submit failed"))
            task_id = rep["task_id"]
            for _ in range(240):  # max 2min per sub-batch
                sock.send(msgpack.packb({"cmd": "check", "task_id": task_id}, use_bin_type=True))
                if not sock.poll(60_000):
                    # REP single-thread de brain_worker est starve par le
                    # TaskWorker ML (GIL) sous charge soutenue : un embed
                    # 64-textes ~16.5s. Tolerance large au lieu d'abandonner.
                    raise TimeoutError("check timeout (60s)")
                res = msgpack.unpackb(sock.recv(), raw=False)
                status = res.get("status", "pending")
                if status == "completed":
                    data = res.get("data")
                    if isinstance(data, dict):
                        all_vecs.extend(data.get("vecs", []))
                    elif isinstance(data, list):
                        all_vecs.extend(data)
                    break
                elif status == "error":
                    raise RuntimeError(res.get("error", "embed error"))
                time.sleep(0.5)
            else:
                raise TimeoutError(f"sub-batch {i // SUB_BATCH} never completed")
        finally:
            sock.close()
            ctx.term()
    return all_vecs


def _save_heartbeat(stats: dict):
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il pose `ts` et `pid`.
    # L'ancienne version ecrivait sans aucun garde — une erreur disque y remontait
    # jusqu'a l'appelant, alors qu'un pouls ne doit jamais tuer son porteur.
    from nokido_agent.app.forge_heartbeat import beat_daemon

    beat_daemon("embed_auto_trigger", **stats)


CAMPAGNE_BATTEMENT = LAFORGE_ROOT / "sandbox" / "modal_campagne.heartbeat"
CAMPAGNE_FRAICHE_S = 180


def campagne_cloud_active() -> bool:
    """Une campagne d'embeddings CLOUD bat-elle en ce moment ?

    Mesure 2026-09-01 : la campagne Modal et ce drain vectorisent la MEME file.
    Lances ensemble, ils se disputent l'unique writer SQLite -- la campagne est
    morte a 11 776/200 868 sur `database is locked`, et le GPU distant DEJA PAYE
    pour ce lot a ete perdu. Pire, ce drain reclame `embed.wanted` des qu'il ne
    trouve pas :8099, si bien que le keeper rallumait 12 Go d'embedder local
    pendant que Modal faisait deja le travail, 26 fois plus vite.

    La regulation appartient au CORPS, pas au client : personne ne doit avoir a
    eteindre un service a la main pour faire de la place. Ce drain s'efface donc
    de lui-meme tant qu'une campagne cloud bat, et surtout NE RECLAME PAS
    l'embedder local pendant ce temps.

    Un battement PERIME (> CAMPAGNE_FRAICHE_S) ne retient rien : une campagne
    morte ne doit pas geler le drain pour toujours. Illisible = absent, mais on
    le DIT plutot que de le confondre avec « pas de campagne ».
    """
    try:
        d = json.loads(CAMPAGNE_BATTEMENT.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except Exception as exc:  # noqa: BLE001
        print("[campagne] battement ILLISIBLE (%s) -- drain poursuit"
              % type(exc).__name__, flush=True)
        return False
    if d.get("fini"):
        return False
    return (time.time() - float(d.get("ts") or 0)) < CAMPAGNE_FRAICHE_S


def run_pass() -> dict:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    try:
        # SELECTION INDEXABLE (mesure 2026-07-25 : 1,07 s -> 0,00 s sur 707 940 lignes).
        # Deux freins levés :
        #   1. le CASE inline recalculait l'origine PAR LIGNE et rejetait ainsi 138 000
        #      chunks FROIDS un par un, a CHAQUE passe -> `hot_tier_clause` lit la
        #      colonne GENERATED `origin`, strictement equivalente et indexee ;
        #   2. `ORDER BY rowid` forcait le parcours de la table et annulait l'index
        #      partiel `idx_emb_null_origin`. Il n'assurait PAS la progression : celle-ci
        #      vient de ce qu'un chunk embedde QUITTE le set `embedding IS NULL`, et
        #      qu'un chunk non-embeddable est mis en quarantaine (plus bas) donc en sort
        #      aussi. Sans lui, l'anti-stall reste entier.
        # C'est ce cout de selection, et non l'embedding (0,16 s/chunk), qui dominait :
        # ~3,5 min par passe de 512 contre 82 s de calcul reel.
        rows = conn.execute(
            f"SELECT id, text FROM rag_chunks WHERE embedding IS NULL "
            f"AND {hot_tier_clause(conn)} LIMIT ?",
            (BATCH_SIZE,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"embedded": 0, "errors": 0}

    ids = [r[0] for r in rows]
    texts = [r[1] or "" for r in rows]

    t0 = time.time()
    try:
        vecs = embed_batch_fast(texts)
    except Exception as e:
        print(f"[ERROR] batch embed failed: {e}", flush=True)
        return {"embedded": 0, "errors": len(rows)}

    if not vecs or len(vecs) != len(rows):
        print(f"[WARN] got {len(vecs)} vecs for {len(rows)} chunks")
        return {"embedded": 0, "errors": len(rows)}

    # AUTOCOMMIT OBLIGATOIRE ICI — mesure 2026-07-26.
    # `sqlite3.connect()` nu ouvre une transaction IMPLICITE au premier UPDATE et la
    # garde jusqu'au commit final. Or la boucle ci-dessous rappelle `embed_batch_fast`
    # (GPU, ~0,16 s/chunk, davantage sur un retry solo) POUR CHAQUE chunk en echec :
    # le verrou d'ecriture etait donc tenu pendant tous ces calculs. Consequence
    # mesuree ce jour : une veille voisine s'est vu refuser son ingestion apres 6
    # tentatives de write_retry — « un voisin tient une transaction trop longue » —
    # et 223 325 chars de matiere ont ete detruits. Ce n'etait PAS la veille qui etait
    # fautive (forge_watch_agent._get_conn utilise open_writer depuis le 25/07) : c'est
    # ce demon, qui draine en continu et tient le verrou en calculant.
    # Avec `open_writer` (isolation_level=None + WAL + busy_timeout), chaque UPDATE
    # valide seul et le verrou est RELACHE pendant les appels d'embedding.
    try:
        from nokido_agent.app.forge_db_path import open_writer

        conn2 = open_writer(timeout=30.0)
    except Exception:  # noqa: BLE001
        conn2 = sqlite3.connect(str(DB_PATH), timeout=30, isolation_level=None)
        conn2.execute("PRAGMA journal_mode=WAL")
        conn2.execute("PRAGMA busy_timeout=15000")
    embedded = errors = quarantined = 0
    _ph = None  # embedding placeholder (quarantaine), calcule a la demande
    try:
        for chunk_id, vec, ctext in tqdm(zip(ids, vecs, texts), total=len(ids), desc="saving", unit="chunk"):
            if not vec:
                # Microglie anti-stall : un batch peut echouer pour CE chunk a cause d'un
                # chunk poison qui contamine tout le batch. Retry SOLO tronque ; si toujours
                # vide -> quarantaine (sort du set NULL) pour que ORDER BY rowid AVANCE au
                # lieu de re-selectionner le meme poison a chaque passe (stall infini).
                rv = embed_batch_fast([(ctext or "")[:2000]])
                vec = rv[0] if rv and rv[0] else None
                if not vec:
                    if _ph is None:
                        _p = embed_batch_fast(["[chunk non-embeddable mis en quarantaine]"])
                        _ph = _p[0] if _p and _p[0] else None
                    if _ph:
                        conn2.execute(
                            "UPDATE rag_chunks SET embedding=?, domain='quarantine_unembeddable' WHERE id=?",
                            (_struct.pack("1024f", *_ph), chunk_id),
                        )
                        quarantined += 1
                    else:
                        errors += 1
                    continue
            cur = conn2.execute(
                "UPDATE rag_chunks SET embedding=? WHERE id=?",
                (_struct.pack("1024f", *vec), chunk_id),
            )
            if cur.rowcount == 1:
                embedded += 1
            else:
                # FAUX-VERT MESURE 2026-08-20 : 307 lignes portaient `id IS NULL`
                # (ingest vendor_cli du 31/07 sans id explicite, cf regle d'or #3).
                # `WHERE id = NULL` ne matche RIEN et ne leve RIEN -> `embedded`
                # comptait 307, le disque 0, et la passe suivante re-selectionnait
                # les memes lignes : boucle infinie ~1 passe/21 s, iGPU + SQLite
                # de 16,6 Go sollicites en permanence. Le rowcount est la SEULE
                # preuve d'application ; le compteur seul est un faux-vert.
                errors += 1
                print(f"[no-op] UPDATE 0 ligne pour id={chunk_id!r}", flush=True)
        conn2.commit()
    finally:
        conn2.close()

    elapsed = time.time() - t0
    return {
        "embedded": embedded,
        "errors": errors,
        "quarantined": quarantined,
        "avg_latency_s": round(elapsed / max(embedded, 1), 3),
    }


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Embed auto-trigger (daemon ou one-shot drain)")
    ap.add_argument(
        "--once", action="store_true", help="Drain hot-tier puis exit (vs daemon infini par défaut)"
    )
    ap.add_argument("--max-passes", type=int, default=0, help="Cap nombre de passes (0 = illimité)")
    args = ap.parse_args()

    # BRANCHER L'ECOUTEUR, pas seulement le declarer. Un garde pose sur un signal que
    # personne n'emet est une dette de cablage, jamais une securite (regle du corps,
    # payee deux fois le 2026-07-30) : sans ce raccordement, `_DERNIER_MOTIF_QUOTA`
    # resterait faux a vie et le drain marteler ait l'API a quota epuise.
    _ecoute = _EcouteQuota()
    logging.getLogger().addHandler(_ecoute)
    for _nom in ("forge_embed_router", "app.forge_embed_router"):
        logging.getLogger(_nom).addHandler(_ecoute)
    try:  # le logger du routeur peut porter un autre nom selon l'import
        from nokido_agent.app import forge_embed_router as _fer

        _fer.logger.addHandler(_ecoute)
    except Exception as _e:  # noqa: BLE001
        print(f"[embed_auto_trigger] ecouteur de quota non branche au routeur ({_e!r}) "
              f"-- le sommeil de quota ne se declenchera pas", flush=True)

    mode = "one-shot drain" if args.once else "daemon infini"
    print(
        f"[embed_auto_trigger] started ({mode}) — embed via forge_embed_router :8099, "
        f"poll {POLL_INTERVAL}s",
        flush=True,
    )
    total_embedded = total_errors = passes = 0
    # RESILIENCE AU VERROU (mesure 2026-08-20) : `run_pass()` n'etait protege que
    # contre KeyboardInterrupt. Une `sqlite3.OperationalError: database is locked`
    # — transitoire, due a l'unique writer SQLite sous charge concurrente —
    # remontait et TUAIT le daemon. Constate ce jour : drain mort 33 min, 241 862
    # chunks en attente, heartbeat fige a la derniere passe REUSSIE (donc rien ne
    # signalait la mort : le dernier battement disait « 512 embeddings, 0 erreur »).
    # Un daemon permanent doit survivre a une contention passagere : on retente
    # avec un recul croissant, borne, et on le DIT dans le heartbeat.
    _echecs = 0
    _en_pause = False
    try:
        while True:
            try:
                _ram = _ram_pct()
                # RAM illisible -> on ne draine PAS (une non-mesure n'est pas un feu vert),
                # mais on ne s'arrete pas non plus : on re-mesurera au prochain tour.
                if _ram < 0 or (_ram >= RAM_PAUSE) or (_en_pause and _ram > RAM_REPRISE):
                    _en_pause = _ram >= RAM_PAUSE or _ram < 0 or _en_pause
                    _motif = ("RAM illisible" if _ram < 0
                              else f"RAM {_ram:.1f} % >= {RAM_PAUSE:.0f} %" if _ram >= RAM_PAUSE
                              else f"RAM {_ram:.1f} % pas encore retombee sous {RAM_REPRISE:.0f} %")
                    _save_heartbeat({
                        "session_embedded": total_embedded, "session_errors": total_errors,
                        "last_pass": {"embedded": 0, "errors": 0, "abstention": _motif},
                        "passes": passes, "mode": mode, "ram_pct": _ram,
                    })
                    time.sleep(POLL_INTERVAL * 6)
                    continue
                if _en_pause:
                    print(f"[embed_auto_trigger] reprise : RAM {_ram:.1f} % <= "
                          f"{RAM_REPRISE:.0f} %", flush=True)
                    _en_pause = False
                if campagne_cloud_active():
                    # Le corps arbitre : une campagne cloud couvre deja cette file.
                    _save_heartbeat({
                        "session_embedded": total_embedded,
                        "session_errors": total_errors,
                        "last_pass": {"embedded": 0, "errors": 0,
                                      "abstention": "campagne cloud active"},
                        "passes": passes, "mode": mode,
                    })
                    time.sleep(POLL_INTERVAL * 4)
                    continue
                _DERNIER_MOTIF_QUOTA[0] = False
                stats = run_pass()
                _echecs = 0
                if _quota_epuise(stats):
                    _attente = _secondes_avant_reset_quota()
                    _save_heartbeat({
                        "session_embedded": total_embedded, "session_errors": total_errors,
                        "last_pass": {"embedded": 0, "errors": stats.get("errors", 0),
                                      "abstention": "quota cloud epuise -- reprise au "
                                                    "rechargement (00:00 UTC)"},
                        "passes": passes, "mode": mode,
                        "reprise_dans_s": round(_attente),
                    })
                    print(f"[embed_auto_trigger] quota cloud epuise -- sommeil "
                          f"{_attente / 3600:.1f} h jusqu'au rechargement", flush=True)
                    time.sleep(_attente)
                    continue
            except sqlite3.OperationalError as _e:
                # SEULE la contention est reprise. Voir le handler suivant.
                _echecs += 1
                _recul = min(60.0, 2.0 * _echecs)
                print("[pass %d] ECHEC (%s: %s) — reprise dans %.0fs (echec %d)"
                      % (passes + 1, type(_e).__name__, str(_e)[:90], _recul, _echecs),
                      flush=True)
                _save_heartbeat({
                    "session_embedded": total_embedded, "session_errors": total_errors,
                    "last_pass": {"embedded": 0, "errors": 0,
                                  "bloque": "%s: %s" % (type(_e).__name__, str(_e)[:80])},
                    "passes": passes, "mode": mode, "echecs_consecutifs": _echecs,
                })
                time.sleep(_recul)
                continue
            except Exception as _e:  # noqa: BLE001
                # TOUT LE RESTE EST UN DEFAUT, PAS UNE CONTENTION (2026-08-20).
                # Reprendre sur `Exception` transformait un NameError, un KeyError
                # ou une migration ratee en « on reessaie dans 2 s » : le daemon
                # restait vivant et cognitivement casse, avec un heartbeat qui
                # continuait de battre -- plus trompeur qu'un daemon mort. C'est
                # la meme faute que l'`except` large autour d'une mesure, qui
                # change un bug en verdict rassurant.
                # On ECRIT le motif, puis on meurt : la supervision relance, et si
                # le defaut persiste elle le verra persister au lieu de le lisser.
                _save_heartbeat({
                    "session_embedded": total_embedded, "session_errors": total_errors,
                    "last_pass": {"embedded": 0, "errors": 0,
                                  "FATAL": "%s: %s" % (type(_e).__name__, str(_e)[:120])},
                    "passes": passes, "mode": mode, "echecs_consecutifs": _echecs,
                })
                print("[pass %d] DEFAUT NON REPRIS (%s: %s) -- arret volontaire"
                      % (passes + 1, type(_e).__name__, str(_e)[:120]), flush=True)
                raise
            passes += 1
            total_embedded += stats["embedded"]
            total_errors += stats["errors"]
            _save_heartbeat(
                {
                    "session_embedded": total_embedded,
                    "session_errors": total_errors,
                    "last_pass": stats,
                    "passes": passes,
                    "mode": mode,
                }
            )
            if stats["embedded"] or stats["errors"]:
                print(
                    f"[pass {passes}] embedded={stats['embedded']} errors={stats['errors']} "
                    f"avg={stats.get('avg_latency_s', 0):.2f}s",
                    flush=True,
                )
            # Stop conditions
            if args.once and stats["embedded"] == 0 and stats["errors"] == 0:
                print(
                    f"[embed_auto_trigger] drained — total embedded: {total_embedded} "
                    f"errors: {total_errors} passes: {passes}",
                    flush=True,
                )
                return
            if args.max_passes and passes >= args.max_passes:
                print(
                    f"[embed_auto_trigger] max-passes reached — total embedded: {total_embedded}",
                    flush=True,
                )
                return
            # NE DORMIR QUE SI LA FILE EST VIDE (mesure 2026-08-20). Le sommeil
            # etait INCONDITIONNEL : 5 s apres CHAQUE passe, meme avec 241 000
            # chunks en attente. Sur une passe de ~35 s c'est ~12 % de debit
            # jete. Le poll a un sens quand il n'y a rien a faire — pas quand il
            # reste du travail. Mesure : embedder :8099 a 23 % CPU, donc le
            # goulot n'est pas lui mais la serialisation du drain.
            if stats["embedded"] or stats["errors"]:
                continue
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print(f"\n[embed_auto_trigger] stopped — total embedded: {total_embedded}")


if __name__ == "__main__":
    main()
