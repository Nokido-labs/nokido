---
name: laforge-quota
description: Gestion quota Gemini CLI. Pools séparés Flash/Pro/Preview. Sélection auto modèle. Reporter quota réel au hub.
---

# LaForge Quota — Gestion Modèles Gemini

## Règle fondamentale au boot

```python
# TOUJOURS en premier à chaque session
import os, subprocess
subprocess.run([os.path.expanduser('~/miniforge3/python.exe'), 'tools/hub_call.py', 'quota_model', 'quality=medium', 'apply=true'],
    cwd=os.path.expanduser(r'~\Script python IA\Nokido'))
```

## Reporter le quota réel (après /model dans CLI)

```python
import os, subprocess
subprocess.run([os.path.expanduser('~/miniforge3/python.exe'), 'tools/hub_call.py', 'quota_report',
    'flash=100', 'flash_lite=23', 'pro=0', 'preview_pro=0'],
    cwd=os.path.expanduser(r'~\Script python IA\Nokido'))
```

## Niveaux de qualité

| Niveau | Modèle prioritaire | Quand |
|--------|-------------------|-------|
| ultra/high | gemini-3.1-pro-preview | Raisonnement complexe |
| medium | gemini-2.5-flash-lite | Usage général |
| low | gemini-2.5-flash-lite | Poll, routing léger |
| local | groq / llamacpp | Fallback hors quota Google |

## Si erreur 429

```python
import os, subprocess
subprocess.run([os.path.expanduser('~/miniforge3/python.exe'), 'tools/hub_call.py', 'quota_model', 'quality=low', 'apply=true'],
    cwd=os.path.expanduser(r'~\Script python IA\Nokido'))
```

## Pools quota (indépendants)

- Flash 2.5 + Flash-Lite = **même pool** (reset 12h)
- Pro 2.5 = pool séparé (reset 24h)
- Pro 3.1 preview = **pool totalement séparé** (reset 24h)
- 0% utilisé dans /model = vraiment disponible
