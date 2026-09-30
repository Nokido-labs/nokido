# forge dynamic tool : skill_forge — génération NATIVE de SKILL.md (réimpl souveraine Skill_Seekers)
# Émane de Nokido : appelable par tout CLI via forge_call_dynamic("skill_forge", ...).
# Wrapper mince qui compose forge_skill_forge (fetch crawl + structure LLM local + review Guardian).
# Écrit une PROPOSITION (sandbox/skill_proposals) ; install=True = action PRIVILÉGIÉE gatée.


def skill_forge(source="", slug=None, kind="url", provider="router",
                install=False, confirm=False, owner=False, token=""):
    """Génère un SKILL.md depuis une source. kind=url|text. Review SkillGuardian incluse, sortie
    en PROPOSITION (jamais docs/skills direct). install=True → merge privilégié vers docs/skills,
    gaté confirm=True+owner=True. provider forcé souverain (jamais API claude/gemini bare)."""
    from nokido_agent.app import forge_skill_forge as sf

    if install:
        return sf.install_skill(slug or "", confirm=confirm, owner=owner)
    if kind == "text":
        return sf.from_text(source, slug or "skill-auto", source="text", provider=provider)
    return sf.from_url(source, slug=slug, provider=provider)
