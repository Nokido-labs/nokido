# 📖 Nokido — Mode d'Emploi Complet

> Version 17.0.0 — Mars 2026

---

## Table des matières

1. [Installation](#1-installation)
2. [Premiers pas](#2-premiers-pas)
3. [Commandes CLI](#3-commandes-cli)
4. [Architecture & agents](#4-architecture--agents)
5. [Configuration (.env)](#5-configuration-env)
6. [RAG — Base de connaissance](#6-rag--base-de-connaissance)
7. [MCP Server — Intégration Claude Code](#7-mcp-server--intégration-claude-code)
8. [Workflow OSS complet](#8-workflow-oss-complet)
9. [Interface TUI](#9-interface-tui)
10. [Dépannage](#10-dépannage)

---

## 1. Installation

### Prérequis

| Requis | Version |
|--------|---------|
| Python | ≥ 3.10 |
| Docker | Optionnel (pour isolation) |
| Git | ≥ 2.40 |

### Installation rapide

```bash
# Via pip (recommandé)
pip install laforge-agent

# Ou depuis les sources
git clone https://github.com/user/Nokido.git
cd Nokido
pip install -e ".[dev]"
```

### Vérification

```bash
nokido --version
# laforge-agent 17.0.0
```

---

## 2. Premiers pas

### Démo intégrée (aucune config requise)

```bash
nokido --demo
```

Rejoue en direct le fix `psf/requests` PR #7295 — parfait pour comprendre le workflow.

### Voir les statistiques live

```bash
nokido --stats
```

Affiche un tableau Rich avec les PRs ouvertes, tests générés, repos touchés.

### Premier fix en mode dry-run (simulation sans PR)

```bash
nokido "fix bugs in Delgan/loguru" --dry-run
```

Analyse le repo, trouve les bugs, génère le fix — **sans créer de PR ni modifier GitHub**.

---

## 3. Commandes CLI

### Syntaxe générale

```bash
nokido [TASK] [OPTIONS]
```

### Commandes disponibles

```bash
# Lancer un fix autonome
nokido "fix bugs in <owner>/<repo>"
nokido "find type errors in aio-libs/yarl"
nokido "improve test coverage in tkem/cachetools"

# Mode simulation
nokido "fix bugs in psf/requests" --dry-run

# Informations
nokido --stats       # Métriques live
nokido --demo        # Démo animée
nokido --version     # Version
nokido --help        # Aide complète
```

### Exemples réels

```bash
# Fix simple — 1 bug, 1 fichier
nokido "fix CancelledError handling in jd/tenacity"

# Fix complet — scan du repo entier
nokido "find and fix bugs in BerriAI/litellm"

# PR + tests uniquement
nokido "write tests for untested functions in encode/httpcore" --dry-run
```

---

## 4. Architecture & agents

Nokido tourne en 4 modes agent, orchestrés automatiquement :

### CHEF — Le planificateur

```
Rôle : Lit le contexte RAG, analyse la tâche, assigne les sous-tâches
Input : Task texte + RAG context (29 règles)
Output : Plan structuré JSON → CLINE
```

### CLINE — L'exécuteur

```
Rôle : Clone le repo, applique le fix, lance les tests, commit
Input : Plan de CHEF
Output : Patch + résultats de tests → DEBAT
```

### DEBAT — Le validateur

```
Rôle : Relit le fix, cherche les edge cases, valide ou rejette
Input : Patch de CLINE
Output : Approbation ou correction → boucle CLINE
```

### AUTO PILOT — L'autonome

```
Rôle : Surveille le système, relance les boucles, gère les timeouts
Mode : Fonctionne en tâche de fond
Triggers : heartbeat gelé, drift > seuil, entropy critique
```

### Changer de mode manuellement

```bash
# Via l'interface TUI
python app/Nokido.py
# Commande : @mode CHEF | CLINE | DEBAT | AUTO

# Via MCP
nokido exec --mode AUTO
```

---

## 5. Configuration (.env)

Créer `Nokido.env` à la racine du projet :

```env
# ── LLM Principal ─────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
# ou
GEMINI_API_KEY=AIza...
# ou Ollama local (gratuit)
LAFORGE_DEFAULT_MODEL=ollama/qwen2.5-coder:7b

# ── GitHub ────────────────────────────────────────────────────
GITHUB_TOKEN=ghp_...

# ── Environnement ─────────────────────────────────────────────
LAFORGE_ENV=dev          # dev | prod
LAFORGE_MCP_DEV=false    # true = actions simulées

# ── RAG ───────────────────────────────────────────────────────
RAG_MAX_RESULTS=10
RAG_SIMILARITY_THRESHOLD=0.75

# ── Timeouts ──────────────────────────────────────────────────
LAFORGE_IDLE_TIMEOUT=3600   # secondes avant auto-rollback
```

### Modèles supportés

| Provider | Modèle | Usage |
|----------|--------|-------|
| Anthropic | `claude-sonnet-4-6` | Recommandé |
| Anthropic | `claude-opus-4-6` | Tâches complexes |
| Google | `gemini-2.0-flash` | Rapide + gratuit |
| Ollama | `qwen2.5-coder:7b` | Local, gratuit |
| Ollama | `deepseek-coder-v2:16b` | Local, performant |

---

## 6. RAG — Base de connaissance

Nokido accumule des règles à chaque fix. Ces règles sont interrogées avant chaque nouvelle tâche.

### Voir les règles en base

```python
from tools.forge_source_discovery import ForgeSourceDiscovery
disc = ForgeSourceDiscovery()
print(disc.stats())
# {'total_entries': 29, 'by_category': {...}, 'avg_similarity': 0.82}
```

### Ajouter une règle manuellement

```python
disc.ingest_to_rag(
    content="Always check isinstance(x, bytes) before calling .decode()",
    url="https://github.com/user/requests/pull/7295",
    title="bytes decode safety — psf/requests fix",
    query="bytes decode isinstance python safety"
)
```

### Recherche sémantique

```python
results = disc.search("exception handling None check", max_results=5)
for r in results:
    print(r['title'], r['score'])
```

---

## 7. MCP Server — Intégration Claude Code

Nokido expose un serveur MCP pour s'intégrer nativement avec Claude Code.

### Démarrer le serveur MCP

```bash
# Mode stdio (Claude Code)
python tools/nokido_mcp_server.py

# Mode HTTP (développement)
python tools/forge_mcp_http.py --port 8765
```

### Configuration Claude Code

Dans `.claude/settings.json` :

```json
{
  "mcpServers": {
    "laforge": {
      "command": "python",
      "args": ["~/Script python IA/Nokido/tools/nokido_mcp_server.py"],
      "env": {}
    }
  }
}
```

### Outils MCP disponibles

| Tool | Description |
|------|-------------|
| `nokido_fix` | Lance un fix autonome sur un repo |
| `nokido_stats` | Retourne les métriques live |
| `nokido_rag_search` | Recherche sémantique dans le RAG |
| `nokido_pr_status` | Statut des PRs ouvertes |
| `nokido_mode` | Change le mode agent actif |

---

## 8. Workflow OSS complet

Voici le déroulé exact d'un fix de bout en bout :

```
┌─ 1. ANALYSE ────────────────────────────────────────────────┐
│  nokido "fix bugs in Delgan/loguru"                        │
│  → CHEF charge le contexte RAG (29 règles)                  │
│  → CHEF identifie les patterns suspects                      │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ 2. CLONE & SCAN ───────────────────────────────────────────┐
│  git clone --depth 1 --single-branch Delgan/loguru          │
│  → Scan des fichiers .py via tree-sitter AST                │
│  → Identification des candidats (score > 0.75)              │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ 3. FIX ────────────────────────────────────────────────────┐
│  CLINE génère le patch minimal                               │
│  → 1-5 lignes modifiées en moyenne                          │
│  → Respecte le style du fichier existant                    │
│  → AST Sentinel valide avant commit                         │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ 4. TESTS ──────────────────────────────────────────────────┐
│  CLINE génère les tests                                      │
│  → Cas nominal + edge cases + régression                    │
│  → pytest --tb=short                                        │
│  → Si échec → boucle DEBAT → correction → retry             │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ 5. PR ─────────────────────────────────────────────────────┐
│  Fork du repo sur user/                                   │
│  git commit -m "fix: ..."                                   │
│  git push user/loguru                                     │
│  GitHub API → create_pull_request()                         │
│  → Description + test results + /claim si bounty           │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ 6. RAG UPDATE ─────────────────────────────────────────────┐
│  La règle apprise est ancrée dans le RAG                    │
│  → Disponible pour le prochain fix                          │
└──────────────────────────────────────────────────────────────┘
```

---

## 9. Interface TUI

### Lancer l'interface complète

```bash
python app/Nokido.py
```

### Raccourcis clavier

| Touche | Action |
|--------|--------|
| `Ctrl+C` | Quitter |
| `Tab` | Changer d'onglet |
| `F1` | Aide |
| `F5` | Rafraîchir |
| `Ctrl+L` | Vider les logs |
| `Ctrl+S` | Sauvegarder situation |

### Commandes dans la TUI

```
@fix <owner>/<repo>         Lance un fix
@mode CHEF|CLINE|DEBAT|AUTO Changer de mode
@rag search <query>         Chercher dans le RAG
@stats                      Afficher les métriques
@pr list                    Lister les PRs ouvertes
@snapshot                   Sauvegarder l'état
```

---

## 10. Dépannage

### "Nokido engine not fully loaded"

```bash
# S'assurer d'être dans le bon répertoire
cd "~/Script python IA/Nokido"
python nokido_cli.py --stats
```

### "No module named 'faiss'"

```bash
pip install faiss-cpu
```

### "GitHub API rate limit"

```bash
# Vérifier le token dans Nokido.env
echo $GITHUB_TOKEN
# ou
grep GITHUB_TOKEN Nokido.env
```

### Tests qui échouent

```bash
# Lancer uniquement les tests rapides
pytest tests/ -m "not slow" -v

# Tests de non-régression
pytest tests/nr/ -v
```

### Reset complet

```bash
# Supprimer le cache RAG (garde la DB)
python rag_sanitize.py

# Reset complet (⚠️ perte des règles RAG)
python cleanup_logs.py --all
```

---

## 📞 Support

- **GitHub Issues** : https://github.com/user/Nokido/issues
- **Discord** : *(à venir)*

---

*Nokido v17.0.0 — Autonomous OSS Contribution Agent*  
*Documentation générée avec l'aide de Nokido lui-même.*
