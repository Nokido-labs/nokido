<!-- DEPORTE depuis CLAUDE.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de CLAUDE.md, re-facture a chaque tour. -->

# 8. Stack services active (au 2026-05-07)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## 8. Stack services active (au 2026-05-07)

> ⚠️ **TABLE HISTORIQUE — la source de vérité des services est
> `proxy_deno/core/services.toml`** (88 services, flags `enabled`, hot-reload
> `/supervisor/reload`). Cette table date du 2026-05-07 et a été rustinée
> inline depuis ; pour l'état RÉEL d'un service (live/disabled), lire le
> `services.toml` ou `hub action=whoami` (`services_degraded`). Le chemin
> `config/services.toml` cité ailleurs N'EXISTE PAS (audit 2026-08-21).

Services NSSM geres par LaForge-Master supervisor :8765 :

| Service | Port | Role |
|---|---|---|
| LaForge-Master | :8765 | Supervisor — proprietaire exclusif LaForgeMCP |
| nokido_hub (LaForgeMCP) | :8766 | 13 tools MCP HTTP. ROOT auto-detect. ⚠ RAM optimisé à 98 Mo (faiss skip_emb sur sidecar vectoriel). |
| brain_worker | :5557 ZMQ | ⚠ DISABLED 2026-06-03 (ONNX BGE-M3 'bad allocation' OOM). Protocole §13 si réparé |
| NokidoLlamaEmbed | :8099 | ⚠ DISABLED 2026-08-10 (boot-trim RAM, save 2.5 Go). Embedder BGE-M3 local (woke on-demand) |
| NokidoLlamaReranker | :8100 | ⚠ DISABLED 2026-08-10 (boot-trim RAM, save 6.5 Go). Fallback Etage 1.5 Cloud Cohere (/v2/rerank) + Etage 2 Lexical. |
| NokidoGraphExplorer | :7474 | ⚠ DISABLED 2026-08-10 (boot-trim RAM, save 399 Mo). Cytoscape 3D graph web server (woke on-demand) |
| netcfg-agent UI | :7500 | uvicorn netcfg.views |
| netcfg-agent-mcp | :8767 | .exe compile v0.1.3, 9 tools netcfg_* |
| Deno Web Hub | :7401 | API evenementielle TypeScript + SSE |
| FastAPI Web Portal | :7400 | Dashboard + auth |
| ollama | :11434 | 12 modeles (laforge-qwen, deepseek-r1:14b, qwen2.5-coder:32b...) |
| lmstudio | :1234 | OpenAI-compat (backup local) |
| llamacpp_native | :8080 | qwen2.5-coder:7b-instruct-q4_K_M, ~5s/42tok CPU |
| clawhub API | — | Skills marketplace |

Daemons Python (nohup / NSSM) :
- `tools/forge_embed_auto_trigger.py` — embed chunks NULL en continu (batch 200, 20/submit, ~48k/h)
- `tools/forge_auto_compact.py` — compaction RAG 30min cycle
- `tools/forge_auto_evolution_loop.py` — heartbeats 10min + lessons 30min
- `tools/gemini_poll_daemon.py` — polling Gemini CLI autonome

Clients MCP :
- Claude Desktop (STDIO local, 13 tools)
- Gemini CLI (HTTP Bearer, 24 tools via Hub)
- Cline (Nokido_Plan / Nokido_Act)

---

