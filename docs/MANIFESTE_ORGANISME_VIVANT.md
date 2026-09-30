# Manifeste architectural : Nokido comme organisme vivant
# Date : 2026-04-28 · Revue d'etat : 2026-08-10
# Concept : homogénèse vivant ↔ IA — clôture opérationnelle par analogie biologique

## Comment lire ce document (2026-09-06)

Le texte d'origine du 28 avril est conservé INTÉGRALEMENT : il porte la vision, et une
vision ne se réécrit pas parce qu'elle s'est réalisée. Les revues d'état ci-dessous disent ce
qui est NÉ depuis, avec le module qui l'incarne. Les « manques » listés plus bas se lisent
donc à leur date : la quasi-totalité est aujourd'hui comblée ou en passe de l'être.

## Revue d'état - 2026-09-06

L'écart entre ce manifeste et le code s'est effondré au cours du mois d'août. L'organisme n'est plus une métaphore, c'est une contrainte d'architecture physique imposée par le CI.

| Mécanisme | État aujourd'hui (06/09/2026) |
|---|---|
| **Anatomie stricte (Recensement)** | ACCOMPLI : Plus de 100 modules `tools/`, 40 scripts jetables, et les daemons régulés déclarent formellement leur organe. Le *Gate CI* refuse tout module non classé. L'organisme connaît exactement la taille et la fonction de son propre corps. |
| **Clôture de la Mémoire (Scission M2M)** | ACCOMPLI : Base M2M dédiée, séparée du flux nerveux (Hub/Registry). L'archive du hub est définitivement hors de la boucle cognitive rapide. |
| **Régulation et "Sensibilité"** | EN COURS/AVANCÉ : Création d'un socle de mesure étendu (drains bornés, profil d'un "tick" d'organe). L'audit instruit désormais ses propres "zones mortes". Le système surveille ses limites. |
| **Homéostasie d'urgence (Survie)** | ACCOMPLI : Le système a prouvé sa capacité à s'amputer pour survivre. Face à des requêtes trop lourdes (ex: 24,9 Go sur `OrganPulse`), des balayeurs et modules non critiques ont été basculés en "mode sauvegarde" (désactivés) pour protéger le runtime. |
| **Élagage synaptique (Sommeil)** | AVANCÉ : Les orphelins Python sont tués proprement, les ponts STDIO sont épargnés, et le sommeil paradoxal (circadian) a été resserré. La boucle de rattrapage attend désormais explicitement que le hub écoute. |

## Revue d'état — 2026-08-10

| Organe annonce manquant en avril | Etat aujourd'hui |
|---|---|
| Systeme endocrinien (« MANQUE COMPLETEMENT », `forge_system_mood.py` a creer) | NE, sous un autre nom : `forge_endocrine.py`. Hormones reelles et mesurees (`CORTISOL_EPISTEMIC`, `INSULIN_VECTORIZATION`). Deux pathologies propres decouvertes : une hormone emise SANS recepteur declare (ligand orphelin), et un garde branche sur une hormone que PERSONNE n'emet. |
| Sommeil paradoxal (janitor etendu) | NE : `forge_circadian.py` — NREM1 (22 h, consolidation), NREM3 (2 h, replay batch), REM (4 h, nettoyage glymphatique), avec dette de sommeil (`debt_hours > 48`). |
| EventBus PUSH (bidirectionnalite reelle) | NE : `proxy_deno/core/nervous_system.ts` (SystemBus / BloodCell) + `sandbox/event_bus_replay.jsonl`. Encodage evenementiel AER mesure a −95,3 % d'octets. |
| Cervelet : SNN statique, entraine une fois | IL APPREND (0.848 → 1.0 mesure). Mais le verdict d'aout est plus dur : ni LIF ni noyau appris ne battent un simple seuil. Ce qui manquait n'etait pas un modele, c'etaient des CAPTEURS — le vecteur vitals est passe de 4 scalaires a ~17-20 canaux mesures. |
| Moelle epiniere : « le hub decide trop » | Corrige dans le principe : le hub transporte et delegue, la decision passe par des routes gouvernees (`governed_edit`, `nokido_ensure_service`) et une couche identite×ring unique (`forge_videur`). Le ring n'est plus une propriete de l'agent : il est RESOLU PAR REQUETE. |
| Immunitaire : patterns statiques | Partiel : firewall semantique + membrane + RBAC sont vivants ; l'apprentissage depuis l'audit log reste a faire. |
| Inconscient : remontee controlee | Le canal existe (blackboard + `forge_critical_events` + daemon epistemique qui pose des DOULEUR → algedonique), mais il CRIAIT SANS ETRE ECOUTE : le reflexe de tour comptait les alertes sans jamais les delivrer. Corrige le 2026-08-10. |

Ce que le corps a appris sur lui-meme, et qui ne figurait pas au manifeste d'avril :

1. Un organe ne vit pas parce qu'il est ECRIT, il vit parce qu'il est CABLE. Plusieurs
   gardes justes, ecrits pour de bonnes raisons, ne se sont jamais declenches : le signal
   dont ils dependent n'avait aucun emetteur, ou le hook n'etait pas branche. Un module
   present et muet est indiscernable d'un module absent.
