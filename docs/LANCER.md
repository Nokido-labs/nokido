# Nokido — Comment lancer

## 1. Premier lancement — config token

Le hub exige un **token admin** pour sécuriser l'accès. À ajouter dans
`Nokido.env` à la racine (une seule fois) :

```
LAFORGE_ADMIN_TOKEN=un-secret-long-et-aleatoire-minimum-32-chars
```

Pour générer un token solide :

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Colle la sortie dans `Nokido.env` à côté des autres clés existantes.

**Sécurité** : `Nokido.env` est déjà dans `.gitignore` (pas commité),
et `tools/nokido.py` charge ce fichier automatiquement au démarrage via
`app/web_hub/envfile.py` (zero dependence, override=False).

## 2. Démarrage au double-clic

Quatre raccourcis `.cmd` à la racine :

| Fichier | Ce qu'il fait |
|---|---|
| **`laforge-start.cmd`** | Diagnostic → start hub+modules → ouvre navigateur |
| `laforge-stop.cmd` | Arrêt propre de tous les modules |
| `laforge-open.cmd` | Ouvre juste le navigateur |
| `laforge-status.cmd` | Affiche l'état + pause |

→ Double-clic sur `laforge-start.cmd` et c'est parti.

## 3. Raccourcis Bureau (optionnel)

Pour avoir les boutons directement sur ton Bureau :

```powershell
powershell -ExecutionPolicy Bypass -File tools/install_shortcuts.ps1
```

Crée 4 `.lnk` sur le Desktop avec icônes.

## 4. URL du hub

Une fois lancé :

- **http://localhost:7400/** — dashboard principal
- **http://localhost:7400/launcher** — pilotage des modules
  (Start / Stop / Logs live / Ouvrir)
- **http://localhost:7400/ctf/** — CTF Runner
- **http://localhost:7400/tui/** — Terminal xterm.js (si tui_bridge running)

Login : colle ton `LAFORGE_ADMIN_TOKEN` dans le formulaire.

## 5. CLI (sans raccourci)

```bash
python tools/nokido.py doctor     # diagnostic deps + ports + token
python tools/nokido.py up         # start hub + modules
python tools/nokido.py status     # vue d'ensemble
python tools/nokido.py open       # navigateur
python tools/nokido.py down       # arrêt
python tools/nokido.py logs <module> -n 100
```

Pilotage module-par-module :

```bash
python tools/nokido_modules.py start tui_bridge
python tools/nokido_modules.py restart recon
```

## 6. Activer le Watcher auto-restart (optionnel, sécurité)

Par défaut le watcher est **désactivé** (fail-closed). Une fois loggué
dans le hub, dans la console du navigateur (F12) :

```javascript
await fetch("/api/config", {
  method: "PATCH",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({enable_watcher: true, enable_remote_start: true})
});
await fetch("/api/watcher/start", {method: "POST"});
```

Ou via la CLI plus tard (un script wrapper à faire si besoin).

## 7. Logs et fichiers runtime

- `sandbox/run/<module>.pid` — PID + start_time + cmd (JSON)
- `sandbox/logs/<module>.log` — stdout+stderr append
- `sandbox/audit/launcher.log` — audit start/stop (JSONL)
- `sandbox/audit/watcher.log` — audit auto-restart (JSONL)
- `sandbox/audit/config.log` — audit modifs config (JSONL)
