# Contrat concret d’interoception par identité et endpoint

Date : 2026-10-23  
Statut : spécification fondée sur le code lu; aucun nouveau comportement runtime n’est affirmé ici.

## Décision

Faire d’abord apparaître, pour chaque appel d’agent, le lien vérifiable entre **identité effective → endpoint réellement appelé → signaux corporels disponibles → décision du régulateur → effet observé**. Conserver les événements comme transport et déclencheurs; utiliser les mesures continues pour moduler la cadence et les seuils. Ne pas remplacer le bus par une simulation chimique.

## État vérifié dans le code

| Élément | Existant | Limite observée |
|---|---|---|
| État des ressources | `forge_resource_manager.get_snapshot()` fournit un instantané avec amorçage froid et âge; `should_throttle()` applique RAM/CPU/GPU/disque/TDR et durcit certains seuils sous cortisol. | `should_throttle()` rend un booléen; l’appelant ne reçoit pas un dossier unifié « mesure → motif → action ». |
| Régulation cognitive | `FlowRegulator.get_dynamic_threshold()` combine CPU, signal endocrinien et surprise récente; facteurs bornés et repli neutre si source indisponible. | L’identité d’endpoint qui reçoit la modulation n’est pas portée par ce contrat de retour. |
| Hormones | `forge_hormones.release/active` diffuse, expire et persiste certains signaux; `forge_endocrine.receptors()` énumère des récepteurs déclarés. | Un récepteur déclaré ne prouve pas qu’il a consommé le signal ni qu’il a changé une décision. |
| Proprioception | `forge_proprioception.measure_regulation()` compte des hormones et détecte quatre « hooks » par recherche de chaînes. | Ce score est un indice de présence, pas une preuve d’exécution; le nombre d’hormones n’est pas une mesure de charge par endpoint. |
| Carte anatomique | `forge_anatomy_state.get_anatomy_state()` assemble organes, hormones et trafic; expose `flows_live` et `flows_reason`. | Quand les spans ne sont pas joignables, la carte retombe explicitement sur la topologie déclarée. Le code note que les requêtes HTTP n’émettent pas le `span_id` nécessaire à la corrélation. |
| Identité | `tools/forge_client_bootstrap.identities()` lit les rings déclarés dans `config/agent_identities.json`; `forge_tool_gate` distingue l’identité observée de l’identité déclarée; `forge_agent_authority` porte l’autorité. | Le registre bootstrap ne définit pas à lui seul le modèle effectif, l’endpoint, les sens ou l’accès mémoire. Ne jamais traiter le ring déclaré comme autorité. |
| Constantes du corps | Le registre dynamique expose `constantes_du_corps(section)`, en lecture seule. Les sections sont `declare`, `observe` et `tout`. | Une lecture via le tool MCP direct a été refusée (« tool not allowed »), mais le même outil est accessible via `forge_call_dynamic`. La voie effective est donc le registre dynamique, pas le wrapper MCP direct testé. |

## Lecture réelle du corps dans cette session

Lecture du registre dynamique `constantes_du_corps(section="tout")` :

