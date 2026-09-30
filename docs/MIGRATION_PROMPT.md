# PROMPT DE MIGRATION — Session Nokido 2026-04-29

## CONTEXTE RAPIDE
Tu reprends une session de développement du hub Nokido multi-agents.
Gemini CLI tourne en parallèle et attend des tâches.
Lis d'abord le snapshot complet :
```
query sql="SELECT text FROM rag_chunks WHERE id='snapshot_20260429'"
```

## ÉTAT SYSTÈME
- Hub Nokido :8766 UP (PID actif)
- Bridge STDIO Claude → Hub : OK
- Gemini CLI actif, OAuth Google, flash-lite ~52% utilisé
- Policy Engine : codebase_investigator bloqué (nokido.toml)
- GEMINI.md allégé (1118 chars) + 6 skills MCP

## CE QUI A ÉTÉ FAIT CETTE SESSION
- forge_quota_manager.py — pools quota séparés Flash/Pro/Preview
- quota_hook.py v3 — SessionStart injecte BOOT CONTEXT dans GEMINI.md
- hub action=quota_model + quota_report dans schema MCP (forge_mcp_registry.py)
- hub_call.py — interface CLI universelle pour actions MCP avancées
- tools/hub_call.py — toutes les actions hub/ask/rag/query en une commande
- /gui/sidebar + /api/ingest — interface Firefox + ingestion centralisée
- forge_inspector.py patché — faux positifs netcfg corrigés via netcfg_ping MCP
- .gemini/policies/nokido.toml — Policy Engine, bloque codebase_investigator
- .geminiignore — override .gitignore, autorise RAG/ à Gemini
- 6 skills MCP : laforge-hub, laforge-env, laforge-autonomie, laforge-quota, laforge-pipeline, laforge-quota-new
- docs/GEMINI_CLI_HOOKS.md créé et indexé RAG

## PRIORITÉ 1 — RELAY PTY (R2)
C'est le blocage principal. Sans relay PTY stable, Gemini ne peut pas
recevoir de tâches automatiquement.

Fichier : tools/gemini_hub_relay.py v3 (winpty PTY)
Problème : winpty.PtyProcess.spawn() — à tester

Test :
```python
import subprocess
p = subprocess.Popen(
    [r'~/miniforge3/python.exe',
     'tools/gemini_hub_relay.py', '--interval', '15'],
    cwd=r'~/Script python IA/Nokido',
    stdout=open('sandbox/relay_test.log', 'w'),
    stderr=subprocess.STDOUT
)
print('PID:', p.pid)
```

Lire les logs après 30s :
```python
print(open('sandbox/relay_test.log').read())
```

## PRIORITÉ 2 — HOOK SessionEnd Claude
Ajouter système_rules tag=session.automation :
Quand Claude se coupe → mettre à jour snapshot_20260429 automatiquement.
Récupérable via : query sql="SELECT content FROM system_rules WHERE tag='session.automation'"

## PRIORITÉ 3 — HEARTBEAT GEMINI
fleet_heartbeats figés depuis restart hub.
Gemini doit écrire son heartbeat toutes les 30s.
Ajouter dans quota_hook.py :
```python
hub_call("hub", {"action":"notify", "message":"[GEMINI][HB] alive"})
```
Et dans forge_inspector.py : détecter heartbeat Gemini pour savoir s'il est vivant.

## RÈGLES IMPORTANTES

### Python — TOUJOURS chemin absolu
```
~/miniforge3/python.exe
```
Jamais `python` seul dans Shell — mauvais Python.
Toujours `run action=python` du hub MCP.

### Quota Gemini — pools séparés
- Flash 2.5 + Flash-Lite = même pool (reset 12h)
- Pro 3.1 preview = pool SÉPARÉ intact (0% utilisé)
- 0% = vraiment disponible (pas inconnu)
- ❓ = inconnu car logs.json vide

### Schema MCP — restart obligatoire
Si action hub manque dans enum → redémarrer le launcher.
Gemini cache le schema au boot.

### notify vs agent_messages
- notify → s'affiche immédiatement dans le terminal Gemini
- Mais ne pas mettre de code Python avec guillemets dans notify → parsing cassé
- Pour messages complexes : INSERT dans agent_messages + Gemini fait hub action=poll

### Policy Engine
Fichier : ~/.gemini/policies/nokido.toml
codebase_investigator et invoke_agent = DENY (pompent quota Pro inutilement)

## COMMANDES UTILES
```
# Vérifier état hub
run action=python code="import urllib.request,json; print(json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health').read()))"

# Lire logs relay
run action=python code="print(open('sandbox/relay_test.log','r',errors='replace').read()[-2000:])"

# Snapshot complet
query sql="SELECT text FROM rag_chunks WHERE id='snapshot_20260429'"

# Heartbeats
query sql="SELECT node_id,status,last_ping_at FROM fleet_heartbeats ORDER BY last_ping_at DESC LIMIT 5"

# Messages Gemini non lus
query sql="SELECT from_agent,created_at,substr(payload,1,200) FROM agent_messages WHERE to_agent='agt_gemini' AND status='unread' ORDER BY created_at DESC LIMIT 5"
```

## GEMINI EN ATTENTE
Gemini attend des tâches. Pour lui envoyer :
```python
import sqlite3, json
conn = sqlite3.connect('RAG/embeddings.db')
conn.execute("INSERT INTO agent_messages(from_agent,to_agent,method,payload,status,created_at) VALUES('agt_claude','agt_gemini','tool.hub.arg.message',?,?,datetime('now'))",
    (json.dumps({"text": "TA TÂCHE ICI"}), "unread"))
conn.commit()
```
Puis dire à Gemini : hub action=poll

Bonne session !
