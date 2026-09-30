# COCKPIT UNIFIE NOKIDO - Bilan (2026-04-18T04:30:06)

## OBJECTIF

Creer une interface unifiee regroupant :
- TUI Nokido classique (chat, agents, RAG)
- GUI Exegol (containers, CTF CH88, outils pentest)
- Dashboard refacto (DI, CircuitBreakers, tests NR)
- Monitoring (logs, metrics, fan-in)
- Outils integres (mermaid viewer, architecture docs)

## ARCHITECTURE

Textual App multi-screens avec DI Container integre.

```
NokidoCockpit (App principale)
|
+-- Home screen : menu 6 tuiles + navigation clavier
|
+-- DashboardScreen (d) : metriques + services DI
+-- ChatScreen (c)      : chat LLM multi-backends via facade async
+-- ExegolScreen (e)    : containers docker + outils CTF + CH88
+-- ArchitectureScreen (a) : docs + mermaid + bilans refacto
+-- MonitoringScreen (m)   : breakers + logs + fan-in live
+-- ToolsScreen (t)        : tests NR + lints + migrations
```

## STRUCTURE FICHIERS

```
app/cockpit/                       (9 fichiers, 43.3 KB)
|-- __init__.py                    (package cockpit)
|-- app.py                         (6.4 KB, App principale + menu)
|-- screens/
    |-- __init__.py
    |-- dashboard.py               (4.2 KB, metriques)
    |-- chat.py                    (3.6 KB, LLM multi-backends)
    |-- exegol.py                  (9.1 KB, Docker + CTF + CH88)
    |-- architecture.py            (5.6 KB, docs + mermaid)
    |-- monitoring.py              (7.8 KB, breakers + logs)
    |-- tools.py                   (6.6 KB, tests + migrations)

tools/
|-- nokido_cockpit.py             (1.2 KB, launcher CLI)
|-- cockpit_smoke_test.py          (1 KB, smoke test)

tests/nr/test_refacto_nr.py        (+10 tests TestCockpit)
```

## FONCTIONNALITES PAR ECRAN

### DASHBOARD (d)
- 6 metriques temps reel (services, domaines, protocols, agents, breakers, tests)
- Table complete des services DI Container

### CHAT (c)
- Input + Select backend (ollama/gemini/llamacpp/litellm/openrouter)
- RichLog scrollable avec markup colore
- Utilise AsyncNokidoFacade (non-bloquant)
- Commandes clavier : Ctrl+L pour clear, q pour back

### EXEGOL (e) - 4 onglets
1. Containers : liste docker ps, start/stop ch88_crack
2. Tools : 10 boutons outils CTF (nmap, gobuster, ghidra, burp, metasploit, volatility, binwalk, steghide, hashcat, john)
3. Shell : exec direct dans ch88_crack via docker exec
4. CH88 : statut challenge + raccourcis (check target, brute Flask, test panel)

### ARCHITECTURE (a) - 5 onglets
1. Stats : 12 metriques avant/apres refacto
2. Docs : MarkdownViewer pour ARCHITECTURE.md avec TOC
3. Mermaid : boutons pour charger chaque diagramme sandbox/mermaid_*.md
4. Bilans : 7 bilans refacto accessibles
5. Tree : DirectoryTree de app/

### MONITORING (m) - 3 onglets
1. Circuit Breakers : table live avec reset all
2. Logs : tail system + trace depuis logs/debug-*.log
3. Fan-in : top 15 modules par fan-in (couleur code selon severite)

### TOOLS (t) - 2 onglets
1. Tests : 6 boutons (pytest NR, lint cycles, dashboard, setup_check, snapshot, fanin)
2. Migrations : historique des migrations (archive/)

## VALIDATION

- [OK] 12/12 fichiers py_compile
- [OK] 65/65 tests NR passent (1.66s)
- [OK] Smoke test : 6 screens push/pop sans crash
- [OK] 0 cycle d import bloquant
- [OK] DI Container integre (container.get("facade"), etc.)

## LANCEMENT

```bash
# Mode interactif (recommande)
python tools/nokido_cockpit.py

# Mode smoke test (sans TTY)
python tools/cockpit_smoke_test.py

# Tests unitaires
pytest tests/nr/test_refacto_nr.py::TestCockpit -v
```

## RACCOURCIS CLAVIER

| Touche | Action |
|--------|--------|
| d | Dashboard |
| c | Chat LLM |
| e | Exegol + CTF |
| a | Architecture |
| m | Monitoring |
| t | Tools |
| q | Quit (home) |
| r | Refresh (dans chaque screen) |
| Ctrl+L | Clear log (Chat) |

## INTEGRATION AVEC LE REFACTO

Le cockpit utilise EXCLUSIVEMENT le DI Container :

```python
# Dans chaque screen
from app.core.di_container import get_container
c = get_container()
facade = c.get("facade")         # NokidoFacade
afacade = c.get("async_facade")  # AsyncNokidoFacade
domains = c.get("settings_domains")
protocols = c.get("protocols")
breakers = c.get("breakers_snapshot")
```

AUCUN import direct de :
- forge_rag_engine, forge_agents, forge_code
- forge_ollama_bridge, forge_gemini_bridge
- forge_settings (utilise app.core.settings via DI)

## REQUIREMENTS

- textual >= 0.47 (deja installe)
- Python 3.10+
- Optionnel : docker (pour l ecran Exegol)

## PROCHAINES AMELIORATIONS POSSIBLES

1. WebSocket bridge pour RAG query live
2. Mermaid rendering graphique (actuellement texte)
3. Integration vraie shell PTY Exegol (actuellement docker exec)
4. Dark/Light theme switcher
5. Export dashboard -> HTML
6. Integration Nokido_Lanceur (start/stop MCP/brain_worker)
