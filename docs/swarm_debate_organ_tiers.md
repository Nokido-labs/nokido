# Débat Swarm — Organes Nokido -> agents bas-niveau ?

_Panel : groq, cerebras, mistral, gpt4o_github, cohere (5 rôles distincts) · 3 tours._

## Tour 1 — prises de position
**Synthèse du débat :**

Les participants ont largement validé la proposition d'une architecture 3-tiers (Réflexe, Acteur réactif, Agent) pour gérer la complexité et la latence des organes dans le système Nokido. Les points clés d'accord incluent :

1. **Réflexe synchrone** : Les modules critiques synchrones du hot-path (RBAC, firewall, etc.) doivent rester non-agentifiés pour garantir des latences minimales.
2. **Acteurs réactifs** : Les tâches déterministes et à faible complexité peuvent être gérées par des acteurs réactifs (event-driven déterministe) sans nécessiter une agentification complète.
3. **Agents proactifs** : Les processus complexes nécessitant prise de décision autonome ou multi-interaction peuvent être gérés par des agents proactifs, avec une formalisation sous contrat OrganAgent pour garantir une gestion cohérente de leur état et de leur proactivité.
4. **Contrat OrganAgent** : La définition d'un contrat OrganAgent est essentielle pour spécifier les responsabilités, les métriques de performance et les mécanismes d'extensibilité des agents.

Cependant, des tensions structurelles et des divergences notables ont été identifiées :

1. **Risque de surcomplexité** : La séparation stricte en Réflexe/Acteur/Agent peut engendrer une fragmentation inutile si mal calibrée.
2. **Latence additive** : Chaque couche d'agent ajoute une latence, ce qui peut dépasser le SLA de 1 ms.
3. **Deadlock** : Le risque de deadlock existe si un agent proactif attend un accusé de réception du réflexe qui, lui, attend un événement du même agent.
4. **Surface d'attaque exponentielle** : L'ajout d'agents proactifs peut augmenter la surface d'attaque du système.
5. **Gestion de la cohérence** : Les agents proactifs doivent publier leurs changements via un bus NATS/Redis Stream avec accusé de réception pour garantir la cohérence du système.

Pour résoudre ces tensions et divergences, les participants ont proposé des ajustements et des solutions, notamment :

1. **Isolation des hot-paths** : Encapsuler le module réflexe dans un processus dédié pour éviter les effets de contention des agents génériques.
2. **Gestion de la cohérence** : Les agents proactifs doivent publier leurs changements via un bus NATS/Redis Stream avec accusé de réception.
3. **Contrat OrganAgent** : Définir un schéma de sérialisation (protobuf) et un heartbeat ≤ 200 ms pour les agents proactifs.
4. **Supervision** : Mettre en place des mécanismes de supervision pour détecter et récupérer les défaillances des agents.

En résumé, le débat a validé la proposition d'une architecture 3-tiers pour gérer la complexité

## Tour 2 — challenge des tensions
### Synthèse du Tour 2 : Convergence et Ouverture

**Convergence :**

1. **Définition des Acteurs réactifs** : Les intervenants s'accordent sur la nécessité de définir clairement les caractéristiques des Acteurs réactifs pour éviter la confusion avec les Agents proactifs.
2. **Frontière Réflexe/Acteur** : La distinction entre les modules synchrones du hot-path (Réflexe) et les Acteurs réactifs est reconnue comme cruciale, avec des critères à établir pour déterminer quand un module doit être considéré comme un Réflexe ou un Acteur réactif.
3. **Optimisation des acteurs réactifs** : Les intervenants conviennent que les acteurs réactifs doivent être optimisés pour éviter la latence additive et respecter les SLA.
4. **Gestion de la cohérence des données** : La nécessité de gérer la cohérence des données de manière transparente et fiable est soulignée, avec des mécanismes de publication-abonnement et d'accusé de réception.

**Ouverture :**

1. **Critères de détermination des Acteurs réactifs** : Les critères pour déterminer quand un processus doit être traité comme un Acteur réactif ou un Agent proactif restent à définir précisément.
2. **Mécanismes de communication** : Les mécanismes de communication entre les Acteurs réactifs et les Agents proactifs doivent être établis pour garantir la cohérence du système.
3. **Gestion des dépendances** : La gestion des dépendances entre les agents et les réflexes pour éviter les deadlocks et les situations de blocage nécessite des mécanismes de verrouillage et de gestion des dépendances.
4. **Surface d'attaque** : L'augmentation de la surface d'attaque due à l'ajout d'agents proactifs nécessite des mesures de sécurité adéquates, telles que des contrôles d'accès robustes et une surveillance continue des activités des agents.

**Divergences notables :**

1. **Granularité du dispatch** : Les intervenants ont des opinions divergentes sur la granularité du dispatch et les critères pour déterminer quand un module doit être considéré comme un Réflexe ou un Acteur réactif.
2. **Coût de sérialisation inter-tiers** : Les coûts de sérialisation inter-tiers et les mécanismes de communication entre les Acteurs réactifs et les Agents proactifs sont encore à définir.
3. **Contention de la file d'événements** : La gestion de la contention de la file d'événements et les mécanismes pour éviter les deadlocks sont encore à établir.

En résumé, le tour 2 a permis de clarifier certaines questions, mais des points importants restent à résoudre, notamment la définition des critères pour les Acteurs réactifs, les mécanismes de communication

## RECO FINALE (convergence)
**Récapitulatif des recommandations finales :**

1. **Conserver le modèle 3-tiers** : Il offre une bonne séparation des préoccupations et permet une gestion plus efficace de la complexité.
2. **Définition claire des Acteurs réactifs** : Établir des critères précis pour déterminer quand un processus devient un Acteur réactif, en tenant compte de la latence, des SLA et de la granularité du dispatch.
3. **Optimisation des Acteurs réactifs** : Mettre en place des mécanismes d'optimisation pour réduire la latence additive et assurer une réponse rapide aux événements.
4. **Gestion de la cohérence des données** : Implémenter un système de publication-abonnement robuste avec des accusés de réception pour garantir la cohérence des données entre les différents modules.
5. **Mécanismes de communication** : Définir des protocoles de communication clairs entre les Acteurs réactifs et les Agents proactifs, en tenant compte des coûts de sérialisation inter-tiers.
6. **Gestion des dépendances** : Mettre en place des mécanismes de verrouillage et de gestion des dépendances pour éviter les deadlocks et les blocages.

**Règle de décision réflexe-vs-agent :**

1. **Critère de latence** : Un module doit être considéré comme un Réflexe si sa latence est inférieure à 10 ms.
2. **Critère de complexité** : Un module doit être considéré comme un Acteur réactif si sa complexité est élevée.
3. **Critère de cohérence des données** : Un module doit être considéré comme un Acteur réactif si sa cohérence des données est critique.
4. **Critère de sécurité** : Un module doit être considéré comme un Acteur réactif si sa sécurité est critique.
5. **Critère de scalabilité** : Un module doit être considéré comme un Acteur réactif si sa scalabilité est importante.

**Divergences notables :**

* La définition des critères pour déterminer si un module est un Réflexe ou un Acteur réactif varie légèrement entre les différentes recommandations.
* La gestion de la cohérence des données et la sécurité sont des points clés qui nécessitent une attention particulière.
* La scalabilité et la performance sont également des facteurs importants à prendre en compte lors de la conception du modèle 3-tiers.
