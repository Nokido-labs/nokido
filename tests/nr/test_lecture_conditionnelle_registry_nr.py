"""
tests/nr/test_lecture_conditionnelle_registry_nr.py - Tests de non-régression
pour le branchement de forge_token_cache dans forge_mcp_registry.

Vérifie :
1. Sans etag (opt-in strict, 30/10) : réponse IDENTIQUE à avant, aucun en-tête (un client lit du JSON par `read`) ;
   l'etag s'apprend par un premier appel si_etag="0" -> mode PLEIN + en-tête etag.
2. Avec si_etag valide : mode INCHANGE et corps court retourné (format mode: ...\netag: ...\n[INCHANGE ...]).
3. Repli sans échec si forge_token_cache lève une exception : contenu complet inchangé sans plantage.
4. Couverture des 3 handlers : handle_read, handle_read_function_body, handle_get_file_skeleton.
5. Déclaration des paramètres si_etag et depuis_etag dans les schémas d'entrée MCP.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.forge_mcp_registry import ToolRegistry
import app.forge_token_cache as ftc


@pytest.fixture
def registry(tmp_path, monkeypatch):
    cache_dir = tmp_path / "sandbox_token_cache"
    monkeypatch.setenv("LAFORGE_TOKEN_CACHE_DIR", str(cache_dir))
    reg = ToolRegistry(root_dir=tmp_path)
    return reg


@pytest.fixture
def repo_tmp(tmp_path):
    """Crée une fausse structure de dépôt avec fichier .git (comme dans un worktree)."""
    repo = tmp_path / "worktree_test"
    repo.mkdir(parents=True, exist_ok=True)
    git_file = repo / ".git"
    git_file.write_text("gitdir: /fake/path/.git/worktrees/test\n", encoding="utf-8")

    code_dir = repo / "pkg"
    code_dir.mkdir(parents=True, exist_ok=True)

    py_file = code_dir / "sample.py"
    py_code = (
        "import sys\n\n"
        "def compute_total(a, b):\n"
        "    result = a + b\n"
        "    return result\n\n"
        "class Worker:\n"
        "    def run(self):\n"
        "        pass\n"
    )
    py_file.write_text(py_code, encoding="utf-8")
    return repo, py_file, py_code


def test_schema_mcp_declaration():
    """Règle 4 : Declare si_etag et depuis_etag (string, optionnels) dans le schema d'entree MCP des 3 outils."""
    reg = ToolRegistry(root_dir=ROOT)
    catalog = reg._raw_tool_catalog()
    tools_by_name = {t["name"]: t for t in catalog}

    for name in ("read", "read_function_body", "get_file_skeleton"):
        assert name in tools_by_name, f"Outil '{name}' introuvable dans le catalogue brut"
        schema = tools_by_name[name]["inputSchema"]
        props = schema.get("properties", {})
        assert "si_etag" in props, f"si_etag manquant dans le schema de {name}"
        assert props["si_etag"]["type"] == "string"
        assert "depuis_etag" in props, f"depuis_etag manquant dans le schema de {name}"
        assert props["depuis_etag"]["type"] == "string"
        # Optionnels : ne doivent pas être dans required
        required = schema.get("required", [])
        assert "si_etag" not in required
        assert "depuis_etag" not in required


@pytest.mark.asyncio
async def test_handle_read_sans_etag(registry, repo_tmp):
    """Sans etag : réponse IDENTIQUE, et rien écrit dans le cache ; si_etag="0" apprend l'etag."""
    repo, py_file, py_code = repo_tmp
    registry.root = repo

    res = await registry.handle_read({"path": "pkg/sample.py"}, agent="agt_test", ring=0)
    assert res == py_code
    assert not Path(os.environ["LAFORGE_TOKEN_CACHE_DIR"]).exists()

    res0 = await registry.handle_read({"path": "pkg/sample.py", "si_etag": "0"}, agent="agt_test", ring=0)
    assert res0.startswith("mode: PLEIN\n")
    assert f"etag: {ftc.etag(py_code)}\n" in res0
    assert res0.endswith(py_code)


