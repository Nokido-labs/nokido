---
type: guide
title: 16 — FAQ
status: draft
resource: repo://docs/wiki/16-FAQ.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 16 — FAQ

<!-- revu-le: 2026-08-21 -->
> Mise à jour : 2026-08-21

> 🌐 [English](16-FAQ.md) · **Français**

Questions fréquentes. Voir aussi [docs/FAQ.md](../FAQ.md) pour la FAQ courte original.

## 🌟 Général

### Qu'est-ce que Nokido ?

Un **système d'exploitation IA autonome, local-first, à gouvernance neuro-symbolique**. Il orchestre plusieurs cerveaux spécialisés (LLMs, embedders, SNN, GOAP, planner AMI), possède sa mémoire (RAG persistant), filtre chaque appel cloud (Firewall sémantique + Membrane souveraine), et reste local-first par défaut.

Version courte : *un hôpital high-tech où chaque cerveau a une spécialité, chaque échange est filtré, et le tout se souvient de tout 24/7 sur ta machine*. Voir [MANIFESTO.md](../../MANIFESTO.md) pour la philosophie complète.

### Pourquoi "Nokido" ?

Ça forge des choses — code, plans, décisions. Aussi un clin d'œil à Geordi La Forge (Star Trek TNG) — l'ingénieur en chef qui *fait marcher l'impossible* avec des ressources locales.

### Qui maintient ?

