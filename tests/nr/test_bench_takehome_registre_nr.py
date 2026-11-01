"""NR du 27/10 : chaque verdict du banc take-home laisse une preuve CHAINEE et rejouable.

Owner : « n'oublie pas l'observabilite pour prouver notre resolution ». Un score sans trace se
discute ; une ligne de registre chainee (hash de la precedente) se verifie. Ces tests n'executent
aucun simulateur : ils jugent le registre seul.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

N = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(N / "tools"))
import forge_bench_takehome as J  # noqa: E402

V = {"statut": "VALEUR", "correct": True, "cycles": 1017, "cycles_par_graine": [1017] * 8,
     "indices_exacts": False, "arbre_intact": True, "graines": 8}


def test_deux_verdicts_forment_une_chaine_verifiable(tmp_path):
    reg = tmp_path / "registre.jsonl"
    cand = tmp_path / "perf_takehome.py"
    cand.write_text("# candidat\n", encoding="utf-8")
    J.consigner(reg, V, cand, "test:a")
    J.consigner(reg, dict(V, cycles=1016), cand, "test:b")
    lignes = [json.loads(l) for l in reg.read_text(encoding="utf-8").splitlines()]
    assert len(lignes) == 2
    assert lignes[1]["precedent"] == lignes[0]["empreinte"]
    assert lignes[0]["sha256_candidat"] and lignes[0]["provenance"] == "test:a"
    assert lignes[0]["cycles_par_graine"] == [1017] * 8
    assert J.verifier_registre(reg) == {"ok": True, "lignes": 2, "rupture": None}


def test_une_ligne_retouchee_casse_la_chaine(tmp_path):
    reg = tmp_path / "registre.jsonl"
    cand = tmp_path / "perf_takehome.py"
    cand.write_text("# candidat\n", encoding="utf-8")
    J.consigner(reg, V, cand, "test:a")
    J.consigner(reg, V, cand, "test:b")
    l = reg.read_text(encoding="utf-8").splitlines()
    d = json.loads(l[0])
    d["cycles"] = 900  # on « ameliore » un score apres coup
    brut = list(l)
    brut[0] = json.dumps(d, ensure_ascii=False, sort_keys=True)
    reg.write_text("\n".join(brut) + "\n", encoding="utf-8")
    v = J.verifier_registre(reg)
    assert v["ok"] is False and v["rupture"] == 0  # sa propre empreinte ment
    # falsificateur soigneux : il recalcule l'empreinte de la ligne retouchee -> le LIEN suivant ment
    import hashlib
    d.pop("empreinte")
    d["empreinte"] = hashlib.sha256(json.dumps(d, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    soigne = list(l)
    soigne[0] = json.dumps(d, ensure_ascii=False, sort_keys=True)
    reg.write_text("\n".join(soigne) + "\n", encoding="utf-8")
    v = J.verifier_registre(reg)
    assert v["ok"] is False and v["rupture"] == 1
