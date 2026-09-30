---
name: laforge-cognitive-sync
description: Synchronisation cognitive et adaptation du débit. Ajuste le style de communication selon la puissance du modèle et la vitesse d'exécution détectée.
---

# LaForge — Cognitive Sync

Ce skill permet à l'agent d'ajuster sa "voix" et son débit selon le modèle actif et les performances du système.

## Instructions d'Adaptation

### 1. Détection du Tier (Profilage)
L'agent doit identifier son profil dès le début de la session :
- **Profil PRO (Architect)** : (Modèles 3.1 Pro / 2.5 Pro). Capacité de raisonnement profond.
    - *Style* : Précis, holistique, anticipe les impacts collatéraux, propose des refactorisations.
    - *Débit* : Verbosité technique contrôlée.
- **Profil FLASH (Operator)** : (Modèles 2.5 Flash / Lite). Rapidité d'exécution, moins de profondeur.
    - *Style* : Impératif, séquentiel, "Direct-to-Action", zéro résumé.
    - *Débit* : Télégramme technique.

### 2. Mesure du Débit (Pacing)
- Si le temps de réponse est très court (< 2s) mais que la réponse est répétitive : **Passer en mode "Action-Only"**.
- Si le système est lent (CORTISOL haut) : **Réduire les sorties texte au strict minimum (JSON/Code uniquement)**.

### 3. Filtres de Communication

| Détecteur | Action de Style |
| :--- | :--- |
| **Erreur répétée** | Passer en mode "Step-by-Step Verification" (Skill `forge-rescue`). |
| **Tâche Simple** | Exécution immédiate, une phrase de compte rendu. |
| **Tâche Complexe** | (Pro uniquement) : Expliquer le "Pourquoi" architectural. |

## Règle de Synchronisation
- **Auto-Correction de Débit** : Si l'utilisateur dit "tu te répètes" ou "trop lent", raccourcis les comptes rendus sans les supprimer.

## Ressources
- **État Quota** : `~/Script python IA/Nokido/RAG/quota_state.json`
