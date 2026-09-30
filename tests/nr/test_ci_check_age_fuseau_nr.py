"""Non-regression : l'age d'un run CI ne doit pas inventer une heure d'attente.

Mesure 2026-09-02 : un run cree a l'instant s'affichait « queued depuis 3605s —
runner present, rien ne demarre ». Le run allait tres bien ; le calcul d'age
melangeait heure locale et UTC (`mktime` interprete en local, `time.timezone`
ignore l'heure d'ete). Le message envoyait relancer un runner sain -- et c'est
exactement ce qu'un agent avait deja fait une fois cette nuit-la.

Un garde qui crie a faux se fait desarmer : la precision d'un diagnostic fait
partie de sa securite.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_ci_check as cc  # noqa: E402


def _iso(instant: datetime) -> str:
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_un_run_cree_a_l_instant_a_un_age_proche_de_zero():
    """LE cas paye : l'ecart etait de 3600 s pile en heure d'ete."""
    age = cc._age_s(_iso(datetime.now(timezone.utc)))
    assert age is not None
    assert abs(age) < 90, (
        "age=%.0f s pour un run cree a l'instant : le calcul melange les fuseaux "
        "(3600 s = l'heure d'ete)" % age)


def test_un_age_connu_est_rendu_fidelement():
    ref = datetime.now(timezone.utc) - timedelta(seconds=600)
    age = cc._age_s(_iso(ref))
    assert age is not None and 540 < age < 660, age


def test_l_age_ne_part_jamais_dans_le_futur():
    """Un age negatif ferait passer un run ancien pour un run neuf."""
    for delta in (0, 30, 3600, 86400):
        age = cc._age_s(_iso(datetime.now(timezone.utc) - timedelta(seconds=delta)))
        assert age is not None and age > -90, (delta, age)


def test_le_suffixe_z_et_les_fractions_sont_acceptes():
    base = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    for forme in (base + "Z", base + ".123456Z", base + ".1Z"):
        age = cc._age_s(forme)
        assert age is not None and abs(age) < 90, (forme, age)


def test_une_entree_absente_ou_illisible_rend_none_pas_zero():
    """Trois etats : ne pas savoir n'est pas « age nul ». Un 0.0 se lirait
    « cree a l'instant » et masquerait un run reellement bloque."""
    assert cc._age_s(None) is None
    assert cc._age_s("") is None
    assert cc._age_s("pas une date") is None


def test_le_calcul_ne_depend_pas_du_fuseau_du_poste():
    """Le meme horodatage doit rendre le meme age quel que soit TZ.

    On ne peut pas rejouer `time.tzset` sous Windows ; on verifie donc la propriete
    qui compte : l'age est calcule a partir d'un instant CONSCIENT de son fuseau,
    donc il coincide avec le calcul de reference fait en UTC explicite.
    """
    ref = datetime.now(timezone.utc) - timedelta(seconds=1234)
    attendu = time.time() - ref.timestamp()
    obtenu = cc._age_s(_iso(ref))
    assert obtenu is not None
    assert abs(obtenu - attendu) < 5, (obtenu, attendu)
