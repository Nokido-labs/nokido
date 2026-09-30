"""app/forge_snn_monitor.py — Spiking Neural Network monitor (snnTorch LIF).

Phase 39 POC. Complement de forge_lnn_monitor (CfC continuous-time).
SNN event-driven : neurones LIF spike SEULEMENT sur anomalie -> hook
forge_hormones.release("adrenaline") sur spike. Opt-in via FORGE_SNN_ENABLED=1.

Recommandation Plan agent : POC fallback-only sans snnTorch maintenant.
Path snntorch differe (cout install 250MB torch+snntorch ; vrai gain
energetique seulement sur HW neuromorphique Loihi/SpiNNaker hors scope).
Path statique + refractory anti-flood = utile immediate.

Organe : SN vegetatif sympathique. NE remplace PAS le polling 3s du
resource_manager — l'alimente en parallele. Pas de cervelet (cf.
forge_spike_router.py CTF-routing distinct).
"""

from __future__ import annotations

# Le docstring ci-dessus disait deja l'organe en prose ; le census ne lit pas la
# prose (filet retire le 25/07 apres qu'il eut range un pont ADB dans l'immunitaire).
# Sans cette ligne le module ressort « non classe », donc sans regulation surveillee.
__FORGE_COLOR__ = "sympathique/interoception-afferente"

import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("forge_snn_monitor")

try:
    import torch  # noqa: F401
    import snntorch as snn
    from snntorch import surrogate  # noqa: F401

    _SNN_OK = True
except ImportError:
    _SNN_OK = False
    snn = None  # type: ignore
    torch = None  # type: ignore

_THRESHOLDS = {
    "ram": float(os.environ.get("FORGE_SNN_TH_RAM", "0.85")),
    "cpu": float(os.environ.get("FORGE_SNN_TH_CPU", "0.90")),
    "gpu": float(os.environ.get("FORGE_SNN_TH_GPU", "0.95")),
}
_WINDOW = 60
# Refractaire calibre sur MESURE, pas sur intuition (2026-08-04, 30 181 vitals
# reels sur 9 j, 50 episodes de detresse RAM). A 60 s le capteur voyait les
# 50 episodes mais tirait 775 fois, soit 35,7 emissions inutiles par jour. En
# allongeant, la COUVERTURE ne bouge pas et le bruit s'effondre :
#     60 s -> 50/50 episodes, 775 tirs, 35,7 faux positifs/j
#    300 s -> 50/50,          341 tirs, 19,2/j
#    600 s -> 50/50,          264 tirs, 16,2/j
#   1800 s -> 50/50,          145 tirs,  8,9/j   <- retenu
# Aucun episode perdu jusqu'a 30 min : le reglage est strictement meilleur.
# Il aligne aussi le capteur sur la doctrine du corps — le budget de gravite
# `high` (forge_regulation_loops.SEVERITY_BUDGET_PER_HOUR = 6/h) exige au moins
# 600 s entre deux actes ; a 1800 s le debit tombe a 0,67/h, soit 11 % du budget.
# Banc : tools/forge_snn_vitals_baseline.py
_REFRACTORY_S = 1800.0
# Pente de l'ecart au seuil vers le courant d'entree du LIF.
#
# A 4.0 — la valeur posee le 28/08 au matin sur du RAISONNEMENT (point fixe d'un
# depassement de 1 point = 0.80 < 1, donc « bruit ignore ») — le capteur RATAIT
# 5 episodes de detresse sur 16. Le raisonnement etait juste sur le bruit et faux
# sur la detection : corriger un capteur qui criait a faux l'avait rendu SOURD,
# c'est-a-dire pire que le repli statique qu'il remplace.
#
# Mesure (rejeu du chemin de prod sur 19 099 echantillons reels / 6,35 j,
# 16 episodes de detresse, `tools/forge_snn_vitals_baseline.py --gains ... --brief`) :
#
#   gain | episodes vus | avance moyenne | faux positifs/j
#      2 |         3/16 |        1346 s  |  0.63
#      4 |        11/16 |        1069 s  |  1.73   <- ce qui tournait
#     12 |        16/16 |         817 s  |  3.78
#     20 |        16/16 |        1156 s  |  4.41
#     26 |        16/16 |        1158 s  |  4.57
#     32 |        16/16 |        1376 s  |  4.57   <- retenu
#     45 |        16/16 |        1382 s  |  4.73
#   seuil statique (temoin) : 16/16, 1396.7 s, 6.14
#
# A 32 le capteur EGALE le temoin sur la detection et sur l'avance (-1.5 %) en
# faisant 26 % de bruit en moins ; au-dela le gain d'avance est nul et le bruit
# remonte. Ce que la mesure dit AUSSI, et qu'il faut lire en face : sur CE signal
# le LIF n'apporte pas d'anticipation — il apporte de la SOBRIETE. La frontiere
# 26 -> 32 tient a peu d'episodes (16 au total) ; le choix « >= 12 plutot que 4 »
# est, lui, massif et robuste.
_SNN_GAIN = float(os.environ.get("FORGE_SNN_GAIN", "32.0"))


