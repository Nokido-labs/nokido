"""JUGE du banc d'amelioration `juge_ancrage_swarm` : F1 de detection des chiffres SANS SOURCE.

DETERMINISTE : aucun reseau, aucun LLM. Le corpus (corpus_juge_ancrage.jsonl) est etiquete a la MAIN, par les regles
R1..R5 ecrites dans chaque cas, a partir des VRAIS artefacts du 29/10 (cli_swarm_ptr_20261029_100240 : 15-20 %, 12 %,
30 % fabriques ; bornes 6000/16000 legitimes ; cli_swarm_ptr_20261029_112231 : 6/6 ancres ; identifiants) + cas
synthetiques. Le juge charge `tools/forge_cli_swarm.py` de la RACINE donnee (la copie isolee du candidat) ; il vit
HORS du perimetre modifiable : un candidat ne peut pas le toucher.

Metrique : F1 = 2TP / (2TP + FP + FN) sur les elements (cas, chiffre) ; TP = signale ET etiquete sans source.
Usage : banc_juge_ancrage.py [--racine DIR] [--corpus FICHIER]   -> une ligne JSON {"metrique": F1, ...}
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/meta-evaluation"

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

# 29/10 (owner, RSI) : v1 SATURE (F1 1,0, le banc n'apprenait plus) ; v2 ajoute des cas plus durs (formats, exclusions,
# fabriques : F1 0,57 au HEAD). Les DEUX sont mesures : une amelioration sur v2 ne casse jamais v1.
CORPUS = (Path(__file__).resolve().parent / "corpus_juge_ancrage.jsonl",
          Path(__file__).resolve().parent / "corpus_juge_ancrage_v2.jsonl")
_RACINE = Path(__file__).resolve().parents[2]


try:
    from bancs import charger_module
except ImportError:   # lance comme script : tools/ n'est pas sur sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from bancs import charger_module  # noqa: E402


def _charger(racine: Path):
    """forge_cli_swarm de `racine`, charge par chemin (jamais le module deja importe d'un autre arbre)."""
    return charger_module(racine, "forge_cli_swarm_banc", "tools/forge_cli_swarm.py")


def mesurer(corpus=CORPUS, racine: Path = _RACINE) -> dict:
    """`corpus` : un fichier ou une suite de fichiers JSONL, mesures ensemble (empreinte sur leur concatenation)."""
    mod = _charger(racine)
    fichiers = [corpus] if isinstance(corpus, (str, Path)) else list(corpus)
    brut = b"\n".join(Path(f).read_bytes().rstrip(b"\n") for f in fichiers)
    cas = [json.loads(l) for l in brut.decode("utf-8").splitlines() if l.strip()]
    tp = fp = fn = 0
    faux = []
    for c in cas:
        trouve = set(mod._juger_ancrage(c["texte"], c.get("sources") or [])["sans_source"])
        attendu = set(c["sans_source"])
        tp += len(trouve & attendu)
        fp += len(trouve - attendu)
        fn += len(attendu - trouve)
        if trouve != attendu:
            faux.append({"id": c.get("id"), "trouve": sorted(trouve), "attendu": sorted(attendu)})
    den = 2 * tp + fp + fn
    return {"metrique": (2 * tp / den) if den else 1.0, "tp": tp, "fp": fp, "fn": fn, "cas": len(cas),
            "ecarts": faux, "sha256_corpus": hashlib.sha256(brut).hexdigest()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--racine", type=Path, default=_RACINE)
    ap.add_argument("--corpus", type=Path, action="append", default=None,
                    help="fichier de corpus (repetable) ; par defaut v1 + v2")
    a = ap.parse_args(argv)
    print(json.dumps(mesurer(a.corpus or CORPUS, a.racine), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
