# Nokido ↔ GitHub Copilot CLI — intégration

État par direction (cf memory `copilot_cli_integration_2026-06-03`, plan groundé doc officielle).

| Dir | Quoi | État |
|---|---|---|
| **D** | `AGENTS.md` racine (conventions Nokido) | ✅ livré (commit `53ad44f8`) |
| **C** | Hub `:8766` MCP consommé PAR Copilot | 📋 config ci-dessous (action user) |
| **A** | Copilot comme provider free-tier DANS forge_agent_proxy | ⏳ à coder |
| **B** | Nokido comme provider modèle DE Copilot | ⏳ à valider (:7777 stream+tools+128k) |

---

## D — AGENTS.md (fait)

`AGENTS.md` à la racine Nokido : `@RULES_SHARED.md` + specifics Copilot. Copilot CLI lit
`AGENTS.md` (Git root/cwd) → suit les règles Nokido (hub-first, `LAFORGE_PYTHON`, anti-dup,
firewall cloud) dès l'install. Rien à faire.

---

## C — Hub Nokido comme serveur MCP de Copilot (action user)

Le hub `:8766` est déjà un serveur MCP (Gemini CLI + Claude Desktop le consomment via
`tools/mcp_stdio_bridge.py`). On branche Copilot CLI dessus → il gagne `read`/`run`/`rag`/
`query`/`ctf`/… + le pipeline souverain.

### Option 1 — bridge stdio (RECOMMANDÉ, déjà prouvé)

Réutilise `mcp_stdio_bridge.py` (le token `FORGE_MCP_TOKEN` est lu en interne depuis le vault,
rien à embarquer). Config MCP Copilot (fichier `~/.copilot/mcp-config.json` — **vérifier le
chemin/clé exacts via `/mcp` au 1er run**, doc MCP pas re-fetchée) :

```json
{
  "mcpServers": {
    "laforge": {
      "command": "~/miniforge3/python.exe",
      "args": ["~/Script python IA/Nokido/tools/mcp_stdio_bridge.py"]
    }
  }
}
```

### Option 2 — HTTP distant (si Copilot CLI supporte remote MCP)

Le hub expose Streamable HTTP. Pointer directement :

```json
{
  "mcpServers": {
    "laforge": {
      "type": "http",
      "url": "http://127.0.0.1:8766/mcp",
      "headers": { "Authorization": "Bearer <FORGE_MCP_TOKEN>" }
    }
  }
}
```

### Option 3 — interactif

Dans une session `copilot` : `/mcp` (wizard add). Pointer sur la commande de l'Option 1.

### Vérifier

```
copilot                      # ouvre session
/mcp                         # 'laforge' listé + tools chargés
> liste les domaines RAG via le tool nokido       # doit appeler le hub
```

Scoper les permissions : `--allow-tool='laforge'` (auto-approve tools Nokido),
`--deny-tool=...` pour les outils sensibles.

---

## A — Copilot provider free-tier dans forge_agent_proxy (à coder)

`CopilotCLIProvider` calqué sur `gemini_cli`/`claude_cli` (cf memory
`forge_handoff_multiprovider`). `ask()` spawn :

```
copilot -p "{safe_prompt}" --deny-tool='shell(git push)' --allow-tool='shell(git:*)'
```

- **Contexte d'exec** : session **user** (auth GitHub + `~/.copilot` y vivent ; `copilot`
  invisible côté LaForgeTrusted — vérifié). JAMAIS trusted/sandbox.
- **Firewall** : sortie vers serveurs GitHub = egress cloud → `pre_flight`/`post_flight`
  OBLIGATOIRE (wrapper universel déjà en place) + membrane si data sensible.
- **Free-tier** : appels = *premium requests* (quota mensuel) → gate cloud-sur-demande.
- Parse stdout (pas de `--json` documenté ; à confirmer `copilot --help`).

## B — Nokido provider modèle DE Copilot (à valider)

`copilot help providers` → pointer Copilot sur `forge_openai_proxy :7777` (OpenAI-compat +
SemanticFirewall). Pré-requis durs : **streaming + tool-calling + ≥128k ctx**. Perd `/delegate`
(serveur GitHub) + coût caché. Toute la boucle agentique Copilot infère alors via Nokido.

---

## À vérifier (1 cmd chacun, côté user)

- `copilot --version` / `install-copilot-cli`
- `copilot --help` → format sortie `-p` (JSON ?)
- `copilot help providers` → schéma provider (dir B)
- `/mcp` in-session → chemin fichier config MCP exact (dir C)
- Quota Copilot Free actuel (premium requests/mois)
