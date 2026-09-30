"""forge_skill_forge — réimpl native Skill_Seekers. Logique pure + gate privilégié, sans réseau."""
import importlib

sf = importlib.import_module("forge_skill_forge")


def test_safe_provider_anti_api():
    # API claude/gemini bare interdite -> fallback router souverain
    assert sf._safe_provider("claude") == "router"
    assert sf._safe_provider("gemini") == "router"
    assert sf._safe_provider("anthropic_x") == "router"
    assert sf._safe_provider("google") == "router"
    assert sf._safe_provider("groq") == "groq"
    assert sf._safe_provider("ollama") == "ollama"
    assert sf._safe_provider("inconnu") == "router"


def test_slugify():
    assert sf._slugify("https://docs.aruba.com/bundle/aoscx") == "docs-aruba-com-bundle-aoscx"
    assert sf._slugify("") == "skill-auto"


def test_ensure_frontmatter():
    assert sf._ensure_frontmatter("# Titre\ntexte", "s", "src").startswith("---")
    pre = "---\nname: x\n---\n\ncorps"
    assert sf._ensure_frontmatter(pre, "s", "src") == pre  # frontmatter déjà présent = inchangé


def test_install_skill_gated(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, "PROPOSALS", tmp_path / "prop")
    monkeypatch.setattr(sf, "SKILLS_DIR", tmp_path / "skills")
    # proposition absente -> erreur
    assert sf.install_skill("foo")["ok"] is False
    # crée la proposition
    d = tmp_path / "prop" / "_new_foo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: foo\n---\nx", encoding="utf-8")
    # confirm manquant -> BLOQUÉ (action privilégiée)
    r = sf.install_skill("foo", confirm=False, owner=True)
    assert r["ok"] is False and "blocked" in r
    # confirm + owner -> installé
    r2 = sf.install_skill("foo", confirm=True, owner=True)
    assert r2["ok"] is True and (tmp_path / "skills" / "foo" / "SKILL.md").exists()
