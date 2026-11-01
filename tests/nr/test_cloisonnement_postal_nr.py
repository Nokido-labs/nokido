"""NR 30/10 -- cloisonnement postal inter-LLM (item P1_audit_cloisonnement_inter_llm_ponts_certifies_20261024, S1).

Un courrier poste pour GEMINI se draine par secretaire/digest de GEMINI et JAMAIS par ceux de CLAUDE (et
inversement). Base postale JETABLE (tmp_path, monkeypatch de forge_postal.DB) : la vraie postal.db n'est pas
touchee. Logique reprise du rendu INACHEVE d'OPENCODE_GLM (job_2292487d, commit 9706bcdc5).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_postal  # noqa: E402


# CODEX et CLAUDE : deux boites sans alias (GEMINI est un alias d'ANTIGRAVITY -- le rendu GLM l'ignorait et
# affirmait des tests « passes » jamais executes).
def _deposer_et_livrer(tmp_path, monkeypatch):
    """Meme chemin que handle_notify : post (queued) puis facteur du canal (delivered). Bus du swarm neutralise."""
    monkeypatch.setattr(forge_postal, "DB", tmp_path / "postal_test.db")
    monkeypatch.setattr(forge_postal, "_emit", lambda *a, **k: None)
    r_x = forge_postal.post("SENDER1", "CODEX", "test codex")
    r_c = forge_postal.post("SENDER2", "CLAUDE", "test claude")
    for r in (r_x, r_c):
        forge_postal.facteur(r.get("recipient_channel", ""))
    return r_x, r_c


def test_courrier_draine_par_son_seul_destinataire(tmp_path, monkeypatch):
    r_x, r_c = _deposer_et_livrer(tmp_path, monkeypatch)
    assert r_x["status"] == "queued" and r_c["status"] == "queued"

    boite_x = forge_postal.secretaire("CODEX")
    boite_c = forge_postal.secretaire("CLAUDE")
    assert [m["from"] for m in boite_x] == ["SENDER1"]
    assert [m["from"] for m in boite_c] == ["SENDER2"]
    assert all("test claude" not in m["body"] for m in boite_x)
    assert all("test codex" not in m["body"] for m in boite_c)


def test_digest_ne_melange_pas_les_boites(tmp_path, monkeypatch):
    _deposer_et_livrer(tmp_path, monkeypatch)
    d_x = forge_postal.digest("CODEX")
    d_c = forge_postal.digest("CLAUDE")
    assert d_x["n_pending"] == 1 and d_c["n_pending"] == 1
    corps_x = " ".join(m.get("body", "") for m in d_x.get("urgent", []))
    corps_c = " ".join(m.get("body", "") for m in d_c.get("urgent", []))
    assert "test claude" not in corps_x and "test codex" not in corps_c


def test_alias_gemini_rejoint_la_boite_antigravity():
    assert forge_postal.canonical("gemini") == forge_postal.canonical("GEMINI") == "ANTIGRAVITY"
    assert forge_postal.canonical("claude") == forge_postal.canonical("CLAUDE") == "CLAUDE"
