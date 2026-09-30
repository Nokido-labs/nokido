---
name: forge-skill-seekers
description: >
  Génération NATIVE de SKILL.md depuis une source de documentation (URL, texte).
  Capacité SOUVERAINE de Nokido exposée comme tool hub dynamique `skill_forge` —
  réimplémentation du subset utile de Skill_Seekers, sans dépendance externe ni
  serveur tiers. Triggers : l'utilisateur fournit une URL de doc (vendor, framework,
  API) et demande « crée un skill depuis cette doc », « transforme docs.X en skill »,
  « scrape et indexe cette doc », « skill auto depuis URL », ou évoque un vendor sans
  skill associé (Cisco IOS-XE, Juniper Junos, MikroTik RouterOS). Le tool fetch (crawl)
  → structure (LLM LOCAL) → review (SkillGuardian) → écrit une PROPOSITION ; l'install
  dans docs/skills/ est une action privilégiée gatée (confirm + owner).
---

# forge-skill-seekers — capacité native docs → SKILL.md

## Statut

LIVE. Réimplémenté en natif dans `app/forge_skill_forge.py`, exposé comme tool hub dynamique
`skill_forge` (registre `app/forge_tools_dynamic/registry.json`, handler
`app/forge_tools_dynamic/tool_skill_forge.py`). La capacité ÉMANE de Nokido : aucun serveur MCP
externe, aucune dépendance `pip`, aucun code tiers (donc aucune attribution MIT requise).
Souveraineté : structuration via LLM LOCAL (router/ollama/lmstudio/groq), jamais d'API
claude/gemini bare (provider forcé via `_safe_provider`).

## Pipeline (composition de l'existant, anti-dup)

```
URL/texte → forge_crawl_tool.crawl_url (trafilatura → markdown épuré)
         → forge_agent_proxy.ask (LLM local) structure en SKILL.md
         → forge_clawhub_bridge.SkillGuardian.review (patterns + LLM + SAST)
         → sandbox/skill_proposals/_new_<slug>/SKILL.md (PROPOSITION, jamais docs/skills direct)
         → [action privilégiée gatée] install_skill(confirm, owner) → docs/skills/<slug>/
```

## Quand se déclencher

- URL de doc (`docs.aruba.com`, `developer.cisco.com`, doc d'une API REST) à convertir en skill.
- Vendor sans skill (Cisco IOS-XE, Juniper Junos, MikroTik RouterOS) alors qu'on en a besoin.
- Ingérer une doc tierce avec une structure skill (plus utile que l'ingest brut).

## Usage

Via n'importe quel CLI parlant au hub :8766 :

```
forge_call_dynamic("skill_forge", kwargs={"source": "https://docs.aruba.com/bundle/aoscx",
                                           "kind": "url", "provider": "router"})
# → {ok, slug, proposal_path, review_status, risk, reason}
```

Install (privilégié, après review humaine du frontmatter) :

```
forge_call_dynamic("skill_forge", kwargs={"slug": "<slug>", "install": true,
                                           "confirm": true, "owner": true})
```

## Exemples

| Cible | kwargs | Skill généré → utilité |
|---|---|---|
| `docs.aruba.com/bundle/aoscx` | `source=…, kind=url` | Étendre netcfg-agent (AOS-CX) |
| `developer.cisco.com/iosxe`   | `source=…, kind=url` | Vendor manquant (Cisco IOS-XE) |
| Texte/doc collé               | `source=<md>, kind=text` | Skill depuis une doc déjà récupérée |

## Anti-patterns

1. **Jamais d'install solo** — `install_skill` est default-deny (confirm + owner requis).
2. **Jamais écrire direct dans docs/skills/** — toujours via la proposition puis review.
3. **Jamais d'API claude/gemini** pour la structuration — provider forcé souverain.
4. **Ne pas dupliquer `forge_ingest_self`** — ce skill ajoute la STRUCTURE SKILL.md par-dessus ;
   l'ingest brut dans le RAG reste `forge_ingest_self` / `/ingest/url`.
5. **Ne pas écraser une skill existante** sans vérifier `docs/skills/<slug>/`.

## Liens

- Module natif : `app/forge_skill_forge.py` (tests `tests/test_skill_forge.py`)
- Tool dynamique : `app/forge_tools_dynamic/tool_skill_forge.py` + `registry.json`
- Review sécurité : `app/forge_clawhub_bridge.py` (SkillGuardian)
- Inspiration conceptuelle (non vendorée) : Skill_Seekers — github.com/yusufkaraaslan/Skill_Seekers
