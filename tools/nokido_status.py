"""
tools/nokido_status.py - Outil CLI montrant l usage de NokidoFacade.

DEMO (Option E, audit Gemini 2026-04):
  Ce script montre comment un CONSUMER externe (script CLI, test, UI tierce)
  peut interagir avec Nokido SANS importer directement les modules backend.

USAGE:
    python tools/nokido_status.py              # Dashboard complet
    python tools/nokido_status.py --domains    # Liste domaines settings
    python tools/nokido_status.py --agents     # Status agents
    python tools/nokido_status.py --breakers   # Circuit breakers LLM

CE SCRIPT:
  - N IMPORTE PAS forge_rag_engine, forge_agents, forge_code, etc.
  - N IMPORTE QUE app.api_facade
  - Valide que la facade suffit pour usages simples
  - Future: sera le template pour tous les scripts externes / dashboards
"""

from __future__ import annotations

__FORGE_COLOR__ = "observabilite/status : CLI montrant l'usage de NokidoFacade (demo)"  # organe declare le 2026-09-06 (audit de raccordement)

import sys
from pathlib import Path

# Add project root to path pour import app.api_facade
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.api_facade import get_facade


def print_section(title: str) -> None:
    """Helper: affiche un separateur visuel."""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def cmd_domains(facade) -> None:
    """Affiche les domaines de settings disponibles."""
    print_section("SETTINGS DOMAINS")
    domains = facade.settings_domains()
    if not domains:
        print("  (aucun domaine detecte)")
        return
    for d in domains:
        print(f"  - {d}")


def cmd_agents(facade) -> None:
    """Affiche le status des agents."""
    print_section("AGENTS STATUS")
    status = facade.agents_status()
    for k, v in status.items():
        print(f"  {k}: {v}")


def cmd_rag(facade) -> None:
    """Affiche le status du RAG."""
    print_section("RAG STATUS")
    status = facade.rag_status()
    for k, v in status.items():
        print(f"  {k}: {v}")


def cmd_breakers() -> None:
    """Affiche l etat des circuit breakers des providers LLM."""
    print_section("CIRCUIT BREAKERS (LLM providers)")
    # On utilise encore l API directe pour les breakers (Option D)
    try:
        from nokido_agent.app.forge_llm_router import get_circuit_breakers_snapshot

        snap = get_circuit_breakers_snapshot()
        if not snap:
            print("  (aucun provider instancie)")
            return
        for prov, state in snap.items():
            status = state.get("status", "?")
            failures = state.get("failures", 0)
            symbol = {"CLOSED": "[OK]", "HALF_OPEN": "[WARN]", "OPEN": "[DOWN]"}.get(status, "[?]")
            print(f"  {symbol} {prov:<30} status={status:<10} failures={failures}")
    except ImportError as e:
        print(f"  Erreur import: {e}")


def cmd_container() -> None:
    """Affiche les services du DI Container."""
    print_section("DI CONTAINER SERVICES")
    try:
        from app.core.di_container import get_container

        c = get_container()
        services = c.list_services()
        print(f"  Total: {len(services)} services enregistres")
        print()
        for svc in sorted(services):
            # Essaye de determiner le type du service
            try:
                inst = c.get(svc)
                type_name = type(inst).__name__
                if isinstance(inst, (list, dict, tuple)):
                    info = f"{type_name} (len={len(inst)})"
                else:
                    info = type_name
                print(f"  - {svc:<25} -> {info}")
            except Exception as e:
                print(f"  - {svc:<25} -> ERROR: {type(e).__name__}")
    except ImportError as e:
        print(f"  Erreur import: {e}")


def cmd_full(facade) -> None:
    """Dashboard complet."""
    cmd_domains(facade)
    cmd_agents(facade)
    cmd_rag(facade)
    cmd_breakers()
    cmd_container()
    print()


def main() -> int:
    """Point d entree CLI."""
    facade = get_facade()
    args = sys.argv[1:]
    if not args:
        cmd_full(facade)
        return 0
    cmd = args[0].lstrip("-")
    if cmd == "domains":
        cmd_domains(facade)
    elif cmd == "agents":
        cmd_agents(facade)
    elif cmd == "rag":
        cmd_rag(facade)
    elif cmd == "breakers":
        cmd_breakers()
    elif cmd == "container":
        cmd_container()
    elif cmd in ("help", "h"):
        print(__doc__)
    else:
        print(f"Commande inconnue: {cmd}")
        print("Options: domains, agents, rag, breakers, container, help")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
