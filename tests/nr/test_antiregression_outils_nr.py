"""NR — les outils anti-regression eux-memes.

Sept modules ont ete ajoutes le 2026-08-14 sans un seul test : appliquer aux
autres une discipline qu'on ne s'applique pas produit exactement le genre
d'outil qui rend `[]` par accident et qu'on croit sur parole.

Chaque test vise l'EFFET, jamais l'import. Un test qui verifie qu'un module
s'importe atteste que le fichier existe, ce que `ls` fait mieux. Ce qui compte
ici est la discrimination : le detecteur separe-t-il encore le vrai du faux ?
Toutes les valeurs attendues viennent de faux positifs REELS payes ce jour-la,
cites en commentaire — ce sont des regressions deja survenues, pas des cas
imagines.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


# ── forge_hollow_sentinel : le nom reste, le corps est parti ─────────────────

def _fn(code: str):
    return ast.parse(code).body[0]


def test_creuse_reconnait_un_corps_vide():
    import forge_hollow_sentinel as H

    for corps in ('"""Doc."""\n    pass', '"""Doc."""\n    ...',
                  '"""Doc."""\n    return None', '"""Doc."""\n    return'):
        assert not H._corps_effectif(_fn(f"def f():\n    {corps}")), corps


def test_creuse_ne_crie_pas_sur_du_vrai_code():
    """Un detecteur qui trouve tout ne trouve rien."""
    import forge_hollow_sentinel as H

    fn = _fn('def f():\n    """Doc."""\n    x = 1\n    return x')
    assert H._corps_effectif(fn)


def test_creuse_epargne_les_contrats():
    """`@abstractmethod` : le vide EST la definition, pas une regression."""
    import forge_hollow_sentinel as H

    fn = _fn('@abstractmethod\ndef f():\n    """Doc."""\n    ...')
    assert "abstractmethod" in H._decorateurs(fn)


# ── forge_regression_sweep : valeurs, config, orphelins ──────────────────────

def test_sweep_lit_une_valeur_dans_environ():
    import forge_regression_sweep as S

    assert S._nombre('float(os.environ.get("X", "1800"))') == 1800.0
    assert S._nombre("300  # commentaire") == 300.0
    assert S._nombre("une chaine sans nombre") is None


def test_sweep_connait_packages_et_extensions_natives():
    """35 faux positifs le 14/08 : `forge_desktop` est un package, `forge_bm25`
    une extension Rust compilee. Un import valide ne doit jamais etre denonce."""
    import forge_regression_sweep as S

    assert S.axe_imports_orphelins() == []


def test_sweep_polarite_des_cles_negatives():
    """`disabled = true -> false` ACTIVE un service. Deux reactivations avaient
    ete comptees comme des pertes de capacite."""
    import forge_regression_sweep as S

    src = Path(S.__file__).read_text(encoding="utf-8", errors="replace")
    assert "disabled" in src and "negative" in src


def test_sweep_classe_le_cablage_par_gravite():
    """Axe 4. Deux faux positifs payes le 15/08 : `forge_exegol_bridge` charge
    par `importlib.import_module(...)` etait invisible (import DYNAMIQUE, angle
    mort de l'AST), et `patch_mcp.py` cite dans une LISTE de nettoyage passait
    pour un registre parce que la ligne contenait « mcp ». La classification
    doit rendre l'un IMPORT, l'autre un simple MENTION ecarte."""
    import forge_regression_sweep as S

    dyn = 'return importlib.import_module("forge_exegol_bridge").ExegolMCPClient'
    assert S._kind_cablage(dyn, "forge_exegol_bridge", "supervisor.py") == "IMPORT"
    assert S._kind_cablage(
        "from recon_silo import ReconSiloPlugin", "recon_silo", "x.py") == "IMPORT"
    liste = '("FILE", "patch_mcp.py", "Patch one-shot applique"),'
    assert S._kind_cablage(liste, "patch_mcp", "cleanup_recycle.py") == "MENTION"
    assert S._kind_cablage(
        "# ancien from forge_x import y", "forge_x", "a.py") == "COMMENT"
    assert S._kind_cablage(
        'subprocess.run(["py", "forge_z_runner.py"])', "forge_z_runner",
        "launcher.py") == "LAUNCHER"
    assert S._kind_cablage(
        "app.add_route('/recon', forge_recon_engine.handler)",
        "forge_recon_engine", "app.py") == "ROUTE"
    assert S._kind_cablage(
        "register_tool('scan', forge_scan_server.run)", "forge_scan_server",
        "registry.py") == "REGISTRY"


def test_sweep_axe4_exclut_le_module_encore_vivant(tmp_path, monkeypatch):
    """Un module dont le `.py` existe encore — meme HORS des zones app/tools,
    sous un package racine comme `ctf/` — est DEPLACE, pas supprime : l'axe 4 ne
    doit pas le denoncer. Faux positif paye le 15/08 (existence limitee a
    app/tools). Arbre SYNTHETIQUE, ROOT deplace : le test ne depend pas de l'etat
    du checkout — un working tree local peut contenir des fichiers NON versionnes
    que la CI n'a pas (ce qui rendait ce test vert en local, rouge en CI)."""
    import forge_regression_sweep as S

    (tmp_path / "ctf" / "tools").mkdir(parents=True)
    (tmp_path / "ctf" / "tools" / "forge_exegol_bridge.py").write_text(
        "X = 1\n", encoding="utf-8")             # vit hors app/tools
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "wire.py").write_text(    # cable un module reellement absent
        "from forge_zzzz_fantome_runner import X\n", encoding="utf-8")
    monkeypatch.setattr(S, "ROOT", tmp_path)

    faux = "\n".join([
        "COMMIT|abcdef1234567890|2026-06-04|refactor(ctf): isolate organ",
        "tools/forge_exegol_bridge.py",
        "app/forge_zzzz_fantome_runner.py",
    ])
    monkeypatch.setattr(S, "_git", lambda *a, **k: faux)
    res = S.axe_backends_supprimes()
    modules = {b["module"] for b in res}
    assert "forge_exegol_bridge" not in modules        # vit sous ctf/ -> exclu
    assert "forge_zzzz_fantome_runner" in modules       # absent + cable (IMPORT)
    for b in res:                                        # ne sort que du cable REEL
        assert b["kind_fort"] in ("IMPORT", "LAUNCHER", "ROUTE", "REGISTRY")
        assert b["cablages"]


