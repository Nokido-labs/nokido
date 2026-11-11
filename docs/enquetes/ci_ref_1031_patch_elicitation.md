# Enquete CI de reference 31/10 : patch elicitation

## Affirmations

| Affirmation | Preuve (fichier:ligne ou commit) | Etat |
|-------------|--------------------------------|-------|
| L'import direct de forge_mcp_elicitation dans tools/nokido_hub.py (observer_requete) a ete pose HORS de l'outil de patch dont le test verifie les points d'appel | tools/nokido_hub.py:999 | PROUVEE |

## Cause

L'import direct de forge_mcp_elicitation dans tools/nokido_hub.py a ete ajoute manuellement sans utiliser l'outil de patch, ce qui a conduit a une violation du contrat du test.

## Correctif propose

1. Retirer l'import direct de forge_mcp_elicitation dans tools/nokido_hub.py
2. Utiliser l'outil de patch pour ajouter l'import
3. Mettre a jour le test pour reflechir les changements

## NR

- Verifier que l'import est bien pose par le patch
- Confirmer que le test passe apres les modifications
- Documenter le processus de patching dans le README

