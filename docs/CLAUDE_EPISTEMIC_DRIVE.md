<!-- DEPORTE depuis CLAUDE.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de CLAUDE.md, re-facture a chaque tour. -->

# 16. CHANTIER EN COURS (Septembre 2026) : L'EPISTEMIC DRIVE

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## 16. CHANTIER EN COURS (Septembre 2026) : L'EPISTEMIC DRIVE

Un nouveau paradigme architectural a été défini le 2026-09-06. Il représente le prochain grand couplage entre le Cortex et le Système Nerveux Autonome.
**Ne pas chercher à le coder dans l'immédiat sans ordre explicite**, mais l'intégrer dans toute réflexion sur le RAG, le Swarm, et le système Endocrinien.

**La Soif Épistémique (Epistemic Drive) :**
- **Boucle d'autorégulation de la connaissance** : Le système ne répond plus seulement aux questions, il détecte ce qu'il ne sait pas (UNKNOWN, BLIND_SPOT) et formule des questions candidates.
- **Homeostatic Epistemic Controller** : L'enquête scientifique (lancement du swarm, expériences empiriques) n'est déclenchée que si le budget métabolique le permet (ressources CPU/RAM abondantes).
- **Curiosité par Surprise (Friston)** : Une anomalie (xpected ≠ observed) génère un EPISTEMIC_EVENT traité par Active Inference.
- **Swarm à Preuves concurrentes** : Le statut CONTESTED (agents en désaccord) déclenche l'Epistemic Drive. La connaissance acquise empiriquement (par l'expérience) l'emporte sur la documentation statique.
- **Dette Épistémique (epistemic_debt)** : Les "trous" sont stockés et résolus de manière asynchrone pendant le sommeil paradoxal (orge_circadian.py).

Voir la ROADMAP.md (section Px) pour les détails.

---