user ([@user](https://github.com/user)). Projet solo, ouvert aux contributeurs.

### C'est quelle licence ?

**AGPLv3-or-later**. Si tu hostes Nokido en service réseau, tu dois publier tes modifs. Lire [CONTRIBUTING.md](../../CONTRIBUTING.md) pour le pourquoi.

### Nokido est stable ?

C'est **alpha**. La branche `alpha` = dev actif, `beta` = release-prep, `main` trackera releases stables. Pin à un tag pour usage production-like.

## 🚀 Démarrage

### Quel hardware il faut ?

Minimum :
- 8 GB RAM
- 4 cores CPU
- 2 GB disque

Recommandé :
- 16+ GB RAM (32 si tu veux les extras `ml` avec torch)
- 8+ cores
- iGPU intégré (Radeon iGPU, Intel Arc, NVIDIA, M1+ Metal) pour brain_worker embedder
- 10+ GB disque si tu gardes l'historique RAG

Testé sur AMD Ryzen 7 8700G + Radeon 780M iGPU (APU consumer). Tous les benchmarks README viennent de ce setup.

### Pourquoi Python 3.12 et pas 3.11 ?

Plusieurs raisons :
- Type hints modernes (`X | None`, `dict[K, V]`)
- `tomllib` en stdlib
- Meilleure perf async
- Les wheels `faiss-cpu` ciblent 3.12

Python 3.13 et 3.14 marchent aussi.

### Faut connaître Python pour utiliser Nokido ?

Non. Le setup Docker te fait tourner en 5 min. Tu interagis via ton client MCP (Claude Code, Gemini CLI, Codex CLI, Cline) ou via le TUI (`nokido-cli`).

Pour **étendre** Nokido (nouveaux modules, skills custom), oui — Python est le langage primaire.

### Différence entre Nokido et Ollama ?

Ollama = **runtime LLM local** — un process, un ou plusieurs fichiers modèle, API compatible OpenAI. Nokido **utilise** Ollama comme un de ses 29 providers LLM.

Nokido ajoute :
- Routage multi-provider avec cascade fallback
- Mémoire persistante (RAG)
- Firewall sémantique + membrane souveraineté
- Orchestration multi-agent
- Gouvernance neuro-symbolique
- Pile cognitive AMI
- RBAC réel
- Sandboxing, vault, audit, etc.

Ollama = la station service. Nokido = la voiture.

### Différence entre Nokido et LangChain / AutoGPT / Agents SDK ?

L'inversion majeure : **dans Nokido le hub est l'orchestrateur, le LLM est un worker transient**. LangChain / AutoGPT font du LLM l'orchestrateur (qui re-envoie le chain-of-thought à chaque tool call). Résultat mesuré : Nokido consomme **5-15× moins de tokens** pour le même résultat. Voir [MANIFESTO §3.5](../../MANIFESTO.md#35--le-client-est-jetable-le-système-est-permanent--économie-radicale-des-tokens).

Nokido a aussi des choses qu'ils n'ont pas : Firewall Sémantique, Membrane Souveraine, pile cognitive AMI, RBAC 6-rings, voie verdict neuro-symbolique. La comparaison la plus proche = **OpenHands** (ex-OpenDevin), mais même là Nokido diffère : souveraineté + mémoire + gouvernance.

## 🤖 LLMs & providers

### Quel LLM utiliser ?

Pour la plupart des tâches, **`auto`** routing : la cascade pick pour toi. Pour forcer :
- **Code** : `qwen2.5-coder:32b` via Ollama (local), ou `groq` (free cloud, rapide).
- **Reasoning** : `gemini_pro` (free tier 1k/mois), ou `cohere_command_r_plus`.
- **Vision** : `gemini_flash` (1M context, gratuit).
- **Long context** : `gemini_flash` aussi, ou `cohere_command_r_plus` (128k).
- **Tool calling** : `llamacpp_local` (qwen2.5-coder + `--jinja`), ou `ollama`.

### Obligé d'utiliser un LLM cloud ?

Non. Le tier `local` (Ollama, llama.cpp, LM Studio, brain_worker) couvre la plupart des workflows. Le cloud = boost qualité quand le local suffit pas.

### Privacy pour appels cloud ?

Deux couches automatiques :
1. **SemanticFirewall.pre_flight** : DLP + check injection + canary.
2. **SovereignMembrane.wrap** : anonymisation alias HMAC des hostnames, paths, IPs, tokens, UUIDs.

Le provider cloud voit `[host:xxx]` et `[path:yyy]`, pas tes vraies données. Hub restore aliases dans la réponse transparently.

Tu peux aussi désactiver complètement cloud : delete les clés API du vault, et la cascade utilisera que les providers locaux.

### Ajouter un provider custom ?

Voir [05 — Providers LLM § Ajouter provider custom](05-LLM-Providers.fr.md#-ajouter-un-provider-custom).

### Pourquoi mon appel Groq / Cerebras / Cohere échoue ?

Cause la plus probable = **quota**. Check :
```
http://127.0.0.1:8766/admin/providers
```

Si % rouge, le provider est skip par la cascade jusqu'à reset quota (début mois/jour suivant).

## 🛡️ Sécurité

### Comment les secrets sont stockés ?

Dans un vault OS-encrypted machine-wide :
- **Windows** : DPAPI `CRYPTPROTECT_LOCAL_MACHINE`.
- **macOS** : Keychain.
- **Linux** : libsecret / Secret Service.

Voir [08 — Vault & secrets](08-Vault-and-Secrets.fr.md).

### Et si le vault leak ?

Le fichier vault (`data/machine_vault.dat`) est chiffré avec la *clé machine*. Un attaquant réseau qui pull le fichier ne peut pas le déchiffrer sans accès local.

S'ils ont accès local (compte utilisateur compromis), c'est le même profil de menace qu'un `.env` sur disque. Le vault aide contre leak *passif* (backups, git push, file sync), pas contre compromission *active*.

### Exposer le hub à internet ?

**Don't.** Hub bind `127.0.0.1` par défaut. Pour accès depuis autre machine, utiliser **Tailscale ou WireGuard**. Ne change pas le bind à `0.0.0.0`.

### Reporter une vulnérabilité ?

Disclosure privée : onglet *Security* → *Report a vulnerability*. Voir [SECURITY.md](../../SECURITY.md). 72h ack target.

### Y a-t-il des backdoors ?

Non. Code AGPLv3 — entièrement lisible, auditable. Le hub bind localhost, aucune télémétrie, aucun "phone home". Hooks pre-commit (Gitleaks + `forge_secret_guard`) préviennent inclusion accidentelle secrets.

Si tu veux paranoïa extra : build localement, audit `app/forge_*.py`, inspect `network_log` pour outbound calls.

## 💾 RAG & mémoire

### Quelle taille du RAG ?

Install fresh défaut : ~3k chunks (seed data — lessons, configs, ADRs). Après quelques semaines d'usage actif : 50-100k. Le setup dev référence = ~380k chunks à ~16k embeddings (tier warm).

### Delete le RAG et recommencer ?

Oui :
```bash
rm RAG/embeddings.db
python tools/forge_db_bootstrap.py  # re-import baseline
```

Tu perds toutes les leçons apprises et contenu indexé.

### Comment interroger le RAG ?

Trois manières :
- **MCP** : tool `rag` avec `action=search`, `topic=<query>`.
- **UI web** : `http://127.0.0.1:8766/forge/rag`.
- **SQL** (ring 0 only) : tool `query` avec syntaxe FTS5.

### Exporter le RAG ?

Oui. `tools/forge_db_seed_export.py` dump tables en JSONL avec schéma. Utile pour backups et sync cross-machines.

## 🔌 MCP & clients

### MCP c'est quoi ?

**Model Context Protocol** — standard ouvert Anthropic (2024) pour interaction client-LLM tool. Nokido implémente MCP 2025-03-26.

### Quels clients marchent ?

Testés : Claude Desktop, Claude Code, Gemini CLI, Codex CLI, Cline (VS Code), MCP Inspector, clients HTTP custom. Tout client MCP-compatible devrait marcher — voir [04 — Configuration clients MCP](04-MCP-Clients-Setup.fr.md).

### Écrire mon propre client MCP ?

Oui. Parle JSON-RPC 2.0 sur HTTP ou STDIO avec le schéma de [06 — Référence API hub](06-Hub-API-Reference.fr.md). 25 tools dispo.

## ⚙️ Opérations

### Mettre à jour Nokido ?

```bash
cd Nokido
git pull
# Docker
docker compose -f docker/nokido/docker-compose.yml build
# Natif
EXTRAS=$TON_PROFIL bash install.sh
```

### Backup ?

Paths critiques à backup :
- `RAG/embeddings.db` — la mémoire.
- `data/machine_vault.dat` — vault (Windows).
- `Nokido.env` — config (no secrets).
- `seed/*.jsonl` — bootstrap data.
- `logs/lessons_learned.md` — trace human-readable.

```bash
tar czf laforge-backup-$(date +%F).tar.gz \
    RAG/embeddings.db data/machine_vault.dat \
    Nokido.env seed/ logs/lessons_learned.md
```

### Combien coûte Nokido ?

- **Local-only** : 0 € / mois.
- **Avec free-tier clouds** : 0 € / mois si tu restes sous les quotas.
- **Avec APIs payantes** : dépend de l'usage. Session dev typique : $0.50–$5 / jour si tu sollicites Claude Sonnet pour tâches dures.

La cascade est conçue pour minimiser le coût — local d'abord, free ensuite.

### Run Nokido headless ?

Oui. Ne lance pas le TUI ; juste run `laforge-hub` (ou Docker compose). Toute la fonctionnalité est dispo via HTTP MCP.

### Run plusieurs instances Nokido même machine ?

Oui — change le mapping port. Hub prend env var `LAFORGE_HUB_PORT`. Chaque instance a besoin de ses propres dirs `RAG/`, `data/`, `logs/`, `sandbox/`.

## 🧪 Dev

### Ajouter un nouveau tool au hub ?

1. Register dans `app/forge_mcp_registry.py::ToolRegistry`.
2. Ajouter handler dispatch.
3. Ajouter à `tools/hub_middleware.py::_ALLOWED_TOOLS`.
4. Test : `pytest tests/test_forge_mcp_registry.py`.

### Écrire un skill custom ?

Voir [docs/skills/nokido/SKILL.md](../skills/nokido/SKILL.md).

### Run les tests ?

```bash
pytest tests/                   # tous
pytest tests/ -m unit           # rapides only
pytest tests/ -m security       # suite security
pytest tests/test_forge_scorecard.py
```

CI matrix : Ubuntu + macOS + Windows. Voir `.github/workflows/ci.yml`.

### Ouvrir une issue ?

GitHub : <https://github.com/Nokido-labs/nokido/issues>. Templates **Bug report** ou **Feature request**. Pour sécurité : email privé (voir au-dessus).

## 🛣️ Futur

### C'est quoi la roadmap ?

Voir [MANIFESTO §9](../../MANIFESTO.md#9-roadmap-résumée) et [13 — Roadmap matérielle](13-Hardware-Roadmap.fr.md). Résumé :
- Phase A (current → 12 mois) : support NPU edge accelerator.
- Phase B (12-24 mois) : backend neuromorphique (Akida, Loihi).
- Phase C (24-48 mois) : analogique CIM / RRAM / photonique.
- Phase D (48+ mois) : grilles neuronales continues.

### Y aura-t-il une version SaaS ?

Pas dans le futur prévisible. Tout l'intérêt de Nokido = **souveraineté locale**. Une Nokido SaaS serait auto-contradictoire.

### Support Windows ARM / Apple Silicon ?

Apple Silicon : marche déjà (M1/M2/M3) — CoreML backend brain_worker, Metal pour torch. Windows ARM : pas testé ; PRs welcome.

### Utiliser Nokido sur Mac sans Docker ?

Oui : `bash install.sh` sur macOS marche nativement. Voir [01 — Installation § macOS](01-Installation.fr.md#-chemin-2--install-natif-linux--macos).

### Supporter plus de providers LLM ?

Oui — mais vendor-neutrally, via `litellm`. Si `litellm` le support, Nokido aussi (ajouter spec dans `forge_provider_specs.py`). Si provider a besoin client custom (SDK Anthropic, mistral_common…), file une issue.

## 🤝 Communauté

### Où trouver de l'aide ?

- Ce wiki.
- GitHub Discussions (une fois activé sur repo public).
- Mentionner @user pour les questions de design.

### Sponsoriser / donner ?

Public release setupera GitHub Sponsors. D'ici-là, contribuer des PRs = meilleur moyen de soutenir.

### Comment citer Nokido en académique ?

```bibtex
@software{nokido_2026,
  author = {user},
  title  = {Nokido: An Autonomous, Local-First AI Operating System
            with Neuro-Symbolic Governance},
  year   = 2026,
  url    = {https://github.com/Nokido-labs/nokido}
}
```

Replace l'URL par la citation URL canonique une fois une release taggée.
