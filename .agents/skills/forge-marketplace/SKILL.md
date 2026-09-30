---
name: forge-marketplace
description: >
  Catalogue des skills externes installées chez Claude Code via marketplaces
  (anthropic-agent-skills officiel + caveman alternatif). Déclencher quand
  l utilisateur demande : "créé doc Word/Excel/PowerPoint", "génère PDF",
  "compose email pro", "build artifact web", "test webapp", "créé GIF Slack",
  "design canvas", "art algorithmique", "construis MCP server", "créé un
  skill", "frontend design", "brand guidelines", "rédige internal comms",
  "use Claude API". Routing : visible côté Claude Code natif uniquement
  (caches dans .claude/plugins/cache/). Autres CLIs doivent passer par
  agt_claude pour exécution.
---

# claude-skills-marketplace — Skills externes installées chez Claude

## Inventaire (au 2026-05-02)

2 marketplaces actifs, 19 skills total.

```
~/.claude/plugins/marketplaces/
├── anthropic-agent-skills/   ← officiel Anthropic (18 skills)
└── caveman/                  ← alt community (caveman mode + variants)
```

⚠ **trailofbits-skills retiré 2026-05-02** : install initiale rejetée
par user (review sécu pas suffisante). Ne PAS réinstaller sans validation
explicite du user + audit complet du contenu de chaque plugin.

---

## Marketplace #1 : `anthropic-agent-skills` (officiel)

3 plugins → 18 skills uniques. Triggered automatiquement par mots-clés.

### Document & bureautique (4)

| Skill | Trigger | Capacités |
|---|---|---|
| `pdf` | .pdf, "PDF", "extract text" | Read/extract/merge/split/rotate/watermark/create/fill forms/encrypt/OCR PDFs |
| `docx` | .docx, "Word doc" | Create/edit/extract text/styles/tables MS Word |
| `xlsx` | .xlsx, "Excel" | Read/write spreadsheets, formules, pivot, charts |
| `pptx` | .pptx, "PowerPoint", "slide deck" | Create/edit présentations, slides, themes |

### Design & artefacts visuels (5)

| Skill | Trigger | Capacités |
|---|---|---|
| `algorithmic-art` | "art génératif", "fractale" | Génère art via algos (p5.js, processing) |
| `brand-guidelines` | "charte graphique", "brand kit" | Définit palette, typo, logo system |
| `canvas-design` | "design canvas", "infographie" | Compositions visuelles HTML5 canvas |
| `frontend-design` | "design UI", "mockup", "wireframe" | Génère mockups frontend |
| `theme-factory` | "thème CSS", "dark/light mode" | Génère themes complets |

### Web & test (2)

| Skill | Trigger | Capacités |
|---|---|---|
| `web-artifacts-builder` | "artifact web", "single-page app" | Build artefact web autonome |
| `webapp-testing` | "teste webapp", "e2e test" | Playwright tests automatisés |

### Communication (3)

| Skill | Trigger | Capacités |
|---|---|---|
| `doc-coauthoring` | "rédige doc collab", "écris ensemble" | Co-écriture structurée |
| `internal-comms` | "annonce interne", "email équipe", "memo" | Communications internes pro |
| `slack-gif-creator` | "GIF Slack", "GIF réaction" | Génère GIFs animés thématiques |

### Méta-tooling (4)

| Skill | Trigger | Capacités |
|---|---|---|
| `claude-api` | "Claude API", "appel API Anthropic" | Helper utilisation Claude API natif |
| `mcp-builder` | "build MCP server", "créé serveur MCP" | Génère skeleton serveur MCP |
| `skill-creator` | "créé skill", "nouveau skill" | Génère skill conforme spec Anthropic |
| `template` | template builder | Méta : template SKILL.md |

---

## Marketplace #2 : `caveman` (alternatif community)

| Skill | Trigger | Capacités |
|---|---|---|
| `caveman` | `/caveman lite\|full\|ultra` | Mode terse (drop articles/filler), économie 75% output / 46% input tokens |

Cache : `~/.claude/plugins/cache/caveman/caveman/84cc3c14fa1e/`

Multi-CLI : exporte aussi vers `.cline rules`, `.cursor/rules`, `.codex/`,
`.github/copilot-instructions.md` → utilisable depuis Cline / Cursor /
Codex / Copilot, pas que Claude.

---

## Marketplace #3 (potentiel) : `MCP_DOCKER` gateway

Pas un marketplace de skills mais **catalogue MCP servers** Docker Hub
accessible via `docker mcp gateway run` (registered Claude Desktop).

Exemples MCP servers disponibles :
- **Prisma** (DB ORM) — `prisma/mcp-prisma`
- Stripe, Sentry, Snowflake, MongoDB, Redis, Neo4j
- GitHub MCP, Linear MCP, Atlassian MCP (alternatives natives)
- Filesystem, fetch, time, sequential-thinking

Lister catalogue :
```bash
docker mcp catalog
docker mcp tool list
```

→ Accessible **TOUS CLIs** (Cline, Codex, Gemini si configuré, llama.cpp).

---

## Quand se déclencher (intent triggers)

Activer ce skill quand l'utilisateur demande :

