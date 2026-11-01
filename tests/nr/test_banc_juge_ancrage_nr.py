"""NR -- juge pilote du banc d'amelioration : F1 de detection des chiffres SANS SOURCE, calcule exactement."""
# pylint: disable=wrong-import-position
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

from bancs import banc_juge_ancrage as J  # noqa: E402


def test_f1_exact_sur_mini_corpus(tmp_path):
    """Cas a : 2 attendus, 1 trouve (tp1 fn1). Cas b : rien. Cas c : 0 attendu, 1 trouve (fp1)."""
    cas = [
        {"id": "a", "texte": "gain de 30 % et 12 %", "sources": ["30 % mesure"], "sans_source": ["12%", "99%"]},
        {"id": "b", "texte": "rien", "sources": [], "sans_source": []},
        {"id": "c", "texte": "gain de 40 %", "sources": ["40 s"], "sans_source": []},
    ]
    p = tmp_path / "c.jsonl"
    p.write_text("\n".join(json.dumps(c) for c in cas), encoding="utf-8")
    r = J.mesurer(p, ROOT)
    assert r["tp"] == 1 and r["fp"] == 1 and r["fn"] == 1
    assert r["metrique"] == 0.5  # 2*1 / (2*1 + 1 + 1)
    assert r["cas"] == 3


def test_deterministe(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text(json.dumps({"id": "a", "texte": "12 %", "sources": [], "sans_source": ["12%"]}), encoding="utf-8")
    assert J.mesurer(p, ROOT) == J.mesurer(p, ROOT)


def test_corpus_reel_present_et_etiquete():
    # 29/10 : CORPUS = (v1, v2) -- v1 porte les origines reelles 100240 / 112231 ; v2 ajoute des cas plus durs.
    cas = [json.loads(l) for l in J.CORPUS[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(cas) >= 12 and all("regle" in c and "sans_source" in c for c in cas)
    assert any("100240" in c.get("origine", "") for c in cas) and any("112231" in c.get("origine", "") for c in cas)
