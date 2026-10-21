"""NR -- Hamilton SUSPEND avant d'arreter, et ne reprend qu'apres un calme durable (hysteresis en temps). OBSERVATION.

Decision owner 19/10 (« pause avant kill ») : le delestage arretait directement les services DIFFERABLE. Geste pur
`gestes_observes` : un service a delester est d'abord SUSPENDU ; s'il reste a delester au-dela de `pause_max_s`, il
serait ARRETE (une suspension gele la croissance et le CPU mais NE LIBERE PAS la memoire privee : elle ne suffit pas
contre une pression qui dure) ; sorti de la liste, il n'est REPRIS qu'apres `calme_min_s` de calme continu -- jamais
au premier releve sain (oscillation). Aucun geste reel : l'armement reste une decision owner.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_resource_manager as R  # noqa: E402


def test_premiere_pression_suspend_puis_pression_durable_arrete():
    g, etat = R.gestes_observes(["svc_fond"], {}, 1000.0)
    assert g == {"svc_fond": "SUSPENDRE"} and etat["svc_fond"]["pause_ts"] == 1000.0
    g, etat = R.gestes_observes(["svc_fond"], etat, 1030.0)
    assert g == {"svc_fond": "MAINTENIR_PAUSE"}
    g, etat = R.gestes_observes(["svc_fond"], etat, 1050.0)
    # l'arret est MEMORISE pour la reprise apres calme (4007375b4 : l'effacer laissait le service endormi a jamais)
    assert g == {"svc_fond": "ARRETER"} and etat["svc_fond"].get("arrete") is True


def test_la_reprise_attend_un_calme_durable():
    _, etat = R.gestes_observes(["svc_fond"], {}, 1000.0)
    g, etat = R.gestes_observes([], etat, 1010.0)
    assert g == {"svc_fond": "MAINTENIR_PAUSE"} and etat["svc_fond"]["calme_ts"] == 1010.0
    g, etat = R.gestes_observes([], etat, 1100.0)
    assert g == {"svc_fond": "MAINTENIR_PAUSE"}
    g, etat = R.gestes_observes([], etat, 1131.0)
    # le service n'est plus en pause ; seul reste l'historique des reprises (hysteresis, a887b5510)
    assert g == {"svc_fond": "REPRENDRE"} and "svc_fond" not in etat and set(etat) <= {"_rechutes"}


def test_une_rechute_remet_le_calme_a_zero():
    _, etat = R.gestes_observes(["svc_fond"], {}, 1000.0)
    _, etat = R.gestes_observes([], etat, 1010.0)
    _, etat = R.gestes_observes(["svc_fond"], etat, 1020.0)
    assert etat["svc_fond"]["calme_ts"] is None
    g, _ = R.gestes_observes([], etat, 1100.0)
    assert g == {"svc_fond": "MAINTENIR_PAUSE"}


def test_rien_a_delester_rien_en_pause_aucun_geste():
    assert R.gestes_observes([], {}, 1000.0) == ({}, {})
