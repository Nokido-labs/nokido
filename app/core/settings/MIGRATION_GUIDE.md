# Migration vers app.core.settings

## Contexte

`forge_settings.py` a un fan-in de **34** imports (le plus sollicite du projet).
Gemini a identifie ce module comme le plus dangereux a modifier : un bug ici
se propage a toute l'application.

## Strategie de migration (non-breaking)

Pour REDUIRE progressivement le fan-in, les nouveaux modules et les modules
modifies doivent utiliser `app.core.settings` au lieu de `forge_settings`
directement.

## Table de correspondance

| AVANT (forge_settings) | APRES (app.core.settings) |
|---|---|
| `from forge_settings import Settings` | `from app.core.settings import Settings` |
| `from forge_settings import create_settings` | `from app.core.settings import create_settings` |
| `from forge_settings import get_settings` | `from app.core.settings import get_settings` |
| `from forge_settings import get_app_attr` | `from app.core.settings import get_app_attr` |
| `from forge_settings import _SETTINGS_FIELDS` | `from app.core.settings import ALL_FIELDS` |
| `from forge_settings import _SETTINGS_FIELDS` (filtree manuellement) | `from app.core.settings import OLLAMA_FIELDS, RAG_FIELDS, SSH_FIELDS, ...` (split par domaine) |

## Avantages du nouveau pattern

- **Couplage reduit** : si tu n'as besoin que de OLLAMA_FIELDS, tu n'importes que ca
- **Monkey-patching facilite** pour tests : mock de `app.core.settings.get_settings` plus stable
- **Migration progressive** : les 39 consommateurs peuvent basculer module par module
- **Preparation DI** : futur remplacement de `get_settings()` par injection via DI container

## Domaines disponibles

Pour settings par domaine metier, cibler directement :

```python
from app.core.settings.fields import (
    SSH_FIELDS,      # 4 champs
    OLLAMA_FIELDS,   # 6 champs
    RAG_FIELDS,      # 5 champs
    RUNTIME_FIELDS,  # 3 champs
    LOOP_FIELDS,     # 3 champs
    AUTO_FIELDS,     # 1 champ
    ALERTING_FIELDS, # 1 champ (Slack)
    TIME_FIELDS,     # 1 champ
    ENV_FIELDS,      # 1 champ
    DB_FIELDS,       # 1 champ
    ALL_FIELDS,      # tous les 26
    BY_DOMAIN,       # dict des 10 domaines
)
```

## Plan de reduction du fan-in

**Objectif** : passer de `forge_settings: fan-in=34` vers `<20`.

### Vague 1 (prochaine session) - modules a 1 symbole

Cibler les modules qui n'importent QU'UN symbole. Ils sont faciles a migrer.
Candidats identifies (29 modules) :
- `forge_agents.py`, `forge_agent_benchmarker.py`, `forge_agent_hardware.py`, `forge_agent_roles.py`
- `forge_collab_modes.py`, `forge_compose.py`, `forge_disco.py`
- `forge_dispatch_ai.py`, `forge_dispatch_network.py`
- etc.

### Vague 2 - modules a 2 symboles

- `forge_app_context.py` (Settings, create_settings)
- `forge_startup.py` (create_settings, get_app_attr)

### Vague 3 - modules a 3+ symboles

- `Nokido.py` (5 symboles) -> utiliser via app.core.settings ou via facade

## Verification

Apres chaque migration, verifier :

```bash
# Le module cible ne compile plus si forge_settings est renomme temporairement
python -m py_compile app/nouveau_module.py

# Les tests NR passent toujours
pytest tests/nr -v

# Fan-in de forge_settings en baisse
python tools/analyze_imports.py forge_settings  # (TODO : script a creer)
```
