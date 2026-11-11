"""NR -- pouls du drain d'embedding lu sur le CONTENU du journal (un Traceback en boucle ecrit aussi), et dette
non mesuree = signal de faible gravite sans parler de panne, non repete a chaque cycle."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_remediation as R  # noqa: E402


def _journal(monkeypatch, tmp_path, texte):
    d = tmp_path / "logs" / "supervisor"
    d.mkdir(parents=True, exist_ok=True)
    if texte is not None:
        (d / "NokidoDeportEmbed.log").write_text(texte, encoding="utf-8")
    monkeypatch.setattr(R, "ROOT", tmp_path)


def test_progression_reelle_est_progresse(monkeypatch, tmp_path):
    _journal(monkeypatch, tmp_path, "x\nembed 817/5754 (14%) ~0.8/s\nembed 818/5754 (14%) ~0.8/s\n")
    assert R._pouls_drain_embed()["etat"] == "PROGRESSE"


def test_traceback_en_boucle_est_echoue(monkeypatch, tmp_path):
    _journal(monkeypatch, tmp_path, "Traceback (most recent call last):\n  File x\nValueError: boom\n" * 50)
    out = R._pouls_drain_embed()
    assert out["etat"] == "ECHOUE" and out["progresse"] is False


def test_rien_de_lisible_est_illisible(monkeypatch, tmp_path):
    _journal(monkeypatch, tmp_path, "bonjour\n")
    assert R._pouls_drain_embed()["etat"] == "ILLISIBLE"
    monkeypatch.setattr(R, "ROOT", tmp_path / "vide")
    out = R._pouls_drain_embed()
    assert out["etat"] == "ILLISIBLE" and out["progresse"] is None


def _brancher(monkeypatch, snap):
    sig = []
    monkeypatch.setattr(R, "_signal", lambda nom, sev, p: sig.append((nom, sev, p)) or 1)
    import forge_memory_availability as MA
    monkeypatch.setattr(MA, "snapshot", lambda *a, **k: dict(snap))
    monkeypatch.setattr(R, "_INCONNU_DERNIER_SIGNAL", {})
    return sig


def test_inconnu_donne_un_signal_faible_sans_panne_et_une_seule_fois(monkeypatch):
    sig = _brancher(monkeypatch, {"frais": True, "vector_pending": 5, "age_s": 3 * 3600})
    out = R.check_embed_backlog(False)
    assert out["etat"] == "INCONNU"
    assert len(sig) == 1 and sig[0][1] == "info", sig
    txt = str(sig[0][2]).lower()
    assert "non mesuree depuis 3 h" in txt and "panne" not in txt
    R.check_embed_backlog(False)
    assert len(sig) == 1, "pas de repetition a chaque cycle"
