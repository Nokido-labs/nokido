#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_embed_8099_mesure_bornee.py - mesure BORNEE de l'embedder local :8099.

__FORGE_COLOR__ = "vegetatif/embedding : mesure bornee de la croissance RAM de :8099 sur un drain fini"

Question posee par l'owner le 2026-09-06 (« reparer l'embedding local ») : la RAM de
`NokidoLlamaEmbed` (llama.cpp, bge-m3-Q8_0, :8099) est-elle BORNEE quand il draine, ou
croit-elle sans limite (2,73 -> 6,07 Go mesures le 2026-08-05) ? Sans cette reponse, le
rouvrir dans la politique des piliers ramene la boucle wake/eviction du 2026-09-01.

Ce que fait ce script, en UN job detache (jamais une rafale d'appels hub) :
  1. preconditions dites, jamais devinees : RAM systeme < RAM_MAX_DEMARRAGE, :8099 libre
     ou deja servi (on ne relance pas un serveur qui repond) ;
  2. demarre :8099 par la voie GOUVERNEE (`forge_ensure_service.ensure`, superviseur) -
     le binaire vit dans le profil owner, illisible depuis les comptes sandbox ;
  3. draine un lot FINI de chunks sans vecteur (meme selection indexee que
     `forge_embed_auto_trigger.run_pass` : `embedding IS NULL AND hot_tier_clause`,
     plan verifie par EXPLAIN avant la premiere lecture), POST direct :8099
     `/v1/embeddings` (contrat de `_llama8099_call`, SANS la cascade cloud : une mesure
     locale ne doit pas basculer sur Voyage/Jina en silence) ;
  4. echantillonne toutes les PERIODE_S secondes : RSS de llama-server, RAM systeme,
     chunks ecrits - `progress.json` a chaque echantillon ;
  5. s'ARRETE avant que le corps ne souffre : RAM >= RAM_ARRET -> stop gouverne de
     :8099, verdict `ARRET_RAM` ; fin de lot -> stop gouverne, verdict sur la pente.

Ecriture des vecteurs : `open_writer` (autocommit, verrou relache entre les appels) +
UPDATE avec rowcount (le compteur seul est un faux-vert, mesure 2026-08-20). Un chunk
sans vecteur est COMPTE, pas mis en quarantaine : la mesure ne prend pas de decision.

Verdict :
  BORNE      rss_max - rss_apres_chargement < SEUIL_BORNE_GO et pente 2e moitie ~ 0
  CROISSANT  sinon (delta et pente imprimes)
  ARRET_RAM  garde declenchee (la question reste ouverte, on le dit)
  INDETERMINE :8099 injoignable / trop peu de chunks / loopback muet - la raison est nommee

Usage (run_job) :
  LAFORGE_PYTHON tools/forge_embed_8099_mesure_bornee.py [--chunks 2000] [--batch 32]
      [--ram-arret 88] [--periode 10] [--garder]   (--garder : ne pas eteindre :8099 a la fin)
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# La RACINE aussi (2026-09-25) : l'import namespace plus bas (`nokido_agent.tools...`) l'exige ;
# n'inserer que app/ et tools/ faisait mourir ce script en ModuleNotFoundError des qu'on le
# lancait par chemin (prouve sous miniforge3 et laforge_py314). NR : test_pypi_amorce_nr.
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

URL = "http://127.0.0.1:8099"
SERVICE = "NokidoLlamaEmbed"
RAM_MAX_DEMARRAGE = 82.0
SEUIL_BORNE_GO = 2.0
OUT = ROOT / "sandbox" / "embed_8099_mesure_bornee.json"


def _ram() -> float:
    import psutil
    return float(psutil.virtual_memory().percent)


def _pid_8099() -> int | None:
    """PID qui ecoute :8099 - psutil d'abord, netstat en repli (comptes sans droits)."""
    try:
        import psutil
        for c in psutil.net_connections(kind="tcp"):
            if c.laddr and c.laddr.port == 8099 and c.status == "LISTEN" and c.pid:
                return int(c.pid)
    except Exception as e:  # noqa: BLE001
        print(f"[pid] psutil.net_connections illisible: {e!r} -> netstat", flush=True)
    try:
        import subprocess
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             errors="replace", timeout=20).stdout
        for l in out.splitlines():
            if ":8099 " in l and "LISTEN" in l.upper():
                return int(l.split()[-1])
    except Exception as e:  # noqa: BLE001
        print(f"[pid] netstat illisible: {e!r}", flush=True)
    return None


