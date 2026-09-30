# -*- coding: utf-8 -*-
"""NR — `OnnxGenerator` doit lier `og` (onnxruntime-genai) au chargement et a la generation.

`OnnxGenerator.load` et `_generate_sync` utilisent `og.Model`, `og.Tokenizer`,
`og.GeneratorParams`, `og.Generator` alors que le module n'importe plus
onnxruntime-genai depuis le passage au sidecar : NameError au chargement
(rattrape en erreur de chargement) et a chaque generation. Releve par l'audit
« noms non definis » (mesures/audits/noms_non_definis.md).

Correctif : import local dans les deux methodes (au chargement, dans le `try`).
Test statique : Phi-3.5 ONNX pese plusieurs Go.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402

FICHIER = "app/forge_runtime.py"


def test_og_est_lie_au_chargement():
    assert "og" not in noms_globaux_non_lies(FICHIER, "OnnxGenerator.load")


def test_og_est_lie_a_la_generation():
    assert "og" not in noms_globaux_non_lies(FICHIER, "OnnxGenerator._generate_sync")
