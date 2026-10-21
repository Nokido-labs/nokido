"""NR 18/10 -- passe natif mesuree : second poste du cout A FROID d'introspect.

Profil du 18/10, processus neuf : forge_callgraph_jit._index_fichier = 6,9 s (147 fichiers re-indexes par ast) sur
13,65 s ; a chaud 0,45 s. `_INDEX_CACHE` (cle mtime+taille) n'existait qu'en MEMOIRE. Contrat : `_persister_index()`
ecrit le cache dans `_CACHE_DISQUE`, un processus neuf le relit et ne re-indexe pas un fichier inchange ; un fichier
modifie l'est ; un cache corrompu est ignore sans casser l'index ; les fonctions publiques (callers, definitions)
persistent d'elles-memes.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_callgraph_jit as cg  # noqa: E402

SRC = "def f(x):\n    return g(x)\n\ndef g(y):\n    return y\n"


def _monter(monkeypatch, tmp_path, appels):
    mod = importlib.reload(cg)                      # « processus neuf »
    monkeypatch.setattr(mod, "_CACHE_DISQUE", tmp_path / "cache" / "callgraph_index.json")
    vrai = mod._indexer_arbre

    def compte(arbre):
        appels.append(1)
        return vrai(arbre)
    monkeypatch.setattr(mod, "_indexer_arbre", compte)
    return mod


def test_un_processus_neuf_ne_reindexe_pas_un_fichier_inchange(monkeypatch, tmp_path):
    fp = tmp_path / "forge_x.py"
    fp.write_text(SRC, encoding="utf-8")
    appels = []
    mod = _monter(monkeypatch, tmp_path, appels)
    premier = mod._index_fichier(str(fp))
    mod._persister_index()
    assert appels == [1] and premier is not None
    appels.clear()
    mod = _monter(monkeypatch, tmp_path, appels)
    second = mod._index_fichier(str(fp))
    assert appels == [], "un processus neuf a re-indexe un fichier inchange : le cache n'a pas survecu"
    assert second == premier, "l'index relu du disque differe de l'index calcule"


def test_un_fichier_modifie_est_reindexe_et_un_cache_corrompu_ignore(monkeypatch, tmp_path):
    fp = tmp_path / "forge_x.py"
    fp.write_text(SRC, encoding="utf-8")
    appels = []
    mod = _monter(monkeypatch, tmp_path, appels)
    mod._index_fichier(str(fp))
    mod._persister_index()
    fp.write_text(SRC + "\ndef h():\n    return f(1)\n", encoding="utf-8")
    appels.clear()
    mod = _monter(monkeypatch, tmp_path, appels)
    assert mod._index_fichier(str(fp)) is not None and appels == [1]
    (tmp_path / "cache" / "callgraph_index.json").write_text("{pas du json", encoding="utf-8")
    appels.clear()
    mod = _monter(monkeypatch, tmp_path, appels)
    assert mod._index_fichier(str(fp)) is not None and appels == [1]


def test_les_fonctions_publiques_persistent_d_elles_memes():
    src = (ROOT / "app" / "forge_callgraph_jit.py").read_text(encoding="utf-8", errors="replace")
    for nom in ("callers", "definitions"):
        m = re.search(r"\ndef %s\(.*?(?=\ndef |\Z)" % nom, src, re.S)
        assert m, "%s() introuvable" % nom
        assert "_persister_index(" in m.group(0), "%s() ne persiste pas l'index : le processus suivant repaiera" % nom
