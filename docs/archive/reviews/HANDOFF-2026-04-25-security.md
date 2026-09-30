# HANDOFF — Session 2026-04-25 (Sécurité + Durcissement)
## Reprendre ici après le redémarrage

### État du repo (branche alpha)
- HEAD : `92ece0a` (pushé GitHub + Codeberg)
- Tag backup : `pre-rebase-2026-04-25` (ne pas supprimer)
- Mode Nokido : CHEF (lockdown — ne pas remettre en AUTO avant fin rotation clés)

### Ce qui est ACTIF après redémarrage
- ✅ SecretGuard branché dans forge_mcp_registry.py v3
  - `handle_read` → bloque Nokido.env + tous patterns sensibles
  - `handle_write` → bloque écriture sur fichiers sensibles
  - `handle_run python` → bloque code qui lit .env / dotenv / os.environ secrets
  - `handle_query` → bloque SELECT sur event_log / shared_prompt_log
  - Bypass officiel : LAFORGE_ALLOW_SECRETS_READ=1 (jamais par défaut)
- ✅ forge_secrets.py (abstraction WCM via keyring)
- ✅ migrate_secrets_to_wcm.py (script de migration prêt)
- ✅ Token codeberg retiré de .git/config (GCM-core prend le relais)
- ✅ Daemon Gemini tué (kill-gemini.ps1)
- ✅ Convention commits signés (docs/CONTRIBUTING.md)

### Ce qui reste à faire (dans cet ordre)

#### 1. Migration secrets Nokido.env → WCM (AVANT rotation)
```powershell
cd "~\Script python IA\LaForge"
# Migre les 6 secrets manquants dans WCM (option B : .env = vérité donc --force)
python tools/migrate_secrets_to_wcm.py --force
# Vérifier que tout est dans WCM
python app/forge_secrets.py diagnostic
```

#### 2. Wrapper PowerShell launch-nokido.ps1 (à créer)
Lira les secrets depuis WCM et les injectera en $env: avant de lancer Claude Desktop.
Pattern à créer dans tools/launch-nokido.ps1

#### 3. Sanitize Nokido.env (après migration validée)
```powershell
python tools/migrate_secrets_to_wcm.py --force --sanitize-env
```
⚠️ Crée un backup automatique avant modification.

#### 4. Restart service LaForgeMCP (pour activer SecretGuard côté hub HTTP)
```powershell
# Nécessite peut-être des droits admin
Restart-Service LaForgeMCP -Force
# Vérifier
Invoke-WebRequest http://127.0.0.1:8766/health -UseBasicParsing | Select StatusCode
```

#### 5. Rotation des 13 clés exposées (APRÈS durcissement complet)
Clés à rotater par priorité :
- 🔴 GITHUB_TOKEN ([REDACTED-PAT]) → github.com/settings/tokens
- 🔴 GITHUB_MODELS_TOKEN ([REDACTED-PAT]) → idem
- 🔴 LAFORGE_ADMIN_TOKEN + FORGE_MCP_TOKEN + MCP_DEV_SECRET → générer nouveaux
- 🟡 OPENROUTER_API_KEY → openrouter.ai/keys
- 🟡 XAI_API_KEY → console.x.ai
- 🟡 DEEPSEEK_API_KEY → platform.deepseek.com/api_keys
- 🟡 GEMINI_API_KEY → aistudio.google.com/apikey
- 🟡 GROQ_API_KEY → console.groq.com/keys
- 🟡 HF_TOKEN → huggingface.co/settings/tokens
- 🟡 CODEBERG_TOKEN → codeberg.org (settings/applications) ← déjà dans URL git, prioritaire
- 🟢 SMITHERY_API → smithery.ai

#### 6. Faux-positif SecretGuard à corriger (non-bloquant)
Pattern "credential manager" trop large dans forge_secret_guard.py ligne ~85.
Remplacer par `r"\bwin32cred\b"` uniquement. (le pattern `credential\s*manager` est trop général)

#### 7. Injection Claude Desktop (bug client)
- Cause confirmée : store Electron sérialisé dans messages sortants
- Rapport : docs/INCIDENT-2026-04-25-MCP-INJECTION.md
- Action : envoyer à support@anthropic.com ou security@anthropic.com
- Workaround temporaire : chercher Settings → Developer → toggle tool definitions

### Commits de la session (résumé)
```
92ece0a docs(security): rapport forensique injection MCP
13c8396 feat(security): SecretGuard centralise + integration registry
397983c docs(contributing): convention commits multi-agent
745c0d8 fix(web_hub): forge_feed.html oublie dans 0b27e3e
0de50f3 fix(registry): stdin=DEVNULL subprocess.run
c4c0241 feat(agent_proxy): +3 providers Cohere/Perplexity/Tavily
0a3d7e2 fix(mcp): retire _stdin_watchdog (cause du "could not attach")
```

### Fichiers M non committés restants
- app/mcp_bridge.py : fix PyCompileError lineno — propre, committable
- tools/nokido_stdio_bridge.py : bridge v17.04 dormant (Claude Desktop n'utilise pas ce bridge)

### Contacts pour reprise
- EventBus : event `security.incident.mcp_injection` (evt_20260425T135004_18b2)
- Notification envoyée à Gemini : lockdown CHEF maintenu