@dataclass
class SNNMonitor:
    """3 neurones LIF (RAM/CPU/GPU). Spike = anomalie -> hormone adrenaline."""

    enabled: bool = _SNN_OK
    window: deque = field(default_factory=lambda: deque(maxlen=_WINDOW))
    last_spike_ts: dict[str, float] = field(default_factory=lambda: {"ram": 0.0, "cpu": 0.0, "gpu": 0.0})
    lif: dict[str, Any] = field(default_factory=dict)
    mem: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.enabled:
            return
        try:
            from snntorch import surrogate as _surr

            spike_grad = _surr.fast_sigmoid()
            for k in _THRESHOLDS:
                lif = snn.Leaky(beta=0.95, threshold=1.0, spike_grad=spike_grad, init_hidden=False)
                self.lif[k] = lif
                self.mem[k] = lif.init_leaky()
        except Exception as exc:
            logger.warning("snnTorch init failed (%s) — fallback static", exc)
            self.enabled = False

    def feed(self, sample: dict[str, Any], now: float | None = None) -> dict[str, bool]:
        """Feed 1 sample → spike vector {ram, cpu, gpu : bool}.

        `now` = horloge a utiliser pour le refractaire (defaut : l'heure murale).
        Sans ce parametre le capteur n'est pas REJOUABLE : sur un historique de
        30 000 echantillons, le premier spike pose `last_spike_ts` a l'instant du
        rejeu et les 1800 s de refractaire s'ecoulent en temps MURAL — donc le
        rejeu entier ne rend qu'UN tir par canal, quelle que soit la donnee. Un
        capteur de regulation qu'on ne peut pas rejouer sur ses propres mesures ne
        peut pas etre recalibre autrement qu'en production.
        """
        self.window.append(sample)
        spikes = {"ram": False, "cpu": False, "gpu": False}
        if not self.enabled:
            # Fallback statique : pure threshold compare (sans snnTorch)
            for k in spikes:
                v = sample.get(f"{k}_pct")
                if v is not None and (v / 100.0) >= _THRESHOLDS[k]:
                    spikes[k] = True
            return self._apply_refractory(spikes, now)
        # snnTorch path : l'entree est l'ECART AU SEUIL, nulle en dessous.
        #
        # Elle valait `v / 100 / seuil`, donc STRICTEMENT POSITIVE pour toute mesure :
        # un Leaky integre (V <- beta*V + x, point fixe x/(1-beta) = 20x), si bien que
        # n'importe quelle valeur finissait par franchir le seuil. Mesure 2026-08-28 :
        # cpu a 22 % spikait au pas 5, gpu a 15 % au pas 8, ram a 74 % au pas 2 — le
        # contrat « spike = anomalie » etait viole a chaque tick, et seul le refractaire
        # de 1800 s masquait le bruit. Le repli statique, lui, etait correct : c'est le
        # chemin « voulu » qui criait a faux, ce qui desarme un garde.
        #
        # Avec l'ecart, sous le seuil x = 0 : aucune integration, aucun spike. Au-dessus,
        # le LIF apporte ce que le seuil statique n'a pas — la duree : +1 pt reste sous
        # le point fixe 1.0 et ne spike JAMAIS (bruit), +2 pts spike au pas 20, +5 pts au
        # pas 6, une anomalie franche au pas 3.
        for k in spikes:
            v = sample.get(f"{k}_pct")
            if v is None:
                continue
            try:
                _ecart = max(0.0, v / 100.0 - _THRESHOLDS[k]) * _SNN_GAIN
                x = torch.tensor([[_ecart]], dtype=torch.float32)
                spk, self.mem[k] = self.lif[k](x, self.mem[k])
                spikes[k] = bool(spk.item() > 0.5)
            except Exception as exc:
                logger.debug("snn forward %s err: %s", k, exc)
        return self._apply_refractory(spikes, now)

    def _apply_refractory(self, spikes: dict[str, bool],
                          now: float | None = None) -> dict[str, bool]:
        now = time.time() if now is None else float(now)
        for k, s in list(spikes.items()):
            if s and (now - self.last_spike_ts[k]) < _REFRACTORY_S:
                spikes[k] = False
            elif s:
                self.last_spike_ts[k] = now
        return spikes


_INSTANCE: SNNMonitor | None = None
_ETAT_DIT = False


def etat() -> dict:
    """Ce que le capteur EST, pas ce qu'on espere qu'il soit.

    `available()` ne rend qu'un booleen : il ne distingue pas « je tourne en LIF
    snntorch » de « je suis retombe sur des seuils statiques ». Or c'est
    exactement cette difference-la qui s'est perdue le 28/08, ou 503 tirs sont
    partis en repli sans que personne ne le voie."""
    return {
        "backend": "snntorch" if _SNN_OK else "repli-statique",
        "snntorch": _SNN_OK,
        "actif": os.environ.get("FORGE_SNN_ENABLED") == "1",
        "seuils": dict(_THRESHOLDS),
        "refractaire_s": _REFRACTORY_S,
        "instancie": _INSTANCE is not None,
    }


def get_monitor() -> SNNMonitor:
    global _INSTANCE, _ETAT_DIT
    if _INSTANCE is None:
        _INSTANCE = SNNMonitor()
    if not _ETAT_DIT:
        # UNE ligne, UNE fois. Mesure 2026-08-29 : aucun journal vivant ne portait
        # la moindre trace « snn » — impossible de savoir du dehors si le capteur
        # tirait, ni sous quel backend. C'est ce silence qui a rendu invisibles les
        # 503 tirs en repli du 28/08 : un repli CORRECT ne se signale pas tout
        # seul, et un capteur muet ressemble a un corps calme.
        _ETAT_DIT = True
        logger.warning(
            "[snn] backend=%s actif=%s seuils=%s refractaire=%ss",
            "snntorch" if _SNN_OK else "REPLI-STATIQUE (snntorch absent)",
            os.environ.get("FORGE_SNN_ENABLED") == "1", _THRESHOLDS, _REFRACTORY_S)
    return _INSTANCE


def available() -> bool:
    return _SNN_OK