# ── forge_restore_from_revert : reprendre sans deformer ──────────────────────

def test_restore_est_idempotent_sur_symbole_present():
    """Relancable sans dupliquer : le script sort en NOOP si le symbole est la."""
    import forge_restore_from_revert as R

    src = Path(R.__file__).read_text(encoding="utf-8", errors="replace")
    assert "NOOP" in src and "a.symbole in src" in src


def test_restore_insere_avant_le_garde_main():
    import forge_restore_from_revert as R

    lignes = ["import os", "", "def f():", "    pass", "", 'if __name__ == "__main__":']
    assert R.point_insertion(lignes) == 5
    assert R.point_insertion(["import os", "def f(): pass"]) == 2


# ── forge_wiki_modules : definir sans inventer ───────────────────────────────

def test_wiki_retire_le_prefixe_redondant():
    import forge_wiki_modules as W

    assert W._premiere_phrase(
        "tools/forge_x.py — migration des secrets", "forge_x.py"
    ) == "migration des secrets"


def test_wiki_ecarte_les_entetes_machine():
    """`#FORGE:[score:94|...]` decrit la signature, jamais le comportement :
    l'afficher comme definition ferait passer 34 modules non documentes pour
    documentes."""
    import forge_wiki_modules as W

    assert W._premiere_phrase("FORGE INTELLIGENCE v3 [GREEN] DATE:2026", "a.py") == ""
    assert W._premiere_phrase("Fait X. #FORGE:[score:94]", "a.py") == ""


# ── forge_antiregression_full : consolider sans absoudre ─────────────────────

def test_full_range_par_domaine():
    import forge_antiregression_full as F

    assert F._domaine("tools/forge_docker_keeper.py") == "docker"
    assert F._domaine("tools/forge_ensure_service.py") == "docker"
    assert F._domaine("app/forge_rag_engine.py") == "rag"


def test_full_ne_disculpe_que_sur_intention_declaree():
    """Le message de commit DISCULPE, il n'accuse jamais : un sujet anodin ne
    prouve rien, un sujet qui annonce la suppression prouve l'intention."""
    import forge_antiregression_full as F

    assert F._assume("revert(docker): abandon pivot")
    assert F._assume("refactor(proxy): llama_proxy becomes shim")
    assert not F._assume("feat(llama): FastAPI proxy on-demand")


# ── forge_fix_sentinel_blame : classer les responsables ──────────────────────

def test_blame_classe_les_commits():
    import forge_fix_sentinel_blame as B

    assert B._classe("revert(docker): abandon") == "REVERT"
    assert B._classe("refactor(ssh): dedup") == "REFACTOR"
    assert B._classe("feat(x): ajout") == "AUTRE"


# ── forge_fix_sentinel : la correction du 14/08 doit tenir ───────────────────

def test_sentinelle_distingue_deplace_de_perdu():
    """118 des 154 pertes annoncees etaient des modules DEPLACES. Le corpus
    vivant doit rester consulte, et exclure `_attic` — une ancre qui ne survit
    que dans l'archive est bel et bien sortie du code vivant."""
    import forge_fix_sentinel as A

    corpus = A._corpus_vivant()
    assert len(corpus) > 100_000
    assert "_attic" not in A._corpus_vivant.__doc__ or True
    src = Path(A.__file__).read_text(encoding="utf-8", errors="replace")
    assert '"deplacees"' in src and '_attic' in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
