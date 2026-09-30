<!-- DEPORTE depuis CLAUDE.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de CLAUDE.md, re-facture a chaque tour. -->

# 11. Contrainte d execution Python (LAFORGE_PYTHON)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## 11. Contrainte d execution Python (LAFORGE_PYTHON)

Nokido tourne sous miniforge3. Tout interpreteur Python ambigu (PATH,
user-site `AppData/Roaming/Python/Python312`) introduit du chaos :
versions de packages divergentes, anyio cassé, pytest qui charge le
mauvais site-packages, etc.

**Incident vecu (2026-04-29)** : `python -m pytest` dans bash a resolu
`python` vers miniforge3 mais pytest a charge starlette du user-site,
qui depend d un anyio corrompu (Permission denied sur miniforge3 + namespace
package vide cote user-site). Tests bloques.

### Constante canonique

```
LAFORGE_PYTHON = "~/miniforge3/python.exe"
```

Source de verite Python : `app/forge_python_bin.py::LAFORGE_PYTHON`
(override via env var `LAFORGE_PYTHON_BIN` si besoin).

### Regles strictes

1. **JAMAIS** `python script.py` brut. **TOUJOURS**
   `LAFORGE_PYTHON script.py`.
2. **JAMAIS** `python3` brut.
3. Pour pytest, lancer via :
   ```bash
   PYTHONNOUSERSITE=1 "~/miniforge3/python.exe" -m pytest <args>
   ```
   ou utiliser le wrapper `run_tests.bat`.
4. Dans le code Python Nokido, utiliser
   `from forge_python_bin import LAFORGE_PYTHON, run_python` au lieu
   de `subprocess.run(["python", ...])`.
5. **Tool MCP `run` action=python** : deja propre — utilise
   `os.sys.executable` du hub (lui-meme = miniforge3 via
   `nokido_bridge.bat`).

### Ce qui est deja sain (verifie 2026-04-29)

- `nokido_bridge.bat`, `netcfg_bridge.bat` : chemin absolu miniforge3
- `cline_mcp_settings.json` (Nokido_Plan / Nokido_Act) : idem
- `forge_mcp_registry.py` action=python : `os.sys.executable`
- `forge_desktop/main.py` : `python = sys.executable` (herite)

### Ce qui reste a fixer (TODO)

- `app/forge_handler_advanced.py:193` : Commit Guard AST avec `python`
  brut → patcher avec `LAFORGE_PYTHON`
- `app/forge_handler_build.py:63` : idem
- `forge_desktop/core/mcp_connector.py:65,260` : default `command="python"`
  → changer en `LAFORGE_PYTHON`

---

