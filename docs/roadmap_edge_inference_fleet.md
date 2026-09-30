# Roadmap : Edge Inference Fleet (semaines)

Source : memory `roadmap_edge_inference_fleet`. Web-llm + transformers.js
sur parc Linux/Android/Xbox. Fleet horizontal (pas sharding). Compagnon
Petals.

## Vision

Inférence LLM distribuée sur appareils edge :
- Android (RAM 6-12 GB, NPU récent)
- Linux box (Ryzen/Apple Silicon)
- Xbox / consoles (peu courant mais 16 GB RAM)
- Raspberry Pi 5 (8 GB) pour POC

Pas de sharding model = chaque device fait inférence complète sur petit modèle (Qwen2.5 1.5B / Phi-3 mini). Coordinator distribue REQUESTS (load-balance) pas WEIGHTS.

## 4 Phases

### Phase 1 : Stack edge unifié (1-2 semaines)
- web-llm (WebGPU/WASM) pour navigateur
- transformers.js (ONNX Web) pour fallback CPU
- llama.cpp serveur HTTP standard (ou Ollama)
- API unifiée `/v1/chat/completions` (OpenAI-compat)

### Phase 2 : Discovery + heartbeat (1 semaine)
- mDNS / Bonjour pour découverte LAN
- Heartbeat HTTP `/health` toutes les 30s
- Telemetry : RAM libre, charge CPU, model loaded, last-seen

### Phase 3 : Coordinator (router) (1 semaine)
- Reçoit requête centrale
- Sélectionne meilleur edge (load + RAM + model match)
- Forward + stream response back
- Fallback si edge timeout

### Phase 4 : Tests + dashboard (1 semaine)
- Bench latence inter-LAN
- Failure tests (kill random edge, verify rerouting)
- Tile dashboard `/edge/fleet` montrant carte topology
- Observability : Prometheus exporter

## Différentiateur vs Petals

| | Petals | Nokido Fleet |
|---|---|---|
| Sharding model | Oui (pivots layer N a N+M) | Non (full model per device) |
| Public network | Tor + crypto | LAN local seulement |
| Modèle | 70B+ via sharding | 1-7B per device |
| Latency p50 | 2-5s (latency reseau) | 200-500ms (LAN) |
| Privacy | Encrypted forward | Local only |

## Effort total

3-5 semaines pour POC fonctionnel. Production-ready ~2 mois.

## ROI

- ⭐⭐ : utile pour démo + souveraineté (data jamais cloud)
- Pas revenue direct sauf si packagé MSP
- Showcase pour DEF CON / publications

## Dépendances bloquantes

- forge_llm_router doit accepter providers dynamiques (URL discovery)
- Auth inter-edge (mTLS minimum)
- Mise à l'échelle modèles : automation load/unload selon RAM dispo
