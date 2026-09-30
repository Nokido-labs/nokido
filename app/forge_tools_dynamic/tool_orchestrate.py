# forge dynamic tool : orchestrate — exposition MCP de forge_viable_system.orchestrate
# Appelable par tout CLI via forge_call_dynamic("orchestrate", ...) / le tool dyn_orchestrate.
# Wrapper mince (PAS de LLM-forge) : compose l'existant. Passe denylist + SecretGuard.


def orchestrate(macro_task="", roles=None, plan_id=None, token="", local=True, execute=False):
    """Orchestrateur multi-pool VSM : decompose macro_task en roles -> pools -> providers
    (2 CLI OAuth claude_cli+gemini_cli + local ollama + cloud groq), plan dans un blackboard
    temporaire (zone hub + fichier), execution gouvernee par authorize (S5, fail-closed),
    garde anti-API (jamais claude/gemini bare). roles = [{name, tier, pool, task?, tool?}]
    avec tier in {reason_premium, bulk_local, fast_cloud}."""
    from nokido_agent.app.forge_viable_system import orchestrate as _orc
    return _orc(macro_task, roles or [], plan_id=plan_id, token=token, local=local, execute=execute)
