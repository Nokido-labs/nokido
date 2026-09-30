# -*- coding: utf-8 -*-
"""forge_handoff_worker.py — worker AUTONOME de dispatch multi-agents (py314t).

POURQUOI CE MODULE (mesures 2026-08-30)
---------------------------------------
`forge_handoff` est le SEUL des neuf candidats de `forge_py314t_readiness` qui
survive aux trois conditions : son code threade reellement (`ThreadPoolExecutor`
+ `threading`), il s'importe sous py314t, et il n'a aucune dependance lourde
absente de cet environnement. Le bench du jour donne x4,53 a 8 threads sur de la
charge CPU-Python en free-threaded, la ou le meme code sous GIL REGRESSE (x0,92).

Mais il n'etait lance par AUCUN des 87 services : importe par un seul module, il
tournait dans le processus appelant — donc sous l'interpreteur du hub, avec GIL.
Le gain etait inatteignable non par manque de capacite, mais faute d'une frontiere
de processus. Ce worker EST cette frontiere.

CE QU'IL N'EST PAS
------------------
Pas un serveur HTTP de plus. Il depile une file et rend ses resultats la ou le hub
les lit deja. Pas non plus un ordonnanceur : c'est `forge_resource_manager` qui
decide s'il a le droit de travailler, et a combien de threads.

BACKPRESSURE
------------
La file interne est une `BoundedQueue` (`app/forge_bounded_queue.py`) — un organe
qui existait depuis des mois SANS aucun importeur, signale tel quel par la roadmap.
Le cabler ici lui donne son premier consommateur : saturation => relache de leptine,
donc un signal que la regulation voit, au lieu d'une file qui gonfle en silence.

Usage :
    ${PY314T} tools/forge_handoff_worker.py --once
    ${PY314T} tools/forge_handoff_worker.py --daemon
    ${PY314T} tools/forge_handoff_worker.py --etat
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path  # noqa: F401 — utilise par les chemins d'etat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HEARTBEAT = ROOT / "sandbox" / "handoff_worker.heartbeat"
ETAT = ROOT / "sandbox" / "handoff_worker_state.json"

# Bornes du pool. Le plafond n'est pas une preference : au-dela du nombre de coeurs
# le dispatch coute plus qu'il ne rend, ce que le bench du jour montre deja sur des
# taches courtes (x0,26 a 8 fils sur ~6 us de travail par item).
POOL_MIN = 1
POOL_MAX = 8
# Sous ce seuil de RAM libre, on ne demarre RIEN. Meme reserve que le lane
# d'admission, qui refusait un job a 3,7 Go dispo le 2026-08-30.
RAM_MIN_GB = 4.0


def _ram_libre_gb() -> float | None:
    """RAM libre en Go, ou None si la mesure est ILLISIBLE (jamais 0.0 par defaut)."""
    etat = ROOT / "sandbox" / "resource_state.json"
    try:
        d = json.loads(etat.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = d.get("ram_free_gb")
    return float(v) if isinstance(v, (int, float)) else None


def taille_pool(ram_libre_gb: float | None, cpu_count: int | None = None) -> int:
    """Combien de threads le worker s'autorise, d'apres la RAM libre.

    Rend 0 quand il ne doit pas travailler du tout. Une RAM ILLISIBLE rend 0 elle
    aussi : on ne parallelise pas sur une mesure qu'on n'a pas pu prendre — c'est
    la difference entre « il reste de la place » et « je ne sais pas ».
    """
    if ram_libre_gb is None or ram_libre_gb < RAM_MIN_GB:
        return 0
    coeurs = cpu_count if cpu_count is not None else (os.cpu_count() or 2)
    # Un thread par Go au-dela de la reserve, borne par les coeurs et par POOL_MAX.
    par_ram = int(ram_libre_gb - RAM_MIN_GB) + 1
    return max(POOL_MIN, min(POOL_MAX, coeurs, par_ram))


def free_threading_actif() -> dict:
    """Le worker tourne-t-il VRAIMENT sans GIL ? Mesure, pas supposition.

    Un worker py314t lance par erreur sous l'interpreteur du hub travaillerait
    avec GIL sans que rien ne le dise — le faux vert habituel. On le DECLARE au
    demarrage et on l'ecrit dans l'etat.
    """
    try:
        gil = sys._is_gil_enabled()  # noqa: SLF001
    except AttributeError:
        return {"free_threading": False, "motif": "build classique (pas de _is_gil_enabled)"}
    return {"free_threading": not gil,
            "motif": "GIL actif malgre un build free-threaded" if gil else "GIL desactive"}


# Identite postale du worker. `forge_postal` est la SOURCE DE VERITE du travail :
# queued -> delivered -> claimed -> acked, avec dedup sur (sender, recipient, body)
# et une exclusion mutuelle ATOMIQUE dans `claim()`. On ne cree donc ni file, ni
# base, ni socket : le quatrieme transport n'existera pas.
CANAL = "HANDOFF_WORKER"

# Le postal VALIDE le protocole M2M a l'entree (`forge_m2m_protocol.check`), et pour
# un courrier postal il exige `intent`, `pointer_ref` et `confidence`. Le worker parle
# donc le protocole du systeme au lieu d'inventer ses champs : `pointer_ref` EST le
# renvoi vers la charge utile durable, ce qui evite de recopier de gros prompts dans
# les courriers — la RAM que ce worker est cense respecter.
CHAMPS_REQUIS = ("intent", "pointer_ref", "job_id")
INTENT_ATTENDU = "HANDOFF_NEXT"     # dictionnaire routing de config/m2m_intents.json

# Au-dela de ce remplissage du tampon local, on cesse de RECLAMER du courrier plutot
# que de le reclamer puis de decouvrir qu'on n'a pas la capacite : un travail claime
# et non traite est un travail que personne d'autre ne prendra.
SEUIL_ARRET_CLAIM = 0.80


def _file(capacite: int = 256):
    """Tampon LOCAL de capacite instantanee — PAS la file de verite.

    La verite est dans `postal.db` (durable, reclamable, reprenable). Cette
    `BoundedQueue` ne sert qu'a mesurer la pression du moment et a relacher de la
    leptine a saturation : elle etait jusqu'ici un organe sans aucun importeur.
    """
    from nokido_agent.app.forge_bounded_queue import BoundedQueue  # noqa: PLC0415

    return BoundedQueue(name="handoff_worker", capacity=capacite)


def valider_enveloppe(body) -> tuple[bool, str]:
    """Une enveloppe incomplete est REFUSEE en le disant, jamais traitee a moitie.

    `body` arrive du postal comme une CHAINE (colonne SQL), pas comme un dict :
    ma premiere version passait un dict a `post()` et sqlite refusait le parametre.
    On accepte les deux et on decode, plutot que de supposer la forme.
    """
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError as exc:
            return False, "corps non-JSON (%s)" % str(exc)[:60]
    if not isinstance(body, dict):
        return False, "corps de courrier inattendu (%s)" % type(body).__name__
    intent = body.get("intent") or body.get("intent_code")
    if intent != INTENT_ATTENDU:
        return False, "intent %r, attendu %r" % (intent, INTENT_ATTENDU)
    manquants = [c for c in CHAMPS_REQUIS if not (body.get(c) or body.get("intent_code"))]
    if manquants:
        return False, "champs requis absents : %s" % ", ".join(manquants)
    return True, "ok"


def depiler_postal(pool: int, limite: int = 32) -> dict:
    """Releve le courrier, en RECLAME ce qu'on peut traiter, rend un compte-rendu.

    Trois refus possibles, chacun NOMME : pool nul (ressources), tampon sature
    (backpressure), enveloppe invalide. Un courrier reclame par un autre worker
    n'est pas une erreur : `claim` est atomique, un seul gagne, et le perdant
    passe au suivant.
    """
    if pool <= 0:
        return {"claimes": 0, "saute": True, "motif": "pool nul (ressources insuffisantes)"}
    try:
        from nokido_agent.app.forge_postal import ack_mail, claim, secretaire  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"claimes": 0, "saute": True,
                "motif": "postal indisponible (%s)" % type(exc).__name__}

    tampon = _file()
    courriers = secretaire(CANAL, ack=False) or []
    claimes = refuses = perdus = 0
    for mail in courriers[:limite]:
        if tampon.fill_pct() >= SEUIL_ARRET_CLAIM * 100:
            break                       # backpressure AVANT de reclamer, pas apres
        mid = mail.get("id") if isinstance(mail, dict) else None
        if not mid:
            continue
        if not claim(CANAL, mid):
            perdus += 1                 # un autre worker l'a pris : normal
            continue
        corps = mail.get("body") if isinstance(mail, dict) else None
        ok, motif = valider_enveloppe(corps)
        if not ok:
            refuses += 1
            print("[handoff_worker] courrier %s REFUSE : %s" % (mid, motif))
            ack_mail(mid, CANAL)        # on solde : ne pas le relever en boucle
            continue
        tampon.try_put(corps)
        claimes += 1
    return {"claimes": claimes, "refuses": refuses, "perdus_par_concurrence": perdus,
            "releves": len(courriers), "saute": False, "fill_pct": tampon.fill_pct()}


def _heartbeat(extra: dict | None = None) -> None:
    charge = {"ts": time.time(), "pid": os.getpid()}
    charge.update(extra or {})
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(json.dumps(charge), encoding="utf-8")
    except OSError as exc:
        print("[handoff_worker] heartbeat non ecrit : %s" % type(exc).__name__)


def etat_courant() -> dict:
    ram = _ram_libre_gb()
    ft = free_threading_actif()
    return {
        "interpreteur": sys.version.split()[0],
        "ram_libre_gb": ram,
        "pool": taille_pool(ram),
        "raison_pool_nul": ("RAM illisible" if ram is None else
                            ("RAM sous la reserve de %.1f Go" % RAM_MIN_GB
                             if ram < RAM_MIN_GB else None)),
        **ft,
    }


def un_cycle(pool: int) -> dict:
    """Un tour : postal -> claim -> tampon local. Jamais d'exception nue.

    RESERVE HONNETE : l'ingress est branche, l'EXECUTION du dispatch ne l'est pas.
    Executer demande de resoudre `payload_ref` dans le store durable et d'appeler
    `run_workflow_parallel` ; tant que ce n'est pas fait, ce cycle reclame et solde
    le courrier sans produire de resultat. Le compte-rendu porte `execute: 0` pour
    que personne ne lise ce worker comme s'il travaillait deja.
    """
    cr = depiler_postal(pool)
    cr["execute"] = 0
    if not cr.get("saute"):
        cr["reserve"] = "ingress postal cable ; execution du dispatch NON cablee"
    return cr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="un seul cycle")
    ap.add_argument("--daemon", action="store_true", help="boucle continue")
    ap.add_argument("--etat", action="store_true", help="imprime l'etat et sort")
    ap.add_argument("--intervalle", type=float, default=5.0)
    a = ap.parse_args(argv)

    e = etat_courant()
    if a.etat:
        print(json.dumps(e, indent=2, ensure_ascii=False))
        return 0

    print("[handoff_worker] python %s | %s | pool=%d | ram_libre=%s Go"
          % (e["interpreteur"], e["motif"], e["pool"], e["ram_libre_gb"]))
    if not e["free_threading"]:
        # Pas une erreur : un repli DECLARE. Le worker fonctionne, sans le gain.
        print("[handoff_worker] AVERTISSEMENT : pas de free-threading ici — "
              "le dispatch marchera, sans le gain mesure x4,53. "
              "Lancer avec ${PY314T} pour l'obtenir.")

    if a.once or not a.daemon:
        cr = un_cycle(e["pool"])
        _heartbeat({"dernier_cycle": cr})
        print(json.dumps(cr, ensure_ascii=False))
        return 0

    while True:
        e = etat_courant()
        cr = un_cycle(e["pool"])
        _heartbeat({"dernier_cycle": cr, "pool": e["pool"]})
        try:
            ETAT.write_text(json.dumps({**e, "dernier_cycle": cr}, ensure_ascii=False),
                            encoding="utf-8")
        except OSError:
            pass  # muet-ok : l'etat est un confort, le heartbeat est la preuve
        time.sleep(a.intervalle)


if __name__ == "__main__":
    sys.exit(main())
