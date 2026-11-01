"""NR -- recette owner 28/10 : la mesure du banc de traduction « n'avance pas ».

Cause lue dans le code : _textes_jsonl() parcourait TOUTES les conversations Claude Code, ligne par ligne, et
DEUX fois (volet 1, puis volet 2 avec un json.dumps de chaque objet), sans progression. Le corpus n'a besoin que de
20 prompts et 5 injections : lecture bornee aux conversations les plus RECENTES, arret des que c'est atteint.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_bench_traduction as B  # noqa: E402


def _conversations(dossier: Path, n_fichiers: int, n_lignes: int):
    for i in range(n_fichiers):
        f = dossier / f"s{i:03d}.jsonl"
        with f.open("w", encoding="utf-8") as fh:
            for j in range(n_lignes):
                fh.write(json.dumps({"type": "user", "message": {
                    "content": f"Peux-tu verifier le service numero {i}-{j} et me dire ce qui ne va pas ?"}}) + "\n")
        os.utime(f, (time.time() - (n_fichiers - i), time.time() - (n_fichiers - i)))


def test_seules_les_conversations_recentes_sont_lues(tmp_path, monkeypatch):
    _conversations(tmp_path, 30, 50)
    monkeypatch.setattr(B, "PROJETS", tmp_path)
    ouverts = []
    vrai_open = Path.open

    def _espion(self, *a, **k):
        if self.suffix == ".jsonl":
            ouverts.append(self.name)
        return vrai_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", _espion)
    corpus = B.corpus_volet1(n=20)
    assert len(corpus) == 20
    assert len(set(ouverts)) <= B.MAX_CONVERSATIONS, "toutes les conversations ont ete parcourues"
    assert "s029.jsonl" in ouverts, "la plus recente doit etre lue en premier"
