# -*- coding: utf-8 -*-
"""Sonde PASSIVE de latence du chemin chaud : elle mesure, elle ne regule RIEN.

Attente en file et duree de dispatch par type d'evenement (EventStream), inter-arrivee par
source, profondeur de file, debit par (agent, outil) au point de rate-limit du ByteRouter.
Sert a FIXER sur mesure les constantes de la couche reflexe (roadmap P2 « priorite Hamilton,
deux boucles ») : aucun tau ne se pose avant une baseline ET un flood reels.

Origine : capsule claude.ai `pair_21b7736c9eb475c5` (13/10), corrigee avant integration --
- `_inflight` etait NON borne : un evenement publie jamais consomme (le corps en jette :
  hormones en `put_nowait` sur file pleine) fuyait a vie. Plafonne, evictions DITES.
- l'auto-test « user_msg p99 2,2 us sous flood » publiait puis depilait aussitot : vrai par
  construction. Remplace par un NR sur une vraie file asyncio (tests/nr/test_sonde_hotpath_nr.py).
- `_suggest_tau` derivait le refractaire de la source la plus bavarde -- circulaire (c'est
  elle qu'on freine). Retire : le rapport ne rend que des percentiles.

Interrupteur GLOBAL (partage entre processus) : presence de `sandbox/hotpath_probe.on`, relu au
plus toutes les 5 s. Eteinte, un point d'appel coute une lecture d'horloge, aucune I/O. Le
rapport (`sandbox/hotpath_probe_rapport.json`) s'ecrit a l'extinction et toutes les 5 min
pendant la fenetre -- seules ecritures, hors de chaque evenement.

    LAFORGE_PYTHON app/forge_hotpath_probe.py --allumer | --eteindre | --rapport
"""
from __future__ import annotations

__FORGE_COLOR__ = "Observabilite/Trace : sonde passive de latence du chemin chaud (attente en file, dispatch, debit par outil)"

import argparse
import json
import logging
import time
from collections import OrderedDict, defaultdict, deque
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
INTERRUPTEUR = ROOT / "sandbox" / "hotpath_probe.on"
RAPPORT = ROOT / "sandbox" / "hotpath_probe_rapport.json"
RELIRE_S = 5.0
DUMP_S = 300.0
_NS = time.perf_counter_ns


def _pct(vals, q: float) -> float:
    if not vals:
        return 0.0
    return vals[min(len(vals) - 1, int(q * (len(vals) - 1) + 0.5))]


def _resume_us(buf) -> dict:
    s = sorted(buf)
    return {"n": len(s), "p50_us": round(_pct(s, 0.50) / 1000, 1), "p95_us": round(_pct(s, 0.95) / 1000, 1),
            "p99_us": round(_pct(s, 0.99) / 1000, 1), "max_us": round((s[-1] if s else 0) / 1000, 1)}


