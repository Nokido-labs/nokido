# Backlog Sécurité MCP - Investigation 2026-04-28

## État actuel (audit complet)

### Ce qui EXISTE et fonctionne

1. **SecretGuard** : bloque lecture de fichiers sensibles (Nokido.env, .env, *_creds*)
   via `assert_can_write` qui appelle `safe_path` + SecretGuardViolation
   
2. **AST Guard** : tout write sur `forge_*.py` passe par `compile(content)` avant écriture
   => empêche injection de code syntaxiquement invalide
   
3. **DangerGuard code scan** : patterns dangereux bloqués (os.system, eval, exec, rm -rf)
   => SAUF si FORGE_DEV_MODE=1 (mode dev assoupli, uniquement eval/exec/__import__)

4. **Path sandboxing** : `safe_path()` vérifie que tout write reste sous ROOT
   => traversal `../` bloqué

5. **Audit log** : `logs/mcp_audit.log` append-only, non modifiable par les agents
   => traçabilité de chaque appel ALLOW/BLOCK

6. **_AGENT_TOKENS** : chaque agent a son propre token Bearer dans nokido_hub.py
   => identification forte par hmac.compare_digest

7. **RBAC** : `forge_rbac.py` avec check capability par tool (forge_mcp_registry RBAC DENY)

### Ce qui MANQUE (gaps identifiés)

#### GAP CRITIQUE 1 : forge_mcp_registry.py et nokido_hub.py sont modifiables

```python
# Situation actuelle :
assert_can_write("app/forge_mcp_registry.py", "GEMINI", ring=0)
# -> passe ! Ces fichiers ne sont PAS dans la liste noire de SecretGuard

# Impact : n'importe quel agent Ring 0 (GEMINI, CLINE, CLAUDE) peut
# modifier le registre MCP qui définit TOUS les handlers
# => modification silencieuse de la gouvernance du hub
```

#### GAP 2 : MCPSecurity._RIGHTS ne bloque pas Gemini sur write

```python
"gemini": "ollama",  # Gemini mappé comme "ollama"
"ollama": {"read": ["*"], "query": ["*"], "write": ["shadow_mutation"]},
# => Gemini peut écrire seulement dans shadow_mutation selon MCPSecurity
# MAIS MCPSecurity n'est PAS utilisé dans handle_write ! Guard() l'est.
# Guard() n'a PAS de liste de fichiers protégés.
```

#### GAP 3 : Les tokens _AGENT_TOKENS sont en clair dans nokido_hub.py

```python
_AGENT_TOKENS = {
    "GEMINI": "0ce30fa9...",  # visible dans le code source
    "CLAUDE": "...",
}
# Tout agent qui peut lire nokido_hub.py récupère les tokens de tous les autres.
```

#### GAP 4 : Pas de rate limiting par agent sur les writes

Un agent ring 0 peut écrire 1000 fichiers par minute sans aucune throttle.

## Plan correctif (priorité décroissante)

### P0 - Liste noire fichiers critiques dans SecretGuard (30min)

Ajouter dans `forge_mcp_security.py` une constante :

```python
# Fichiers critiques : modification réservée à RING_0 HUMAIN (pas aux agents LLM)
# Même Ring 0 agent ne peut PAS écrire ces fichiers via MCP write()
CRITICAL_FILES = {
    "tools/nokido_hub.py",           # cœur du hub
    "app/forge_mcp_registry.py",      # registre des handlers
    "app/forge_mcp_security.py",      # le guard lui-même
    "app/forge_rbac.py",              # contrôle d'accès
    "app/forge_auth.py",              # authentification
    "app/web_hub/auth.py",            # JWT
    ".env",                           # secrets
    "Nokido.env",                    # secrets
}
```

Dans `assert_can_write` : si path dans CRITICAL_FILES -> SecretGuardViolation.

Exception : si `LAFORGE_ALLOW_CRITICAL_WRITE=1` dans l'env (mode maintenance manuelle).

### P1 - Migrer _AGENT_TOKENS vers keyring/env (1h)

```python
# Au lieu de :
_AGENT_TOKENS = {"GEMINI": "0ce30fa9..."}

# Charger depuis keyring ou .env au démarrage :
import keyring
_AGENT_TOKENS = {
    "GEMINI": keyring.get_password("laforge", "TOKEN_GEMINI") or os.environ.get("TOKEN_GEMINI"),
    "CLAUDE": keyring.get_password("laforge", "TOKEN_CLAUDE") or os.environ.get("TOKEN_CLAUDE"),
    ...
}
```

### P2 - Rate limiting write par agent (30min)

Token bucket par agent : max 20 writes/min (ajustable par ring).

### P3 - MCPSecurity intégré dans handle_write (30min)

Brancher MCPSecurity.check_rights() dans handle_write avant assert_can_write :

```python
# Dans handle_write :
sec = MCPSecurity()
role = sec._resolve_role(agent)  # gemini -> ollama -> write: [shadow_mutation]
allowed, reason = sec.check_rights(role, "write", path_str)
if not allowed:
    return f"RBAC_DENIED: {reason}"
```

## Décision

P0 est la seule correction urgente. P1/P2/P3 en backlog beta.
P0 n'impacte PAS les workflows normaux (Claude, Gemini, Cline ne modifient
pas forge_mcp_registry.py en usage normal - seulement moi [Claude] lors des sprints
et encore, c'est toi qui valides explicitement chaque sprint).
