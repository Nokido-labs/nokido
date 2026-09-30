"""NR -- soupape ANTI-PERTE ETROITE du gate pre-commit (decision owner 2026-09-24).

« Ne jamais empecher de SAUVER » (regle user) ; mais la soupape precedente -- le gate conseillait
`--no-verify` quand un .ts/.ps1 bloquait -- desarmait AUSSI le scan de secrets. Contrat :
  scan secrets -> TOUJOURS (jamais derogeable, meme demande) ;
  ts / ps1     -> derogeables NOMMEMENT (LAFORGE_GATE_DEROGATION), seul le controle fautif ;
  derogation   -> TRACEE avant d'etre accordee ; sans trace ecrite, refusee (fail-closed).
Chemin reel : `_precommit`, avec les controles remplaces par des doubles (aucun deno, aucun git).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_git_gate as gg  # noqa: E402


@pytest.fixture()
def gate(monkeypatch, tmp_path):
    etat = {"secrets": 0, "ts": 0, "ps1": 0}
    monkeypatch.setattr(gg, "_staged_files", lambda: ["proxy_deno/core/x.ts", "tools/y.ps1"])
    monkeypatch.setattr(gg, "_scan_secrets", lambda: etat["secrets"])
    monkeypatch.setattr(gg, "_ts_parse_gate", lambda f: etat["ts"])
    monkeypatch.setattr(gg, "_ps1_parse_gate", lambda f: etat["ps1"])
    for nom in ("_desync_warn_and_claim", "_quality_warn", "_firehose_warn", "_syntax_warn",
                "_alignment_warn", "_recidive_warn"):
        monkeypatch.setattr(gg, nom, lambda f: None)
    monkeypatch.setattr(gg, "_agent", lambda: "TEST")
    trace = tmp_path / "derogations.jsonl"
    monkeypatch.setattr(gg, "_TRACE_DEROGATIONS", trace)
    monkeypatch.delenv("LAFORGE_GATE_DEROGATION", raising=False)
    return etat, trace, monkeypatch


def test_le_scan_de_secrets_n_est_jamais_derogeable(gate):
    etat, trace, mp = gate
    etat["secrets"] = 1
    mp.setenv("LAFORGE_GATE_DEROGATION", "ts,ps1,secrets")
    assert gg._precommit() != 0
    assert not trace.exists(), "aucune derogation ne doit meme etre tentee quand un secret bloque"


def test_derogation_ts_tracee_et_accordee(gate):
    etat, trace, mp = gate
    etat["ts"] = 1
    mp.setenv("LAFORGE_GATE_DEROGATION", "ts")
    assert gg._precommit() == 0
    lignes = trace.read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 1 and json.loads(lignes[0])["controle"] == "ts"


def test_la_derogation_vise_le_seul_controle_fautif(gate):
    etat, trace, mp = gate
    etat["ts"] = 1
    mp.setenv("LAFORGE_GATE_DEROGATION", "ps1")
    assert gg._precommit() != 0, "deroger ps1 ne doit pas lever un blocage ts"
    assert not trace.exists()


def test_sans_trace_pas_de_derogation(gate):
    etat, trace, mp = gate
    etat["ps1"] = 1
    mp.setenv("LAFORGE_GATE_DEROGATION", "ps1")
    mp.setattr(gg, "_TRACE_DEROGATIONS", trace.parent)  # un DOSSIER : l'ouverture en ajout leve OSError
    assert gg._precommit() != 0, "une derogation qui ne peut pas s'ecrire est REFUSEE"


def test_sans_demande_le_blocage_tient(gate):
    etat, trace, _ = gate
    etat["ps1"] = 1
    assert gg._precommit() != 0 and not trace.exists()


def test_le_conseil_ne_recommande_plus_l_enjambement():
    c = gg._conseil_bloque("ts")
    assert "LAFORGE_GATE_DEROGATION=ts" in c
    assert "git commit --no-verify" not in c
