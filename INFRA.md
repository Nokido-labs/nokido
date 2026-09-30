# INFRA Nokido — Manifeste Architecture
Généré : 2026-04-18T18:56:48

## Identité Système
- Nom : Nokido TUI v0.13.2
- Supercontrôleur souverain : Nokido
- Racine projet : ~\Script python IA\Nokido

## Stack Technique
- Python : miniforge3
- TUI : Textual 8.0.1
- LLM local : Ollama (qwen2.5-coder, deepseek-coder)
- Embeddings : bge-m3 via NPU/DirectML (Ryzen 8700G iGPU)
- MCP Server : tools/nokido_mcp_server.py (port 8765)
- Brain Worker : app/brain_worker.py (ZMQ port 5557)
- Base vectorielle : RAG/embeddings.db (SQLite WAL)

## Rings d'Intégrité
- Ring -1 : MASTER_OVERRIDE (TTL 5min)
- Ring  0 : Nokido (supercontrôleur)
- Ring  1 : Agents système (NR_runner, audit)
- Ring  2 : Agents DEV (Claude MCP avec token LF-)
- Ring  3 : Agents TRUSTED (Ollama local avec droits RAG)
- Ring  4 : Agents UNTRUSTED (cloud sans MCP = lecture seule)

## Règle d'Or
Un agent sans accès MCP validé (token LF-) ne peut pas proposer de patch.
Les modèles cloud (deepseek-cloud, gpt-oss) = interdit de patch.
Nokido émet les tokens LF- et reste souverain.

## Ports & Interfaces
- MCP HTTP  : 127.0.0.1:8765/mcp
- Brain ZMQ : tcp://127.0.0.1:5557
- Ollama    : http://localhost:11434

## Fichiers Critiques
- app/LaForge.py          : TUI principale (622 KB)
- app/forge_rag_engine.py : Moteur RAG (85 KB)
- app/forge_task_bus.py   : Bus tâches multi-agents
- app/forge_integrity.py  : Rings + tokens LF-
- tools/nokido_mcp_server.py : Serveur MCP (DEV mode actif)
- Nokido.env             : Configuration (LAFORGE_MCP_DEV=true)
