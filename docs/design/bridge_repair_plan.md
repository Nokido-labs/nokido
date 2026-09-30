# Plan de Réparation du Bridge MCP (tools/mcp_stdio_bridge.py)

**Statut actuel** : CRITIQUE
- **Encoding** : Double-mojibake (UTF-8 lu comme CP1252 puis ré-encodé).
- **Bug Runtime** : `NameError: name '_bridge_log' is not defined` à la ligne 348.
- **Régression** : Le commit `0e038b5` a supprimé `os.execv`, rendant le fallback inopérant (boucle infinie d'erreurs au lieu de bascule stdio).

---

## 1. Objectifs
1.  **Nettoyage Encoding** : Restaurer un fichier UTF-8 propre sans caractères corrompus.
2.  **Implémentation `_bridge_log`** : Ajouter la fonction manquante pour le logging SQLite et le heartbeat.
3.  **Restauration Fallback** : Rétablir la bascule vers `nokido_mcp_server.py` via `os.execv` si le hub est DOWN.
4.  **Stabilité** : Assurer que `py_compile` ET le runtime sont nominaux.

---

## 2. Étapes de Réalisation

### Étape A : Correction de l'encodage (UTF-8)
- Identifier et remplacer tous les motifs mojibake (ex: `Ã ` -> `à`, `Ã©` -> `é`, `â€”` -> `—`).
- S'assurer que le header `# -*- coding: utf-8 -*-` est respecté par l'éditeur.

### Étape B : Définition de `_bridge_log`
Ajouter la fonction suivante avant `_handle_single` :
```python
def _bridge_log(method: str, tool: str, latency_ms: float, response: bytes, req_id: Any):
    """Log l'appel dans network_log.db et met à jour le heartbeat du bridge."""
    try:
        import sqlite3
        db_path = _ROOT / "data" / "network_log.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(db_path), timeout=5) as conn:
            # 1. Insert log
            conn.execute(\"\"\"
                INSERT INTO bridge_logs (ts, method, tool, latency_ms, status, req_id)
                VALUES (datetime('now'), ?, ?, ?, ?, ?)
            \"\"\", (method, tool, latency_ms, "OK" if response else "ERR", str(req_id)))
            # 2. Heartbeat (last_seen)
            conn.execute(\"\"\"
                INSERT INTO bridge_status (id, last_seen) VALUES ('stdio_bridge', datetime('now'))
                ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen
            \"\"\" )
            conn.commit()
    except Exception as e:
        logger.error(f"bridge_log error: {e}")
```

### Étape C : Restauration du Fallback (Revert partiel 0e038b5)
Modifier `_fallback_stdio()` pour réintroduire l'exécution directe du serveur si le hub est injoignable :
```python
def _fallback_stdio():
    \"\"\"Hub indisponible - exécute le serveur MCP local directement (stdio).\"\"\"
    logger.warning("Hub DOWN - Bascule sur serveur local (stdio)")
    server_py = _ROOT / "app" / "nokido_mcp_server.py"
    if not server_py.exists():
        logger.error(f"Serveur local non trouvé: {server_py}")
        sys.exit(1)
    
    # Remplacement du process actuel par le serveur MCP
    os.execv(sys.executable, [sys.executable, str(server_py)])
```

### Étape D : Validation
1.  **Validation Statique** : `python -m py_compile tools/mcp_stdio_bridge.py`.
2.  **Test Hub UP** : Lancer le bridge manuellement, vérifier que `_bridge_log` écrit en DB.
3.  **Test Hub DOWN** : Couper le service NSSM, lancer le bridge, vérifier l' `os.execv`.

---

## 3. Risques et Rollback
- **Risque** : `os.execv` sur Windows peut se comporter différemment selon l'environnement Python.
- **Rollback** : Utiliser la sauvegarde `sandbox/backups/bridge-20260427-164932/mcp_stdio_bridge.WORKING_TREE.py`.

---
*Plan rédigé par Gemini CLI - 2026-04-28*
