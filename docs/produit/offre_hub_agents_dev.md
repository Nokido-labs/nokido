<!-- revu-le: 2026-10-06 -->
> Mise à jour : 2026-10-06

# Offre 1 — le hub d'agents pour développeurs

> Décision owner du 2026-10-06 : la première offre vendue est un **hub local d'agents de code, gouverné et
> doté de mémoire**, pour les développeurs. Nom commercial et prix : à décider par l'owner. Ce document fixe
> le périmètre de la v1 et les critères qui disent qu'elle est prête — chacun MESURABLE.

## Le problème

Un développeur qui travaille avec plusieurs agents de code (Claude Code, Codex CLI, Gemini CLI) les voit
repartir de zéro à chaque session, écrire dans son dépôt sans garde-fou commun, envoyer son code au cloud sans
qu'il sache quoi ni combien, et annoncer « c'est fait » sans preuve.

## La promesse

Un hub qui tourne sur sa machine et que tous ses agents partagent :

1. **Une mémoire commune** — l'historique du projet, ses décisions et ses pièges, retrouvés par recherche
   locale (texte et vecteurs), sans rien envoyer dehors.
2. **Des écritures gouvernées** — chaque édition et chaque commande d'agent passe par un garde : syntaxe
   vérifiée, secrets refusés, verrou anti-écrasement entre agents, journal de qui a fait quoi.
3. **La preuve plutôt que l'annonce** — une CI de référence locale qui ne valide qu'avec preuve, et un statut
   qui distingue ce qui est déclaré, observé et vérifié.
4. **Local d'abord** — le calcul reste sur la machine par défaut ; ce qui part au cloud est dit, borné et
   compté.

Différenciant : la gouvernance et la preuve. Les autres outils donnent de la mémoire ou de l'orchestration ;
aucun ne refuse de déclarer « fait » ce qui n'est pas prouvé.

## Pour qui

Développeurs solo et petites équipes techniques (2 à 15 personnes), sous Windows ou Linux, qui utilisent déjà
au moins un agent de code et tiennent à la confidentialité de leur code ou au coût de leurs tokens.

## Périmètre de la v1

| Inclus | Exclu de la v1 (reste dans le dépôt, hors offre) |
| --- | --- |
| Hub MCP local et ses outils gouvernés (édition, exécution, recherche, introspection) | L'« organisme » complet : rythme circadien, soif épistémique, essaim, couche neuronale, AMI, NPU |
| Mémoire RAG locale, ingestion du dépôt de l'utilisateur | Interfaces grand public (hub web :7400), domotique, réseau (netcfg) |
| Branchement automatique de Claude Code, Codex CLI, Gemini CLI | Base de connaissance pré-remplie de 45 Go |
| Gardes : commandes, secrets, AST, verrou multi-agents, journal | Modèles locaux lourds obligatoires |
| CI de référence locale et statut prouvé | Mode multi-machines, pairs distants |
| `nokido-doctor` : diagnostic et remède nommés | |

## Profil « dev » (le profil allégé de cette offre)

Seuls les services nécessaires à la promesse démarrent : le hub, le superviseur, l'embedder local, la base de
la mémoire de l'utilisateur. Tout le reste est désactivé par défaut et activable à la demande.

Cible : **8 Go de RAM** minimum, 16 Go recommandés ; **moins de 5 Go de disque** hors modèles. À mesurer.

## Critères d'acceptation de la v1

Chaque critère se mesure en CI ou sur une machine vierge, jamais à l'estime.

| # | Critère | Mesure |
| --- | --- | --- |
| 1 | Installation de zéro au premier succès en **moins de 15 minutes** | chronométrée en CI sur une VM vierge Windows et Linux |
| 2 | **Premier succès** = un agent de code connecté au hub fait une recherche dans la mémoire du dépôt et une édition gouvernée | test de bout en bout du parcours |
| 3 | **Sept jours sans intervention humaine**, reprise automatique après redémarrage | test d'endurance |
| 4 | Profil « dev » sous **8 Go de RAM** en charge normale | relevé de l'empreinte pendant l'endurance |
| 5 | **Zéro vulnérabilité haute** connue à la publication | pip-audit et Dependabot à chaque version |
| 6 | Mise à jour d'une version à la suivante **sans perte** de mémoire ni de réglages | test de montée de version |
| 7 | Désinstallation propre | test sur VM : plus aucun service, aucun fichier hors des dossiers choisis |
| 8 | Documentation par parcours : installer, brancher un agent, retrouver, gouverner, diagnostiquer | relue sur VM par quelqu'un qui ne connaît pas Nokido |

## Ce qui reste à décider par l'owner

- Le nom commercial de l'offre.
- Le modèle de prix (par poste, par équipe, support inclus ou non) et l'articulation AGPL / licence commerciale.
- Les trois partenaires de conception à approcher en premier.

## Prochains chantiers techniques, dans l'ordre

1. Définir le profil « dev » dans la configuration des services (profil de démarrage), et mesurer son empreinte.
2. Installation en une commande, prouvée en CI sur VM vierge (critère 1).
3. Test de bout en bout du premier succès (critère 2).
4. Test d'endurance et reprise automatique (critères 3 et 4).
