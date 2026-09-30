"""Non-regression : la consolidation opportuniste decide, et s'abstient quand il le faut.

Cadrage owner 2026-09-01 : le NREM ne doit JAMAIS concurrencer l'intelligence active. Il
transforme de la capacite qui dort en qualite memoire, et il s'arrete des que le corps a
besoin de ses ressources.

Ces tests portent sur l'EFFET des decisions, et surtout sur les ABSTENTIONS -- c'est la
partie qu'un scheduler rate le plus souvent :

  1. backlog non mesurable -> WAIT. On ne consolide pas sur une non-mesure ;
  2. backlog trop faible -> WAIT. Reveiller un pilier couterait plus que le gain ;
  3. cloud vivant -> CLOUD, et le pilier local n'est meme PAS reclame (zero RAM) ;
  4. cloud muet + corps qui refuse -> WAIT, en nommant le substitut ;
  5. cloud muet + corps qui accorde -> LOCAL ;
  6. ASYMETRIE DES COUTS : une grandeur de capacite NON MESURABLE bloque l'accord.
     Rater une fenetre coute un cycle differe ; consommer sous pression fait tomber le
     poste (mesure le jour meme : refus de baseline a 4,67 Go libres).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "app",):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_nrem_scheduler as nrem  # noqa: E402
import forge_pillar_arbiter as arbitre  # noqa: E402


def _politique(monkeypatch, tmp_path, fiche):
    import json

    cible = tmp_path / "pillar_policy.json"
    cible.write_text(json.dumps({"piliers": {"embed.wanted": fiche}}), encoding="utf-8")
    monkeypatch.setattr(arbitre, "_POLITIQUE", cible)
    monkeypatch.setattr(arbitre, "_CACHE", {"lu_a": 0.0, "mtime": None, "data": None})
    monkeypatch.setattr(arbitre, "_DERNIER_LOG", {})


def test_backlog_non_mesurable_sabstient(monkeypatch):
    monkeypatch.setattr(nrem, "_backlog", lambda: None)
    d = nrem.decider()
    assert d["action"] == nrem.WAIT
    assert "NON MESURABLE" in d["motif"]


def test_backlog_trop_faible_sabstient(monkeypatch):
    monkeypatch.setattr(nrem, "_backlog", lambda: 10)
    d = nrem.decider(backlog_min=500)
    assert d["action"] == nrem.WAIT
    assert d["backlog"] == 10


def test_cloud_vivant_ne_reclame_pas_le_pilier_local(monkeypatch):
    """La voie sans RAM locale prime : on ne reveille rien de lourd pour rien."""
    monkeypatch.setattr(nrem, "_backlog", lambda: 100_000)
    monkeypatch.setattr(nrem, "_cloud_repond", lambda timeout=20.0: (True, "backend vivant"))
    reclames = []
    monkeypatch.setattr(arbitre, "reclamer",
                        lambda f, m="": reclames.append(f) or {"accorde": True})

    d = nrem.decider()

    assert d["action"] == nrem.CLOUD
    assert reclames == [], "le pilier local a ete reclame alors que le cloud repondait"


def test_cloud_muet_et_corps_qui_refuse_attend(monkeypatch, tmp_path):
    monkeypatch.setattr(nrem, "_backlog", lambda: 100_000)
    monkeypatch.setattr(nrem, "_cloud_repond", lambda timeout=20.0: (False, "quota epuise"))
    _politique(monkeypatch, tmp_path,
               {"accorde": False, "substitut": "modal", "motif": "directive owner"})

    d = nrem.decider()

    assert d["action"] == nrem.WAIT
    assert d["substitut"] == "modal"


def test_cloud_muet_et_fenetre_de_capacite_autorise_le_local(monkeypatch, tmp_path):
    monkeypatch.setattr(nrem, "_backlog", lambda: 100_000)
    monkeypatch.setattr(nrem, "_cloud_repond", lambda timeout=20.0: (False, "quota epuise"))
    _politique(monkeypatch, tmp_path,
               {"accorde": False, "accorde_si": {"ram_libre_go_min": 9.0},
                "substitut": "modal", "motif": "directive owner"})
    monkeypatch.setattr(arbitre, "_capacite", lambda: {"ram_libre_go": 12.0, "cpu_pct": 5.0})

    d = nrem.decider()

    assert d["action"] == nrem.LOCAL
    assert "fenetre de capacite" in d["motif"]


def test_capacite_insuffisante_refuse_avec_le_chiffre(monkeypatch, tmp_path):
    _politique(monkeypatch, tmp_path,
               {"accorde": False, "accorde_si": {"ram_libre_go_min": 9.0}})
    monkeypatch.setattr(arbitre, "_capacite", lambda: {"ram_libre_go": 4.67, "cpu_pct": 10.0})

    v = arbitre.reclamer("embed.wanted")

    assert v["accorde"] is False
    assert "4.7" in v["capacite"] and "9.0" in v["capacite"], v["capacite"]


def test_capacite_non_mesurable_bloque_laccord(monkeypatch, tmp_path):
    """ASYMETRIE : rater une fenetre est benin, consommer sous pression ne l'est pas."""
    _politique(monkeypatch, tmp_path,
               {"accorde": False, "accorde_si": {"ram_libre_go_min": 9.0}})
    monkeypatch.setattr(arbitre, "_capacite", lambda: {"ram_libre_go": None, "cpu_pct": None})

    v = arbitre.reclamer("embed.wanted")

    assert v["accorde"] is False
    assert "NON MESURABLE" in v["capacite"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
