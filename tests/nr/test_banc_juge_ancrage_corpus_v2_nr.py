"""NR 29/10 (owner : la methode takehome transposee au RSI) -- le banc juge_ancrage_swarm etait SATURE (F1 1,0 sur le
corpus v1) : il ne pouvait plus rien apprendre. Le juge mesure desormais v1 ET v2 (cas plus durs : formats,
exclusions, fabriques) ; v1 reste dedans, pour qu'une amelioration sur v2 ne casse jamais v1. Empreintes a jour."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]

from bancs import banc_juge_ancrage as J  # noqa: E402


def _ids(p):
    return {json.loads(l)["id"] for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()}


def test_le_juge_mesure_v1_et_v2_par_defaut():
    noms = {Path(c).name for c in J.CORPUS}
    assert noms == {"corpus_juge_ancrage.jsonl", "corpus_juge_ancrage_v2.jsonl"}


def test_la_mesure_couvre_tous_les_cas_des_deux_corpus():
    r = J.mesurer()
    assert r["cas"] == sum(len(_ids(c)) for c in J.CORPUS)


def test_la_configuration_du_banc_fige_les_deux_corpus():
    cfg = json.loads((ROOT / "config" / "bancs_amelioration.json").read_text(encoding="utf-8"))["juge_ancrage_swarm"]
    assert "tools/bancs/corpus_juge_ancrage_v2.jsonl" in cfg["juge"]["empreintes"]
    assert "tools/bancs/corpus_juge_ancrage.jsonl" in cfg["juge"]["empreintes"]
