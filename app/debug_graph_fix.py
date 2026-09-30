import sqlite3
import os
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Setup paths
sys.path.insert(0, os.path.abspath("app"))
from nokido_agent.app.forge_graph_linker import GraphLinker


def debug_one_file():
    gl = GraphLinker()
    gl.index.load()

    file_rel = "app/LaForge.py"
    print(f"🕵️ DEBUG CHIRURGICAL : {file_rel}")

    # 1. Résolution de la source
    src_cid = gl._file_src_to_chunk_id(file_rel)
    print(f"  -> Source Chunk ID : {src_cid}")

    # 2. Scan AST direct
    from nokido_agent.app.forge_graph_linker import ASTScanner

    scanner = ASTScanner()
    scanner.scan_file(Path(file_rel))
    print(f"  -> Imports trouvés ({len(scanner.imports)}) : {scanner.imports[:5]}...")

    # 3. Résolution des cibles
    for mod in scanner.imports[:10]:
        dst_cid = gl.index.resolve_module(mod)
        print(f"     * Resolve {mod:25} -> {dst_cid}")


if __name__ == "__main__":
    debug_one_file()
