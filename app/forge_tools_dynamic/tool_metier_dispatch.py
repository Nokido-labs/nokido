"""forge_tool_dynamic: metier_dispatch
Description: Route une tache vers la bonne persona metier (89) + assemble sa KB et son system_prompt.
Signature: (task: str)
Registered: wrapper manuel vers app/forge_metier_dispatch.dispatch (2026-08-02)
"""
from __future__ import annotations


def metier_dispatch(task: str) -> dict:
    """Aiguillage metier : route_intent choisit un MODELE, CECI choisit la PERSONA.

    Wrapper mince vers forge_metier_dispatch.dispatch (routage semantique BGE-M3 +
    repli lexical). Appeler via forge_call_dynamic(name='metier_dispatch',
    sandboxed=False, task='...') — in-process pour garder l'acces embedder :8099.
    """
    import sys
    from pathlib import Path

    app = Path(__file__).resolve().parent.parent
    if str(app) not in sys.path:
        sys.path.insert(0, str(app))
    from nokido_agent.app.forge_metier_dispatch import dispatch

    return dispatch(task)
