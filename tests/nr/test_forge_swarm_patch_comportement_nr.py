import pytest
from pathlib import Path
from app.forge_swarm_patch import VFSOverlay, PatchError

def test_patch_comportement_principal(tmp_path: Path):
    vfs = VFSOverlay(tmp_path)
    # Creation
    vfs.apply({"op": "create", "target": "test.py", "content": "def a(): pass\n"})
    assert vfs.read("test.py") == "def a(): pass\n"
    
    # Edition (Search/Replace)
    vfs.apply({
        "op": "edit_sr",
        "target": "test.py",
        "blocks": [("def a(): pass\n", "def b(): pass\n")]
    })
    
    # Verification de l'overlay (memoire)
    assert "def b():" in vfs.read("test.py")
    
    # Commit
    vfs.commit()
    assert (tmp_path / "test.py").read_text(encoding="utf-8") == "def b(): pass\n"

def test_patch_comportement_erreur(tmp_path: Path):
    vfs = VFSOverlay(tmp_path)
    vfs.apply({"op": "create", "target": "test.py", "content": "def a(): pass\n"})
    
    # Cas limite: erreur de syntaxe python detectee a chaud
    with pytest.raises(PatchError, match="syntaxe Python cassée"):
        vfs.apply({
            "op": "edit_sr",
            "target": "test.py",
            "blocks": [("def a(): pass\n", "def a()  # bad syntax\n")]
        })

def test_patch_erreur_ancre_introuvable(tmp_path: Path):
    vfs = VFSOverlay(tmp_path)
    vfs.apply({"op": "create", "target": "f.txt", "content": "hello world"})
    
    # Cas d'erreur: ancre introuvable
    with pytest.raises(PatchError, match="ancre SEARCH non trouvée"):
        vfs.apply({
            "op": "edit_sr",
            "target": "f.txt",
            "blocks": [("bye", "goodbye")]
        })
