"""JUGE du banc d'amelioration `redaction_dlp` (organe immunitaire) : F1 du caviardage de forge_semantic_firewall.redact_text.

DETERMINISTE : aucun reseau, aucun LLM. AUCUN vrai secret : le corpus (corpus_redaction_dlp.jsonl) ne porte que des
GABARITS ; chaque valeur sensible est FABRIQUEE ici depuis l'empreinte de l'id du cas (rien de secret dans le depot,
rien que le scanner de secrets puisse prendre pour une fuite). Ce qui doit etre caviarde suit la doctrine ecrite
(CLAUDE.md : « une IP · un email · un chemin Windows suffisent ») + identifiants d'acces (cles, jetons, mots de passe).

Metrique : F1 = 2TP / (2TP + FP + FN) ; TP = valeur sensible ABSENTE du texte rendu ; FN = encore presente ;
FP = element qui DOIT RESTER (version, sha de commit, nombre) absent du texte rendu. Le juge charge le firewall de la
RACINE donnee (copie isolee du candidat) et vit hors du perimetre modifiable.
Usage : banc_redaction_dlp.py [--racine DIR] [--corpus FICHIER]   -> une ligne JSON {"metrique": F1, ...}
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/meta-evaluation"

import argparse
import hashlib
import importlib.util
import json
import string
import sys
from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "corpus_redaction_dlp.jsonl"
_RACINE = Path(__file__).resolve().parents[2]


def _h(graine: str, n: int, alphabet: str) -> str:
    """n caracteres deterministes de `alphabet`, tires de sha256(graine) etendu."""
    out, i = [], 0
    while len(out) < n:
        for b in hashlib.sha256(("%s|%d" % (graine, i)).encode()).digest():
            out.append(alphabet[b % len(alphabet)])
        i += 1
    return "".join(out[:n])


_ALNUM = string.ascii_letters + string.digits
_FABRIQUES = {
    "CLE_SK": lambda g: "sk-" + _h(g, 48, _ALNUM),
    "CLE_GHP": lambda g: "ghp" + "_" + _h(g, 36, _ALNUM),
    "CLE_AKIA": lambda g: "AK" + "IA" + _h(g, 16, string.ascii_uppercase + string.digits),
    "JWT": lambda g: "ey" + "J" + _h(g, 30, _ALNUM) + "." + "ey" + "J" + _h(g + "p", 40, _ALNUM) + "." + _h(g + "s", 43, _ALNUM),
    "MOT_DE_PASSE": lambda g: _h(g, 14, _ALNUM) + "!",
    "EMAIL": lambda g: "%s.%s@exemple-%s.fr" % (_h(g, 6, string.ascii_lowercase), _h(g + "n", 7, string.ascii_lowercase),
                                                _h(g + "d", 5, string.ascii_lowercase)),
    "IP": lambda g: "192.168.%d.%d" % (int(_h(g, 2, string.digits)) % 250 + 1, int(_h(g + "b", 2, string.digits)) % 250 + 2),
    "CHEMIN_WIN": lambda g: "C:\\Users\\%s\\Documents\\%s.txt" % (_h(g, 7, string.ascii_letters), _h(g + "f", 6, string.ascii_lowercase)),
}


try:
    from bancs import charger_module
except ImportError:   # lance comme script : tools/ n'est pas sur sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from bancs import charger_module  # noqa: E402


def _charger(racine: Path):
    """forge_semantic_firewall de `racine`, charge par chemin (chargeur commun des bancs)."""
    return charger_module(racine, "forge_semantic_firewall_banc", "app/forge_semantic_firewall.py")


def instancier(cas: dict) -> tuple[str, list[str], list[str]]:
    """(texte, valeurs sensibles fabriquees, elements qui doivent rester) d'un cas du corpus."""
    texte, sensibles = cas["gabarit"], []
    for i, nature in enumerate(cas.get("sensibles") or []):
        v = _FABRIQUES[nature]("%s#%d" % (cas["id"], i))
        texte = texte.replace("{%d}" % i, v, 1)
        sensibles.append(v)
    return texte, sensibles, list(cas.get("doit_rester") or [])


def mesurer(corpus: Path = CORPUS, racine: Path = _RACINE) -> dict:
    mod = _charger(racine)
    brut = Path(corpus).read_bytes()
    cas = [json.loads(l) for l in brut.decode("utf-8").splitlines() if l.strip()]
    tp = fp = fn = 0
    ecarts = []
    for c in cas:
        texte, sensibles, rester = instancier(c)
        rendu, _mapping = mod.redact_text(texte)
        fuites = [n for n, v in zip(c.get("sensibles") or [], sensibles) if v in rendu]
        perdus = [r for r in rester if r not in rendu]
        tp += len(sensibles) - len(fuites)
        fn += len(fuites)
        fp += len(perdus)
        if fuites or perdus:
            ecarts.append({"id": c["id"], "fuites": fuites, "caviardes_a_tort": perdus})  # natures, jamais de valeur
    den = 2 * tp + fp + fn
    return {"metrique": (2 * tp / den) if den else 1.0, "tp": tp, "fp": fp, "fn": fn, "cas": len(cas),
            "ecarts": ecarts, "sha256_corpus": hashlib.sha256(brut).hexdigest()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--racine", type=Path, default=_RACINE)
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    a = ap.parse_args(argv)
    print(json.dumps(mesurer(a.corpus, a.racine), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