@pytest.mark.asyncio
async def test_handle_read_avec_bon_si_etag(registry, repo_tmp):
    """Avec bon si_etag : mode INCHANGE et corps court [INCHANGE etag=...]."""
    repo, py_file, py_code = repo_tmp
    registry.root = repo

    tag = ftc.etag(py_code)
    # Première lecture pour peupler les instantanés du cache
    await registry.handle_read({"path": "pkg/sample.py"}, agent="agt_test", ring=0)

    # Deuxième lecture avec si_etag
    res = await registry.handle_read(
        {"path": "pkg/sample.py", "si_etag": tag}, agent="agt_test", ring=0
    )
    assert "mode: INCHANGE" in res
    assert f"etag: {tag}" in res
    assert f"[INCHANGE etag={tag}]" in res
    assert py_code not in res  # Le contenu complet n'est pas renvoyé


@pytest.mark.asyncio
async def test_handle_read_exception_repli(registry, repo_tmp, monkeypatch):
    """Règle 5 : Toute exception de forge_token_cache -> repli sur la reponse normale."""
    repo, py_file, py_code = repo_tmp
    registry.root = repo

    def mock_lecture_conditionnelle(*args, **kwargs):
        raise RuntimeError("Erreur simulateur cache crash")

    monkeypatch.setattr(ftc, "lecture_conditionnelle", mock_lecture_conditionnelle)

    res = await registry.handle_read({"path": "pkg/sample.py"}, agent="agt_test", ring=0)
    # Repli sur le contenu brut normal sans plantage
    assert res == py_code


@pytest.mark.asyncio
async def test_handle_read_function_body_sans_et_avec_etag(registry, repo_tmp):
    """Vérifie handle_read_function_body avec et sans etag."""
    repo, py_file, py_code = repo_tmp
    registry.root = repo

    # 1. Premier appel si_etag="0" : PLEIN + etag
    res_sans = await registry.handle_read_function_body(
        {"file_path": str(py_file), "function_name": "compute_total", "si_etag": "0"},
        agent="agt_test",
        ring=0,
    )
    assert res_sans.startswith("mode: PLEIN\n")
    assert "def compute_total(a, b):" in res_sans
    val_etag = res_sans.splitlines()[1].replace("etag: ", "").strip()

    # 2. Avec bon si_etag
    res_avec = await registry.handle_read_function_body(
        {"file_path": str(py_file), "function_name": "compute_total", "si_etag": val_etag},
        agent="agt_test",
        ring=0,
    )
    assert "mode: INCHANGE" in res_avec
    assert f"[INCHANGE etag={val_etag}]" in res_avec
    assert "def compute_total(a, b):" not in res_avec


@pytest.mark.asyncio
async def test_handle_get_file_skeleton_sans_et_avec_etag(registry, repo_tmp):
    """Vérifie handle_get_file_skeleton avec et sans etag."""
    repo, py_file, py_code = repo_tmp
    registry.root = repo

    # 1. Premier appel si_etag="0" : PLEIN + etag
    res_sans = await registry.handle_get_file_skeleton(
        {"file_path": str(py_file), "si_etag": "0"},
        agent="agt_test",
        ring=0,
    )
    assert res_sans.startswith("mode: PLEIN\n")
    assert "### SKELETON" in res_sans
    assert "def compute_total(a, b): ..." in res_sans
    val_etag = res_sans.splitlines()[1].replace("etag: ", "").strip()

    # 2. Avec bon si_etag
    res_avec = await registry.handle_get_file_skeleton(
        {"file_path": str(py_file), "si_etag": val_etag},
        agent="agt_test",
        ring=0,
    )
    assert "mode: INCHANGE" in res_avec
    assert f"[INCHANGE etag={val_etag}]" in res_avec
    assert "def compute_total(a, b): ..." not in res_avec


@pytest.mark.asyncio
async def test_resolution_racine_git(registry, repo_tmp):
    """Règle 3 : racine = premier parent du fichier contenant .git (fichier OU dossier)."""
    repo, py_file, _ = repo_tmp
    racine_trouvee = registry._resoudre_racine_git(py_file)
    assert Path(racine_trouvee).resolve() == repo.resolve()