**Bureautique** :
- "créé un .pdf/.docx/.xlsx/.pptx", "ouvre/lis ce fichier"
- "merge ces PDFs", "extrait texte du PDF"

**Design** :
- "design une page d'accueil", "mockup", "wireframe"
- "thème dark", "charte graphique", "brand kit"

**Web** :
- "build une mini-app", "artifact HTML autonome"
- "tests e2e Playwright", "vérifie cette webapp"

**Communication** :
- "rédige email équipe", "annonce interne"
- "GIF Slack pour célébrer", "doc co-écrite"

**Tooling** :
- "créé un skill", "créé un serveur MCP"
- "appelle l'API Anthropic"

**Style** :
- "/caveman", "mode terse", "réponds court"

---

## Routing depuis autres CLIs

Skills marketplaces installés UNIQUEMENT côté Claude Code natif :
- Cline / Cursor / Codex peuvent utiliser `caveman` (export cross-CLI)
- TOUTES autres skills (pdf/docx/xlsx/pptx/design/etc.) → uniquement
  Claude. Routing :

```
[GEMINI] @claude génère PDF rapport mensuel à partir de data.csv
[CLAUDE] Utilise skill `pdf` + `xlsx` → output.pdf généré
[GEMINI] OK reprise
```

Pour `MCP_DOCKER` : tous CLIs équipés MCP_DOCKER gateway peuvent appeler
directement (Prisma, Stripe, etc.) sans routing.

---

## 🌐 Marketplaces externes (non-installés, candidats pertinents Nokido)

### Top 4 alignés Phase 6 / cervelet WASM / sécurité

| Marketplace | Skills | Pertinence Nokido |
|---|---|---|
| **trailofbits/skills-curated** | ~28 | Sécurité offensive/défensive (ghidra-headless, ffuf-web-fuzzing, security-threat-model, scv-scan, sentry, security-best-practices). Aligne avec `forge_security_scan` + `forge_clawhub_bridge::SkillGuardian` |
| **LerianStudio/ring** | 89 | TDD + systematic-debugging + production-readiness-audit + pr-review-multi-source + explore-codebase. **Extend `forge-tdd` + `forge-systematic-debugging` existants** |
| **daymade/claude-code-skills** | 51 | debugging-network-issues, cloudflare-troubleshooting, tunnel-doctor (cohérent netcfg-agent + DNS work), terraform, ASR transcribe, youtube-downloader |
| **cosmonic-labs/mcp-server-template-ts** | (template WASM) | Template MCP server compilé en WASM — directement compatible `forge_wasm_cervelet.py` + Docker WASM cervelet (wasmedge :55555). **C'est probablement le "skill wasm" vu par user** |

### Autres (à étudier)

- `obra/superpowers-marketplace` — curated général
- `Piebald-AI/claude-code-lsps` — LSP servers (autocomplete IDE)
- `MadAppGang/claude-code` — général
- `SimoneAvogadro/android-reverse-engineering-skill` — Android RE
- `blader/humanizer` — anti-AI-tells dans textes
- `tjfontaine/agent-in-a-browser` — agent browser sandbox WASM TypeScript

### MCP servers WASM natifs (pas marketplace)

| Repo | Capacité |
|---|---|
| `cosmonic-labs/mcp-server-template-ts` | Template Wasm MCP TS |
| `tjfontaine/agent-in-a-browser` | TS dynamique exécuté dans wasm mcp Rust |

→ **Intégration Nokido** : déjà un cervelet WASM (Docker wasmedge + nomic
embeddings :55555). Ajouter un MCP server WASM permettrait d'exécuter
des outils sandboxed indépendants du runtime hôte. Pertinent pour
exécution de code untrusted depuis Claude → wasmedge isole.

---

## Installer plus de skills

```bash
# Via Claude Code (ouvre marketplace UI)
/install <skill-name>

# Marketplace officiel : github.com/anthropics/skills
# Marketplace caveman : github.com/teabranch/caveman
# Autres community : voir claude.ai/extensions
```

Les skills s'extraient dans `~/.claude/plugins/cache/<marketplace>/<plugin>/<hash>/`.
Nokido skill_enricher peut détecter nouvelles skills installées (TODO :
extension de `forge_skill_enricher.py` pour scanner ce path).

---

## Sécurité

⚠ Les skills externes peuvent inclure du code Python/JS exécuté.

1. Ne **pas** installer skills non-officielles sans review (cf
   SkillGuardian Phase 6 dans Nokido — `app/forge_clawhub_bridge.py`)
2. Vérifier `manifest.json` + `skill.yaml` avant install
3. Préférer marketplaces signed (Anthropic officiel = signature vérifiée)

---

## Anchor RAG après usage skill externe

```python
from forge_self_correction import anchor_solution
anchor_solution(
    problem="<demande user>",
    solution=f"Used skill {skill_name} from {marketplace} | output: {ref}",
    domain="connectors",
)
```

---

## Voir aussi

- `claude-connectors` — connecteurs cloud Claude.ai (Gmail/GCal/GDrive/Notion)
- `laforge-skills` — skills locales Nokido ClawHub
- `forge-anatomy` — cartographie modules biomimétique
- `forge_clawhub_bridge.py::SkillGuardian` — review skills tier
