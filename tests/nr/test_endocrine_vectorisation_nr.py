"""Non-regression : l'accelerateur de vectorisation doit ATTEINDRE son recepteur.

Defaut mesure le 2026-08-25. `TSH_VECTORIZATION` est lue par `forge_rag_warmup`, qui
double le `batch_size` au-dessus de **0.4**. Son niveau valait `(80 - pct) / 80`, soit
0,0125 a pct=79 % : le seuil n'etait donc franchi qu'en dessous de **48 %** de corpus
vectorise. Et entre 80 % et 95 %, aucune emission n'avait lieu du tout — c'est-a-dire
sur toute la plage de fonctionnement normale.

Releve du jour : pct=86,7 %, 176 467 chunks en attente, `read_full("TSH_VECTORIZATION")`
ne rendait AUCUNE ligne en base, pendant que l'antagoniste `INSULIN_VECTORIZATION`
tenait 0,477 — au-dessus de son propre seuil de frein — renouvele 144 fois en 4 h 05.
Frein permanent, accelerateur hors d'atteinte.

Ces tests portent sur l'EFFET : le niveau franchit-il le seuil que le recepteur
applique reellement ? Un test qui verifierait seulement « une hormone est emise »
serait passe sur le defaut, puisqu'une hormone L'ETAIT — a 0,0125.

Hermetique : `release` est double, rien n'est ecrit dans le systeme endocrinien reel.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import forge_endocrine  # noqa: E402
import forge_health_diagnostic as hd  # noqa: E402

# Seuil applique par le recepteur `forge_rag_warmup`. Ecrit ici pour que le test
# echoue si quelqu'un deplace le seuil sans reconsiderer l'emetteur : c'est le
# couplage qu'on veut rendre visible, pas une constante a dupliquer.
SEUIL_RECEPTEUR = 0.4


@pytest.fixture()
def emissions(monkeypatch):
    vues: list[dict] = []

    def _faux_release(hormone, level=None, source=None, reason=None, meta=None, **kw):
        vues.append({"hormone": hormone, "level": level, "reason": reason})
        return {"hormone": hormone, "level": level}

    monkeypatch.setattr(forge_endocrine, "release", _faux_release)
    return vues


def _audit(pct: float, non_vec: int = 176467) -> dict:
    return {
        "rag_chunks": {"pct_vectorized": pct, "non_vectorized": non_vec},
        "messages": {"agent_messages_pct_unread": 0.0, "agent_messages_total": 10},
    }


def _niveau(emissions, hormone):
    for e in emissions:
        if e["hormone"] == hormone:
            return e["level"]
    return None


def test_le_releve_reel_du_jour_atteint_le_seuil_du_recepteur(emissions):
    """86,7 % vectorise et 176 467 chunks en attente : le corps DOIT demander."""
    hd._release_hormones_from_audit(_audit(86.7))
    niveau = _niveau(emissions, "TSH_VECTORIZATION")
    assert niveau is not None, "aucune demande emise sur la plage de fonctionnement"
    assert niveau > SEUIL_RECEPTEUR, (
        "signal emis mais SOUS le seuil du recepteur (%.3f) : une hormone qui "
        "n'atteint pas son recepteur ne regule rien" % niveau
    )


def test_le_defaut_dorigine_ne_peut_plus_revenir(emissions):
    """L'ancienne formule rendait 0,0125 a 79 % — le seuil n'etait franchi qu'en
    dessous de 48 %. On verifie le point qui la trahissait."""
    hd._release_hormones_from_audit(_audit(79.0))
    niveau = _niveau(emissions, "TSH_VECTORIZATION")
    assert niveau is not None
    assert niveau > SEUIL_RECEPTEUR
    assert niveau > (80.0 - 79.0) / 80.0, "l'ancienne courbe est revenue"


def test_la_courbe_est_monotone_et_continue(emissions):
    """Sans monotonie, un corpus MIEUX vectorise pourrait crier plus fort — et un
    capteur qui s'affole quand la situation s'ameliore finit desarme."""
    niveaux = []
    for pct in (70.0, 80.0, 86.7, 90.0, 94.0):
        emissions.clear()
        hd._release_hormones_from_audit(_audit(pct))
        niveaux.append(_niveau(emissions, "TSH_VECTORIZATION"))
    assert all(n is not None for n in niveaux)
    assert niveaux == sorted(niveaux, reverse=True), niveaux
    assert niveaux[0] == 1.0, "le deficit franc doit saturer le signal"


def test_a_la_cible_la_demande_se_tait(emissions):
    """Temoin : un signal qui ne redescend jamais est un signal qu'on ignore."""
    emissions.clear()
    hd._release_hormones_from_audit(_audit(94.9, non_vec=100))
    faible = _niveau(emissions, "TSH_VECTORIZATION")
    assert faible is not None and faible < SEUIL_RECEPTEUR, faible


def test_la_saturation_emet_lantagoniste_et_non_la_demande(emissions):
    """Au-dela de la cible, c'est le FREIN qui parle. Les deux ne doivent jamais
    partir ensemble depuis cette source."""
    hd._release_hormones_from_audit(_audit(97.0, non_vec=10))
    assert _niveau(emissions, "INSULIN_VECTORIZATION") is not None
    assert _niveau(emissions, "TSH_VECTORIZATION") is None


def test_la_raison_nomme_le_chiffre_qui_a_declenche(emissions):
    """Une hormone sans raison chiffree est un signal qu'on ne peut pas refuter —
    et `CORTISOL_FRUSTRATION` circule justement a 0,87 avec une raison VIDE."""
    hd._release_hormones_from_audit(_audit(86.7))
    raison = next(e["reason"] for e in emissions
                  if e["hormone"] == "TSH_VECTORIZATION")
    assert "86.7" in raison and "176467" in raison, raison