class HotPathProbe:
    """Collecte O(1) par evenement ; toute memoire est BORNEE et ce qui deborde est COMPTE."""

    def __init__(self, cap: int = 20000, cap_inflight: int = 50000) -> None:
        self._cap = cap
        self._cap_inflight = cap_inflight
        self.reset()

    def reset(self) -> None:
        cap = self._cap
        self._inflight: "OrderedDict[int, tuple]" = OrderedDict()
        self.inflight_evincees = 0
        self._attente = defaultdict(lambda: deque(maxlen=cap))
        self._dispatch = defaultdict(lambda: deque(maxlen=cap))
        self._dernier_pub: dict = {}
        self._inter = defaultdict(lambda: deque(maxlen=cap))
        self._profondeur = deque(maxlen=cap)
        self._appels = defaultdict(int)
        self._pool_file = deque(maxlen=cap)
        self._pool_occupes = deque(maxlen=cap)
        self._pool_max = None
        self._pool_illisible = 0
        self._pool_absent = 0
        self._t0 = _NS()

    # -- points d'appel du chemin chaud (O(1), aucune I/O) --------------------------
    def on_publish(self, source: str, kind: str, seq: int) -> None:
        now = _NS()
        if len(self._inflight) >= self._cap_inflight:
            self._inflight.popitem(last=False)
            self.inflight_evincees += 1
        self._inflight[seq] = (now, kind)
        dernier = self._dernier_pub.get(source)
        if dernier is not None:
            self._inter[source].append(now - dernier)
        self._dernier_pub[source] = now

    def on_dequeue(self, kind: str, seq: int, qsize: int) -> None:
        now = _NS()
        self._profondeur.append(qsize)
        pub = self._inflight.pop(seq, None)
        if pub is not None:
            self._attente[kind].append(now - pub[0])

    @staticmethod
    def dispatch_start() -> int:
        return _NS()

    def dispatch_end(self, kind: str, t_debut: int) -> None:
        self._dispatch[kind].append(_NS() - t_debut)

    def on_tool_call(self, agent: str, tool: str) -> None:
        self._appels[(agent, tool)] += 1
        self.echantillonner_pool()

    def echantillonner_pool(self) -> None:
        """La file REELLE du hub : l'executeur par defaut d'asyncio, ou partent les `to_thread` (2026-10-13 : le bus
        d'evenements instrumente d'abord n'est pas le chemin des requetes -- 0 evenement en 5 min). Lecture
        d'attributs, aucun verrou, aucune attente. Ce qui est illisible est COMPTE, jamais lu comme 0."""
        try:
            import asyncio

            ex = asyncio.get_running_loop()._default_executor
        except (RuntimeError, AttributeError):
            self._pool_illisible += 1
            return
        if ex is None:
            self._pool_absent += 1  # aucun to_thread depuis le demarrage de la boucle : pas de file, et c'est dit
            return
        try:
            occupes = len(ex._threads) - ex._idle_semaphore._value
            self._pool_file.append(ex._work_queue.qsize())
            self._pool_occupes.append(max(0, occupes))
            self._pool_max = ex._max_workers
        except AttributeError:
            self._pool_illisible += 1

    # -- restitution (hors chemin chaud) ------------------------------------------------
    def rapport(self) -> dict:
        prof = sorted(self._profondeur)
        return {
            "fenetre_s": round((_NS() - self._t0) / 1e9, 1),
            "attente_file_par_kind": {k: _resume_us(v) for k, v in self._attente.items()},
            "dispatch_par_kind": {k: _resume_us(v) for k, v in self._dispatch.items()},
            "inter_arrivee_par_source": {s: _resume_us(v) for s, v in self._inter.items()},
            "profondeur_file": {"n": len(prof), "max": prof[-1] if prof else 0,
                                "p95": _pct(prof, 0.95) if prof else 0},
            "appels_par_agent_outil": {"%s:%s" % k: n for k, n in self._appels.items()},
            # File reelle : travaux en attente d'un thread du pool to_thread, et threads occupes, a chaque appel.
            "pool_to_thread": {
                "echantillons": len(self._pool_file),
                "file_max": max(self._pool_file) if self._pool_file else 0,
                "file_p95": _pct(sorted(self._pool_file), 0.95) if self._pool_file else 0,
                "occupes_max": max(self._pool_occupes) if self._pool_occupes else 0,
                "occupes_p95": _pct(sorted(self._pool_occupes), 0.95) if self._pool_occupes else 0,
                "max_workers": self._pool_max,
                "illisible": self._pool_illisible,
                "absent": self._pool_absent,
            },
            # Ce que la mesure n'a PAS vu se dit : publies jamais depiles, et evinces du suivi.
            "inflight_en_cours": len(self._inflight),
            "inflight_evincees": self.inflight_evincees,
        }


PROBE = HotPathProbe()
_etat = {"actif": False, "lu_a": float("-inf"), "dump_a": 0.0}


def _ecrire_rapport() -> None:
    try:
        tmp = RAPPORT.with_suffix(".partiel")
        tmp.write_text(json.dumps(PROBE.rapport(), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(RAPPORT)
    except OSError as e:
        logger.warning("[hotpath] rapport NON ecrit (%s: %s)", type(e).__name__, e)


def sonde_active():
    """PROBE si l'interrupteur est pose, sinon None (le point d'appel ne fait alors rien)."""
    t = time.monotonic()
    if t - _etat["lu_a"] >= RELIRE_S:
        _etat["lu_a"] = t
        avant = _etat["actif"]
        _etat["actif"] = INTERRUPTEUR.exists()
        if _etat["actif"] and not avant:
            PROBE.reset()  # une fenetre de mesure commence : rien de l'ancienne ne s'y melange
            _etat["dump_a"] = t
        elif avant and not _etat["actif"]:
            _ecrire_rapport()  # fin de fenetre : rapport ecrit une fois
        elif _etat["actif"] and t - _etat["dump_a"] >= DUMP_S:
            _etat["dump_a"] = t
            _ecrire_rapport()
    return PROBE if _etat["actif"] else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--allumer", action="store_true", help="pose l'interrupteur (fenetre de mesure)")
    g.add_argument("--eteindre", action="store_true", help="retire l'interrupteur (rapport ecrit au plus 5 s apres)")
    g.add_argument("--rapport", action="store_true", help="affiche le dernier rapport ecrit")
    a = ap.parse_args(argv)
    if a.allumer:
        INTERRUPTEUR.parent.mkdir(parents=True, exist_ok=True)
        INTERRUPTEUR.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
        print("[hotpath] interrupteur pose : %s" % INTERRUPTEUR)
    elif a.eteindre:
        INTERRUPTEUR.unlink(missing_ok=True)
        print("[hotpath] interrupteur retire ; rapport attendu dans %s" % RAPPORT)
    else:
        try:
            print(RAPPORT.read_text(encoding="utf-8"))
        except OSError as e:
            print("[hotpath] aucun rapport lisible (%s) : la sonde a-t-elle tourne ?" % type(e).__name__)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
