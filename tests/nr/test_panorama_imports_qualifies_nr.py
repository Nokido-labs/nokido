"""NR 5/11 -- le graphe d'imports d'introspect etait quasi vide : 34 aretes pour 603 modules.

Mesure AST du 5/11 : `_extract_imports_brut` ne gardait que `module.split(".")[0]`. `from nokido_agent.app.forge_x
import y` donnait `nokido_agent`, puis disparaissait au filtre des noms internes : 1 967 imports sur 2 004 perdus
(`nokido_agent.app.forge_x` 1 718, `nokido_agent.app import forge_x` 165, `app.forge_x` 70, `app import forge_x` 14).
Le voisinage rendait `aval`/`amont` vides et `importe_par: 0`, sans le dire. Attendu apres correctif : ~1 359 aretes.

Le cache disque garde les extractions passees sous la cle (mtime, taille) : sans changer de fichier, un module
inchange garderait son ancienne extraction et le correctif ne se verrait pas.
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


def _monter(monkeypatch, tmp_path, *noms):
    """Module neuf sur une arborescence de test, cache de test ; rend (module, dossier app)."""
    mod = importlib.reload(pb)
    app = tmp_path / "app"
    app.mkdir(exist_ok=True)
    for nom in noms:
        (app / f"{nom}.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.setattr(mod, "APP_DIR", app)
    monkeypatch.setattr(mod, "VIRTUAL_ROOTS", [])
    monkeypatch.setattr(mod, "_CACHE_DISQUE", tmp_path / "cache" / "imports.json")
    return mod, app


def test_chaque_forme_d_import_donne_une_arete(monkeypatch, tmp_path):
    cibles = [f"forge_{c}" for c in "bcdefghi"]
    mod, app = _monter(monkeypatch, tmp_path, *cibles)
    (app / "forge_a.py").write_text(
        "from nokido_agent.app.forge_b import x\n"
        "from nokido_agent.app import forge_c\n"
        "from app.forge_d import y\n"
        "from app import forge_e\n"
        "from forge_f import z\n"
        "from . import forge_g\n"
        "import nokido_agent.app.forge_h\n"
        "def paresseux():\n"
        "    from nokido_agent.app.forge_i import w\n"
        "    return w\n", encoding="utf-8")
    assert mod.scan_forge_modules()["forge_a"] == set(cibles)


def test_un_symbole_homonyme_n_invente_pas_d_arete(monkeypatch, tmp_path):
    """`from forge_b import forge_c` importe un SYMBOLE de forge_b : aucune dependance vers le module forge_c."""
    mod, app = _monter(monkeypatch, tmp_path, "forge_b", "forge_c")
    (app / "forge_a.py").write_text("from nokido_agent.app.forge_b import forge_c\n", encoding="utf-8")
    assert mod.scan_forge_modules()["forge_a"] == {"forge_b"}


def test_le_cache_d_avant_le_correctif_n_est_plus_relu():
    """L'ancien fichier porte des extractions fausses sous des cles encore valides pour tout module inchange."""
    assert importlib.reload(pb)._CACHE_DISQUE.name != "panorama_imports.json"


def test_les_outils_entrent_au_graphe_sur_demande_seulement(monkeypatch, tmp_path):
    """Un outil qui importe un module fait partie de ce qu'une modification casse. Les autres lecteurs du scan
    (panorama, schema d'architecture) gardent leur perimetre : l'option est explicite."""
    mod, app = _monter(monkeypatch, tmp_path, "forge_b")
    outils = tmp_path / "tools"
    outils.mkdir()
    monkeypatch.setattr(mod, "TOOLS_DIR", outils)
    (app / "forge_a.py").write_text("from forge_b import x\n", encoding="utf-8")
    (outils / "hook_t.py").write_text("from nokido_agent.app.forge_a import y\nimport hook_u\n", encoding="utf-8")
    (outils / "hook_u.py").write_text("X = 1\n", encoding="utf-8")
    (outils / "forge_a.py").write_text("from nokido_agent.app.forge_b import z\nimport hook_u\n", encoding="utf-8")

    assert "hook_t" not in mod.scan_forge_modules()
    graphe = mod.scan_forge_modules(include_tools=True)
    assert graphe["hook_t"] == {"forge_a", "hook_u"}
    assert graphe["forge_a"] == {"forge_b", "hook_u"}, "un homonyme app/tools fusionne, il n'ecrase pas"


def test_introspect_voit_les_outils_et_nomme_ce_qu_il_ne_voit_pas():
    """Par le chemin reel : _voisinage. 606 noeuds sans les outils, 1 342 tools/*.py mesures le 5/11."""
    from nokido_agent.app.forge_introspect import _voisinage  # noqa: PLC0415
    non_consulte: list = []
    rendu = _voisinage(["forge_panorama_builder"], non_consulte)
    assert rendu["graphe"]["noeuds"] > 1000
    assert any("imports dynamiques" in str(e.get("raison")) for e in non_consulte)


def test_import_qualifie_d_un_outil_sans_prefixe_forge(monkeypatch, tmp_path):
    """Le prefixe forge_ ne decide pas : `hook_*` importe par chemin qualifie reste une arete."""
    mod, _app = _monter(monkeypatch, tmp_path, "forge_b")
    outils = tmp_path / "tools"
    outils.mkdir()
    monkeypatch.setattr(mod, "TOOLS_DIR", outils)
    (outils / "hook_t.py").write_text("from nokido_agent.tools.hook_u import x\nfrom tools import hook_v\n", encoding="utf-8")
    (outils / "hook_u.py").write_text("X = 1\n", encoding="utf-8")
    (outils / "hook_v.py").write_text("X = 1\n", encoding="utf-8")
    assert mod.scan_forge_modules(include_tools=True)["hook_t"] == {"hook_u", "hook_v"}


def test_importe_par_lit_les_imports_qualifies_et_differes():
    """Mesure du 5/11 sur introspect : `importe_par` 0 pour un module importe par forge_introspect."""
    from nokido_agent.app import forge_callgraph_jit as jit
    from nokido_agent.app.forge_introspect import _modules
    rendu = _modules("forge_panorama_builder", [], jit)
    m = next(x for x in rendu if x["module"] == "forge_panorama_builder")
    assert m["importe_par"] >= 2
    assert "app/forge_introspect.py" in m["exemples_import"]


def test_le_graphe_reel_du_depot_n_est_pas_vide(monkeypatch, tmp_path):
    """Par le chemin reel : le depot, pas une fixture. Seuil bas : 1 359 mesures le 5/11, 34 avant correctif."""
    mod = importlib.reload(pb)
    monkeypatch.setattr(mod, "_CACHE_DISQUE", tmp_path / "imports.json")
    graphe = mod.scan_forge_modules()
    assert sum(map(len, graphe.values())) > 1000
    assert "forge_graph_ppr" in graphe["forge_introspect"]
    assert any("forge_introspect" in cibles for cibles in graphe.values()), "introspect a des appelants mesures"
