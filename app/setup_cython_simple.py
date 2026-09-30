from setuptools import setup
from Cython.Build import cythonize

ext_modules = cythonize(
    [
        str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "forge_swarm.py"),
        str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "forge_retry_strategies.py"),
        str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "forge_prompt_builder.py"),
    ],
    compiler_directives={"language_level": "3"},
    build_dir="build_cython",
    quiet=True,
)

setup(name="nokido_modules", ext_modules=ext_modules)
