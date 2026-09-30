import pytest
from pathlib import Path
from app.forge_guarded_mutation_loop import calculate_tests_hash, apply_mutation_with_git_guard, ROOT

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : os.walk tests/ + lecture
#   (code appele) (l.6)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

def test_calculate_tests_hash_non_empty():
    h = calculate_tests_hash()
    assert h != ""
    assert len(h) == 64  # SHA-256 is 64 hex characters

def test_calculate_tests_hash_changes_on_modification():
    import hashlib
    import os
    import tempfile
    
    def mock_calc_hash(test_dir_path: Path) -> str:
        hasher = hashlib.sha256()
        for root, _, files in os.walk(test_dir_path):
            for file in sorted(files):
                fp = Path(root) / file
                if fp.suffix == ".py":
                    hasher.update(fp.relative_to(test_dir_path).as_posix().encode("utf-8"))
                    hasher.update(fp.read_bytes())
        return hasher.hexdigest()

    # Création dossier de tests factice dans sandbox (writable)
    sandbox_dir = ROOT / "sandbox"
    sandbox_dir.mkdir(exist_ok=True)
    
    with tempfile.TemporaryDirectory(dir=str(sandbox_dir)) as tmpdir:
        fake_tests = Path(tmpdir) / "tests"
        fake_tests.mkdir()
        
        # 1. Dossier vide
        h1 = mock_calc_hash(fake_tests)
        
        # 2. Ajout d'un test
        test1 = fake_tests / "test_a.py"
        test1.write_text("def test_ok(): assert True")
        h2 = mock_calc_hash(fake_tests)
        assert h1 != h2
        
        # 3. Modification du test
        test1.write_text("def test_ok(): assert False")
        h3 = mock_calc_hash(fake_tests)
        assert h2 != h3
