---
name: forge-quota
description: "À utiliser par tout agent du swarm avant un travail gourmand en modèle, sur une erreur 429 ou un quota épuisé, ou pour arbitrer entre abonnement CLI, offre gratuite, API payante et modèle local. Lit l'état réel des quotas (hub quota_status, forge_quota_tracker), déclare le sien, et bascule sans bloquer vers le local ou un autre fournisseur."
---

# forge-quota — ne jamais être bloqué par un quota, ni brûler un abonnement sur du déportable

Vaut pour toutes les surfaces : Claude Code, Antigravity/Gemini, Codex, Copilot, Cline et les agents
du swarm. `forge-models` choisit le modèle ; cette skill gère le budget et la bascule.

## Les quatre régimes

| Régime | Exemples | Ce qui s'épuise |
|---|---|---|
| Abonnement CLI (OAuth) | claude_cli, AGY/gemini_cli, codex, copilot | fenêtres d'usage du compte de l'owner |
| Offre gratuite | groq, openrouter_free, cerebras | requêtes et jetons par minute ou par jour |
| API payante | clés du coffre | crédit (402 = solde, pas quota) |
| Local | ollama, llama.cpp, LM Studio | rien : RAM et temps seulement |

## Lire l'état réel

- **`hub action=quota_status`** : instantané de tous les fournisseurs (`forge_quota_tracker`) ;
  `provider=<nom>` pour le détail, `format=json`, `fetch_live=true` pour interroger les endpoints.
  ⚠️ Cette action est traitée par le hub mais **absente de l'enum du schéma** de l'outil `hub` : une
  surface qui valide strictement son schéma passe par `LAFORGE_PYTHON tools/hub_call.py quota_status`.
- **`hub action=whoami`** : `providers_available`, avec latence au premier jeton et note.
- Le tracker **apprend seul** : chaque réponse qui passe par `forge_agent_proxy` livre ses en-têtes de
  rate-limit (`record_response_headers`, `record_429`, `capacite_observee`). Passer par le hub, c'est
  nourrir la mesure de tout le swarm.

## Déclarer son état

- **`hub action=quota_report`** : aujourd'hui seulement les 4 pools Gemini (`flash`, `flash_lite`,
  `pro`, `preview_pro`), après `/model` dans AGY. Les autres surfaces n'ont pas encore de champ pour
  déclarer leur solde : limite connue, le tracker comble en partie par les en-têtes.
- **`hub action=quota_model quality=low|medium|high|ultra`** : choix automatique d'un modèle Gemini
  selon la qualité demandée (écrit `~/.gemini/settings.json`).

## Conduite

1. **Avant un gros lot** : lire `quota_status` ; déporter le déportable (relecture, résumé,
   reformulation, typage) par `ask provider=auto` ou `ollama` ; garder l'abonnement pour l'interactif
   et le raisonnement lourd.
2. **Sur 429** : pas de boucle de réessai. Basculer, dans l'ordre : autre pool du même fournisseur,
   autre fournisseur gratuit, modèle local ; abaisser la qualité si besoin ; DIRE la bascule. C'est
   une action autonome (forge-autonomie).
3. **Abonnement CLI épuisé** : router le CLI vers les modèles Nokido (`forge-route`) ou déléguer au
   swarm local.
4. **402, 401, 403 ne sont pas des quotas** : solde, clé ou palier. Ne pas réessayer, ne pas déclarer
   le fournisseur mort : le signaler, c'est une décision owner.

## Gemini (AGY) — pools séparés

- Flash et Flash-Lite partagent un pool (remise à zéro en 12 h) ; Pro a le sien (24 h) ; la
  préversion a le sien (24 h). Noms de modèles à revérifier dans `/model` : ils changent.
- 0 % utilisé dans `/model` = réellement disponible.

Liens : `forge-models` (choisir), `forge-route` (router un CLI), `forge-cognitive-sync` (adapter le
débit quand le budget baisse).
