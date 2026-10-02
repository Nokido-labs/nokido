# -*- coding: utf-8 -*-
"""Campagne de vectorisation du backlog (tier CHAUD) via le CLOUD : Cloudflare Workers AI
`@cf/baai/bge-m3` (allocation gratuite quotidienne), puis l'endpoint Modal (BGE-M3, 1024D ; budget
mensuel) en relais -- le MEME modele (mesure 2026-10-01 : cos 0,9997-1,0000 avec les vecteurs
locaux deja en base). Texte MASQUE avant envoi (`masquer_pour_cloud`).

Idempotente et REPRENABLE : chaque lot re-interroge `embedding IS NULL`, donc un
arret (kill, restart, cap RSS) ne perd que le lot en cours. Relancer reprend ou
ca s'est arrete, sans etat externe a maintenir.

GARDE D'ECRITURE PRECOCE : le premier lot verifie qu'on peut REELLEMENT ecrire en
base et RELIT ce qu'il vient d'ecrire. Les jobs detaches tournent sous
`LaForgeSbxOffline` et se voient refuser certains chemins (mesure 2026-08-19 :
`Permission denied` sur le coffre). Sans ce garde, la campagne tournerait deux
heures pour ne rien persister — le faux-vert le plus cher possible.

PROGRESSION : `flush=True` partout et un heartbeat par lot. Un log bufferise
parait FIGE et fait conclure a tort qu'un job est mort (piege deja paye).

Intention (run_job ne passe aucun argument) : `sandbox/modal_campagne.wanted`
contenant le nombre de chunks vises (vide = tout le froid). Consommee a la lecture.

    run action=run_job script=tools/forge_embed_modal_campagne.py online=true
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT))

DIM = 1024
INTENTION = _ROOT / "sandbox" / "modal_campagne.wanted"
BATTEMENT = _ROOT / "sandbox" / "modal_campagne.heartbeat"


def _cible_par_intention() -> int | None:
    """Nombre vise depuis le fichier d'intention. None = pas d'intention."""
    try:
        if not INTENTION.is_file():
            return None
        brut = INTENTION.read_text(encoding="utf-8", errors="replace").strip()
        INTENTION.unlink()
        n = int("".join(c for c in brut if c.isdigit()) or 0)
        print("[intention] %s consommee -> cible=%s" % (INTENTION.name, n or "tout"), flush=True)
        return n or 0
    except Exception as e:  # noqa: BLE001 - intention illisible : on ne devine pas
        print("[intention] illisible (%s)" % type(e).__name__, flush=True)
        return None


def premier_qui_rend(textes, essais, dim, actif=None):
    """(vecteurs, nom, echecs) : le premier fournisseur qui rend len(textes) vecteurs de `dim`.

    FOURNISSEURS COMPATIBLES SEULEMENT (2026-10-01) : Modal et Cloudflare servent le MEME
    modele que le local (bge-m3, 1024D) -- mesure du 01/10 sur 5 chunks deja vectorises en
    local : cos(cloudflare, base) = 0,9997 a 1,0000, temoin croise 0,41. Jina / Voyage /
    OpenRouter servent d'AUTRES modeles : les meler a la colonne `embedding` rendrait les
    distances incomparables, ils ne figurent donc PAS ici. `actif` (le dernier qui a rendu)
    est essaye d'abord : on ne repaie pas la panne connue d'un fournisseur a chaque lot."""
    ordre = sorted(essais, key=lambda e: e[0] != actif)
    ko = []
    for nom, appel in ordre:
        try:
            vecs = appel(textes)
        except Exception as e:  # noqa: BLE001 - un fournisseur qui leve est un fournisseur KO, DIT
            ko.append("%s:%s" % (nom, type(e).__name__))
            continue
        if vecs and len(vecs) == len(textes) and all(v and len(v) == dim for v in vecs):
            return vecs, nom, ko
        ko.append("%s:%s" % (nom, "vide" if not vecs else "forme"))
    return None, None, ko


def _battre(**champs) -> None:
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il pose `ts` et le
    # `pid` qui manquait, et ne leve jamais — le battement ne peut pas tuer la
    # campagne, invariant conserve.
    from nokido_agent.app.forge_heartbeat import beat_daemon

    beat_daemon("modal_campagne", **champs)


def main() -> int:
    ap = argparse.ArgumentParser(description="Campagne Modal sur le backlog a vectoriser")
    ap.add_argument("--n", type=int, default=0, help="chunks a traiter (0 = tout)")
    ap.add_argument("--taille", type=int, default=64, help="chunks par appel Modal")
    # MESURE 2026-09-01 : viser le FROID ne peut RIEN ecrire. Le trigger SQLite
    # `forge_tier_guard` (BEFORE UPDATE OF embedding) annule silencieusement toute
    # pose de vecteur sur un chunk d'origine froide — c'est la politique « l'externe
    # reste FTS-only », posee apres 278 k chunks externes vectorises a tort. La garde
    # d'ecriture de ce script l'a prouve net : « 256 ecritures annoncees, 256 encore
    # NULL ». Le defaut passe donc au tier CHAUD, seul tier ou l'ecriture aboutit ;
    # `--tier froid` reste accessible pour le jour ou la politique changerait, mais
    # il echouera sur la garde tant que le trigger est en place. Le chemin pour
    # vectoriser de l'externe n'est pas de forcer ici : c'est
    # `forge_veille_triage_vectorisation`, qui PROMEUT la matiere de valeur vers un
    # domain que le trigger laisse passer.
    ap.add_argument("--tier", choices=("chaud", "froid", "tout"), default="chaud",
                    help="cible : chaud (defaut, seul tier ou le trigger laisse ecrire), "
                         "froid (refuse par forge_tier_guard), tout")
    args = ap.parse_args()

    cible = args.n
    if not cible:
        par_intention = _cible_par_intention()
        if par_intention is not None:
            cible = par_intention

    from nokido_agent.app.forge_db_path import checkpoint_wal, write_retry
    from nokido_agent.app.forge_embed_router import _cloudflare_call, _modal_call, _modal_url, encode_blob
    from nokido_agent.tools.forge_tier_policy import base_rag, hot_tier_clause

    # CLOUDFLARE D'ABORD, MODAL EN RELAIS (decision owner 2026-10-01). Les deux servent le meme
    # modele. Cloudflare Workers AI : allocation gratuite QUOTIDIENNE ; Modal : budget MENSUEL de
    # l'espace de travail (modal_docs guide/budgets : une fois le budget du cycle atteint, Modal
    # arrete ce qui facturerait -- c'etait le « workspace disabled » du 01/10, recharge le jour
    # meme au changement de cycle). On consomme le quotidien, on garde le mensuel en relais.
    essais = [("cloudflare", lambda t: _cloudflare_call(t, timeout=120.0))]
    if _modal_url():
        essais.append(("modal", lambda t: _modal_call(t, timeout=180.0)))
    else:
        print("LAFORGE_MODAL_EMBED_URL introuvable (coffre + env) -- Modal ecarte", flush=True)
    actif = None

    db = base_rag()
    ro = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=15.0)
    _hot = hot_tier_clause(ro)
    clause = {"chaud": _hot, "froid": "NOT (%s)" % _hot, "tout": "1=1"}[args.tier]
    total = ro.execute(
        "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL AND %s" % clause).fetchone()[0]
    ro.close()
    vise = min(cible, total) if cible else total
    print("base          : %s" % db, flush=True)
    print("tier vise     : %s" % args.tier, flush=True)
    print("backlog       : %d chunks" % total, flush=True)
    print("cible         : %d chunks (lots de %d)\n" % (vise, args.taille), flush=True)

    faits = echecs = 0
    t_debut = time.time()
    garde_faite = False

    while faits < vise:
        reste = vise - faits
        n_lot = min(args.taille, reste)
        ro = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=15.0)
        lignes = ro.execute(
            "SELECT id, text FROM rag_chunks WHERE embedding IS NULL AND %s LIMIT ?" % clause,
            (n_lot,)).fetchall()
        ro.close()
        if not lignes:
            print("plus rien a vectoriser", flush=True)
            break

        textes = [(r[1] or "")[:8000] for r in lignes]
        t0 = time.time()
        vecs, nom, ko = premier_qui_rend(textes, essais, DIM, actif)
        dt = time.time() - t0

        if not vecs:
            echecs += 1
            print("  lot SANS VECTEUR (%.1fs) echecs=%d -- %s" % (dt, echecs, ", ".join(ko)), flush=True)
            if echecs >= 5:
                print("5 echecs consecutifs sur TOUS les fournisseurs -- arret "
                      "(cause de chacun au journal ci-dessus)", flush=True)
                return 4
            time.sleep(3)
            continue
        if nom != actif:
            print("  fournisseur : %s%s" % (nom, (" (KO : %s)" % ", ".join(ko)) if ko else ""), flush=True)
            actif = nom
        echecs = 0

        # ECRITURE PAR `write_retry`, PAS par un `sqlite3.connect()` nu.
        # Mesure 2026-09-01 : la campagne est morte a 11 776/200 868 sur
        # `OperationalError: database is locked`. La connexion nue ouvre une
        # transaction IMPLICITE au premier UPDATE et la tient jusqu'au commit ;
        # un voisin qui ecrit en meme temps (le drain d'embeddings, le POST_COMMIT)
        # suffit alors a faire echouer le lot ENTIER. C'est le piege que
        # `forge_db_path` documente depuis le 2026-07-25, et un arret ici coute
        # double : le lot est perdu ET le GPU distant a deja ete paye pour lui.
        # `write_retry` reprend sur verrou avec recul et jitter, et ne rattrape
        # QUE les erreurs de verrou : une contrainte violee remonte tout de suite.
        def _ecrire(conn):
            n = 0
            for (cid, _t), vec in zip(lignes, vecs):
                if vec and len(vec) == DIM:
                    conn.execute("UPDATE rag_chunks SET embedding=? WHERE id=?",
                                 (encode_blob(vec), cid))
                    n += 1
            return n

        try:
            ecrits = write_retry(_ecrire)
        except Exception as e:  # noqa: BLE001
            print("ECRITURE REFUSEE apres reprises (%s: %s) -- arret immediat"
                  % (type(e).__name__, e), flush=True)
            return 5

        # Garde d'ecriture : RELIRE ce qu'on croit avoir ecrit (un commit sans
        # erreur ne prouve pas que la ligne a change : mauvais chemin de base,
        # transaction avalee, id absent...).
        if not garde_faite:
            garde_faite = True
            ctrl = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=15.0)
            restants = ctrl.execute(
                "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL AND id IN (%s)"
                % ",".join("?" * len(lignes)), [r[0] for r in lignes]).fetchone()[0]
            ctrl.close()
            if restants == len(lignes):
                print("GARDE : %d ecritures annoncees, %d encore NULL -- rien n'est "
                      "persiste, arret" % (ecrits, restants), flush=True)
                return 6
            print("  garde d'ecriture OK (%d/%d persistes)\n"
                  % (len(lignes) - restants, len(lignes)), flush=True)

        faits += ecrits
        deb = faits / max(1e-9, time.time() - t_debut)
        reste_s = (vise - faits) / max(1e-9, deb)
        print("  %6d/%d  %.1f chunks/s  lot %.1fs  ETA %.1f min"
              % (faits, vise, deb, dt, reste_s / 60), flush=True)
        _battre(faits=faits, vise=vise, debit=round(deb, 2), backlog_froid=total - faits)
        # Rendre la main au disque PENDANT la campagne. Sans cela le WAL ne
        # redescend jamais : le 2026-09-01, une journee d'ingestion l'a porte a
        # 53 Go et sature V: (0 octet libre), jusqu'a `disk I/O error` sur toute
        # ecriture RAG. Mesure sur cette campagne : 1,21 Go de WAL pour 9 728
        # chunks, soit ~25 Go projetes sur les 200 868. PASSIVE : `busy=1` est un
        # lecteur qu'on refuse de bloquer, pas un echec — on reessaiera au lot
        # suivant.
        if faits % 20000 < args.taille:
            _ck = checkpoint_wal()
            if _ck.get("fait"):
                print("  WAL %s -> %s Mo (busy=%s)"
                      % (_ck["wal_mo_avant"], _ck["wal_mo_apres"], _ck["busy"]), flush=True)

    duree = time.time() - t_debut
    print("\n=== FIN ===", flush=True)
    print("  vectorises : %d en %.1f min (%.1f chunks/s)"
          % (faits, duree / 60, faits / max(1e-9, duree)), flush=True)
    ro = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=15.0)
    reste = ro.execute(
        "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL AND %s" % clause).fetchone()[0]
    ro.close()
    print("  backlog restant (%s) : %d (etait %d)" % (args.tier, reste, total), flush=True)
    _battre(faits=faits, vise=vise, fini=True, backlog_froid=reste)
    return 0


if __name__ == "__main__":
    sys.exit(main())
