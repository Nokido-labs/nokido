# ⚡ Nokido

Nokido is a system that learns, remembers, and regulates — on your machine, with your hardware, for your data.

## Architecture

```text
                              NOKIDO
                        DIGITAL ORGANISM
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
     NERVOUS SYSTEM          IMMUNE SYSTEM          ENDOCRINE SYSTEM
        │                      │                      │
   events / routing        firewall / RBAC        resource regulation
   M2M / protocols          membrane / trust       quotas / pressure
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
                  ┌────────────┴────────────┐
                  │                         │
                MEMORY                   MUSCLES
               RAG / FTS               workers / tools
             vector space              execution / actions
                  │                         │
                  └────────────┬────────────┘
                               │
                        CENTRAL INTEGRATION
                           Hub / MCP
                               │
                 distributed cognition layer
                  ACP / A2A / M2M / SWARM
                               │
                         neural substrate
                          SNN / edge / NPU
                               │
                      neuromorphic substrates
                           (future)
```
## Quickstart

```bash
pip install nokido-agent

nokido-doctor          # what the machine has, lacks, or cannot read
nokido-hub

curl http://localhost:8766/health
```
## Supported clients

- Claude Code · MCP HTTP
- Antigravity (agy) · MCP HTTP
- Codex CLI · MCP HTTP
- OpenCode · MCP HTTP
- Mistral Vibe · MCP HTTP
- Cline · MCP STDIO
- Claude Desktop · MCP STDIO

## Security

Secrets live in a DPAPI vault, every caller gets an integrity ring (RBAC), and outbound text crosses a semantic
firewall and a sovereign membrane before reaching any cloud model.

## Learn more

- [Installation](docs/wiki/01-Installation.md)
- [Architecture](docs/wiki/03-Architecture.md)
- [Security model](docs/wiki/07-Security-Model.md)
- [Vault and secrets](docs/wiki/08-Vault-and-Secrets.md)

## License

AGPLv3-or-later · commercial licensing available.

