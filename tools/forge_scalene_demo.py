# -*- coding: utf-8 -*-
"""Cible de DEMONSTRATION pour scalene — a profiler, pas a importer.

Melange trois profils distincts pour que scalene les attribue ligne a ligne :
  - CPU pur (boucle Python) ;
  - memoire (grosse allocation Python) ;
  - natif/BLAS (produit matriciel numpy, hors GIL).

Lancer (env qui a scalene + numpy = laforge_py314) :
    "%USERPROFILE%\\miniforge3\\envs\\laforge_py314\\python.exe" -m scalene tools/forge_scalene_demo.py

Scalene ouvre un rapport HTML : % CPU Python vs natif, Mo alloues et pics
memoire, le tout PAR LIGNE. C'est la ou tu vois quelle ligne coute quoi.
"""

__FORGE_COLOR__ = "qualite/profiling : cible de demonstration pour scalene"  # organe declare le 2026-09-06 (audit de raccordement)
import numpy as np


def boucle_cpu(n: int = 2_000_000) -> float:
    """CPU-lourde, Python pur : scalene doit l'attribuer en temps CPU Python."""
    total = 0.0
    for i in range(n):
        total += (i % 7) * 0.5
    return total


def alloc_memoire(n: int = 8_000_000) -> float:
    """Memoire-lourde : une allocation que scalene doit voir en Mo/pic."""
    gros = [0.0] * n
    return sum(gros[:1000])


def calcul_numpy(k: int = 1200) -> float:
    """Natif/BLAS : temps hors GIL, scalene le distingue du CPU Python."""
    a = np.random.rand(k, k)
    b = np.random.rand(k, k)
    return float((a @ b).trace())


def main() -> None:
    print("cpu   :", boucle_cpu())
    print("mem   :", alloc_memoire())
    print("numpy :", calcul_numpy())


if __name__ == "__main__":
    main()
