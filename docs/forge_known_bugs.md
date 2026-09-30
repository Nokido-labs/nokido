# Nokido — Registre des erreurs récurrentes
*Mis à jour session 5 — 2026-04-27*
*Source : git log RAG + sessions Claude*

---

## PATTERN 1 : Bridge stdio bloquant (RÉCURRENT x3)
**Symptôme** : `→ tools/call id=N` sans `←`, timeout 2-8 min  
**Causes connues** :
- Keep-alive socket morte côté hub (idle >30s) → `getresponse()` bloque
- `trigger_autonomous_evolution` SSE stream sans timeout hard
- `_stdin_watchdog` volant les bytes JSON-RPC (fix commit 0a3d7e2d)
- `_get_conn()` singleton HTTPConnection (fix commit 8c428afc)
**Fix appliqué** : urllib.urlopen (connexion fraîche), timeout 30s, SSE timeout hard  
**Fichier** : `tools/mcp_stdio_bridge.py`  
**Détection** : `[SLOW]` dans `mcp_bridge.log` si lat >10s

---

## PATTERN 2 : `No module named 'app'` subprocess (RÉCURRENT x2)
**Symptôme** : `ERROR Nokido.AgentProxy — Provider ollama failed: No module named 'app'`  
**Cause** : Subprocess lancé sans `sys.path` incluant `app/` ; imports relatifs `collab_modes._participants`  
**Fix appliqué** : Import direct `forge_ollama` + injection `sys.path` dans `Ollama.ask()`  
**Fichier** : `app/forge_agent_proxy.py`  
**Fix générique** : Tout subprocess doit faire `sys.path.insert(0, str(ROOT/"app"))` en tête

---

## PATTERN 3 : UnicodeDecodeError cp1252 subprocess (RÉCURRENT x2)
**Symptôme** : `UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d`  
**Cause** : `subprocess.run(..., text=True)` sans `encoding=` hérite de cp1252 Windows  
**Fix appliqué** : `encoding='utf-8', errors='replace'` sur GeminiCLI, ClaudeCLI  
**Fichier** : `app/forge_agent_proxy.py`  
**Fix générique** : Tout `subprocess.run/Popen` avec `text=True` DOIT avoir `encoding='utf-8'`

---

## PATTERN 4 : network_log vide / _write_db silencieux (RÉCURRENT)
**Symptôme** : Dashboard `/forge/network` vide, `network_log` à 0 lignes  
**Cause** : INSERT avec colonnes absentes du schéma (`channel`, `provider`, `model`, `meta`, `session_id`)  
**Fix appliqué** : Migration ALTER TABLE ADD COLUMN sur `RAG/embeddings.db`  
**Fichier** : `tools/nokido_hub.py::_write_db`

---

## PATTERN 5 : Config `claude_desktop_config.json` écrasée (RÉCURRENT x4)
**Symptôme** : Tools MCP disparaissent au reboot  
**Cause** : Claude Desktop écrase `%APPDATA%\Roaming\Claude\` lors des updates  
**Fix appliqué** : `tools/forge_rescue.py --restore`  
**Prévention** : Ne jamais dépendre de ce fichier comme source de vérité unique

---

## PATTERN 6 : Imports relatifs cassés hors package (RÉCURRENT x2)
**Symptôme** : `ImportError: attempted relative import with no known parent package`  
**Cause** : `from .module import X` dans un fichier importé top-level (pas via package)  
**Fix** : Toujours utiliser `from app.module import X` ou injection sys.path  
**Exemple** : commit caa51407 (forge_collab_modes)

---

## PATTERN 7 : 7 tools manquants dans hub dispatcher (x1 majeur)
**Symptôme** : `"Outil inconnu: poll"` alors que tools/list les déclare  
**Cause** : tools/list déclarait N tools mais `_tool_call()` n'en implémentait que N-7  
**Fix** : commit 4e7e39ca — ajout des 7 handlers manquants  
**Test** : Toujours vérifier que chaque tool déclaré a un handler dans `_tool_call()`

---

## PATTERN 8 : EventBus replay boucle infinie (x1)
**Symptôme** : Log identique répété x8-10 depuis 04:49  
**Cause** : Rotation à 5MB sans avancement du curseur → relecture infinie  
**Fix** : `f.seek(self._replay_cursor)` + `self._replay_cursor = f.tell()`  
**Fichier** : `forge_event_bus.py` ou `forge_state_manager.py`

---

## RÈGLES GÉNÉRIQUES DÉDUITES
1. `subprocess.run` avec `text=True` → toujours `encoding='utf-8', errors='replace'`
2. Subprocess qui importe du code Nokido → toujours `sys.path.insert(0, ROOT/"app")`
3. Tout tool déclaré dans `tools/list` → vérifier handler dans `_tool_call()`
4. SQLite INSERT → vérifier colonnes vs `PRAGMA table_info()` avant
5. SSE stream → toujours un timeout hard, jamais de lecture infinie
6. Bridge stdio → urllib.urlopen (pas HTTPConnection singleton)
7. Config Claude Desktop → jamais source de vérité, toujours `forge_rescue.py` en backup
