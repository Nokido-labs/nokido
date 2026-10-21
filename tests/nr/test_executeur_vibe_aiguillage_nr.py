"""NR -- executeur Mistral Vibe partie 3 : aiguillage, plancher et service dedie (16/10).

RED ecrit par Claude. Sans MISTRAL dans _INTERACTIVE_FLOOR, l'executeur generique (sans --agent) prendrait les taches
Vibe en ring 4 -> GATE_DENIED -> tache brulee (race task-queue documentee le 2026-06-23). L'aiguillage des agents
dedies passe par deux helpers (delegation, capacite) au lieu d'un if par agent dans la boucle principale.
"""
import os
import sys
import tomllib
from pathlib import Path

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_task_executor as T  # noqa: E402

TOML = Path(__file__).resolve().parents[2] / "proxy_deno" / "core" / "services.toml"


def test_le_generique_ne_vole_pas_les_taches_vibe():
    assert "MISTRAL" in T._INTERACTIVE_FLOOR


def test_l_aiguillage_dedie_couvre_codex_et_mistral():
    assert T._delegation_pour("MISTRAL") is T._delegate_to_vibe
    assert T._capacite_pour("MISTRAL") is T._peut_lancer_vibe
    assert T._delegation_pour("CODEX") is T._delegate_to_codex
    assert T._capacite_pour("CODEX") is T._peut_lancer_codex
    assert T._delegation_pour("GEMINI") is None


def test_la_boucle_aiguille_par_les_helpers_et_non_par_un_if_par_agent():
    """Revue 16/10 de 92a72ebfc : les helpers existaient mais run_loop ne les appelait pas -- le bloc Codex
    avait ete recopie en un second `if agent == "MISTRAL"` (code mort + clone). Le RED precedent ne gardait
    que l'existence des helpers, pas leur usage."""
    import inspect

    src = inspect.getsource(T.run_loop)
    assert "_delegation_pour(" in src and "_capacite_pour(" in src, "run_loop n'aiguille pas par les helpers"
    assert "_delegate_to_vibe(" not in src and "_delegate_to_codex(" not in src, \
        "run_loop appelle encore un delegue en dur : un if par agent dedie"


def test_un_service_dedie_mistral_est_declare_comme_l_executeur_agy():
    services = {s["name"]: s for s in tomllib.loads(TOML.read_text(encoding="utf-8"))["service"]}
    s = services.get("NokidoTaskExecutorMistral")
    assert s, "service NokidoTaskExecutorMistral absent de services.toml"
    args = [str(a) for a in s.get("args", [])]
    assert "--agent" in args and args[args.index("--agent") + 1] == "MISTRAL", args
    agy = services.get("NokidoTaskExecutorAntigravity") or {}
    assert s.get("runAs") == agy.get("runAs"), (s.get("runAs"), agy.get("runAs"))
