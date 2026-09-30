# Fiche de sortie — Veille « openrouter » (2026-09-27)

Corpus : `watch:openrouter:` — **1 page** (`docs/quickstart`), 11 chunks actifs (dossier
`sandbox/workspace/veille_fiches_dossier_3themes_2026-09-27.md`). **Couverture MINCE, DITE** : ni la doc de routage des
fournisseurs ni celle des replis de modèles n'ont été captées. Premiers 3 500 caractères lus.

## 1. PATTERNS
| # | Pattern | Source (quickstart) |
|---|---|---|
| O1 | Une API unique pour des centaines de modèles, replis automatiques, choix du moins cher | « OpenRouter gives you access to hundreds of AI models through a single API endpoint. It handles fallbacks automatically and picks the most cost-effective option for each request. » |
| O2 | Alias « latest » qui change de modèle sans redéploiement | `~openai/gpt-latest` « always resolves to the newest OpenAI flagship model, so your code keeps using the freshest version without redeploying » |
| O3 | Catalogue interrogeable | `GET /api/v1/models` |
| O4 | En-têtes d'attribution optionnels (URL et nom du site) | `HTTP-Referer`, `X-OpenRouter-Title` |
| O5 | Index de documentation pour agents | `openrouter.ai/docs/llms.txt` |

## 2. NOKIDO_EXISTING
| Pattern | fichier:ligne | Constat |
|---|---|---|
| O1 | `app/forge_agent_proxy.py:818` `class ClaudeOpenRouter(Provider)`, modèle `anthropic/claude-sonnet-4` | fournisseur OpenRouter PRÉSENT ; usage réel non mesuré. |
| replis | `app/forge_cognitive_router.py:241` `_call_with_fallback` ; cascade des free-tiers (`call_cascade`) ; routage litellm (fiche dépendances, D7) | replis PRÉSENTS côté Nokido, indépendamment d'OpenRouter. |
| O2 | doctrine owner du 24/09 | « un alias vers une famille sert son modèle par défaut — prouver le modèle servi » : un alias `~…-latest` est une substitution silencieuse. |
| O4 | RULES « le cloud reçoit peu, et filtré » | les en-têtes d'attribution enverraient l'identité du site à un tiers. |

## 3. EVIDENCE
- **PRÉSENT** : section 2, lue en recon, non exécutée.
- La page ne dit rien de mesurable sur la qualité des replis ; aucune affirmation chiffrée reprise.

## 4. GAPS
1. **Modèle réellement servi non tracé** quand un agrégateur replie : le champ `model` de la réponse est-il comparé au
   modèle demandé ? NON ÉTABLI.
2. **Nom de modèle épinglé et daté** (`claude-sonnet-4`) : existe-t-il encore chez le fournisseur ? Non mesuré.
3. **Corpus trop mince** pour juger le routage des fournisseurs.

## 5. MINIMAL_EXPERIMENT (aucun appel payant ; lecture seule)
a. Lire dans `forge_agent_proxy` si le `model` retourné est comparé au `model` demandé.
b. `GET /api/v1/models` pour vérifier que le slug épinglé existe (clé requise : la page ne le dit pas) — en ligne, feu vert.

## 6. NR (si ADOPT)
Une réponse dont le `model` diffère du modèle demandé est marquée SUBSTITUÉE, jamais servie comme le modèle demandé.

## 7. DECISION
- **REJECT** : alias `~…-latest` en production (contraire à la doctrine du 24/09) ; en-têtes d'attribution.
- **ADOPT** : mesures a et b.
- **DEFER** : fiche sur le routage des fournisseurs — re-sourcer la doc « provider routing » et « model fallbacks ».
