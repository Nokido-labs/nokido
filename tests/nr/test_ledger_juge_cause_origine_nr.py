"""NR 18/10 -- audit Gemini web verifie (sandbox/mutation_ledger.jsonl = 5 lignes de BANC, sans ts ni origine, `cause`
null sur les 3 REFUSE) + decision owner. Le tableau de bord affichait « 5 tentatives, 0 % » : en production, le juge
n'a jamais recu un candidat reel. Contrat :
  * chaque entree porte `ts`, une `cause` jamais vide (un REFUSE porte sa raison) et une `origine`
    (`production` par defaut, `qualification` sous LAFORGE_JUGE_ORIGINE=qualification) ;
  * `tableau_de_bord` exclut de ses taux le banc et les entrees historiques sans horodatage, et les COMPTE a part
    (les 5 lignes historiques sont gelees telles quelles, jamais reecrites ni supprimees) ;
  * le banc tools/verify_gain_gate.py declare son origine.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_mutation_judge as mj  # noqa: E402


def _lire(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_un_refuse_porte_sa_cause_son_horodatage_et_son_origine(tmp_path, monkeypatch):
    monkeypatch.setattr(mj, "_LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.delenv("LAFORGE_JUGE_ORIGINE", raising=False)
    mj._journaliser("tools/x.py", {"verdict": "REFUSE", "pourquoi": "patron sain indisponible (git show refuse)"})
    (e,) = _lire(tmp_path / "ledger.jsonl")
    assert e.get("cause"), "un REFUSE doit porter sa cause, jamais null"
    assert e.get("ts") and e.get("origine") == "production", e


def test_le_banc_s_etiquette_qualification(tmp_path, monkeypatch):
    monkeypatch.setattr(mj, "_LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setenv("LAFORGE_JUGE_ORIGINE", "qualification")
    mj._journaliser("tools/x.py", {"verdict": "MEURT", "cause": "syntaxe"})
    assert _lire(tmp_path / "ledger.jsonl")[0]["origine"] == "qualification"


def test_le_tableau_de_bord_exclut_banc_et_historique_et_les_compte(monkeypatch):
    entrees = [
        {"verdict": "REFUSE", "cause": None},                                   # historique sans ts
        {"verdict": "MEURT", "cause": "syntaxe", "ts": "2026-10-18T10:00:00", "origine": "qualification"},
        {"verdict": "AMELIORE", "cause": None, "ts": "2026-10-18T11:00:00", "origine": "production",
         "baseline": {"duree_s": 2.0}, "candidat": {"duree_s": 1.0}},
    ]
    t = mj.tableau_de_bord(entrees)
    assert t["tentatives"] == 1 and t["acceptees_AMELIORE"] == 1 and t["taux_acceptation"] == 1.0, t
    assert t.get("exclues_banc_ou_historique") == 2, t


def test_verify_gain_gate_declare_son_origine():
    src = (ROOT / "tools" / "verify_gain_gate.py").read_text(encoding="utf-8", errors="replace")
    assert "LAFORGE_JUGE_ORIGINE" in src and "qualification" in src, (
        "le banc doit s'etiqueter qualification : il ecrivait 5 lignes dans le ledger de production")