def _rss_go(pid: int | None) -> float | None:
    if not pid:
        return None
    try:
        import psutil
        return round(psutil.Process(pid).memory_info().rss / 2**30, 3)
    except Exception as e:  # noqa: BLE001
        print(f"[rss] pid {pid} illisible: {e!r}", flush=True)
        return None


def _health(timeout: float = 5.0) -> str:
    """Trois etats : UP / DOWN (refus franc) / MUET (timeout = loopback peut-etre bloque)."""
    try:
        with urllib.request.urlopen(f"{URL}/health", timeout=timeout) as r:
            return "UP" if r.status == 200 else f"HTTP{r.status}"
    except urllib.error.URLError as e:
        if "timed out" in str(e).lower():
            return "MUET"
        return "DOWN"
    except TimeoutError:
        return "MUET"
    except Exception as e:  # noqa: BLE001
        return f"DOWN({type(e).__name__})"


def _embed(texts: list[str], timeout: float = 120.0) -> list[list[float]] | None:
    body = json.dumps({"input": texts, "model": "bge-m3"}).encode("utf-8")
    req = urllib.request.Request(f"{URL}/v1/embeddings", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = data.get("data") or []
    if len(items) != len(texts):
        print(f"[embed] {len(items)} vecteur(s) pour {len(texts)} texte(s) -> lot rejete", flush=True)
        return None
    items.sort(key=lambda x: x.get("index", 0))
    vecs = [x.get("embedding") for x in items]
    if any((not v) or len(v) != 1024 for v in vecs):
        print("[embed] dimension inattendue (attendu 1024) -> lot rejete", flush=True)
        return None
    return vecs


def _evince_recemment(fenetre_s: float = 180.0) -> str:
    """L'organe de regulation a-t-il repris :8099 dans les dernieres `fenetre_s` ?

    Lit le journal des actions de cycle de vie (`sandbox/lifecycle_actions.jsonl`), le
    seul endroit ou l'eviction est ECRITE avec son motif. Rend la raison, ou "" si rien
    n'est journalise -- et "" veut alors dire « pas de trace », jamais « pas d'eviction ».
    """
    p = ROOT / "sandbox" / "lifecycle_actions.jsonl"
    try:
        lignes = p.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
    except Exception as e:  # noqa: BLE001
        print(f"[eviction] journal illisible ({e!r}) -- cause indeterminee", flush=True)
        return ""
    import datetime as _dt

    limite = _dt.datetime.now(_dt.timezone.utc).timestamp() - fenetre_s
    for l in reversed(lignes):
        if "LlamaEmbed" not in l:
            continue
        try:
            o = json.loads(l)
            t = _dt.datetime.fromisoformat(str(o.get("ts", "")).replace("Z", "+00:00")).timestamp()
        except Exception:  # noqa: BLE001
            continue
        if t >= limite and "evict" in str(o.get("action", "")):
            return f"{o.get('action')} :: {str(o.get('reason'))[:180]}"
    return ""


def _ensure(etat: str) -> dict:
    from nokido_agent.tools.forge_ensure_service import ensure  # type: ignore
    res = ensure(SERVICE, etat)
    return res if isinstance(res, dict) else {"success": bool(res)}


from nokido_agent.tools.forge_embed_lot_commun import (  # noqa: E402  (apres l'amorce sys.path)
    candidats_sans_vecteur, ecrire_rapport, ouvrir_lecture,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", type=int, default=2000)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--ram-arret", type=float, default=88.0)
    ap.add_argument("--periode", type=float, default=10.0)
    ap.add_argument("--garder", action="store_true")
    ap.add_argument("--lots", type=int, default=1,
                    help="repeter le cycle demarrer/drainer/arreter N fois (recyclage : "
                         "la croissance residuelle du RSS repart de zero a chaque lot)")
    ap.add_argument("--attendre-min", type=float, default=0.0,
                    help="minutes d'attente d'une fenetre de RAM basse avant chaque lot "
                         "(0 = ne pas attendre). Le corps travaille quand il PEUT : en "
                         "journee la machine tourne a 76-82 %% (navigateur + flotte), la "
                         "fenetre s'ouvre la nuit.")
    a = ap.parse_args()
    if a.lots > 1:
        return _campagne(a)
    return _un_lot(a)


def _campagne(a) -> int:
    """N lots successifs, service RECYCLE entre chaque.

    Le plateau de RAM n'etant PAS prouve (0,21 a 0,47 Go / 1000 chunks mesures le
    2026-09-06), une campagne longue ne se fait pas en un seul drain : chaque lot
    repart d'un serveur neuf a 0,61 Go, et la RAM machine est rendue entre deux
    (87,6 % -> 78,7 % mesures au lot 1). Une charge passagere SUSPEND la campagne, elle
    ne l'abandonne pas : un lot arrete par la garde ne consomme pas son tour et repart
    des que la fenetre se rouvre. Seul un lot INEXPLOITABLE (INDETERMINE) arrete tout.
    """
    import copy

    total = 0
    faits = 0
    while faits < a.lots:
        sous = copy.copy(a)
        sous.lots = 1
        sous.garder = False
        if a.attendre_min > 0 and not _attendre_fenetre(a.attendre_min):
            print(f"[campagne] fenetre de RAM jamais ouverte en {a.attendre_min:.0f} min "
                  f"-- arret apres {total} chunk(s)", flush=True)
            return 0
        i = faits + 1
        print(f"\n===== LOT {i}/{a.lots} =====", flush=True)
        rc = _un_lot(sous)
        try:
            r = json.loads(OUT.read_text(encoding="utf-8"))
            total += int(r.get("ecrits") or 0)
            verdict = r.get("verdict")
        except Exception as e:  # noqa: BLE001
            print(f"[campagne] rapport du lot {i} illisible ({e!r}) -- arret", flush=True)
            return 2
        print(f"[campagne] lot {i}/{a.lots} : {verdict} | cumul ecrits = {total}", flush=True)
        if verdict in ("INDETERMINE",):
            print("[campagne] arret : un lot n'a pas pu mesurer (raison ci-dessus)", flush=True)
            return rc
        if verdict == "ARRET_RAM":
            # SUSPENDRE, PAS ABANDONNER (correctif 2026-09-06, apres avoir vu la campagne
            # s'arreter au lot 2 sur 40). Une garde de charge dit « pas maintenant », pas
            # « plus jamais » : avec une fenetre d'attente configuree, on retourne
            # attendre en tete de boucle ; sans elle, il n'y a rien a attendre, on sort.
            if a.attendre_min > 0:
                print("[campagne] machine chargee -- on suspend et on attend la fenetre "
                      "(le travail reprendra tout seul)", flush=True)
                continue
            print("[campagne] arret : la machine est chargee et aucune fenetre n'est "
                  "configuree (--attendre-min)", flush=True)
            return rc
        faits += 1
        time.sleep(10)  # laisser la RAM redescendre entre deux lots
    print(f"[campagne] TERMINEE : {total} chunk(s) vectorise(s) en {a.lots} lot(s)", flush=True)
    return 0


def _attendre_fenetre(minutes: float, seuil: float = RAM_MAX_DEMARRAGE - 2.0,
                      periode: float = 60.0) -> bool:
    """Attend que la RAM machine descende sous `seuil`. Rend True si la fenetre s'ouvre.

    Une RAM ILLISIBLE n'ouvre jamais la fenetre (abstention, jamais feu vert). L'attente
    est DITE au fil de l'eau, sinon un job silencieux de plusieurs heures ne se distingue
    pas d'un job mort.
    """
    fin = time.time() + minutes * 60.0
    dernier_dit = 0.0
    while time.time() < fin:
        r = _ram()
        if 0 <= r <= seuil:
            print(f"[fenetre] RAM {r:.1f} % <= {seuil:.0f} % -- on travaille", flush=True)
            return True
        if time.time() - dernier_dit > 600:
            dernier_dit = time.time()
            reste = (fin - time.time()) / 60.0
            print(f"[fenetre] RAM {r:.1f} % (attendu <= {seuil:.0f} %) -- "
                  f"encore {reste:.0f} min d'attente", flush=True)
        time.sleep(periode)
    return False


def _un_lot(a) -> int:

    rapport: dict = {"debut": time.strftime("%Y-%m-%dT%H:%M:%S"), "chunks_demandes": a.chunks,
                     "batch": a.batch, "ram_arret": a.ram_arret, "echantillons": []}

    def _fin(verdict: str, raison: str = "", rc: int = 0) -> int:
        ecrire_rapport(OUT, rapport, verdict, raison, sans=("echantillons",))
        return rc

    ram0 = _ram()
    rapport["ram_debut_pct"] = ram0
    if ram0 >= RAM_MAX_DEMARRAGE:
        return _fin("INDETERMINE", f"RAM {ram0:.1f} % >= {RAM_MAX_DEMARRAGE} % au depart, on ne charge pas", 2)

    # --- :8099 : deja la, ou a demarrer par la voie gouvernee ---
    h = _health()
    rapport["health_initial"] = h
    demarre_ici = False
    if h == "MUET":
        return _fin("INDETERMINE", "loopback :8099 MUET (timeout) depuis ce compte - pas un serveur mort, un canal non prouve", 2)
    if h != "UP":
        # Intention declaree AVANT le reveil : le reclaimer (forge_resource_manager) lit
        # `sandbox/embed.wanted` et epargne :8099 tant qu'elle est fraiche ; sans elle,
        # un embedder reveille par un job est evince comme un orphelin (73 arrets de
        # llama :8091 en 7,6 j pour cette seule raison, 2026-07-30).
        try:
            from nokido_agent.app.forge_embed_router import declare_embed_wanted  # type: ignore
            rapport["embed_wanted_pose"] = bool(declare_embed_wanted(cooldown=0.0))
        except Exception as e:  # noqa: BLE001
            rapport["embed_wanted_pose"] = f"ECHEC {e!r}"
        print(f"[intention] embed.wanted={rapport['embed_wanted_pose']}", flush=True)
        res = _ensure("running")
        rapport["ensure_running"] = res
        demarre_ici = True
        t0 = time.time()
        while time.time() - t0 < 180:
            h = _health()
            if h == "UP":
                break
            time.sleep(3)
        rapport["chargement_s"] = round(time.time() - t0, 1)
        if h != "UP":
            return _fin("INDETERMINE", f":8099 ne repond pas apres 180 s (etat {h}) ; ensure={res}", 2)
    pid = _pid_8099()
    rss_charge = _rss_go(pid)
    rapport.update({"pid": pid, "rss_apres_chargement_go": rss_charge, "ram_apres_chargement_pct": _ram()})
    print(f"[8099] up pid={pid} rss={rss_charge} Go ram={rapport['ram_apres_chargement_pct']} %", flush=True)

    # --- candidats + ecrivain ---
    from nokido_agent.app.forge_db_path import open_writer  # type: ignore
    ro = ouvrir_lecture()
    try:
        rows = candidats_sans_vecteur(ro, a.chunks, dire=lambda m: print(m, flush=True))
    finally:
        ro.close()
    rapport["candidats"] = len(rows)
    if len(rows) < max(64, a.batch):
        if demarre_ici and not a.garder:
            rapport["ensure_stopped"] = _ensure("stopped")
        return _fin("INDETERMINE", f"seulement {len(rows)} chunk(s) candidat(s) - trop peu pour une pente", 2)

    conn = open_writer(timeout=30.0)
    ecrits = echecs = 0
    rss_max = rss_charge or 0.0
    t_debut = time.time()
    t_ech = 0.0
    verdict_garde = None
    try:
        for i in range(0, len(rows), a.batch):
            lot = rows[i:i + a.batch]
            try:
                vecs = _embed([(r[1] or "")[:4000] for r in lot])
            except Exception as e:  # noqa: BLE001
                print(f"[embed] lot {i // a.batch} ECHOUE: {e!r}", flush=True)
                vecs = None
            if not vecs:
                echecs += len(lot)
                h = _health()
                if h != "UP":
                    rapport["health_pendant"] = h
                    ev = _evince_recemment()
                    if ev:
                        # L'organe de regulation a repris la RAM : c'est une DECISION du
                        # corps, pas une panne. La campagne doit suspendre, pas conclure.
                        rapport["eviction"] = ev
                        verdict_garde = f"EVINCE par la regulation apres {ecrits} chunks :: {ev}"
                    else:
                        verdict_garde = (f":8099 ne repond plus ({h}) apres {ecrits} chunks "
                                         f"- aucune eviction journalisee, cause INCONNUE")
                    break
            else:
                for (cid, _), v in zip(lot, vecs):
                    cur = conn.execute("UPDATE rag_chunks SET embedding=? WHERE id=? AND embedding IS NULL",
                                       (struct.pack("1024f", *v), cid))
                    if cur.rowcount == 1:
                        ecrits += 1
                    else:
                        echecs += 1
            # GARDE A CHAQUE LOT, PAS A LA PERIODE D'ECHANTILLONNAGE (correctif
            # 2026-09-06). Avec un controle toutes les 30 s, la RAM est passee de 84 %
            # a 0,76 Go libres entre deux mesures et le resource manager a evince
            # l'embedder en urgence vitale : la garde etait juste, sa CADENCE ne l'etait
            # pas. Lire la RAM coute ~0,1 ms, un lot en coute 500 : rien ne justifie
            # de l'espacer.
            ram_lot = _ram()
            if ram_lot < 0 or ram_lot >= a.ram_arret:
                verdict_garde = (f"RAM illisible apres {ecrits} chunks" if ram_lot < 0 else
                                 f"RAM {ram_lot:.1f} % >= {a.ram_arret} % apres {ecrits} chunks")
                rapport["echantillons"].append({"t_s": round(time.time() - t_debut, 1),
                                                "ecrits": ecrits, "echecs": echecs,
                                                "rss_go": _rss_go(pid), "ram_pct": ram_lot})
                break
            now = time.time()
            if now - t_ech >= a.periode:
                t_ech = now
                rss = _rss_go(pid)
                ram = _ram()
                if rss is not None:
                    rss_max = max(rss_max, rss)
                ech = {"t_s": round(now - t_debut, 1), "ecrits": ecrits, "echecs": echecs,
                       "rss_go": rss, "ram_pct": ram}
                rapport["echantillons"].append(ech)
                print(f"[ech] {ech}", flush=True)
                try:
                    (OUT.parent / "embed_8099_mesure_bornee.progress.json").write_text(
                        json.dumps(ech), encoding="utf-8")
                except Exception:  # noqa: BLE001
                    pass  # muet-ok : le progres est aussi sur stdout
                if ram >= a.ram_arret:
                    verdict_garde = f"RAM {ram:.1f} % >= {a.ram_arret} % apres {ecrits} chunks"
                    break
    finally:
        conn.close()

    duree = time.time() - t_debut
    rss_fin = _rss_go(pid)
    rapport.update({"ecrits": ecrits, "echecs": echecs, "duree_s": round(duree, 1),
                    "s_par_chunk": round(duree / max(ecrits, 1), 4),
                    "rss_fin_go": rss_fin, "rss_max_go": rss_max,
                    "ram_fin_pct": _ram()})
    if demarre_ici and not a.garder:
        rapport["ensure_stopped"] = _ensure("stopped")
        time.sleep(5)
        rapport["ram_apres_arret_pct"] = _ram()

    if verdict_garde:
        # Trois familles, trois verdicts : la CHARGE et l'EVICTION se suspendent (le corps
        # a decide, on attend son tour) ; l'inconnu s'instruit (on ne relance pas dans le
        # noir). Confondre les trois, c'est soit forcer, soit abandonner a tort.
        if verdict_garde.startswith("EVINCE"):
            v = "ARRET_RAM"
        elif verdict_garde.startswith(":8099"):
            v = "INDETERMINE"
        else:
            v = "ARRET_RAM"
        return _fin(v, verdict_garde, 1)
    ech = [e for e in rapport["echantillons"] if e.get("rss_go") is not None]
    if rss_charge is None or len(ech) < 4:
        return _fin("INDETERMINE", f"RSS illisible ou {len(ech)} echantillon(s) seulement", 2)
    moitie = ech[len(ech) // 2:]
    pente_go_par_1000 = 0.0
    if moitie[-1]["ecrits"] > moitie[0]["ecrits"]:
        pente_go_par_1000 = (moitie[-1]["rss_go"] - moitie[0]["rss_go"]) / (moitie[-1]["ecrits"] - moitie[0]["ecrits"]) * 1000
    delta = rss_max - rss_charge
    rapport["delta_rss_go"] = round(delta, 3)
    rapport["pente_2e_moitie_go_par_1000_chunks"] = round(pente_go_par_1000, 4)
    if delta < SEUIL_BORNE_GO and abs(pente_go_par_1000) < 0.15:
        return _fin("BORNE", f"delta {delta:.2f} Go < {SEUIL_BORNE_GO} Go, pente {pente_go_par_1000:.3f} Go/1000 chunks")
    return _fin("CROISSANT", f"delta {delta:.2f} Go, pente {pente_go_par_1000:.3f} Go/1000 chunks", 1)


if __name__ == "__main__":
    raise SystemExit(main())
