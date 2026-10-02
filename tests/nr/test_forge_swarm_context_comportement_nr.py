import pytest
from pathlib import Path
from app.forge_swarm_context import sterile_read, assert_writable, ScopeViolation

def test_context_comportement_principal(tmp_path: Path):
    (tmp_path / "cible.py").write_text("contenu_autorise")
    
    # Lecture normale
    out = sterile_read("cible.py", ["cible.py"], tmp_path)
    assert out == "contenu_autorise"
    
    # Verification ecriture
    assert_writable("cible.py", ["cible.py"], tmp_path)  # passe silencieusement

def test_context_rejet_hors_scope(tmp_path: Path):
    (tmp_path / "secret.txt").write_text("secret_data")
    
    # Fichier existant mais hors scope
    with pytest.raises(ScopeViolation, match="lecture hors périmètre"):
        sterile_read("secret.txt", ["cible.py"], tmp_path)
        
    with pytest.raises(ScopeViolation, match="écriture hors cible"):
        assert_writable("secret.txt", ["cible.py"], tmp_path)

def test_context_rejet_traversal(tmp_path: Path):
    # Sortie de la racine via ..
    with pytest.raises(ScopeViolation, match="hors-racine"):
        sterile_read("../hors_racine.txt", ["../hors_racine.txt"], tmp_path)
