---
name: laforge-hub
description: Accès au hub LaForge. Tools MCP disponibles + actions non exposées dans le schema. Pattern hub_call.py pour actions avancées.
---

# LaForge Hub — Tronc Cérébral

Hub MCP : http://127.0.0.1:8766/mcp (configuré dans settings.json)

## Actions MCP directes (dans le schema)

```
hub action=poll                     → messages en attente
hub action=notify message="..."     → envoyer message inter-agents
hub action=whoami                   → contexte agent complet
hub action=list_providers           → providers LLM disponibles
```

## Actions avancées NON dans le schema MCP

Ces actions existent dans le hub mais Gemini CLI ne les voit pas via tools/list.
**Ne jamais essayer de les appeler via le tool hub directement — utiliser hub_call.py.**

```
quota_model  quality=high|medium|low  apply=true   → sélection auto modèle Gemini
quota_report flash=X flash_lite=Y pro=Z preview_pro=W → reporter quota réel
```

## Pattern hub_call.py — LA bonne méthode

```python
# Via run action=python
import subprocess
r = subprocess.run(
    ['python', 'tools/hub_call.py', 'quota_model', 'quality=medium', 'apply=true'],
    capture_output=True, text=True,
    cwd=r'~\Script python IA\Nokido'
)
print(r.stdout)
```

Exemples hub_call.py :
```
python tools/hub_call.py poll
python tools/hub_call.py quota_model quality=medium apply=true
python tools/hub_call.py quota_report flash=100 flash_lite=23 pro=0 preview_pro=0
python tools/hub_call.py notify message="[GEMINI][DONE] tache terminee"
```

## Quota — Pools séparés (ne pas confondre)

| Pool | Modèles | Reset |
|------|---------|-------|
| flash_25 | gemini-2.5-flash + flash-lite | 12h |
| pro_25 | gemini-2.5-pro | 24h |
| preview_pro | gemini-3.1-pro-preview | 24h — POOL SÉPARÉ |

**Si Flash 100% épuisé → Pro 3.1 preview est intact (pool différent).**
0% dans /model = vraiment disponible, pas "inconnu".

## Snapshot système

```
query sql="SELECT text FROM rag_chunks WHERE id='snapshot_20260429'"
```

## Appeler d'autres LLM via le hub

Le hub route vers tous les providers via le tool `ask` :

```python
# Groq — llama-3.3-70b rapide
python tools/hub_call.py ask provider=groq message="ta question"

# Mistral
python tools/hub_call.py ask provider=mistral message="ta question"

# LLM local (llamacpp/LM Studio)
python tools/hub_call.py ask provider=llamacpp message="ta question"

# Ollama local
python tools/hub_call.py ask provider=ollama message="ta question"

# Claude (via API Anthropic)
python tools/hub_call.py ask provider=claude message="ta question"

# SambaNova
python tools/hub_call.py ask provider=sambanova message="ta question"
```

## Appeler Claude spécifiquement

```python
python tools/hub_call.py ask provider=claude message="[CLAUDE] question ou tache"
```

## Providers disponibles (ring 0)

| Provider | Modèle | Latence | Usage |
|----------|--------|---------|-------|
| groq | llama-3.3-70b | ~350ms | Rapide, général |
| mistral | mistral-large | ~450ms | Raisonnement |
| llamacpp | qwen3:8b | ~300ms | Local, privé |
| ollama | qwen3:8b | ~7s | Local lourd |
| sambanova | llama-3.3-70b | ~700ms | Backup |
| claude | sonnet | ~2s | Tâches complexes |

## Débat inter-agents

```python
python tools/hub_call.py agent_debate question="..." agents=groq,mistral
```

## RÈGLE CRITIQUE — Schema MCP et redémarrage

**Gemini CLI cache le schema MCP au démarrage.**
Si une action hub retourne "action inconnue" ou n'est pas dans l'enum :
1. Le hub a peut-être été mis à jour après le démarrage du CLI
2. **Solution : redémarrer le launcher** `python tools\gemini_launcher.py`
3. Le nouveau schema sera chargé avec toutes les actions disponibles

Ne jamais essayer de contourner via python -c ou shell — redémarrer le launcher.

## Actions hub disponibles (schema complet post-restart)

```
hub action=poll
hub action=notify message="..."
hub action=whoami
hub action=quota_model quality=medium apply=true
hub action=quota_report flash=X flash_lite=Y pro=Z preview_pro=W
hub action=list_providers
hub action=search_recent
hub action=emit_telemetry
```
