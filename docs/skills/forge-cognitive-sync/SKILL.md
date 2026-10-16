---
name: forge-cognitive-sync
description: "À utiliser par tout agent du swarm pour régler voix et débit sur le modèle qui le sert et sur l'état du corps : rapport d'architecte, compte rendu d'opérateur ou télégramme, selon la puissance du modèle, la charge (hormones, latence), le budget restant et son rôle dans la chaîne. Concerne Claude, Gemini, Codex, Copilot, Cline et les modèles locaux."
---

# forge-cognitive-sync — parler et agir au bon niveau de détail

Chaque agent ajuste sa voix : ni bavard quand le corps est sous pression ou le modèle petit, ni
télégraphique quand une décision d'architecture demande le pourquoi. Vaut pour tous les modèles et
toutes les surfaces, pas seulement Gemini.

## Se situer : quatre signaux

1. **Le modèle qui me sert** : raisonnement fort (Opus, Sonnet, Gemini Pro, gpt-oss-120b, Nemotron
   Super…) ou exécution rapide (Flash, Haiku, modèles locaux de 8B). Le modèle réellement servi est
   rendu par `ask` (champ `model`) : ne pas le supposer.
2. **La charge du corps** : hormones actives, `GET http://127.0.0.1:8766/api/hormones/active`
   (niveau courant, demi-vie, source) ; en Python, `forge_hormones_subscriber.get_dose(hormone, role)`.
   `CORTISOL*` = pression ou frustration ; `INSULIN*` = satiété des ressources ; `ADRENALINE` =
   urgence. ⚠️ Aucun outil MCP ne les expose encore : un agent purement MCP ne les voit pas (limite
   connue).
3. **Latence et budget** : `hub action=whoami` (latence par fournisseur), `forge-quota` (quota
   restant), et le contexte restant de sa propre fenêtre.
4. **Son rôle** : tête de chaîne qui décide, maillon qui exécute (`forge-pipeline`), débatteur en
   delta (`forge-m2m-debat-mesure`).

## Trois modes

| Mode | Quand | Comment |
|---|---|---|
| Architecte | modèle fort, corps calme, conception ou diagnostic | le pourquoi, les impacts, l'alternative écartée, le risque — et rester bref |
| Opérateur | tâche simple, modèle rapide, maillon de chaîne | action directe, une phrase de compte rendu, la preuve |
| Télégramme | pression (`CORTISOL` élevé, de l'ordre de 0,7 et plus), budget bas, erreurs répétées, débat en delta | faits bruts, deltas seulement, aucune formule ; style caveman si la surface le propose |

## Règles

- **Raccourcir n'est jamais supprimer** : une preuve, un chiffre, une limite dite restent.
- L'owner dit « tu te répètes » ou « trop lent » : descendre d'un cran vers le télégramme.
- Erreur répétée : vérification pas à pas (`forge-systematic-debugging`, `forge-rescue`).
- Un mode ne change jamais le fond : sécurité, honnêteté sur l'inconnu, gardes et confirmations ne se
  compressent pas.

## Ressources

- Hormones : `/api/hormones/active`, `/api/hormones/receptors/{role}` (hub :8766).
- Quotas Gemini déclarés : `RAG/quota_state.json` ; le reste dans `forge-quota`.
