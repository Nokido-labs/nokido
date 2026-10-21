"""NR -- Hamilton : une RECHUTE peu apres une reprise double le calme exige (hysteresis), sinon le delestage oscille.

Mesure 19/10 23:36 -> 00:00 (logs/laforge-master.log) : POST /supervisor/sleep puis /wake sur NokidoDeportEmbed ET
NokidoMemoryConsolidator toutes les ~3 min (sleep 23:36:45, wake 23:39:51, sleep 23:42:55, wake 23:46:13, sleep 23:48:03,
wake 23:51:22, 23:55:34...) : la reprise apres 120 s de calme relance le service, dont le DEMARRAGE (vague d'embedding,
balayage de 5000 traces) recree la pression -> sommeil -> calme -> reveil. Boucle auto-induite : DeportEmbed n'a plus
jamais fini une vague. Remede : une rechute dans les 15 min suivant une reprise double le calme exige (plafond x16),
historique persiste avec l'etat (la cle `_rechutes` n'est jamais un service).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as R  # noqa: E402

PAUSE, CALME = 45.0, 120.0


def _cycle(etat, t0):
    """Pause a t0, calme des t0+10, reprise des que le calme exige est atteint ; rend (t_reprise, etat)."""
    _, etat = R.gestes_observes(["svc"], etat, t0, PAUSE, CALME)
    _, etat = R.gestes_observes([], etat, t0 + 10, PAUSE, CALME)
    t = t0 + 10
    while True:
        t += 30
        g, etat = R.gestes_observes([], etat, t, PAUSE, CALME)
        if g.get("svc") == "REPRENDRE":
            return t, etat
        assert t < t0 + 10_000, "jamais repris"


def test_une_rechute_rapide_double_le_calme_exige():
    t1, etat = _cycle({}, 0.0)
    assert t1 - 10 >= CALME and t1 - 10 < 2 * CALME          # 1re reprise : calme normal
    t2, etat = _cycle(etat, t1 + 60)                           # rechute 60 s apres la reprise
    assert t2 - (t1 + 70) >= 2 * CALME                          # 2e reprise : calme double


def test_une_rechute_tardive_ne_penalise_pas():
    t1, etat = _cycle({}, 0.0)
    t2, etat = _cycle(etat, t1 + 3600)                         # pression revenue une heure plus tard
    assert t2 - (t1 + 3610) < 2 * CALME


def test_le_calme_exige_est_plafonne():
    etat, t = {}, 0.0
    for _ in range(8):
        t, etat = _cycle(etat, t + 60)
    t_fin, _ = _cycle(etat, t + 60)
    assert t_fin - (t + 70) <= 16 * CALME + 30


def test_l_historique_se_persiste_et_n_est_pas_un_service():
    t1, etat = _cycle({}, 0.0)
    etat = json.loads(json.dumps(etat))                          # l'etat est ecrit en JSON entre deux ticks
    g, _ = R.gestes_observes([], etat, t1 + 30, PAUSE, CALME)
    assert "_rechutes" not in g
