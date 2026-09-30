---
name: laforge-ops
description: "Contraintes d'exécution dans Nokido : interpréteur LAFORGE_PYTHON, lancement des tests, erreurs \"Tool execution failed\" / \"Hub error 400\". À charger avant de lancer du Python ou pytest sur le dépôt, ou sur une panne du hub ou du pont MCP."
---

# LaForge Ops — Contraintes et Bonnes Pratiques

## ⚠️ Contrainte d'exécution Python (LAFORGE_PYTHON)

LaForge tourne sous miniforge3 (`~/miniforge3/python.exe`).
**JAMAIS** appeler `python script.py` brut depuis bash/PowerShell —
le PATH peut résoudre vers `AppData/Roaming/Python/Python312` qui a
des packages divergents (incident anyio 2026-04-29).

**Toujours** :
- Code Python : `from forge_python_bin import LAFORGE_PYTHON, run_python`
- Tests : `PYTHONNOUSERSITE=1 ~/miniforge3/python.exe -m pytest` (depuis Nokido/)
- Subprocess : `run_python(["-m", "py_compile", path])` au lieu de
  `subprocess.run(["python", ...])`

Source de vérité : `app/forge_python_bin.py::LAFORGE_PYTHON`.
Détails : CLAUDE.md §11.
