"""NR — porte d'autorisation FAIL-CLOSED du push public (owner 2026-09-15).

Verrouille : refus PAR DEFAUT, refus si un signal manque (decision BREVET/IP OU l'une des
deux confirmations owner), passage seulement si TOUT est present, et cablage effectif aux
deux points de push (forge_dist_publish.push_remotes, launch_public_mirror.phase_push).

Hermetique : decision en tmp, env monkeypatchee, aucun reseau, aucun push.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_publication_gate as G  # noqa: E402


def _armer_confirm(monkeypatch):
    monkeypatch.setenv("NOKIDO_GO_PUBLIC_1", G.CONFIRM_1)
    monkeypatch.setenv("NOKIDO_GO_PUBLIC_2", G.CONFIRM_2)


def _decision(tmp_path, monkeypatch, contenu):
    f = tmp_path / "DECISION_PUBLICATION.json"
    f.write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(G, "DECISION", f)
    return f


def test_refuse_par_defaut_sans_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "DECISION", tmp_path / "absent.json")
    _armer_confirm(monkeypatch)
    ok, motif = G.porte_publique()
    assert ok is False and "BREVET/IP ABSENTE" in motif


def test_refuse_si_ip_non_tranchee(tmp_path, monkeypatch):
    _decision(tmp_path, monkeypatch, '{"brevet_ip_tranche": false}')
    _armer_confirm(monkeypatch)
    ok, motif = G.porte_publique()
    assert ok is False and "NON TRANCHEE" in motif


def test_refuse_si_decision_illisible(tmp_path, monkeypatch):
    _decision(tmp_path, monkeypatch, "{ pas du json")
    _armer_confirm(monkeypatch)
    ok, motif = G.porte_publique()
    assert ok is False and "ILLISIBLE" in motif


def test_refuse_sans_confirmation(tmp_path, monkeypatch):
    _decision(tmp_path, monkeypatch, '{"brevet_ip_tranche": true, "date": "2026-09-15"}')
    monkeypatch.delenv("NOKIDO_GO_PUBLIC_1", raising=False)
    monkeypatch.delenv("NOKIDO_GO_PUBLIC_2", raising=False)
    ok, motif = G.porte_publique()
    assert ok is False and "1re confirmation" in motif


def test_refuse_si_une_seule_confirmation(tmp_path, monkeypatch):
    _decision(tmp_path, monkeypatch, '{"brevet_ip_tranche": true}')
    monkeypatch.setenv("NOKIDO_GO_PUBLIC_1", G.CONFIRM_1)
    monkeypatch.delenv("NOKIDO_GO_PUBLIC_2", raising=False)
    ok, motif = G.porte_publique()
    assert ok is False and "2e confirmation" in motif


def test_autorise_si_tout_present(tmp_path, monkeypatch):
    _decision(tmp_path, monkeypatch, '{"brevet_ip_tranche": true, "date": "2026-09-15"}')
    _armer_confirm(monkeypatch)
    ok, motif = G.porte_publique()
    assert ok is True and "AUTORISATION" in motif


def test_cablee_dans_les_deux_publieurs():
    import forge_dist_publish as D  # noqa: PLC0415
    import launch_public_mirror as M  # noqa: PLC0415
    assert "porte_publique" in inspect.getsource(D.push_remotes)
    assert "porte_publique" in inspect.getsource(M.phase_push)
