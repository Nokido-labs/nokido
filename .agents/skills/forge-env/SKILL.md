---
name: forge-env
description: "À utiliser avant d'exécuter un script, de lire la base RAG ou un journal, ou face à une erreur de chemin, un PermissionError ou un accès refusé depuis un compte restreint. Donne les chemins et constantes canoniques (LAFORGE_PYTHON, dépôt, bases), les comptes d'exécution (owner, bac à sable du hub) et les voies gouvernées pour agir sur les services."
---

# LaForge — Environnement Système

## Chemins critiques

```
PYTHON  = ~/miniforge3/python.exe   ← TOUJOURS utiliser celui-ci
NODE    = C:/Program Files/nodejs/node.exe
ROOT    = ~/Script python IA/Nokido
HOME    = ~
GEMINI  = ~/.gemini
HUB     = http://127.0.0.1:8766/mcp
```

## Token MCP Gemini

Lu depuis le coffre (`forge_secrets.get_secret`) ; jamais en clair dans un fichier que lit un modèle.

## Règles chemins

- Ne JAMAIS utiliser `python` seul → mauvais Python
- Toujours `~/miniforge3/python.exe`
- Pour run action=python → OK automatiquement (bon Python)
- Pour Shell → chemin absolu obligatoire

## Lancer scripts Python

```python
# Bon — via run action=python
run action=python code="import sys; print(sys.executable)"

# Bon — via Shell avec chemin absolu  
Shell: ~/miniforge3/python.exe tools/mon_script.py

# MAUVAIS — mauvais Python
Shell: python tools/mon_script.py
```

## Relay hub background

```python
import subprocess
from os.path import expanduser
p = subprocess.Popen(
    [expanduser('~/miniforge3/python.exe'),
     'tools/gemini_hub_relay.py', '--interval', '15'],
    cwd=expanduser('~/Script python IA/Nokido'),
    stdout=open(expanduser('~/Script python IA/Nokido/sandbox/gemini_hub_relay.log'),'a'),
    stderr=subprocess.STDOUT
)
print('Relay PID:', p.pid)
```

## Services

Source de vérité : `proxy_deno/core/services.toml`. État réel : `hub action=whoami`
(`services_degraded`) — un port qui répond ne prouve pas que le service travaille.

- **Hub :8766** : propriété exclusive du superviseur (LaForge-Master :8765). JAMAIS
  `nssm restart` direct (règle d'or : conflit de port, crash loop). Relance par
  `hub action=redemarrer_stack` (dialogue owner).
- **Service périphérique** (embedder, SearXNG, Docker, ollama, workers…) : le relever par
  `nokido_ensure_service{service, desired_state=running}`, idempotent. Sans demander s'il
  ne coupe aucun pair (cf. forge-autonomie).
- **netcfg-agent** : web :7500, MCP :8767.

## Accès fichiers — chemins absolus

Gemini CLI peut avoir des restrictions d'accès aux fichiers du projet.
Toujours utiliser **run action=python** avec des chemins absolus :

```python
# Lire quota_state.json
import json
from pathlib import Path
f = Path(r'~/Script python IA/Nokido/RAG/quota_state.json').expanduser()
print(json.loads(f.read_text()) if f.exists() else 'absent')

# Lire embeddings.db
import sqlite3
conn = sqlite3.connect(Path(r'~/Script python IA/Nokido/RAG/embeddings.db').expanduser())
rows = conn.execute('SELECT COUNT(*) FROM rag_chunks').fetchone()
conn.close()
print(rows)

# Lire les logs
from pathlib import Path
log = Path(r'~/Script python IA/Nokido/sandbox/hub.log').expanduser()
print(log.read_text(encoding='utf-8', errors='replace')[-2000:])
```

## Règle générale
Si FindFiles ou read_file échoue → run action=python avec chemin absolu, pour les fichiers du dépôt.
run action=python tourne sous un compte de bac : il ne lit pas le profil owner (~/.claude, ~/.local → PermissionError).
