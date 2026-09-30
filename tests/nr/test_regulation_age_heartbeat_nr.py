# -*- coding: utf-8 -*-
"""NR — la mesure d'inactivite doit ARRIVER au decideur, quel que soit le format.

DEFAUT MESURE LE 2026-09-05, effet massif pour une seule ligne. Les keepers
n'ecrivent pas `ts` de la meme facon : `docker_keeper` publie un epoch,
`llama_keeper` une date ISO. `_inutile_s_llama()` faisait `float(d["ts"])`, donc
`ValueError` sur l'ISO, avalee par un `except` qui rendait `None`.

L'arbitre lisait alors « inactivite INCONNUE » et s'abstenait PAR PRUDENCE, a chaque
tick, indefiniment — alors que le keeper publiait `inutile_s = 211`. `llama-server`
(4,8 Go) n'etait donc JAMAIS evince, ce qui bloquait d'un coup la lane d'admission CI,
le redemarrage du keeper Docker par le superviseur (`resource gate refused`) et
jusqu'aux sondes de diagnostic (throttle homeostat).

Ce garde tient les DEUX cotes, et ils ne sont pas symetriques :

- une date LISIBLE, epoch ou ISO, doit donner un age — sinon la regulation est
  aveugle a une mesure qui existe ;
- une date ABSENTE ou ILLISIBLE doit rendre `None` — la propriete « ne jamais
  evincer sur une non-mesure » (regression du 2026-07-26) reste entiere.

Hermetique : aucun heartbeat reel, aucun service touche.
"""
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

rm = pytest.importorskip("forge_resource_manager")


def test_horodatage_epoch_donne_un_age():
    age = rm._age_heartbeat_s({"ts": time.time() - 42})
    assert age is not None and 40 <= age <= 60


def test_horodatage_iso_donne_un_age():
    """Le cas paye : `llama_keeper` ecrit une date ISO naive."""
    from datetime import datetime, timedelta

    iso = (datetime.now() - timedelta(seconds=30)).isoformat(timespec="seconds")
    age = rm._age_heartbeat_s({"ts": iso})
    assert age is not None, "une date ISO doit etre datable : c'est le defaut paye"
    assert 20 <= age <= 90


def test_horodatage_iso_avec_fuseau():
    from datetime import datetime, timedelta, timezone

    iso = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    age = rm._age_heartbeat_s({"ts": iso})
    assert age is not None and 20 <= age <= 90


def test_horodatage_absent_ou_illisible_rend_none():
    """L'autre moitie du contrat : ne jamais fabriquer un age."""
    assert rm._age_heartbeat_s({}) is None
    assert rm._age_heartbeat_s({"ts": ""}) is None
    assert rm._age_heartbeat_s({"ts": "pas une date"}) is None
    assert rm._age_heartbeat_s({"ts": None}) is None


def _pouls_temoin(tmp_path, monkeypatch, age_s: float):
    """Fichier temoin dont le mtime est COHERENT avec l'age teste.

    Depuis d25a9f134, `_inutile_s_llama` confronte le `ts` du pouls au mtime du
    fichier reel `sandbox/llama_keeper.heartbeat` (contre-mesure du repere
    d'horloge). Un test qui ne patche que `_heartbeat_keeper` lit donc l'ETAT DU
    DISQUE : il passait tant que NokidoLlamaKeeper battait, et il est devenu
    rouge le 2026-09-05 au soir quand ce service a ete coupe (mtime 20:36 contre
    un ts « maintenant » = divergence = INCERTAIN = None). Mesure en CI locale,
    reproduit en isolation. Ce temoin rend le test hermetique : il ne depend
    plus d'aucun service.
    """
    f = tmp_path / "llama_keeper.heartbeat"
    f.write_text("{}", encoding="utf-8")
    t = time.time() - age_s
    os.utime(f, (t, t))
    monkeypatch.setattr(rm, "_hb_keeper_path", lambda: f)
    return f


def test_inactivite_lue_quand_le_pouls_est_frais(monkeypatch, tmp_path):
    from datetime import datetime

    _pouls_temoin(tmp_path, monkeypatch, age_s=0.0)
    monkeypatch.setattr(rm, "_heartbeat_keeper",
                        lambda: {"inutile_s": 211,
                                 "ts": datetime.now().isoformat(timespec="seconds")})
    assert rm._inutile_s_llama() == 211.0, \
        "une inactivite publiee et fraiche doit atteindre l'arbitre"


def test_inactivite_ignoree_quand_le_pouls_est_perime(monkeypatch, tmp_path):
    """Un pouls de plus de 600 s ne decrit plus le present (temoin mtime coherent :
    on teste la PEREMPTION, pas la divergence d'horloge)."""
    _pouls_temoin(tmp_path, monkeypatch, age_s=5000.0)
    monkeypatch.setattr(rm, "_heartbeat_keeper",
                        lambda: {"inutile_s": 211, "ts": time.time() - 5000})
    assert rm._inutile_s_llama() is None


def test_repere_faux_est_denonce_par_le_mtime(tmp_path):
    """Owner 2026-09-05 : « attention a l'horloge UTC ».

    Une date NAIVE est relue en heure LOCALE. Un producteur qui ecrirait en UTC naif
    verrait son age gonfle du decalage du fuseau (+7200 s en UTC+2) : le pouls serait
    juge PERIME et l'arbitre redeviendrait aveugle EN SILENCE — le defaut d'origine,
    revenu par la porte de derriere. Le `mtime`, ecrit par l'OS, est un temoin
    independant : deux mesures qui divergent denoncent le repere.
    """
    from datetime import datetime, timedelta

    f = tmp_path / "pouls.heartbeat"
    f.write_text("{}", encoding="utf-8")
    faux = (datetime.now() - timedelta(seconds=7200)).isoformat(timespec="seconds")
    assert rm._age_heartbeat_s({"ts": faux}, f) is None, \
        "un repere faux doit rendre INCERTAIN, jamais un age fabrique"
    # Sans temoin, on ne peut rien denoncer : l'age est rendu tel quel.
    assert rm._age_heartbeat_s({"ts": faux}) is not None


def test_repere_coherent_passe_la_contre_mesure(tmp_path):
    from datetime import datetime

    f = tmp_path / "pouls.heartbeat"
    f.write_text("{}", encoding="utf-8")
    bon = datetime.now().isoformat(timespec="seconds")
    age = rm._age_heartbeat_s({"ts": bon}, f)
    assert age is not None and age < 60


def test_inactivite_absente_reste_inconnue(monkeypatch):
    monkeypatch.setattr(rm, "_heartbeat_keeper", lambda: {"ts": time.time()})
    assert rm._inutile_s_llama() is None
    monkeypatch.setattr(rm, "_heartbeat_keeper",
                        lambda: {"inutile_s": "beaucoup", "ts": time.time()})
    assert rm._inutile_s_llama() is None