2. EMETTRE N'EST PAS ECOUTER. Le corps a beaucoup de voies efferentes (notify, push,
   blackboard, hormones) et peu de voies afferentes qui ABOUTISSENT. Une alerte comptee
   mais jamais delivree est une information perdue, et le compteur s'auto-entretient.
3. Trois etats, jamais deux : vrai · faux · ILLISIBLE. Un capteur qui rend False pour
   « absent » ET pour « je n'ai pas pu regarder » fabrique des faux negatifs
   indetectables. C'est la lecon la plus chere du corps.
4. L'intention se DECLARE, elle ne se devine pas. Vocabulaire commun `sandbox/*.wanted`
   (docker · llama · embed · rerank · snn) : un consommateur declare, la regulation
   epargne, le keeper rallume. Un lecteur sans declarant ne vaut rien.

## Principe directeur

Nokido n'est pas une machine qui traite des requêtes.
C'est un organisme qui maintient sa propre cohérence tout en interagissant avec le monde.
Ce principe s'appelle autopoïèse (Maturana & Varela, 1972).

## Ce que chaque "organe" doit apprendre du vivant

### Cerveau (forge_rag_engine + forge_memory)
Biologie : consolidation active pendant le sommeil, reconstruction, pas juste stockage.
Manque dans Nokido : relier les chunks par similarité conceptuelle (pas juste vectorielle).
Relier les chunks à des "patterns de session" récurrents.
Élaguer ce qui n'est plus accédé (élagage synaptique).

### Cortex préfrontal (forge_cognitive_router)
Biologie : planification + INHIBITION des réflexes. Sait quand NE PAS agir.
Manque dans Nokido : le routeur décide toujours de router.
Il devrait parfois décider de ne rien faire (réponse directe sans outil).

### Cervelet (forge_spike_router)
Biologie : réflexes APPRIS, automatismes — sans passer par le cortex.
Manque dans Nokido : le SNN est statique, entraîné une fois sur CTF.
Il doit apprendre de chaque interaction (online learning sur network_log).

### Moelle épinière (nokido_hub + forge_mcp_registry)
Biologie : canal bidirectionnel pur. PAS de décision. Juste transport.
Problème actuel : le hub décide trop. Il devrait transporter et déléguer.
Manque : EventBus PUSH (bidirectionnalité réelle).

### Système immunitaire (forge_mcp_security + forge_rbac)
Biologie : mémoire immunitaire — apprend des attaques passées, réponse proportionnée.
Manque dans Nokido : les patterns bloqués sont statiques (DANGEROUS_PATTERNS).
Ils devraient être appris depuis l'audit log (ex : si agent X tente 3 fois un path interdit
→ augmente son niveau de surveillance automatiquement).

### Système endocrinien (MANQUE COMPLÈTEMENT)
Biologie : régulation lente, globale, par diffusion. Le "mood" du système.
À créer : forge_system_mood.py
  - energy (charge), curiosity (nouvelles requêtes), fatigue (uptime), immune_alert
  - Diffusé toutes les 60s via EventBus à tous les modules
  - Les modules ajustent leurs timeouts, leur verbosité, leur agressivité de cache

### Sommeil paradoxal (forge_rag_janitor — étendu)
Biologie : consolidation + ÉLAGAGE des connexions peu utilisées.
Manque : le janitor nettoie les orphelins mais ne réévalue pas la pertinence.
Ajouter : score d'accès + fraîcheur → décision conserver/archiver.

### Sens — transduction (mcp_stdio_bridge + SearXNG)
Biologie : pré-traitement LOCAL avant envoi au cerveau. Encode le GRADIENT (changement).
Manque : normalisation du signal entrant (langue, intention, urgence, domaine).
ByteRouterMiddleware commence à faire ça — l'étendre.

### Inconscient (sandbox/ + shadow_mutation/)
Biologie : traitements parallèles hors conscience, source d'intuitions.
Manque : mécanisme de remontée contrôlée. L'inconscient doit pouvoir
"remonter" des patterns détectés vers le cortex (forge_cognitive_router).

## Clôture opérationnelle — règle architecturale

Chaque module est fonctionnellement clos :
- forge_spike_router ne lit pas le contenu du message, seulement sa structure
- forge_rag_engine ne connaît pas l'agent qui demande, seulement le vecteur
- nokido_hub ne décide pas — il transporte et délègue

## Phase suivante : simulation vivant vs IA edge

Systèmes complexes adaptatifs (Santa Fe Institute, Holland, Kauffman).
Tension à explorer : centralisation (hub) vs distribution (edge/cellulaire).
Le vivant résout ça avec 2 systèmes parallèles :
  - Système nerveux autonome (edge, réflexes) → forge_spike_router
  - Cortex (central, conscient) → forge_cognitive_router
Ces deux ne se parlent pas encore directement dans Nokido.
C'est le chaînon manquant.

## Références pour enrichissement mutuel

- Maturana & Varela, "Autopoiesis and Cognition" (1980)
- Holland, "Hidden Order" (1995) — systèmes adaptatifs complexes
- Kauffman, "At Home in the Universe" (1995) — émergence et auto-organisation
- Damasio, "The Feeling of What Happens" (1999) — conscience comme régulation corporelle
- Friston, "The free energy principle" (2010) — cerveau comme machine à prédire
- Hofstadter, "Gödel Escher Bach" (1979) — boucles étranges et auto-référence
