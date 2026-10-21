"""NR -- un tour capture n'est jamais perdu quand la base refuse (racine R1, 17/10).

Journal de l'organe (sandbox/cli_capture_errors.log, mesure 17/10) : 2 964 echecs d'ecriture jusqu'au 01/09 14:21
(database is locked x2055, disk full x44, unable to open x75) ; le repli n'ecrivait QUE l'erreur -- chaque tour de
l'owner rate etait perdu. Le spool garde le TOUR ; le registre des demandes le relit, meme sans base de capture.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from nokido_agent.tools import cli_capture_lib as C  # noqa: E402
from nokido_agent.tools import forge_intent_verifier as V  # noqa: E402

# Borne 120 s (CI de reference du 19/10 : ce module a depasse les 30 s par defaut sous charge ; pytest-timeout en
# methode thread tue alors TOUTE la suite -- 306 tests executes seulement, SUITE_INCOMPLETE). Meme remede que le
# 29/09 ; la cause probable (threads du sampler de forge_resource_manager vivants dans le processus pytest) est
# instruite a part.
pytestmark = pytest.mark.timeout(120)

# Phrase ABSURDE, a dessein : tests/ est indexe par le verificateur (auto-contamination, cf. _SKIP).
PHRASE = "il faut que le zorglub repeigne les quokkas en mauve chaque mardi"


def test_une_base_qui_refuse_n_efface_pas_le_tour(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "ROOT", tmp_path)
    illisible = tmp_path / "base_qui_est_un_dossier"
    illisible.mkdir()
    assert C.record_turn("gemini", "user", PHRASE + ".", "s1", db_path=illisible) is None
    lignes = (tmp_path / "sandbox" / "cli_capture_spool.jsonl").read_text(encoding="utf-8").splitlines()
    tour = json.loads(lignes[-1])
    assert tour["surface"] == "gemini" and tour["role"] == "user" and PHRASE in tour["content"]


def test_le_spool_n_ecrit_pas_une_donnee_sensible_en_clair(monkeypatch, tmp_path):
    """Revue adverse de Codex (17/10) : le TOUR allait au spool en clair -- un secret colle dans une invite y restait."""
    monkeypatch.setattr(C, "ROOT", tmp_path)
    illisible = tmp_path / "base_qui_est_un_dossier"
    illisible.mkdir()
    C.record_turn("claude", "user", PHRASE + ", ecris a alice@example.com.", "s1", db_path=illisible)
    texte = (tmp_path / "sandbox" / "cli_capture_spool.jsonl").read_text(encoding="utf-8")
    assert "alice@example.com" not in texte and "zorglub" in texte


def test_le_spool_est_borne(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "ROOT", tmp_path)
    monkeypatch.setattr(C, "_SPOOL_MAX_OCTETS", 400)
    illisible = tmp_path / "base_qui_est_un_dossier"
    illisible.mkdir()
    for i in range(12):
        C.record_turn("claude", "user", PHRASE + " numero %d." % i, "s%d" % i, db_path=illisible)
    sp = tmp_path / "sandbox" / "cli_capture_spool.jsonl"
    assert sp.stat().st_size <= 400 + 600 and (tmp_path / "sandbox" / "cli_capture_spool.jsonl.1").exists()


def test_le_registre_relit_les_tours_du_spool(monkeypatch, tmp_path):
    spool = tmp_path / "cli_capture_spool.jsonl"
    spool.write_text(json.dumps({"surface": "opencode", "role": "user", "content": PHRASE + ".",
                                 "ts": "2026-10-17T12:00:00"}) + "\n" +
                     json.dumps({"surface": "opencode", "role": "assistant", "content": PHRASE + "."}) + "\n",
                     encoding="utf-8")
    monkeypatch.setattr(V, "_capture_db", lambda: tmp_path / "absente.db")
    monkeypatch.setattr(V, "_capture_spool", lambda: spool)
    [e] = V._enonces_captures()
    assert e["texte"] == PHRASE and e["occurrences"] == 1 and e["surfaces"] == ["cli_opencode"]
