# Nokido — Topologie runtime

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


Vue **processus / services / ports** — complémentaire de la carte anatomique
(`CLAUDE.md` §10, organes → modules). Ici : ce qui tourne réellement, qui
supervise quoi, sur quel port.

Source : `proxy_deno/core/supervisor.ts` (SERVICES + waves) + endpoint live
`GET http://127.0.0.1:8765/supervisor/status`. Snapshot **2026-05-20**.

## Diagramme

```mermaid
flowchart TD
    subgraph CLIENTS[Clients MCP]
        CD[Claude Desktop]
        GC[Gemini CLI]
        CL[Cline Plan/Act]
    end
    BR[mcp_stdio_bridge.py<br/>stdio - HTTP, agent=BRIDGE]
    CD -->|stdio| BR

    MASTER[LaForge-Master<br/>Deno supervisor<br/>proxy_deno/core/supervisor.ts<br/>ctrl :8765]

    subgraph W1[Wave 1 - Tronc cerebral]
        HUB[LaForgeMCP / hub<br/>nokido_hub.py :8766<br/>25 tools - RUNNING]
        OLL[NokidoOllama<br/>:11434 - RUNNING]
        NCP[NokidoNetcfgProxy<br/>RUNNING]
        NCM[NokidoNetcfgMCP<br/>:8767 - sleeping]
    end
    subgraph W2[Wave 2 - Proxy Deno]
        DPX[NokidoDenoProxy<br/>RUNNING]
        DHM[NokidoDenoHubMCP<br/>:8769 - sleeping]
    end
    subgraph W3[Wave 3 - Memoire / regulation]
        BW[NokidoBrainWorker<br/>brain_worker :5557 ZMQ<br/>BGE-M3 NPU - RUNNING*]
        HOM[NokidoHomeostasis<br/>sleeping]
    end
    subgraph W4[Wave 4 - Cognition / daemons]
        GEM[NokidoGeminiDaemon<br/>CRASH-LOOP x22]
        ING[NokidoIngestDaemon<br/>sleeping]
        AUTO[NokidoAutonomousLoops<br/>sleeping]
        HEB[NokidoHebbian / Graph / MultiLLM<br/>LlamaNative / LlamaRouter / LMStudio<br/>sleeping]
    end
    subgraph W5[Wave 5 - Web / peripherie]
        DWH[NokidoDenoWebHub<br/>:7401 - RUNNING]
        WH[NokidoWebHub<br/>:7400 - RUNNING]
        PERI[OpenAIProxy / RSSWatcher<br/>Capture / NetcfgUI :7500<br/>sleeping]
    end

    MASTER --> W1 --> W2 --> W3 --> W4 --> W5

    BR -->|HTTP :8766/mcp| HUB
    GC -->|HTTP Bearer| HUB
    CL -->|stdio bridge| HUB

    HUB -->|ZMQ :5557 embed| BW
    HUB -->|HTTP :11434| OLL
    HUB -->|proxy HTTP :8767| NCM
    HUB -->|embed daemon| EMB[forge_embed_auto_trigger.py<br/>daemon hors-supervisor]
    EMB -->|ZMQ :5557| BW

    subgraph DOCKER[Docker - 1 seul conteneur]
        C4A[laforge-crawl4ai-1<br/>:11235 - healthy]
    end
    HUB -.->|crawl| C4A

    subgraph CERVELETS[Les 2 cervelets - tous deux natifs Windows]
        SNN[forge_spike_router.py<br/>SNN PyTorch - dans le hub]
        BTS[proxy_deno/core/brain.ts<br/>intent - dans le supervisor]
    end
    HUB -.-> SNN
    DPX -.-> BTS
```

## Notes

- **`RUNNING*`** (brain_worker) : réveillé manuellement le 2026-05-20. Bug
  connu — stalle après ~1 sub-batch de charge soutenue (voir backlog embed).
- **`CRASH-LOOP x22`** : `NokidoGeminiDaemon` — refuse de démarrer, PID file
  `sandbox/gemini_poll_daemon.pid` contesté.
- **`sleeping`** : mis en veille par politique wave du supervisor (pas RAM —
  mesurée à 56 %). Réveil : `POST :8765/supervisor/wake/<nom>`.
- **Pas de cerveau Docker.** Docker = uniquement `crawl4ai`. Les 2 cervelets
  (`forge_spike_router.py` SNN + `brain.ts` intent) tournent natifs Windows.

## Contrôle supervisor (:8765)

| Endpoint | Effet |
|---|---|
| `GET /supervisor/status` | État de tous les services |
| `POST /supervisor/restart/<nom>` | kill SIGTERM + respawn |
| `POST /supervisor/wake/<nom>` | réveil d'un service sleeping |
| `POST /supervisor/sleep/<nom>` | mise en veille |
| `GET /supervisor/logs?name=<nom>` | tail du log service |

Service du hub = **`LaForgeMCP`**. Restart sanctionné (règle #10 CLAUDE.md) :
`POST :8765/supervisor/restart/LaForgeMCP` — pas de `nssm` direct.
