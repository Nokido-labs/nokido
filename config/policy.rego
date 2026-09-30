package nokido.authz

default allow = false

# L'utilisateur systeme (Ring 0) a tous les droits - DURCI : exige system_verified
# explicite (anti default/spoof a ring 0 -> full access aveugle).
allow {
    input.ring == 0
    input.system_verified == true
}

# Règle de Modification des Fichiers Juges (Anti-Reward Tampering)
# Les agents avec Ring > 0 n'ont pas le droit de modifier les fichiers critiques de jugement
# On autorise l'edit de fichiers non critiques pour ring <= 1
allow {
    input.ring <= 1
    input.action == "edit"
    not is_critical_module(input.target_module)
}

allow {
    input.ring <= 1
    input.action == "governed_edit"
    not is_critical_module(input.target_module)
}

# Règle de Séparation des Pouvoirs (Task Review / Validation)
allow {
    input.action == "validate_task"
    input.actor_agent != input.target_agent
    not same_lineage(input.actor_agent, input.target_agent)
}

allow {
    input.action == "task.review"
    input.actor_agent != input.target_agent
    not same_lineage(input.actor_agent, input.target_agent)
}

# Règle de Séparation des Pouvoirs (Task Result)
allow {
    input.action == "task.result"
    input.actor_agent != input.target_agent
}

# Fonctions utilitaires
is_critical_module(path) {
    critical_keywords := [
        "forge_trust_score",
        "forge_pool_registry",
        "forge_scorecard",
        "forge_meta_evolution",
        "forge_agents",
        "forge_evolutionary_stack",
        "forge_orchestration_gate",
        "forge_alignment_invariants"
    ]
    contains(lower(path), critical_keywords[_])
}

same_lineage(a, b) {
    lineage := {
        "CLAUDE": "anthropic",
        "AGY": "google",
        "GEMINI": "google",
        "CODEX": "openai",
        "COPILOT": "openai"
    }
    lineage[normalize_agent(a)] == lineage[normalize_agent(b)]
}

normalize_agent(name) = normalized {
    name_up := upper(name)
    has_prefix(name_up, "AGT_")
    normalized := substring(name_up, 4, -1)
}

normalize_agent(name) = normalized {
    name_up := upper(name)
    not has_prefix(name_up, "AGT_")
    normalized := name_up
}

has_prefix(str, prefix) {
    startswith(str, prefix)
}
