"""
app/ - Package principal Nokido.

Expose les sous-packages :
  - agents/  : orchestration agentique
  - core/    : fondations (settings, bootstrap, state)
  - ui/      : interface Textual TUI
  - llm/     : routeurs LLM + backends
  - rag/     : moteur RAG
  - ctf/     : capture-the-flag
  - security/: code guard, sanitizer
  - hardware/: allocators, watchdogs
  - orchestration/ : dispatchers, collab modes

Et les modules de facade :
  - api_facade : NokidoFacade (API unifiee pour UI)
  - protocols  : Interfaces Protocol pour DI

Cree 2026-04 (audit architectural Gemini).
"""

__version__ = "16.5"
