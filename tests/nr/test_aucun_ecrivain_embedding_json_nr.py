"""NR cliquet (owner 29/10, GO conversion A) : plus AUCUN ecrivain ne met un vecteur en JSON dans rag_chunks.embedding.

Archeologie : le JSON est le format d'origine (mars 2026, NPU MiniLM) ; le binaire float32 est canonique depuis avril
(forge_embed_router.encode_blob). Decision owner du 01/10 : decodeurs TOLERANTS au JSON (359 005 vecteurs JSON :
321 758 TEXT de lecons, 37 247 BLOB de crawl). Un vecteur JSON pese ~20 Ko contre 4 Ko : la conversion en base est
inutile si un ecrivain continue d'en produire. Ce test liste les ecrivains restants (app/, tools/, hors _attic).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_ECRITURE = re.compile(r"(INSERT|UPDATE|REPLACE)[^\n]{0,200}rag_chunks|rag_chunks[^\n]{0,120}SET\s+embedding", re.I)
_JSON_VEC = re.compile(r"json\.dumps\(\s*(list\()?\s*(vec|vecs|vector|emb|embedding|new_vec|v)\b")


def _ecrivains_json():
    trouves = []
    for dossier in ("app", "tools"):
        for p in (ROOT / dossier).rglob("*.py"):
            rel = p.relative_to(ROOT).as_posix()
            if "/_attic/" in "/" + rel or "__pycache__" in rel:
                continue
            lignes = p.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, ligne in enumerate(lignes):
                if not _JSON_VEC.search(ligne):
                    continue
                fenetre = "\n".join(lignes[max(0, i - 8): i + 8])
                if _ECRITURE.search(fenetre) and "embedding" in fenetre:
                    trouves.append("%s:%d" % (rel, i + 1))
    return trouves


def test_aucun_ecrivain_json_dans_rag_chunks_embedding():
    assert _ecrivains_json() == []


def test_le_detecteur_voit_un_ecrivain_json(tmp_path, monkeypatch):
    faux = tmp_path / "app"
    faux.mkdir()
    (faux / "x.py").write_text('import json\nconn.execute("UPDATE rag_chunks SET embedding=? WHERE id=?", '
                               '(json.dumps(vec), cid))\n', encoding="utf-8")
    (tmp_path / "tools").mkdir()
    import sys
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert _ecrivains_json() == ["app/x.py:2"]
