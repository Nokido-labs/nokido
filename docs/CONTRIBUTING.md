# Nokido — Convention de Commits

Auteur unique du projet : **user**. Aucun trailer de co-auteur, aucune
attribution d'agent IA — ni dans les messages de commit, ni dans les en-têtes
de fichiers source. Les LLM sont des outils ; ils ne sont pas auteurs.

---

## 1. Subject (ligne 1)

Format **Conventional Commits** :

```
<type>(<scope>): <description courte impérative, < 72 chars>
```

| `<type>` | Usage |
|---|---|
| `feat` | Nouvelle fonctionnalité |
| `fix` | Correction d'un bug |
| `refactor` | Restructuration sans changement de comportement |
| `perf` | Optimisation perf sans changement de comportement |
| `test` | Ajout/modification de tests |
| `docs` | Documentation seulement |
| `chore` | Maintenance (config, deps) |
| `build` | Build, packaging |
| `ci` | Configuration CI/CD |
| `style` | Formatage, indentation (jamais de logique) |
| `revert` | Revert d'un commit antérieur |

Exemples :

```
fix(mcp): retire _stdin_watchdog qui consommait stdin
feat(agent_proxy): +3 providers Cohere/Perplexity/Tavily
```

Le hook `.githooks/commit-msg` plafonne le sujet à 80 caractères et rejette
les messages placeholder (`wip`, `tmp`, `fix` seul, etc.).

---

## 2. Body (optionnel)

Une ligne vide après le sujet, puis du texte libre expliquant **pourquoi** le
changement et **comment** il fonctionne. Wrapper à ~72 caractères.

Trailers factuels admis, uniquement s'ils servent : `Refs:`, `Fixes:`,
`Reverts:` (hashes de commit ou IDs d'issue liés).

---

## 3. Pas d'attribution IA

- Aucun `Co-Authored-By` pointant vers un LLM (Claude, Gemini, Cline, etc.).
- Aucun bloc `Author-Agent` / `Author-Model` / `Author-Channel` / `Author-Session`
  dans les messages de commit ni dans les en-têtes de fichiers.
- Le code produit avec l'aide d'un LLM est signé par l'humain qui le commite.
  L'outil n'est pas l'auteur.
