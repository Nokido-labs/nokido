from setuptools import setup
from Cython.Build import cythonize
from Cython.Compiler import Options
# DEAD_IMPORT removed: import sys

# Options d'optimisation
Options.annotate = False
Options.embed_pos_in_docstring = False

ext_modules = cythonize(
    [
        str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "forge_handlers.py"),
        str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "forge_orchestrator.py"),
        str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "forge_swarm_team.py"),
        str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "forge_swarm.py"),
    ],
    compiler_directives={
        "language_level": "3",
        "boundscheck": False,
        "wraparound": False,
        "cdivision": True,
        "embedsignature": False,
        "annotation_typing": False,
    },
    build_dir="build_cython",
)

setup(
    name="nokido_core",
    ext_modules=ext_modules,
)
