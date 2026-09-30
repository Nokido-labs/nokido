# -*- coding: utf-8 -*-
"""NR — `OnnxEmbedder.load` doit pouvoir construire le modele local.

Depuis le passage au sidecar (brain_worker), `forge_runtime` n'importe plus
sentence-transformers au chargement ; mais `OnnxEmbedder.load` instancie
toujours `SentenceTransformer(...)` : NameError rattrape en « Erreur chargement
OnnxEmbedder », embeddings locaux desactives meme quand la librairie est
installee. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : import local dans le `try` du chargement (librairie absente ->
meme repli qu'avant, `False`). Test statique : le modele pese plusieurs centaines
de Mo.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_sentence_transformer_est_lie_au_chargement():
    assert "SentenceTransformer" not in noms_globaux_non_lies("app/forge_runtime.py", "OnnxEmbedder.load")