- Paramètres déclarés : `embed.batch_size=32` (bornes 8–128) et `embed.max_workers=4` (bornes 1–8); source indiquée `forge_proposal_applier.py PARAMS_L1 + parametres_l1.json).
- Pour ces deux paramètres, le registre précise `usage_par_le_consommateur = NON OBSERVE`. Valeur effective connue ne signifie donc pas effet consommateur prouvé.
- Mesures observées retournées : `homeostasis_stability=0.537`, `resource_recovery_score=0.938`, `recovery_time_p50_s=566.8`, `pressure_fraction=0.141`, `cpu_calm=0.999`, avec `echantillons=2880`.
- Limite de la réponse observée : pas d’horodatage/âge ni de provenance spécifique par métrique dans la sortie. Les chiffres sont un instantané retourné par l’outil au moment de l’appel, pas une preuve de fraîcheur mesurée ni une mesure associée à un endpoint LLM.

Cela rend l’API de constantes concrète dès maintenant; la prochaine étape est d’attester la consommation et la fraîcheur, puis d’ajouter la corrélation par identité/endpoint.

## Modèle physiologique approfondi

### L’analogie porte sur la boucle, pas sur les noms d’organes

La physiologie utile ici n’est pas une liste de composants baptisés « cerveau », « foie » ou « hormone ». C’est une boucle complète : signaux du milieu et du corps → estimation de l’état → arbitrage → action par un effecteur → mesure du résultat. Pour Nokido : `stimulus → mesure sourcée → estimation → décision bornée → effet → observation après effet`.

Une hormone publiée ou un récepteur déclaré ne ferme pas cette boucle. Il faut prouver qui a lu le signal, quelle décision il a changée, quelle action a eu lieu et comment l’état a évolué.

| Fonction physiologique | Correspondance proposée | Réalité actuelle et limite |
|---|---|---|
| Exteroception | Requête utilisateur, outils, statut provider, réseau et données entrantes | Les entrées existent; il faut préserver leur provenance par appel. |
| Interoception | Vitaux système, quotas, état mémoire, surprise, hormones, santé des services | Plusieurs capteurs existent, mais leurs portées diffèrent : machine, hub, provider, session. Ne pas les fondre en un score sans unités ni champ de portée. |
| Cellule différenciée | Profil effectif : principal, rôle, règles, mémoire et outils autorisés | Le modèle ou endpoint seul n’est pas l’identité. Principal, rôle et route provider sont des axes distincts. |
| Circulation / perfusion | Admission des jobs, attribution de mémoire, priorité et sommeil de services | Correspondance déjà substantielle : `attribuer_pression()` distingue SOI/NON_SOI/NOYAU; `_identites_corps()` s’appuie sur l’inventaire des processus et des preuves de job/battement. Ce diagnostic porte sur les processus/services, pas encore sur chaque requête LLM. |
| Réflexes | RBAC, AST gates, sandbox, règles de sécurité | Doivent rester des invariants déterministes. Les hormones ne peuvent jamais relever les permissions ou désactiver une barrière. La latence doit être mesurée avant d’annoncer « <1 ms ». |
| Modulation endocrine | Signaux bornés, dégradés dans le temps, modulant cadence ou sensibilité | Boucles réelles : cortisol module les seuils de `should_throttle()`; `FlowRegulator` combine CPU, endocrinien et surprise. Le listener SSE journalise l’événement et renvoie un état suggéré; ce chemin seul n’est pas un effecteur. |
| Immunité / compartiments | Firewall, rings, sandbox et scopes mémoire | Bonne analogie pour les frontières. Un refus d’accès est une décision d’autorité, pas un symptôme de fatigue. |
| Mémoire / consolidation | Contexte de tâche = travail immédiat; Blackboard = état partagé transitoire; RAG/SSoT = connaissances persistées et sourcées | Les magasins ont des rôles distincts. Le transfert automatique Blackboard→RAG pendant le sommeil n’est pas démontré ici. |
| Repos / rythme | Fenêtres de maintenance et cadence des workers | Politique d’ordonnancement utile, mais pas sommeil physiologique. Préserver les fonctions critiques et définir les conditions de réveil. |

### Ce que l’allostasie apporte

L’allostasie ne se réduit pas au déplacement d’un setpoint pendant une crise. Elle décrit une régulation qui anticipe les besoins, arbitre entre systèmes et prépare les ressources. La littérature ne stabilise pas une définition unique : plusieurs auteurs discutent si allostasie remplace ou complète homéostasie. Pour Nokido, définition opératoire : **régulation allostatique = changement contextuel ou anticipé de l’allocation et des cibles de service, avec invariants de sécurité fixes, évalué par les résultats et le coût de récupération.**

Cela implique de suivre deux quantités distinctes : l’état présent (pression RAM, latence) et la charge de régulation (durée sous pression, interventions répétées, temps de récupération). Les métriques exposées par `constantes_du_corps` (`homeostasis_stability`, `resource_recovery_score`, `recovery_time_p50_s`) sont utiles, mais leur définition, producteur et ventilation par endpoint restent à établir avant de les utiliser pour commander le système.

### Identité d’un LLM : profil fonctionnel, pas étiquette

Distinguer par appel :

1. **Principal** : identité authentifiée et ring effectif décidé par le hub.
2. **Profil d’agent** : rôle, règles canoniques, mémoire accessible et outils admis.
3. **Endpoint effectif** : client, provider, route et modèle effectivement choisis.
4. **État de l’appel** : trace/span, tâche, usage, latence, erreur et signaux corporels exposés.

Le profil complet ressemble à une cellule différenciée : les mêmes organes, mais des récepteurs et effecteurs permis différents. Le modèle est le substrat de calcul; l’endpoint est la route; l’autorité vient du hub. Le document « âme » peut décrire une finalité et un style, mais ne confère aucun droit d’exécution. Si un provider ne fournit ni quota ni usage, garder le champ `UNKNOWN`; ne pas écrire « l’agent a faim » comme si c’était une observation.

### Trois vitesses, trois responsabilités

- **Voie réflexe** : décision déterministe à la frontière d’une action. Elle protège les invariants; aucun appel LLM n’est requis.
- **Voie autonome/endocrine** : cadence de quelques secondes pour échantillonner les vitaux et moduler admission, concurrence ou délais. Le sampler de ressources vise environ 3 s; les hormones modulent des seuils plutôt que de servir de veto absolu. Utiliser bornes, hystérésis et temps de réfractarité pour éviter les oscillations.
- **Voie allostatique lente** : ajuste des objectifs et la répartition des ressources selon l’historique, l’activité et la récupération. Elle doit apprendre des effets mesurés, pas compter les hormones émises.

Ces voies cohabitent avec les événements : un événement transporte un changement ou réveille un consommateur; des mesures d’état modulent l’intensité de la réponse. La biologie combine elle aussi impulsions nerveuses, concentrations chimiques et rythmes. Les espaces de tuples biochimiques SAPERE inspirent réaction, diffusion, concentration et décroissance, mais ne prouvent ni qu’il faut supprimer le bus ni que Gillespie est un ordonnanceur de production adapté.

### Premier pilote physiologique : perfusion des tâches lourdes

Relier une requête témoin et chaque décision à :

```text
trace + principal/ring résolu
→ provider/model/endpoint effectifs
→ vitaux {valeur, unité, portée, âge, état}
→ décision {contrôleur, seuil, motif}
→ effet {admis, différé, limité, refusé}
→ résultat {latence, erreur, usage, pression après action}
```

Commencer par la pression RAM et l’admission d’un travail lourd : Nokido a déjà snapshots, attribution mémoire SOI/NON_SOI/NOYAU, seuils de throttle et actions sur les services non essentiels. La première greffe est un reçu corrélable « mesure → décision → effet », puis une hystérésis bornée. Mesurer dépassements mémoire, temps de récupération, latence interactive, erreurs et faux ralentissements.

Le keeper n’est pas le premier levier. Il exécute le cycle de vie de services; le rendre plus réactif sans attribution causale ni mesure de récupération peut créer des réveils et endormissements en boucle. Il devient un effecteur à régler lorsque le contrôleur saura quel signal lui demande quel geste et si ce geste a libéré les ressources attendues.

### Sources consultées

- Khalsa et al., [The Emerging Science of Interoception](https://pmc.ncbi.nlm.nih.gov/articles/PMC7780231/) : cadre intégrant perception, interprétation et régulation des signaux internes.
- Chen et al., [Interoception as modeling, allostasis as control](https://doi.org/10.1016/j.biopsycho.2021.108242) : interoception comme modèle et allostasie comme contrôle à référence variable.
- Ramsay & Woods, [Clarifying the Roles of Homeostasis and Allostasis](https://pmc.ncbi.nlm.nih.gov/articles/PMC4166604/) : controverse terminologique et rôle des boucles effectrices.
- Timmis & Neal, [Artificial Homeostasis](https://www.cs.kent.ac.uk/pubs/2003/1586/) : articulation de réseaux neuraux, immunité artificielle et système endocrinien.
- Viroli & Casadei, [Biochemical Tuple Spaces](https://doi.org/10.1007/978-3-642-02053-7_8) : coordination par réactions et concentrations, formalisée avec sémantique stochastique.


## Contre-audit exhaustif des pistes AGY

Audit du code et des propositions retranscrites dans la conversation, au 2026-10-23. Les statuts signifient : **présent** = mécanisme vu dans le code; **partiel** = une brique existe, mais pas le système théorique complet; **non établi** = pas retrouvé dans le périmètre inspecté ou effet non démontré.

| Piste AGY | Verdict sur le principe | Confrontation au code / décision Nokido |
|---|---|---|
| **Active Inference / Free Energy / `pymdp`** | **Partiel, réel.** | `forge_active_inference.py` implémente des prédictions, surprise et free energy explicitement simplifiée; `forge_active_inference_agent.CyberAgent` enveloppe un agent `pymdp`. Ce n’est pas une inférence corporelle unifiée ni une preuve d’agent actif en production. `choose_action()` tombe sur un choix aléatoire uniforme si l’API échoue : ne pas brancher ce chemin à un effecteur de sécurité. L’usage actuel dans `FlowRegulator` est une modulation bornée par la surprise récente, pas une boucle FEP complète. |
| **Markov blankets = compartiments lymphatiques** | **Analogie à corriger.** | Une Markov blanket est une frontière statistique d’indépendance conditionnelle dans un modèle probabiliste; une sandbox/ring est une frontière de sécurité et d’accès. Les deux peuvent inspirer l’isolation, mais ne sont pas « exactement » le même mécanisme. Aucun blanket statistique n’a été identifié dans le câblage inspecté. |
| **SAPERE / biochemical tuple spaces** | **Source pertinente, transposition non réalisée.** | Les travaux définissent des tuples-concentrations et des règles de réaction/diffusion. Le Blackboard Nokido n’est pas encore un moteur réaction-diffusion; hormones et SSE sont explicitement événementiels. Conserver transport événementiel et tester des concentrations/gradients seulement si une politique mesurée en tire avantage. |
| **Gillespie comme ordonnanceur** | **Proposition non justifiée.** | L’algorithme exact simule des réactions chimiques stochastiques; le DGA 2024 en rend une variante différentiable pour apprendre des cinétiques et concevoir des circuits biologiques. Cela ne démontre pas zéro polling, absence d’événements ni adéquation à l’ordonnancement système. Pas de scheduler Gillespie repéré dans le code. |
| **Systèmes endocriniens artificiels / AES** | **Partiel et réellement câblé.** | Les hormones ont bornage, TTL/décroissance et diffusion SSE. Le listener observe et suggère un état; les effecteurs réels vus sont notamment `should_throttle()`, `FlowRegulator`, `should_pause_worker()` et `get_delay_multiplier()`. Une hormone publiée ne prouve toujours pas que chaque endpoint l’a consommée. |
| **Ashby / ultrastabilité** | **Partiel, pas ultrastabilité complète.** | `FlowRegulator` combine CPU, hormone et surprise pour modifier un seuil. Je n’ai pas trouvé une seconde boucle qui identifie les variables essentielles, détecte l’échec de la régulation puis reconfigure de façon autonome ses propres paramètres. La modulation contextuelle seule ne suffit pas à revendiquer l’ultrastabilité. |
| **Control Barrier Functions (CBF)** | **Non établi.** | Aucune fonction barrière ni filtre de commande CBF explicite n’a été retrouvée par introspection. AST, RBAC et sandbox sont des barrières discrètes/politiques utiles, mais une CBF demanderait un état dynamique, un ensemble sûr et un filtre de contrôle défini mathématiquement. Ne pas les rebaptiser CBF. |
| **LIDA / Global Workspace** | **Ressemblance partielle, LIDA non établie.** | Postal et swarm possèdent des fonctions nommées `broadcast`; Blackboard/RAG donnent des espaces partagés. Cela ne prouve pas le cycle LIDA (coalition de contenus, sélection attentionnelle, broadcast global, apprentissage/consolidation). Aucun modèle LIDA complet n’a été repéré. |
| **Hill / Michaelis–Menten sur les récepteurs** | **Pas implémenté.** | Les niveaux hormonaux sont bornés/dégradés et des récepteurs sont déclarés; aucun calcul de saturation de récepteur Hill/Michaelis–Menten ni calibration de `K_d`/coefficient Hill n’a été vu. À envisager seulement si une non-linéarité améliore un contrôleur mesuré; ce n’est pas une loi prête à appliquer aux signaux logiques. |
| **Fièvre PGE₂ et consigne RAM à 95 %** | **Rejet de la forme proposée.** | L’analogie d’une cible régulée modifiable peut inspirer un arbitrage d’urgence. Mais augmenter la limite RAM/CPU tolérée à 95 % confond priorité et limite de survie, augmente le risque OOM et ne respecte pas les barrières invariantes. Une urgence peut déplacer la perfusion ou suspendre du travail secondaire, jamais relever une limite dure de sûreté. PGE₂ n’est pas actuellement un signal mesuré dans Nokido. |
| **`df_out/dx_in = 0` appliqué à RAM/VRAM** | **Mauvaise généralisation.** | Dans `Homeostasis Patterns`, la dérivée nulle formalise une homéostasie infinitésimale en un point isolé d’un réseau entrée-sortie; ce n’est ni une définition universelle de la stabilité ni une loi directement applicable à la pente RAM. Nokido a une décision RAM basée sur une fenêtre/plancher et des mécanismes de pente pour d’autres signaux, pas la formule proposée sur `dM/dt`. |
| **Compartimentation des cascades** | **But utile, justification AGY trop forte.** | Les modèles de réseaux finis étudiés dans l’article cité peuvent produire des distributions de cascades larges ou bimodales pour des hypothèses/topologies données. Cela ne prouve pas une probabilité générale de panne totale dans Nokido. Les silos et quarantaines se justifient par les chemins de panne mesurés, pas par cette extrapolation directe. |
| **NREM3 / glymphatique / transfert Blackboard→RAG** | **Métaphore partielle, transfert non établi.** | Nokido a des cycles de maintenance et des consolidateurs, mais aucune preuve examinée d’un stade NREM3, d’une mélatonine qui pilote le consolidateur, ou d’un transfert automatique de tout fait Blackboard vers RAG. Conserver validation/provenance avant mémoire durable. |
| **Cerveau, sens, mémoire, âme, règles par identité endpoint** | **Registre réel, profil incomplet.** | `agent_identities.json` décrit acteurs, alias, ring, canal, transport, machine, surface, mailbox, chemins d’écriture et parfois mode/drains/acts/wake. Le routeur cognitif sélectionne un backend par complexité/ring. Pas de schéma uniforme par endpoint pour modèle effectif, capteurs disponibles, scope mémoire et âme. Les signaux système sont globaux ou processus; l’attribution requête→endpoint est incomplète. `SOUL.md` et `IDENTITES_ET_CORPS_NOKIDO.md` n’ont pas été retrouvés aux chemins du dépôt explorés : leur présence ailleurs reste UNKNOWN. |
| **Nokido, premier runtime unique sans événementiel** | **Non démontré.** | Aucun audit comparatif exhaustif de LangGraph, AutoGen, CrewAI, Semantic Kernel, Temporal, Ray et Kafka n’a été fait; ne pas revendiquer de primauté ni d’unicité. Le papier Physical AI cité décrit au contraire un active inference réalisé par message passing réactif et événementiel. |

### Équations et sources AGY : corrections décisives

- `arXiv:1510.01087`, invoqué pour les cascades biochimiques, est **retiré par son auteur**; la page signale une version révisée distincte (`1205.0382`). Ne pas le citer comme preuve valide.
- `arXiv:2407.04865` est bien un DGA différentiable de Gillespie pour apprentissage de paramètres/circuits synthétiques, pas une validation du scheduler Nokido.
- `arXiv:2306.15145` formalise l’homéostasie infinitésimale en un point isolé d’un modèle input-output; `arXiv:2309.06509` étudie les réseaux mRNA/protéines bipartites. Ces résultats sont mathématiques/biologiques et ne dérivent pas la régulation RAM ou la perfusion d’agents.
- `arXiv:1802.03286` étudie des distributions de taille de cascades dans des réseaux finis. Il soutient l’intérêt d’examiner les topologies, pas la conclusion qu’une panne locale Nokido risque systématiquement de tout effondrer.
- `arXiv:2608.04126` traite la stabilité de période près d’une bifurcation de Hopf; il ne valide pas un cycle circadien Nokido.
- `arXiv:2512.20275` rapporte les chiffres G-SPEC dans une simulation 5G. Les nombres 0 / 94,1 % / 142 ms sont les résultats du papier dans ce cadre, pas une validation de Nokido ni une preuve indépendante de sa triade.
- `arXiv:2603.20927` présente un argument théorique/architectural pour l’Active Inference en Physical AI, sans benchmark empirique; son résumé décrit du message passing réactif et événementiel.

**Conclusion de confrontation :** garder l’interoception sourcée, l’attribution des ressources, la modulation hormonale mesurée, les réflexes déterministes et l’arbitrage multiniveau. Traiter SAPERE, LIDA, CBF, Markov blankets, NREM3, Hill et Ashby comme pistes de recherche de granularité différente, pas comme composants déjà réalisés. Écarter l’opposition « organique contre événementiel » et toute formule appliquée sans modèle, bornes, données de calibration et comparaison reproductible.


## Contrat par appel

Chaque observation associée à un appel porte au minimum :

- `trace_id` et `span_id` (ou statut explicite `UNKNOWN`);
- `principal_id` résolu par le hub, ring effectif et source de résolution;
- `client_id`, `provider_id`, `model_id` et `endpoint_id` réellement utilisés, chacun distingué de sa valeur déclarée;
- `observed_at`, `age_ms`, `status` (`OBSERVED`, `DECLARED`, `STALE`, `UNAVAILABLE`, `UNKNOWN`);
- mesures disponibles : latence, erreur, tokens/usage retournés par le provider, quota mesurable, état de ressources, hormones actives;
- provenance de chaque mesure : producteur, unité, source, fraîcheur et méthode.

Un champ non exposé par le provider reste `UNKNOWN`; ne pas inférer « fatigue du modèle » à partir d’une fenêtre de contexte supposée, ni transformer une valeur manquante en zéro. Aucun payload de prompt, secret ou contenu mémoire ne doit être ajouté aux métriques.

## Premier incrément à livrer

1. **Corrélation d’abord.** Propager l’identité et le trace/span du hub jusqu’aux appels LLM et aux décisions de régulation. Réutiliser `forge_trace_context` et le mécanisme de transport d’identité déjà résolu; ne pas recalculer le ring dans un consommateur.
2. **Proprioception attestée.** Enrichir la vue existante afin qu’une hormone/mesure indique son lecteur et l’effet constaté. Remplacer le simple « hook présent » par un état séparant déclaré, observé et vérifié. Conserver `flows_live=false` quand la corrélation manque.
3. **Lecture hub en moindre privilège.** Étendre l’interface read-only existante ou son registre après vérification de ses sections réelles. Exposer pour l’identité appelante ses propres métadonnées et signaux autorisés; les champs hors périmètre restent inconnus. Toute lecture globale doit respecter le ring et la provenance.
4. **Pilote de régulation.** Instrumenter la décision déjà prise par `should_throttle()` et `FlowRegulator`: valeurs fraîches d’entrée, seuil nominal/modulé, facteur hormonal, verdict, motif et effet (spawn différé/refusé, fréquence réduite). Garder les gardes de sécurité absolues indépendantes des hormones; aucune « fièvre » ne peut relever les limites d’intégrité.
5. **Seulement après la preuve.** Comparer la réponse aux transitoires par endpoint et ajuster un seul paramètre borné avec hystérésis. Le keeper reste un effecteur de cycle de vie; il ne doit pas improviser sa propre politique physiologique.

## Critères d’acceptation du pilote

- Une requête témoin produit une chaîne corrélable de l’identité effective à la décision et à l’effet, ou affiche explicitement où la chaîne devient `UNKNOWN`.
- Une mesure périmée ou illisible ne déclenche pas une action qui la présente comme actuelle.
- Le rapport montre valeur, unité, provenance, âge, seuil et motif; il distingue configuration déclarée et observation runtime.
- Un signal hormonal sans consommateur prouvé est affiché « publié, consommation UNKNOWN », jamais « boucle fermée ».
- Les règles RBAC et les barrières de sécurité ne peuvent être relâchées par un état hormonal, un prompt ou une âme déclarée.
- Une comparaison avant/après mesure latence, pics de RAM, tâches différées/refusées et faux ralentissements. Aucun gain n’est revendiqué avant résultats reproductibles.

## Ordre de travail

**P0** corrélation identité/span et contrat de provenance.  
**P1** vue interoceptive read-only avec états triés et scopes RBAC.  
**P2** preuve des consommateurs hormonaux et effets réellement exécutés.  
**P3** pilote d’hystérésis bornée, puis benchmark transitoires.  
**P4** seulement si la mesure le justifie : adapter la cadence du keeper ou ajouter une nouvelle dynamique.

## Références de code consultées

- `app/forge_resource_manager.py`: `get_snapshot` (2481–2497), `should_throttle` (2505–2571), `get_snapshot` maintient une mesure fraîche; cortisol module les seuils, sans veto seul.
- `app/forge_homeostasis_orchestrator.py`: `FlowRegulator.get_dynamic_threshold` et ses facteurs endocrine/surprise (212–261).
- `app/forge_hormones.py`: `release` (216–284), `active` (307–358).
- `app/forge_endocrine.py`: `receptors` (226–228), `scan` (587–598).
- `app/forge_proprioception.py`: `measure_regulation` (349–386), `build_atlas` (454–510).
- `app/forge_anatomy_state.py`: `get_anatomy_state` (536–609).
- `tools/forge_client_bootstrap.py`: `identities` (110–115); `app/forge_agent_authority.py` et `tools/forge_tool_gate.py`: autorité et distinction identité observée/déclarée.

## Investigation du chaînage réel par appel (2026-10-23)

### Parcours couvert

Le parcours examiné est l’appel MCP HTTP `tools/call(name="ask")` vers un provider :

1. `tools/nokido_hub.py::mcp_post` résout `(ring, auth_agent)` via `_resolve_ring` (L3225), pose un `trace_id` en ContextVar depuis `traceparent` / `X-Trace-Id` / la session, puis un ActorContext avec `agent_hdr, ring, channel, transport, machine` (L3237–3262).
2. La requête passe par `_tool_call`, `forge_hub_gate`, puis `ToolRegistry.dispatch`; le ring est fourni au gate et au registre (L3414–3518 dans `mcp_post`, `tools/nokido_hub.py::_tool_call` L1467–1529, `app/forge_mcp_registry.py::dispatch` L640–1204).
3. `handle_ask_agent` transmet provider, message, modèle optionnel, timeout et contexte à `forge_agent_proxy.ask` (L4702–4733); l’appel passe ensuite par `Provider.ask_tracked` (L847–893).
4. `_record_provider_call` lit ActorContext et enregistre agent, provider, modèle, tokens, latence et nature de mesure (rapportée ou estimée) par `forge_token_monitor.log_call` (L502–564).
5. En parallèle, `_TraceCtxMW` écrit une trace HTTP avec trace/parent/span, agent/ring, status et durée (L6870–6920 de `tools/nokido_hub.py`). Ce journal atteste la requête HTTP, pas à lui seul l’appel fournisseur ni l’effet d’un régulateur.

### Résultat par maillon

| Maillon | État prouvé | Limite constatée |
|---|---|---|
| Identité et RBAC à l’entrée MCP | Résolution bearer → agent/ring; garde au dispatch. | La mesure TokenUsage prend `ActorContext.agent`, posé depuis le nom d’en-tête, pas explicitement le couple d’autorité retourné par `_resolve_ring`. Le videur conserve séparément la provenance; la ligne usage ne reprend pas cette preuve. Pour le chemin master/delegation, l’attribution du sujet et celle de l’acteur ne sont donc pas équivalentes. |
| Trace HTTP | `trace_id`, `parent_id`, `span_id` sont créés/extraits et persistés pour `http.request`; le ContextVar trace est posé dans `mcp_post`. | Le span HTTP n’est pas posé comme contexte de span par appel provider. `forge_agent_proxy.ask` émet aussi un `corr_id` RPC, mais distinct du trace ID. |
| Mesures de l’appel | `ask_tracked` mesure la latence; usage API est marqué REPORTED quand disponible, sinon les tokens sont ESTIMATED. Provider et modèle effectivement choisis sont consignés. | L’appel à `log_call` ne passe ni trace/span, ni `execution_id`/parent, ni session_id. Les mesures ne sont donc pas jointes à la trace HTTP. |
| Fraîcheur physiologique | `get_snapshot` expose son timestamp; `read_full` expose niveau, âge, TTL et état expiré des hormones. `should_throttle` lit une fenêtre RAM de 60 s et le snapshot courant. | Ces observations ne sont pas attachées à l’enregistrement de chaque appel provider, ni reliées à son verdict/effet. |
| Décision et effet | `should_throttle` module ses seuils par cortisol frais, puis retourne un booléen; certains chemins de spawn s’en servent pour différer/refuser. `FlowRegulator` existe séparément. | Le chemin `ask` MCP direct ne passe pas par `should_throttle` ni par `forge_cognitive_router._select_model`: il appelle le provider demandé. Le garde de spawn n’est pas un effet par appel et ne journalise pas, à lui seul, l’action réellement exécutée. |
| Proprioception endocrine | `forge_endocrine.read_full` calcule decay/âge/TTL; `forge_hormones.active` joint états RAM et SQLite. | `forge_proprioception.measure_regulation` compte aussi des hooks par recherche de chaînes; ce score ne prouve ni lecture effective ni effet. |

### Échantillon runtime en lecture seule

À l’instant de la sonde (2026-10-23), le snapshot ressources avait environ **0,16 s** d’âge; RAM plancher 60 s **83,8 %**, couverture **57,2 s**, CPU **16,5 %**, GPU **3,38 %**, disque **80,5 %**. `should_throttle()` a rendu **False**. `CORTISOL_FRUSTRATION` avait **35 119 s** d’âge pour un TTL de **1 800 s** (expiré); `CORTISOL_QUOTA_CLOUD` était absent. Ceci prouve qu’un capteur peut être frais et qu’un signal endocrine ancien est explicitement marqué expiré; cela ne prouve pas une décision prise pour un appel LLM, puisque la sonde était indépendante de tout appel et le chemin `ask` n’invoque pas ce garde.

Un appel fournisseur témoin a ensuite été déclenché, avec autorisation explicite, via Groq et le prompt neutre « Réponds uniquement : TÉMOIN » (aucune donnée du projet). À 21:31:30–21:31:36, le journal d’audit montre l’entrée `ask` comme **CODEX, ring 1**, puis la sortie et la réponse provider comme **HUB**, modèle `openai/gpt-oss-120b`, latence provider **5 816,4 ms** (durée hub **5 873,2 ms**). La trace est masquée par le lecteur de logs (`[REDACTED:key]`), donc l’égalité exacte du trace ID entre les lignes ne peut pas être vérifiée ici. Le résultat de l’outil est `ok: true`, mais `text: ""`; la réponse témoin attendue n’a pas été obtenue. Aucun second appel n’a été lancé.

Ce témoin prouve qu’une requête a atteint le provider et que le journal réseau contient l’aller/retour; il ne prouve pas une réponse utile ni la corrélation intégrale. Le changement visible d’étiquette d’acteur (**CODEX** à l’entrée, **HUB** sur les événements cloud) confirme que l’identité appelante n’est pas conservée uniformément sur toute la chaîne de journalisation. Le journal de l’appel ne joint toujours pas un snapshot physiologique daté, le verdict de régulation et un effet effectivement appliqué. Le chaînage runtime complet `identité authentifiée → trace provider → mesures fraîches → verdict → effet` reste donc **partiel / non prouvé de bout en bout**.

### Conclusion et incrément minimal

Le corps a déjà des capteurs frais, un contexte d’acteur, une trace HTTP et un registre d’usage. Ils sont toutefois dans des contrats/journaux distincts. L’intégration ne nécessite pas une nouvelle physiologie : il faut d’abord transmettre un identifiant d’exécution stable à travers ces couches et enregistrer, sur la même clé, le principal autorisé (avec délégation distinguée), trace/span, provider/modèle servi, mesure avec âge/provenance, règle évaluée, verdict et effet (passé, différé, refusé, rerouté).

Pour le premier pilote, instrumenter uniquement les appels provider déjà réalisés par `ask_tracked`; ne pas ajouter de throttling global implicite. Mesurer les appels gardés séparément aux points de spawn, et ne revendiquer une boucle par appel qu’après lecture d’un artefact réel joignant les deux. Les tests NR devraient couvrir héritage/reset du contexte, dérivation maître vs agent, hormones expirées, timeout/échec provider, et effet effectif, sans stocker prompt ni secret.
