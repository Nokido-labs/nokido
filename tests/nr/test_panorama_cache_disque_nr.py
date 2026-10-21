"""NR 18/10 -- passe natif mesuree (roadmap_p2_rust_wasm_cible) : le cout A FROID d'introspect.

Profil du 18/10, processus neuf : introspect 13,65 s dont scan_forge_modules 6,2 s (593 modules re-parses par ast pour
leurs imports) ; a chaud 0,45 s. Le cache d'imports n'existait qu'en MEMOIRE (_IMPORTS_CACHE, cle mtime+taille) :
chaque processus neuf (hooks, appels isoles) repayait tout. Contrat : le cache survit au processus (fichier
`_CACHE_DISQUE`), un fichier inchange n'est plus re-parse, un fichier modifie l'est, et un cache illisible ou
corrompu ne casse jamais le scan (il est ignore et le dit).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_panorama_builder as pb  # noqa: E402


def _monter(monkeypatch, tmp_path, appels):
    """(Re)charge le module comme un processus neuf, pointe sur une arborescence et un cache de test."""
    mod = importlib.reload(pb)
    app = tmp_path / "app"
    app.mkdir(exist_ok=True)
    monkeypatch.setattr(mod, "APP_DIR", app)
    monkeypatch.setattr(mod, "VIRTUAL_ROOTS", [])
    monkeypatch.setattr(mod, "_CACHE_DISQUE", tmp_path / "cache" / "panorama_imports.json")
    brut = mod._extract_imports_brut

    def compte(p):
        appels.append(Path(p).name)
        return brut(p)
    monkeypatch.setattr(mod, "_extract_imports_brut", compte)
    return mod, app


def test_un_processus_neuf_ne_reparse_pas_un_fichier_inchange(monkeypatch, tmp_path):
    appels = []
    mod, app = _monter(monkeypatch, tmp_path, appels)
    (app / "forge_a.py").write_text("import forge_b\n", encoding="utf-8")
    (app / "forge_b.py").write_text("import os\n", encoding="utf-8")
    assert mod.scan_forge_modules()["forge_a"] == {"forge_b"}
    assert sorted(appels) == ["forge_a.py", "forge_b.py"]

    appels.clear()
    mod, app = _monter(monkeypatch, tmp_path, appels)          # « nouveau processus »
    assert mod.scan_forge_modules()["forge_a"] == {"forge_b"}
    assert appels == [], "un processus neuf a re-parse des fichiers inchanges : le cache n'a pas survecu"


def test_un_fichier_modifie_est_reparse(monkeypatch, tmp_path):
    appels = []
    mod, app = _monter(monkeypatch, tmp_path, appels)
    (app / "forge_a.py").write_text("import os\n", encoding="utf-8")
    mod.scan_forge_modules()
    (app / "forge_a.py").write_text("import forge_b\nimport os\n", encoding="utf-8")   # taille differente
    (app / "forge_b.py").write_text("x = 1\n", encoding="utf-8")
    appels.clear()
    mod, app = _monter(monkeypatch, tmp_path, appels)
    assert mod.scan_forge_modules()["forge_a"] == {"forge_b"}
    assert sorted(appels) == ["forge_a.py", "forge_b.py"]


def test_un_cache_corrompu_est_ignore_sans_casser_le_scan(monkeypatch, tmp_path):
    appels = []
    mod, app = _monter(monkeypatch, tmp_path, appels)
    (app / "forge_a.py").write_text("import forge_b\n", encoding="utf-8")
    (app / "forge_b.py").write_text("", encoding="utf-8")
    cache = tmp_path / "cache" / "panorama_imports.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("{ceci n'est pas du json", encoding="utf-8")
    assert mod.scan_forge_modules()["forge_a"] == {"forge_b"}
