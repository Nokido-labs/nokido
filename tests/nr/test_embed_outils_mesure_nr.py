"""NR — les outils de mesure du drain d'embedding refusent de balayer la base.

Couvre `forge_embed_lot_commun`, et par lui les trois outils ecrits le 2026-09-06 :
`forge_embed_8099_mesure_bornee` (RAM du pilier local), `forge_embed_cloudflare_lot`
(quota Cloudflare) et `forge_homeostasis_tick_profil` (profil d'un tick d'organe).

Ce qui est verifie est un EFFET, pas un import :
  1. une selection dont le plan BALAYE `rag_chunks` leve `PlanNonIndexe` — la garde qui
     empeche un outil de mesure de devenir le 4e balayeur de la base de 24,9 Go
     (41 min a 98 % de CPU pour zero resultat, 2026-09-03) ;
  2. avec l'index qu'utilise le drain reel, la selection PASSE et rend les lignes ;
  3. `ecrire_rapport` ecrit le rapport COMPLET sur disque tout en gardant stdout resume ;
  4. `chrono` mesure duree et delta RSS de la fonction enveloppee, et journalise MEME
     quand elle leve (sinon une phase qui echoue disparait du profil) ;
  5. les trois outils empruntent ce socle (aucun ne re-code sa propre selection).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_embed_lot_commun as C  # noqa: E402


def _base(tmp_path: Path, avec_index: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, embedding BLOB, "
                 "domain TEXT, source TEXT)")
    conn.executemany("INSERT INTO rag_chunks (id, text, source) VALUES (?,?,?)",
                     [(f"c{i}", f"texte {i}", "veille") for i in range(50)])
    if avec_index:
        conn.execute("CREATE INDEX idx_emb_null ON rag_chunks (id) WHERE embedding IS NULL")
    conn.commit()
    return conn


def test_un_plan_qui_balaye_la_base_est_refuse(tmp_path, monkeypatch):
    conn = _base(tmp_path, avec_index=False)
    monkeypatch.setitem(sys.modules, "forge_tier_policy",
                        type(sys)("forge_tier_policy"))
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_tier_policy",
                        type(sys)("nokido_agent.tools.forge_tier_policy"))
    sys.modules["forge_tier_policy"].hot_tier_clause = lambda c: "1=1"
    sys.modules["nokido_agent.tools.forge_tier_policy"].hot_tier_clause = lambda c: "1=1"
    with pytest.raises(C.PlanNonIndexe) as e:
        C.candidats_sans_vecteur(conn, 10, dire=lambda _m: None)
    assert "SCAN" in str(e.value)


def test_avec_l_index_du_drain_la_selection_passe(tmp_path, monkeypatch):
    conn = _base(tmp_path, avec_index=True)
    monkeypatch.setitem(sys.modules, "forge_tier_policy", type(sys)("forge_tier_policy"))
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_tier_policy", type(sys)("nokido_agent.tools.forge_tier_policy"))
    sys.modules["forge_tier_policy"].hot_tier_clause = lambda c: "embedding IS NULL"
    sys.modules["nokido_agent.tools.forge_tier_policy"].hot_tier_clause = lambda c: "embedding IS NULL"
    vus: list[str] = []
    rows = C.candidats_sans_vecteur(conn, 5, dire=vus.append)
    assert len(rows) == 5 and rows[0][0].startswith("c")
    assert vus and vus[0].startswith("[plan]")


def test_le_rapport_complet_va_sur_disque_et_le_resume_sur_stdout(tmp_path, capsys):
    dest = tmp_path / "r.json"
    C.ecrire_rapport(dest, {"a": 1, "echantillons": [{"x": 1}] * 3}, "BORNE", "parce que",
                     sans=("echantillons",))
    disque = json.loads(dest.read_text(encoding="utf-8"))
    assert disque["verdict"] == "BORNE" and len(disque["echantillons"]) == 3 and disque["raison"] == "parce que"
    sortie = capsys.readouterr().out
    assert "[verdict] BORNE parce que" in sortie and "echantillons" not in sortie


def test_chrono_journalise_meme_quand_la_phase_leve():
    journal: list[dict] = []
    faux_rss = iter([1.0, 2.5, 2.5, 2.5])
    ok = C.chrono(journal, "phase_ok", lambda: 42, rss=lambda: next(faux_rss))
    assert ok() == 42
    assert journal[0]["phase"] == "phase_ok" and journal[0]["delta_go"] == 1.5

    def _boum():
        raise RuntimeError("phase cassee")

    ko = C.chrono(journal, "phase_ko", _boum, rss=lambda: 3.0)
    with pytest.raises(RuntimeError):
        ko()
    assert [j["phase"] for j in journal] == ["phase_ok", "phase_ko"]


def test_les_trois_outils_empruntent_le_socle_et_ne_recodent_pas_la_selection():
    for nom in ("forge_embed_8099_mesure_bornee", "forge_embed_cloudflare_lot",
                "forge_homeostasis_tick_profil"):
        src = (ROOT / "tools" / f"{nom}.py").read_text(encoding="utf-8", errors="replace")
        assert "forge_embed_lot_commun" in src, nom
        assert "EXPLAIN QUERY PLAN" not in src, f"{nom} re-code la selection au lieu du socle"
