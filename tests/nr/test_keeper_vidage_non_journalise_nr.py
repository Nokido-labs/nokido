"""NR -- le keeper DIT pourquoi il ne vide pas le cache WSL (owner 2026-11-10 : « garder dropcache, mesurer »).

Mesure : vmmemWSL 5,0 Go (plafond memory=5GB engage) alors que la VM n'utilise que 1,0 Go ; le journal du keeper ne
portait AUCUNE decision de vidage WSL -- seuls les vidages faits sont audites, un refus (sous le seuil, refractaire,
mesure illisible) etait muet. Contrat : chaque refus est journalise avec vmmem et surcout, au plus 1 fois / 10 min.
"""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_docker_keeper as K  # noqa: E402


def test_refus_journalise_et_borne(monkeypatch, caplog):
    monkeypatch.setattr(K, "mesurer_surcout_vm", lambda: (5000.0, 4800.0))  # surcout 200 Mo : sous le seuil
    monkeypatch.setattr(K, "_dernier_journal_non_vidage", None, raising=False)
    caplog.set_level(logging.INFO)
    for t in (1000.0, 1010.0, 1700.0):
        r = K._tick_vidage_cache(t)
        assert r["vidage"] is False
    lignes = [m for m in caplog.messages if "vidage cache WSL : non" in m]
    assert len(lignes) == 2, lignes
    assert "vmmem 5000 Mo" in lignes[0] and "surcout 200 Mo" in lignes[0]


def test_mesure_illisible_aussi_dite(monkeypatch, caplog):
    monkeypatch.setattr(K, "mesurer_surcout_vm", lambda: (None, None))
    monkeypatch.setattr(K, "_dernier_journal_non_vidage", None, raising=False)
    caplog.set_level(logging.INFO)
    K._tick_vidage_cache(5000.0)
    assert any("mesure illisible" in m for m in caplog.messages)
