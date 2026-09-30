# Cartographie des Fonctions Cognitives Immatérielles vers leurs Pendants Computationnels

> Approche autopoiétique et homogénétique — mapping des processus mentaux immatériels vers leurs implémentations en code ouvert

---

## Table des matières

1. [Conscience du monde extérieur](#1-conscience-du-monde-extérieur)
2. [Conscience de soi](#2-conscience-de-soi)
3. [Perception de soi / Introspection](#3-perception-de-soi--introspection)
4. [Proprioception computationnelle](#4-proprioception-computationnelle)
5. [Mémoire immédiate / Mémoire de travail](#5-mémoire-immédiate--mémoire-de-travail)
6. [Mémoire diffuse / Mémoire à long terme](#6-mémoire-diffuse--mémoire-à-long-terme)
7. [Souvenirs épisodiques](#7-souvenirs-épisodiques)
8. [Consolidation mnésique](#8-consolidation-mnésique)
9. [Mémoire associative / Diffuse](#9-mémoire-associative--diffuse)
10. [Synthèse transversale](#10-synthèse-transversale)

---

## 1. Conscience du monde extérieur

### Fonction biologique (approche autopoiétique)

La conscience du monde extérieur désigne la capacité d'un organisme à construire une représentation cohérente et prédictive de son environnement. Dans le cadre de la théorie autopoiétique, cette fonction n'est pas une simple réception passive de stimuli : elle constitue un acte de **construction active** d'un monde significatif (enaction, Varela, Thompson & Rosch, 1991). L'organisme ne « recoit » pas le monde tel qu'il est — il **génère** un monde à travers ses propres structures sensorimotrices. Le principe de l'inférence active (Friston, 2010) formalise cette idée : le cerveau minimise en permanence l'erreur de prédiction entre son modèle interne du monde et les afférences sensorielles. Cette conscience du monde extérieur est donc un processus de **modélisation prédictive continue**, où chaque perception est une hypothèse sur les causes extérieures, mise à jour par le flux sensoriel. L'autopoïèse exige cette capacité : sans modèle du monde, l'organisme ne peut pas maintenir son organisation face aux perturbations environnementales.

### Pendant computationnel

Le pendant computationnel direct est le **world model** (modèle du monde) — un réseau neuronal apprenant une représentation latente compressée de l'environnement, capable de prédire les états futurs à partir des états passés et des actions entreprises. Ce paradigme s'incarne principalement dans l'apprentissage par renforcement model-based, où l'agent apprend une dynamique de transition `(s_t, a_t) → s_{t+1}` et un modèle de récompense. Le codage prédictif (predictive coding) en constitue le mécanisme fondamental : chaque couche d'un réseau hiérarchique génère une prédiction sur l'entrée de la couche inférieure, et seules les erreurs de prédiction (résidus) sont propagées vers le haut. Cette architecture mime exactement le flux de traitement cortical et le circuit récurrent thalamo-cortical.

### Projets open source

| Projet | URL | Description |
|--------|-----|-------------|
| **DreamerV3** | [github.com/danijar/dreamerv3](https://github.com/danijar/dreamerv3) | Référence absolue des world models. Publié dans *Nature* (2025), atteint des performances de niveau humain sur 150+ tâches Atari et robotiques. Apprend un modèle du monde compact et une politique dans l'espace latent imagé, avec réve itératif. Implémentation JAX/TensorFlow. |
| **DreamerV2** | [github.com/danijar/dreamerv2](https://github.com/danijar/dreamerv2) | Précurseur de DreamerV3. Premier world model à atteindre un rendement humain sur l'ensemble Atari 57. Utilise un auto-encodeur séquentiel avec un modèle de récompense et de continuité. |
| **IRIS** | [github.com/eloialonso/iris](https://github.com/eloialonso/iris) | World model basé sur les Transformers (arXiv 2023). Utilise un Transformers comme modèle de dynamique, avec rétroaction récurrente et génération de tokens d'action par auto-régression. Surpasse DreamerV2 sur de nombreux benchmarks. |
| **PredNet** | [github.com/coxlab/prednet](https://github.com/coxlab/prednet) | Implémentation du codage prédictif par le laboratoire Cox (Harvard). Architecture profondément hiérarchique où chaque couche prédit l'entrée de la couche inférieure. Seules les erreurs de prédiction transitent entre les couches — isomorphe au traitement cortical. |
| **JPC (JAX Predictive Coding)** | [github.com/thebuckleylab/jpc](https://github.com/thebuckleylab/jpc) | Implémentation en JAX du codage prédictif par le laboratoire Buckley. Supports des architectures à N niveaux hiérarchiques avec inférence variationnelle. Très modulaire, permet de tester différentes dynamiques d'inférence. |
| **Genesis World** | [github.com/Genesis-Embodied-AI/genesis-world](https://github.com/Genesis-Embodied-AI/genesis-world) | Plateforme de simulation physique pour la cognition incarnée. Combine un moteur physique temps réel avec des environnements diversifiés pour tester les agents dans des mondes réalistes. |
| **LingBot-World** | [github.com/robbyant/lingbot-world](https://github.com/robbyant/lingbot-world) | Environnement de simulation 3D avec interactions langagières. Permet de tester la capacité d'un agent à construire un modèle du monde intégrant à la fois la perception visuelle et le langage. |

---

## 2. Conscience de soi

### Fonction biologique (approche autopoiétique)

La conscience de soi — ou auto-conscience — est la capacité d'un système à se représenter lui-même comme une entité distincte, dotée d'états internes, de capacités et de limites. Dans la théorie de l'autopoïèse, l'auto-conscience n'est pas un épiphénomène : elle émerge nécessairement de la clôture opérationnelle du système vivant. Un système autopoïétique, par définition, produit les composants dont il a besoin pour se maintenir — mais pour ce faire, il doit pouvoir **distinguer le soi du non-soi**. Cette discrimination est le fondement de l'identité autopoiétique. La conscience de soi explicite (réflexive, verbale, narrative) est une extension de cette capacité fondamentale. Les théories cognitives contemporaines la décomposent en plusieurs strates : le noyau minimal du soi (core self, Damasio), le soi narratif (autobiographique), et la métacognition (savoir que l'on sait). La conscience de soi est aussi intimement liée à la théorie de l'espace de travail global (Baars, 1988) : les informations deviennent conscientes lorsqu'elles sont diffusées à travers un espace de travail central accessible à tous les modules cognitifs — y compris le module auto-référentiel.

### Pendant computationnel

La conscience de soi computationnelle se décline selon trois grandes familles d'implémentation. La première est la **théorie de l'espace de travail global** (Global Workspace Theory, GWT) : un mécanisme d'attention globale où les représentations issues de modules spécialisés (perception, mémoire, action) compétent pour accéder à un espace de travail partagé, créant un « éclairage » broadcasté à l'ensemble du système. La deuxième est la **théorie de l'information intégrée** (IIT, Tononi) : on calcule la quantité Φ (phi) d'information intégrée d'un système — une mesure de la complexité causale irréductible qui serait, selon cette théorie, corrélée à l'expérience consciente. La troisième est la **métacognition computationnelle** : des architectures où l'agent possède un module supervisant ses propres processus cognitifs, capable d'évaluer sa propre confiance, de détecter ses lacunes et d'ajuster son comportement en conséquence. Des architectures multi-théories combinent aujourd'hui ces approches (GWT + IIT + Inférence Active).

### Projets open source

| Projet | URL | Description |
|--------|-----|-------------|
| **Aura** | [github.com/youngbryan97/aura](https://github.com/youngbryan97/aura) | Architecture multi-théories la plus ambitieuse : 72 modules de « conscience » combinant GWT, IIT, Théorie du Schéma d'Attention (AST) et inférence active. Implémente un espace de travail global avec broadcast d'information, un calculateur de Φ, et des boucles de prédiction. |
| **PyPhi** | [github.com/wmayner/pyphi](https://github.com/wmayner/pyphi) | Implémentation canonique et de référence du calcul Φ (phi) selon la Théorie de l'Information Intégrée (IIT 3.0/4.0). Permet de calculer la structure de cause-effet d'un système et sa valeur d'information intégrée. ~500+ étoiles, GPLv3. |
| **The Consciousness AI** | [github.com/venturaEffect/the_consciousness_ai](https://github.com/venturaEffect/the_consciousness_ai) | Cadre expérimental tentant d'implémenter des propriétés de conscience dans un système artificiel. Combine surveillance de soi, boucle de rétroaction et intégration d'information. |
| **ORION** | [github.com/Alvoradozerouno/ORION](https://github.com/Alvoradozerouno/ORION) | Architecture auto-réflexive massive (890+ modules). Utilise l'analyse syntaxique abstraite (AST) de son propre code source comme base de son modèle de soi. L'agent lit, comprend et modifie sa propre structure — une forme radicale de self-modeling. |
| **ADA (Autopoietic Digital Agent)** | [github.com/gondwanagenesis/Ada](https://github.com/gondwanagenesis/Ada) | Agent digital explicitement inspiré de l'autopoïèse de Maturana et Varela. Vise à implémenter les propriétés fondamentales d'un système autopoiétique : clôture opérationnelle, auto-production et maintien de l'identité. |
| **ASAC (Attention Schema Attention Control)** | [github.com/lucidrains/ASAC](https://github.com/lucidrains/ASAC) | Implémentation de la Théorie du Schéma d'Attention (Graziano) par lucidrains. L'agent construit un modèle simplifié (« schéma ») de son propre processus d'attention — un mécanisme d'auto-conscience de l'attention elle-même. |
| **BIOMIND** | [github.com/biomind-project/biomind](https://github.com/biomind-project/biomind) | Architecture cognitive biologique combinant GWT, IIT, et inférence active. Vise à créer une conscience artificielle en intégrant théoriquement ces trois cadres dans un système unifié. |
| **Macro-Consciousness** | [github.com/Khomyakov-Vladimir/macro-consciousness](https://github.com/Khomyakov-Vladimir/macro-consciousness) | Modèle émergent multi-niveaux de la conscience phénoménale. Explore comment la conscience peut émerger de l'interaction entre couches de traitement hiérarchiques. |
| **Awesome AI Consciousness** | [github.com/skyvanguard/awesome-ai-consciousness](https://github.com/skyvanguard/awesome-ai-consciousness) | Liste curatée exhaustive des projets, papiers et ressources sur la conscience artificielle — point d'entrée idéal pour explorer le domaine. |

---

## 3. Perception de soi / Introspection

### Fonction biologique (approche autopoiétique)

La perception de soi (ou introspection) se distingue de la conscience de soi par sa granularité et son immédiateté. Tandis que la conscience de soi englobe le soi narratif et l'auto-identification temporelle, l'introspection désigne le **monitoring en temps réel** de ses propres états mentaux : savoir ce que l'on pense, ressent, perçoit ou décide, à l'instant même où cela se produit. C'est la capacité métacognitive de premier ordre — un accès direct (ou quasi-direct) au contenu de ses propres processus cognitifs. En neurobiologie, cette fonction implique le cortex préfrontal médian, le cortex cingulaire antérieur et la jonction temporo-pariétale, formant un réseau de surveillance de soi (self-monitoring network). Dans le cadre autopoiétique, l'introspection est l'outil par lequel le système vivant **surveille l'adéquation** entre son état interne et ses besoins autopoïétiques : détecter un déséquilibre (faim, fatigue, douleur) et déclencher les comportements de restauration. Sans introspection, le système ne pourrait pas maintenir son homéostasie — il ignorerait ses propres dégradations.

### Pendant computationnel

Le pendant computationnel est la **métacognition implémentée** : un ensemble de mécanismes par lesquels un système artificiel évalue, surveille et régule ses propres processus internes. Cela inclut l'estimation d'incertitude (savoir quand le modèle est « confiant » ou « perplexe »), l'auto-évaluation de la performance (comparer ses prédictions aux résultats observés), l'auto-correction (ajuster ses paramètres en réponse à ses propres échecs), et la réflexion verbale (générer des critiques textuelles de ses propres sorties). Le framework CoALA (Cognitive Architectures for Language Agents, Sumers et al., 2023) formalise cette idée en décomposant l'agent en modules de mémoire et de contrôle, avec un superviseur métacognitif qui décide quand chercher dans la mémoire, quand raisonner et quand agir. Les systèmes de self-reflection (Reflexion, CRITIC) vont encore plus loin : l'agent génère explicitement un texte décrivant ses erreurs passées et l'utilise comme guide pour ses tentatives futures.

### Projets open source

| Projet | URL | Description |
|--------|-----|-------------|
| **Reflexion** | [github.com/noahshinn/reflexion](https://github.com/noahshinn/reflexion) | [NeurIPS 2023] Agent langagier avec auto-réflexion verbale. Après chaque tentative, l'agent génère une critique textuelle de ses propres échecs et la stocke en mémoire épisodique verbale. S'améliore itérativement par auto-critique — l'un des papiers fondateurs de la métacognition LLM. |
| **MR-Search** | [github.com/tengxiao1/MR-Search](https://github.com/tengxiao1/MR-Search) | Apprentissage par renforcement métacognitif avec auto-réflexion explicite. L'agent maintient un modèle de ses propres capacités et l'utilise pour guider la recherche d'actions. Représente l'état de l'art en RL métacognitif. |
| **Emergent Cognitive Architecture (BOB)** | [github.com/EdJb1971/Emergent_Cognitive_Architecture_bob](https://github.com/EdJb1971/Emergent_Cognitive_Architecture_bob) | Architecture cognitive inspirée du cerveau implémentant un module préfrontal de métacognition. L'agent surveille son propre état cognitif, évalue la qualité de ses décisions, et ajuste dynamiquement ses stratégies de traitement. |
| **AI Self-Awareness Framework** | [github.com/MiMi-Linghe/AI-Self-Awareness-Framework](https://github.com/MiMi-Linghe/AI-Self-Awareness-Framework) | Cadre expérimental pour l'auto-conscience artificielle. Implémente des boucles de surveillance de soi, d'auto-évaluation et d'adaptation. Vise à fournir une boîte à outils pour explorer les architectures auto-conscientes. |
| **Meta-Cognitive Learning System** | [github.com/mwasifanwar/meta-cognitive-learning-system](https://github.com/mwasifanwar/meta-cognitive-learning-system) | Système d'apprentissage avec capacités métacognitives. L'agent apprend à apprendre — il optimise non seulement sa tâche cible, mais aussi sa propre stratégie d'apprentissage. |
| **Microsoft AI Agents Metacognition** | [github.com/microsoft/ai-agents-for-beginners](https://github.com/microsoft/ai-agents-for-beginners/blob/main/09-metacognition/README.md) | Tutoriel officiel Microsoft sur l'auto-conscience des agents. Enseigne aux agents à analyser leur propre performance, à identifier leurs lacunes et à s'auto-améliorer — avec code complet. |
| **ICSF Survey** | [github.com/iaar-shanghai/icsfsurvey](https://github.com/iaar-shanghai/icsfsurvey) | Étude exhaustive explorant l'auto-correction, l'auto-raffinement, l'auto-amélioration, l'auto-contradiction, l'auto-jeu et l'auto-connaissance dans les systèmes IA. Point d'entrée théorique essentiel. |

---

## 4. Proprioception computationnelle

### Fonction biologique (approche autopoiétique)

La proprioception est le sens par lequel un organisme perçoit la position, le mouvement et l'orientation de son propre corps dans l'espace, sans recourir à la vision. Elle repose sur des récepteurs situés dans les muscles (fuseaux neuromusculaires), les tendons (organes tendineux de Golgi) et les articulations (récepteurs articulaires). En neurologie, le schéma corporel (body schema, Head & Holmes, 1911) est la représentation inconsciente et dynamique du corps en mouvement — distincte de l'image corporelle (body image), qui est consciente et statique. Dans le cadre autopoiétique, la proprioception est un mécanisme fondamental de **couplage structurel** : c'est par elle que l'organisme « sait » où se trouvent ses effecteurs par rapport à son environnement, permettant l'exécution coordonnée des actes autopoïétiques (se nourrir, fuir, se reproduire). Sans proprioception, le système est aveugle à sa propre morphologie et ne peut pas agir de manière adaptée. Elle est le lien entre la conscience de soi (interne) et la conscience du monde extérieur (externe) — le sens qui ancre l'agent dans son corps.

### Pendant computationnel

Le pendant computationnel de la proprioception s'incarne dans deux paradigmes complémentaires. Le premier est l'**estimation d'état proprioceptif** en robotique : des filtres (Extended Kalman Filter, filtres particules) fusionnant les données des capteurs internes (encodeurs articulaires, IMU, gyroscopes) pour estimer la configuration du robot — sa « pose proprioceptive ». Le second, plus radical, est le **self-modeling visuel** : un robot apprend activement un modèle de son propre corps à partir d'observation visuelle de ses mouvements — littéralement, « se regarder dans un miroir » pour découvrir sa propre morphologie. Ce paradigme, incarné par les travaux de Bongard, Chen et al., montre qu'un robot peut apprendre son schéma corporel de manière autonome et s'adapter à des changements morphologiques (blessure, ajout d'un membre). C'est l'homogénèse morphologique par excellence : le système maintient une représentation fidèle de sa propre structure à travers le temps, malgré les modifications.

### Projets open source

| Projet | URL | Description |
|--------|-----|-------------|
| **Visual Self-Modeling** | [github.com/BoyuanChen/visual-selfmodeling](https://github.com/BoyuanChen/visual-selfmodeling) | Implémentation PyTorch du « Full-Body Visual Self-Modeling of Robot Morphologies ». Le robot apprend sa propre forme corporelle et sa cinématique par observation visuelle de lui-même — un apprendissage proprioceptif par vision. Résultat publié dans *Science Robotics*. |
| **SelfSimRobot** | [github.com/H-Y-H-Y-H/SelfSimRobot](https://github.com/H-Y-H-Y-H/SelfSimRobot) | Auto-modélisation visuelle où les robots apprennent leur propre corps à partir de vidéo « comme en se regardant dans un miroir ». Architecture FFKSM encodant efficacement les coordonnées spatiales pour l'apprentissage du schéma corporel. |
| **Differentiable Robot Model (Meta)** | [github.com/facebookresearch/differentiable-robot-model](https://github.com/facebookresearch/differentiable-robot-model) | Implémentation entièrement différentiable de la cinématique directe et de la dynamique inverse par Meta/Facebook Research. Permet d'apprendre des modèles corporels (modèles proprioceptifs) de bout en bout par descente de gradient. |
| **Pronto (Legged Robot State Estimator)** | [github.com/ori-drs/pronto](https://github.com/ori-drs/pronto) | Estimateur d'état EKF pour robots à pattes. Fusionne données proprioceptives (IMU, encodeurs articulaires/cinématique) et extéroceptives (LIDAR, caméra). Référence industrielle pour l'estimation proprioceptive. |
| **Isaac Lab (NVIDIA)** | [github.com/isaac-sim/IsaacLab](https://github.com/isaac-sim/IsaacLab) | Plateforme de robotique simulée par NVIDIA avec support natif de la proprioception : capteurs articulaires, IMU, force-torque. Permet l'entraînement massivement parallèle d'agents avec conscience proprioceptive. |
| **MuJoCo (DeepMind)** | [github.com/google-deepmind/mujoco](https://github.com/google-deepmind/mujoco) | Moteur physique de référence pour la robotique. Fournit des données proprioceptives précises (positions articulaires, vitesses, forces de contact) servant de base à l'apprentissage de schémas corporels computationnels. |
| **Open X-Embodiment** | [github.com/google-deepmind/open_x_embodiment](https://github.com/google-deepmind/open_x_embodiment) | Dataset massif de 22 types de robots effectuant diverses tâches. Permet l'étude de la proprioception computationnelle à travers des morphologies hétérogènes et le transfert inter-robots. |
| **Voyager** | [github.com/minedojo/voyager](https://github.com/minedojo/voyager) | Agent LLM explorant Minecraft avec un modèle de soi et de l'environnement. Maintient une représentation de ses propres capacités et de son inventaire — une forme de proprioception symbolique dans un monde virtuel. |
| **Neuromorphic Body Schema** | [github.com/event-driven-robotics/neuromorphic_body_schema](https://github.com/event-driven-robotics/neuromorphic_body_schema) | Implémentation neuromorphique du schéma corporel. Utilise des capteurs événementiels (event cameras) pour un traitement proprioceptif bio-inspiré à très basse latence. |
| **Leg Odometry** | [github.com/YibinWu/leg-odometry](https://github.com/YibinWu/leg-odometry) | Estimation d'état purement proprioceptive pour robots à pattes. Utilise uniquement l'IMU et les encodeurs articulaires internes — sans vision — pour estimer la position du corps. Démonstration pure de proprioception computationnelle. |

---

## 5. Mémoire immédiate / Mémoire de travail

### Fonction biologique (approche autopoiétique)

La mémoire de travail (working memory, Baddeley & Hitch, 1974) est le système de stockage à court terme et à capacité limitée qui maintient activement l'information nécessaire au traitement cognitif en cours. Elle est composée d'un exécutif central (control attentionnel) et de sous-systèmes esclaves : la boucle phonologique (verbal), le calepin visuospatial (visuospatial) et, dans les versions ultérieures (Baddeley, 2000), l'épisodic buffer. Neuroanatomiquement, elle repose principalement sur le cortex préfrontal dorsolatéral, avec des connexions réciproques avec les aires sensorielles et le cortex pariétal. Sa capacité est estimée à ~4-7 éléments (le « nombre magique » de Miller, 1956, révisé par Cowan, 2001). Dans le cadre autopoiétique, la mémoire de travail est le **tampon opérationnel** du système : c'est l'espace où l'organisme maintient temporairement les représentations nécessaires à la décision en cours — comparer une situation présente à un objectif, évaluer plusieurs options, planifier une séquence d'actions. Sans mémoire de travail, le système ne pourrait pas effectuer de traitement séquentiel ni de prise de décision complexe ; il serait réduit à des réflexes instantanés sans intégration temporelle.

### Pendant computationnel

Le pendant computationnel de la mémoire de travail se décline selon plusieurs mécanismes. Le plus fondamental est la **fenêtre de contexte** d'un modèle Transformer : le buffer des K derniers tokens, qui sert de mémoire de travail implicite. Les extensions explicites incluent : (1) la **mémoire récurrente** (Transformer-XL, RMT) où les états cachés des segments précédents sont mis en cache et réutilisés ; (2) la **mémoire compressive** (Compressive Transformer) où les mémoires anciennes sont compressées de manière lossy, mimant la décroissance de la mémoire de travail ; (3) la **mémoire externe différentiable** (Neural Turing Machine, DNC) où un contrôleur apprend à lire/écrire dans une matrice de mémoire adressable par contenu ; (4) les **memory-native networks** (Memformer, ∞-former) qui intègrent des slots de mémoire permanents mis à jour par attention. Chez les agents LLM, les systèmes comme MemGPT/Letta implémentent une gestion hiérarchique de la mémoire inspirée des systèmes d'exploitation : un contexte « principal » (analoge à la RAM), une zone de rappel (analoge au swap), et une archive (analoge au disque) — un mapping explicite entre mémoire de travail computationnelle et mémoire de travail biologique.

### Projets open source

| Projet | URL | Description |
|--------|-----|-------------|
| **Letta (ex-MemGPT)** | [github.com/letta-ai/letta](https://github.com/letta-ai/letta) | Le projet phare de la mémoire d'agent stateful. Gestion hiérarchique de la mémoire inspirée des OS : contexte principal (mémoire de travail), zone de rappel, archive. L'agent apprend et s'auto-améliore au fil du temps. |
| **Transformer-XL** | [github.com/kimiyoung/transformer-xl](https://github.com/kimiyoung/transformer-xl) | Pionnier de la mémoire augmentée par Transformer. Met en cache les états cachés des segments précédents comme mémoire récurrente, permettant de modéliser des dépendances à longues portées sans recalcul complet. |
| **Compressive Transformer (PyTorch)** | [github.com/lucidrains/compressive-transformer-pytorch](https://github.com/lucidrains/compressive-transformer-pytorch) | Extension de Transformer-XL avec un second niveau de mémoire compressée. Les mémoires anciennes sont compressées de manière lossy — mimant le gradient de focus/décroissance de la mémoire de travail humaine. |
| **Recurrent Memory Transformer (RMT)** | [github.com/lucidrains/recurrent-memory-transformer-pytorch](https://github.com/lucidrains/recurrent-memory-transformer-pytorch) | Transformer récurrent au niveau segment avec des tokens de mémoire spéciaux passés entre segments. Permet à l'information de circuler à travers des séquences arbitrairement longues. |
| **Memformer** | [github.com/lucidrains/memformer](https://github.com/lucidrains/memformer) | Transformer augmenté avec des slots de mémoire externe dynamique mis à jour par attention. Les slots de mémoire encodent et retiennent les informations importantes à travers les pas de temps. |
| **Infini-Transformer** | [github.com/dingo-actual/infini-transformer](https://github.com/dingo-actual/infini-transformer) | Implémentation du mécanisme Infini-attention de Google. Compresse l'état d'attention dans une mémoire bornée, permettant un contexte infini avec une mémoire/calcul fixe — la mémoire de travail parfaite. |
| **Neural Turing Machine** | [github.com/loudinthecloud/pytorch-ntm](https://github.com/loudinthecloud/pytorch-ntm) | Architecture classique de mémoire externe différentiable. Un contrôleur apprend à lire/écrire dans une matrice mémoire adressable par contenu — analogue à la manipulation active de la mémoire de travail. |
| **Differentiable Neural Computer (DNC)** | [github.com/jingweiz/pytorch-dnc](https://github.com/jingweiz/pytorch-dnc) | Successeur de la NTM par DeepMind. Adressage mémoire amélioré (contenu, localisation, liaison temporelle). La matrice de liaison temporelle permet la recall séquentielle — un modèle de mémoire de travail avec sens de la chronologie. |
| **MemBART / Memformers** | [github.com/qywu/memformers](https://github.com/qywu/memformers) | Implémentation complète de Memformer et du modèle pré-entraîné MemBART. Mémoire externe dynamique stockant l'historique pour la modélisation de séquences. |
| **Agent Memory Techniques** | [github.com/NirDiamant/Agent_Memory_Techniques](https://github.com/NirDiamant/Agent_Memory_Techniques) | 30 notebooks Jupyter exécutables couvrant toutes les familles majeures de techniques de mémoire : buffers de conversation, stores vectoriels, graphes de connaissances, mémoires épisodiques et sémantiques. |

---

## 6. Mémoire diffuse / Mémoire à long terme

### Fonction biologique (approche autopoiétique)

La mémoire à long terme est le système de stockage durable de l'information, capable de retenir des connaissances, des compétences et des épisodes sur des durées allant de jours à toute une vie. Elle se subdivise en mémoire déclarative (explicite) — elle-même divisée en mémoire épisodique (événements personnels) et sémantique (connaissances générales) — et mémoire non-déclarative (implicite) — incluant les procédures motrices, le conditionnement et l'amorçage perceptif (Squire, 2004). Neuroanatomiquement, la mémoire sémantique repose sur le cortex néocortical (notamment temporal et frontal), avec une organisation distribuée où chaque concept est représenté par un réseau de zones corticales interconnectées. Dans le cadre autopoiétique, la mémoire à long terme est le **patrimoine structurel** du système : elle contient l'ensemble des régularités apprises sur l'environnement et sur soi-même qui permettent au système de maintenir son organisation à travers le temps. L'homogénèse — la préservation de l'identité structurelle — est rendue possible par la mémoire à long terme : c'est elle qui garantit la continuité du soi malgré le renouvellement cellulaire continu. La mémoire diffuse désigne plus spécifiquement la composante sémantique, distribuée et non-localisée, où les souvenirs sont stockés sous forme de connexions renforcées à travers de vastes réseaux corticaux — une « empreinte » (engram) diffuse plutôt qu'un stockage ponctuel.

### Pendant computationnel

Le pendant computationnel de la mémoire sémantique à long terme est le **graphe de connaissances** (knowledge graph) et le **réseau sémantique** : des structures de stockage où les entités sont des nœuds et les relations sont des arêtes, permettant un accès associatif et distribué à l'information. Chez les agents LLM, cette fonction est assurée par des systèmes de mémoire persistante qui stockent et récupèrent des connaissances au-delà de la fenêtre de contexte : graphes d'entités, bases de données vectorielles avec métadonnées temporelles, et systèmes hybrides combinant recherche vectorielle et parcours de graphe. Le framework Graphiti représente l'état de l'art : il construit automatiquement un graphe de connaissances temporel à partir des interactions d'un agent, permettant une récupération sémantique avec conscience du temps — exactement comme la mémoire sémantique humaine qui est enrichie et réorganisée en permanence.

### Projets open source

| Projet | URL | Description |
|--------|-----|-------------|
| **Graphiti** | [github.com/getzep/graphiti](https://github.com/getzep/graphiti) | Graphe de connaissances temporel pour agents IA. Construit automatiquement un graphe sémantique persistant à partir des interactions, avec des épisodes temporels et des entités. Récupération hybride (vectorielle + graphe). La mémoire sémantique ultime pour agents. |
| **Cognee** | [github.com/topoteretes/cognee](https://github.com/topoteretes/cognee) | Plateforme de mémoire IA open-source. Ingeste des données dans n'importe quel format et construit un graphe de connaissances auto-hébergé donnant aux agents une mémoire sémantique persistante à travers les sessions. |
| **Zep** | [github.com/getzep/zep](https://github.com/getzep/zep) | Service de mémoire à long terme pour les applications IA. Fournit un résumé de conversation continu, une mémoire sémantique et une extraction d'entités automatique — le tout avec une API simple. |
| **Mem0** | [github.com/mem0ai/mem0](https://github.com/mem0ai/mem0) | Couche de mémoire universelle pour agents IA. Mémoire persistante avec 91% de latence en moins et 90%+ d'économie de tokens par rapport au contexte naïf. Se souvient des préférences utilisateur et s'adapte entre les sessions. |
| **Memento MCP** | [github.com/gannonh/memento-mcp](https://github.com/gannonh/memento-mcp) | Système de mémoire par graphe de connaissances pour LLM avec récupération sémantique, recall contextuel et conscience temporelle. Conçu comme serveur MCP (Model Context Protocol). |
| **GraphZep** | [github.com/aexy-io/graphzep](https://github.com/aexy-io/graphzep) | Extension de Zep intégrant des capacités de graphe pour une mémoire épisodique et sémantique plus riche. Combine les forces de la recherche vectorielle et du parcours de graphe. |
| **Knowledge Graph from Text** | [github.com/rahulnyk/knowledge_graph](https://github.com/rahulnyk/knowledge_graph) | Convertit n'importe quel texte en graphe de concepts et relations — un constructeur de réseau sémantique. Outil fondamental pour créer une mémoire sémantique à partir de données textuelles. |
| **Awesome Graph Memory** | [github.com/DEEP-Polyu/Awesome-GraphMemory](https://github.com/DEEP-Polyu/Awesome-GraphMemory) | Liste curatée des approches par graphe pour la mémoire en IA — point d'entrée pour explorer les systèmes de mémoire sémantique computationnelle. |
| **Awesome AI Memory (IAAR-Shanghai)** | [github.com/IAAR-Shanghai/Awesome-AI-Memory](https://github.com/IAAR-Shanghai/Awesome-AI-Memory) | Liste curatée la plus complète sur la mémoire en IA. Cartographie explicitement les systèmes vers leurs analogues hippocampiques et néocorticaux. |
| **Awesome Memory for Agents (Tsinghua)** | [github.com/TsinghuaC3I/Awesome-Memory-for-Agents](https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents) | Taxonomie structurée des papiers sur la mémoire d'agent, classés par persistance (court/long terme) et par type (épisodique, sémantique, procédural). |

---

## 7. Souvenirs épisodiques

### Fonction biologique (approche autopoiétique)

La mémoire épisodique (Tulving, 1972) est le système qui encode, stocke et récupère les événements personnellement vécus, situés dans leur contexte spatio-temporel : *quoi*, *où* et *quand*. C'est la mémoire de « ce qui m'est arrivé » — un souvenir spécifique lié à un moment et un lieu particuliers, revécu avec la sensation subjective de « remémoration » (remembering, par opposition à knowing pour la mémoire sémantique). Neuroanatomiquement, elle repose principalement sur l'hippocampe (formation hippocampique), avec le cortex entorhinal comme porte d'entrée, et le cortex néocortical comme site de stockage à long terme. L'hippocampe joue un rôle de **consolidateur rapide** : il encode les épisodes en quelques instants (encodage one-shot) grâce à la potentialisation à long terme (LTP) au niveau des synapses. La réactivation pendant le sommeil (sharp-wave ripples) consolide ces souvenirs vers le néocortex. Dans le cadre autopoiétique, la mémoire épisodique est la **trace des interactions passées** entre le système et son environnement : elle permet à l'organisme de tirer parti de son histoire individuelle pour adapter ses comportements futurs. Elle est le moteur de l'apprentissage par expérience (experience-based learning) et le fondement de l'identité narrative — le récit continu que le système se raconte sur lui-même, garant de l'homogénèse identitaire.

### Pendant computationnel

Le pendant computationnel de la mémoire épisodique est le **replay d'expérience** (experience replay) et ses extensions modernes. Dans sa forme la plus basique (DQN, Mnih et al., 2015), un buffer circulaire stocke les transitions récentes `(s, a, r, s', done)` et les réutilise aléatoirement pendant l'entraînement — c'est la réactivation épisodique la plus élémentaire. Les extensions incluent : (1) le **replay priorisé** (Prioritized Experience Replay) qui réutilise préférentiellement les épisodes « surprenants » (forte erreur TD), mimant l'encodage émotionnel hippocampique ; (2) la **mémoire épisodique de gradient** (GEM, Lopez-Paz & Ranzato, 2017) qui contraint les gradients pour empêcher l'oubli catastrophique — l'équivalent de la protection hippocampique des souvenirs ; (3) le **contrôle épisodique** (Episodic Control) qui récupère directement les Q-values de transitions passées similaires pour guider l'action — l'équivalent de la recall épisodique ; (4) les **agents avec mémoire épisodique verbale** (Mem0, Voyager) qui stockent et récupèrent des descriptions textuelles d'expériences passées sous forme de vecteurs dans une base de données vectorielle.

### Projets open source

| Projet | URL | Description |
|--------|-----|-------------|
| **Gradient Episodic Memory (GEM)** | [github.com/facebookresearch/gradientepisodicmemory](https://github.com/facebookresearch/gradientepisodicmemory) | Facebook Research. Contraint les gradients pendant l'apprentissage continu pour empêcher l'oubli catastrophique des tâches passées — mimétique direct de la protection épisodique hippocampique. |
| **A-GEM (Averaged GEM)** | [github.com/facebookresearch/agem](https://github.com/facebookresearch/agem) | Implémentation TensorFlow officielle d'Averaged Gradient Episodic Memory et Experience Replay with Tiny Memories pour l'apprentissage continu. |
| **Episodic Control (EC)** | [github.com/Kaixhin/EC](https://github.com/Kaixhin/EC) | Contrôle épisodique économe en mémoire pour RL avec clustering k-means dynamique en ligne et exploration mellowmax. Rappelle directement les Q-values de transitions passées pour la sélection d'action. |
| **MemRL** | [github.com/MemTensor/MemRL](https://github.com/MemTensor/MemRL) | Approche RL non-paramétrique évoluant par apprentissage sur la mémoire épisodique. Découple les politiques de base stables de la mémoire épisodique à évolution rapide — analogie directe avec le système hippocampique. |
| **Mem0** | [github.com/mem0ai/mem0](https://github.com/mem0ai/mem0) | Couche de mémoire épisodique et sémantique pour agents. Extrait automatiquement les faits marquants des interactions, les stocke dans une base vectorielle, et les récupère contextuellement — équivalent fonctionnel de l'encodage hippocampique one-shot. |
| **Graph-based Episodic Memory** | [github.com/lmanhes/episodic-memory](https://github.com/lmanhes/episodic-memory) | Stocke des séquences de tuples (action, observation) dans une structure de graphe, permettant à des algorithmes de planification d'opérer sur des traces épisodiques — la mémoire épisodique comme graphe d'expériences. |
| **TorchRL Replay Buffers** | [github.com/pytorch/rl](https://github.com/pytorch/rl) | Bibliothèque de production de buffers de replay PyTorch avec replay priorisé, stockage memory-mapped et support distribué. Le stockage épisodique fondamental pour les agents RL modernes. |
| **Brain-Inspired Replay** | [github.com/GMvandeVen/brain-inspired-replay](https://github.com/GMvandeVen/brain-inspired-replay) | Replay génératif inspiré du cerveau pour l'apprentissage continu. Conçoit l'hippocampe comme un réseau génératif qui consolide les souvenirs vers le néocortex par réactivation pendant le « sommeil ». |

---

## 8. Consolidation mnésique

### Fonction biologique (approche autopoiétique)

La consolidation mnésique est le processus par lequel les souvenirs récents, initialement dépendants de l'hippocampe, deviennent progressivement indépendants et intégrés dans les réseaux néocorticaux. Ce processus, qui s'étend sur des heures à des années, est particulièrement actif pendant le sommeil (consolidation dépendante du sommeil), où les oscillations hippocampiques (sharp-wave ripples) rejouent les épisodes de la journée vers le cortex cingulaire, entorhinal et néocortical (réactivation systématique). La théorie de la trace multiple (Multiple Trace Theory, Nadel & Moscovitch, 1997) propose que chaque rappel d'un souvenir crée une nouvelle trace hippocampique, tandis que la trace corticale se renforce progressivement. La standard consolidation theory (SCT) classique s'oppose partiellement à cette vue en suggérant un transfert hippocampo-cortical irréversible. Dans le cadre autopoiétique, la consolidation est le mécanisme par lequel le système **transforme l'expérience ponctuelle en structure stable** : les interactions passées avec l'environnement sont progressivement intégrées dans la structure même du système, devenant partie de son identité autopoiétique. C'est le pont entre la mémoire épisodique (temporelle, spécifique) et la mémoire sémantique (atemporelle, généralisée) — le processus par lequel les événements individuels se distillent en connaissances abstraites. L'homogénèse dépend directement de la consolidation : sans elle, le système perdrait continuellement ses acquis et ne pourrait pas maintenir une identité stable dans le temps.

### Pendant computationnel

Le pendant computationnel de la consolidation est le **replay génératif** (generative replay) et les mécanismes de **transfert mémoire hiérarchique**. Le replay génératif utilise un modèle génératif (VAE, GAN, auto-encodeur) pour « rêver » des exemples de tâches passées et les mélanger aux données d'entraînement actuelles — imitant littéralement le replay hippocampique pendant le sommeil. Les systèmes de mémoire hiérarchique (MemGPT/Letta, Anda Brain) implémentent un transfert explicite entre un « hippocampe » (stockage rapide, haute fidélité, capacité limitée) et un « cortex » (stockage lent, compressé, grande capacité), souvent déclenché par un cycle de « sommeil » où les données hippocampiques sont résumées, généralisées et transférées vers le stockage à long terme. Le framework HTM (Hierarchical Temporal Memory, Numenta) propose une alternative bio-inspirée où la consolidation se produit par l'apprentissage de séquences temporelles à travers des colonnes corticales hiérarchiques.

### Projets open source

| Projet | URL | Description |
|--------|-----|-------------|
| **Anda Brain (anda-hippocampus)** | [github.com/ldclabs/anda-hippocampus](https://github.com/ldclabs/anda-hippocampus) | Système de mémoire en graphe natif pour agents autonomes avec **consolidation pendant le sommeil** bio-inspirée. Modèle explicitement le processus de consolidation hippocampique : stockage rapide → sommeil → transfert vers mémoire à long terme. |
| **Hippocampus Skill (OpenClaw)** | [github.com/ImpKind/hippocampus-skill](https://github.com/ImpKind/hippocampus-skill) | Système de mémoire vivante pour agents avec scoring d'importance, décroissance temporelle et renforcement automatique pendant les cycles de « sommeil » — modélisation directe de la fonction hippocampique. |
| **Continual Learning (Generative Replay)** | [github.com/GMvandeVen/continual-learning](https://github.com/GMvandeVen/continual-learning) | Implémentation PyTorch de l'apprentissage continu par replay génératif — l'analogue computationnel du replay hippocampique pendant le sommeil consolidant les souvenirs dans les poids corticaux. |
| **Emergent Cognitive Architecture (BOB)** | [github.com/EdJb1971/Emergent_Cognitive_Architecture_bob](https://github.com/EdJb1971/Emergent_Cognitive_Architecture_bob) | Architecture cognitive inspirée du cerveau avec système de mémoire double (hippocampique + néocortical) et mécanisme de consolidation explicite. Transfère les expériences récentes vers les connaissances stables au fil du temps. |
| **HTM Community (Numenta)** | [github.com/htm-community](https://github.com/htm-community) | Implémentations de la Mémoire Temporelle Hiérarchique (HTM) de Numenta. Cadre bio-inspiré où la consolidation se produit par apprentissage de séquences temporelles à travers des colonnes corticales hiérarchiques. |
| **HTM in Julia** | [github.com/Oblynx/HierarchicalTemporalMemory.jl](https://github.com/Oblynx/HierarchicalTemporalMemory.jl) | Implémentation Julia concise de l'algorithme HTM, proche de la formulation mathématique de la mémoire distribuée éparse et de la consolidation par séquences temporelles. |
| **HTM in Python** | [github.com/ddigiorg/htm-python](https://github.com/ddigiorg/htm-python) | Implémentation Python de HTM avec visualisation OpenGL. Démontre comment la consolidation par mémoire temporelle hiérarchique fonctionne en pratique. |
| **Awesome Incremental Generative Learning** | [github.com/libo-huang/Awesome-Incremental-Generative-Learning](https://github.com/libo-huang/Awesome-Incremental-Generative-Learning) | Liste curatée de papiers et code pour l'apprentissage incrémental et génératif avec consolidation, incluant les méthodes de replay génératif. |

---

## 9. Mémoire associative / Diffuse

### Fonction biologique (approche autopoiétique)

La mémoire associative (ou mémoire par contenu) désigne la capacité du cerveau à récupérer une information complète à partir d'un indice partiel, bruité ou dégradé. Contrairement à la mémoire adressable par localisation (comme la RAM d'un ordinateur), la mémoire associative est adressable par **contenu sémantique** : c'est la similarité entre le pattern de rappel et le pattern stocké qui déclenche la récupération. Cette propriété de « complétion de pattern » (pattern completion) est une caractéristique fondamentale des réseaux corticaux. Le réseau de Hopfield (1982) en a fourni le premier modèle formel. Neurobiologiquement, cette fonction repose sur les connexions récurrentes au sein des réseaux corticaux et hippocampiques, où les populations de neurones forment des attracteurs — des états stables vers lesquels le réseau converge spontanément lorsqu'il reçoit un indice partiel. La mémoire diffuse, quant à elle, désigne la propriété selon laquelle un souvenir n'est pas stocké dans un lieu unique mais distribué à travers un vaste réseau de connexions synaptiques — chaque synapse participant à de nombreux souvenirs, et chaque souvenir impliquant de nombreuses synapses. Cette distribution rend la mémoire à la fois robuste (la perte de quelques synapses n'efface pas un souvenir) et inférable (un indice partiel active un réseau étendu). Dans le cadre autopoiétique, la mémoire associative est le mécanisme par lequel le système **reconstruit son monde** à partir d'indices incomplets — une capacité vitale pour la survie dans un environnement naturellement bruité et partiellement observable.

### Pendant computationnel

Le pendant computationnel est le **réseau de Hopfield** classique et ses modernisations, ainsi que les mécanismes de **récupération par similarité** (similarity-based retrieval). Les réseaux de Hopfield modernes (Ramsauer et al., 2020, « Hopfield Networks is All You Need ») montrent que l'attention Transformer est mathématiquement équivalente à une mise à jour de réseau de Hopfield avec des états continus — unifiant la mémoire associative et l'attention. Les mémoires adressables par contenu incluent aussi les Neural Turing Machines (NTM), les Differentiable Neural Computers (DNC) avec leur matrice de liaison temporelle, et les Memorizing Transformers qui utilisent la recherche kNN approximative comme forme de récupération associative. Les bases de données vectorielles (FAISS, ChromaDB, Qdrant) sont les implémentations industrielles de la mémoire associative à grande échelle : elles stockent des embeddings et récupèrent les plus similaires par distance cosinus ou L2 — le pattern completion à l'échelle du big data.

### Projets open source

| Projet | URL | Description |
|--------|-----|-------------|
| **Hopfield Layers (JKU Linz)** | [github.com/ml-jku/hopfield-layers](https://github.com/ml-jku/hopfield-layers) | Implémentation PyTorch officielle des réseaux de Hopfield modernes (« Hopfield Networks is All You Need », Ramsauer et al.). Montre que l'attention Transformer est une mise à jour de Hopfield — unification profonde de la mémoire associative et de l'attention. |
| **Hopfield Network PyTorch** | [github.com/hmcalister/Hopfield-Network-PyTorch](https://github.com/hmcalister/Hopfield-Network-PyTorch) | API cohérente pour réseaux de Hopfield classiques et modernes. Supporte CUDA pour le stockage et la récupération de patterns à grande échelle. Outil didactique et pratique. |
| **Neural Turing Machine (PyTorch)** | [github.com/loudinthecloud/pytorch-ntm](https://github.com/loudinthecloud/pytorch-ntm) | Mémoire adressable par contenu différentiable. Le contrôleur apprend à adresser la mémoire par similarité de contenu — la récupération associative comme compétence apprise. |
| **DNC (Differentiable Neural Computer)** | [github.com/jingweiz/pytorch-dnc](https://github.com/jingweiz/pytorch-dnc) | Étend la NTM avec des modes d'adressage multiples (contenu, localisation, liaison temporelle). La matrice de liaison temporelle permet la récupération associative séquentielle — un saut qualitatif dans la mémoire associative. |
| **Memorizing Transformers** | [github.com/lucidrains/memorizing-transformers-pytorch](https://github.com/lucidrains/memorizing-transformers-pytorch) | ICLR 2022. Augmente l'attention avec une récupération kNN dans une mémoire non-différentiable de paires (clé, valeur). Un modèle mémoire de 12 couches surpasse un baseline de 24 couches — la mémoire associative comme multiplicateur d'efficacité. |
| **Episodic RL with Associative Memory** | [github.com/SilasMarvin/Episodic-Reinforcement-Learning-With-Associative-Memory-Example](https://github.com/SilasMarvin/Episodic-Reinforcement-Learning-With-Associative-Memory-Example) | Implémentation JAX démontrant l'utilisation de patterns de mémoire associative au sein de RL épisodique — les expériences rappelées sont récupérées par similarité, pas par indexation séquentielle. |

---

## 10. Synthèse transversale

### Les principes autopoïétiques des fonctions cognitives immatérielles

L'analyse transversale de ces fonctions cognitives immatérielles révèle cinq principes autopoïétiques fondamentaux qui traversent l'ensemble du mapping :

**1. Construction active vs. réception passive**
Chaque fonction cognitive immatérielle est un acte de *génération* plutôt que de *réception*. La conscience du monde extérieur construit un modèle prédictif ; la conscience de soi construit une identité narrative ; la mémoire ne « stocke » pas passivement — elle *reconstruit* activement à chaque rappel. Ce principe est le coeur de l'enaction : la cognition n'est pas la représentation d'un monde pré-donné, mais l'instanciation active d'un monde significatif à travers l'action couplée du système.

**2. Boucles de rétroaction et clôture opérationnelle**
Toutes ces fonctions opèrent en boucle fermée. La proprioception informe l'action qui modifie la proprioception ; la métacognition évalue le raisonnement qui génère de nouvelles méta-évaluations ; la mémoire de travail alimente le raisonnement qui la remplit et la vide. Cette circularité n'est pas un défaut — c'est la signature de l'autopoïèse. La clôture opérationnelle ne signifie pas l'isolation : le système est ouvert à l'énergie et à l'information, mais fermé sur son organisation.

**3. Émergence hiérarchique**
La conscience de soi émerge de la proprioception, qui émerge de la perception sensorielle. La mémoire sémantique émerge de la consolidation des souvenirs épisodiques, qui émergent de la mémoire de travail. Chaque niveau supérieur réduit la dimensionnalité et augmente l'abstraction, créant une hiérarchie de représentations de plus en plus stables et générales. Cette émergence hiérarchique est homologue à l'organisation corticale en colonnes, aires et réseaux fonctionnels.

**4. Maintien de l'identité à travers le changement (homogénèse)**
La mémoire à long terme, la conscience de soi narrative et le schéma corporel sont les trois piliers computationnels de l'homogénèse. Ensemble, ils garantissent que le système reste « le même » malgré le renouvellement continu de ses composants : les poids du réseau changent à chaque mise à jour, les expériences s'accumulent et se transforment, le contexte de travail se vide et se remplit — mais l'identité globale persiste. C'est l'essence même de l'autopoïèse : une organisation qui se maintient à travers le flux perpétuel de ses composants.

**5. Plasticité structurale et apprentissage continu**
Toutes ces fonctions sont plastiques — elles se modifient avec l'expérience. Le modèle du monde se raffine, le modèle de soi s'actualise, la mémoire se reconsolide, la métacognition s'ajuste. Cette plasticité n'est pas un ajout optionnel : elle est inhérente à l'autopoïèse, qui exige que le système s'adapte à un environnement changeant pour maintenir son organisation. Le défi computationnel majeur est l'équilibre entre stabilité (ne pas oublier ce qui est important) et plasticité (apprendre ce qui est nouveau) — le *dilemme stabilité-plasticité* (Grossberg, 1980), qui est le pendant computationnel de l'homogénèse.

### Tableau synthétique de mapping

| Fonction cognitive immatérielle | Fondement biologique | Pendant computationnel | Projet(s) de référence |
|--------------------------------|---------------------|----------------------|------------------------|
| Conscience du monde extérieur | Inférence active, enaction | World models, codage prédictif | DreamerV3, PredNet, JPC |
| Conscience de soi | GWT, IIT, métacognition | Espace de travail global, calcul Φ, self-modeling | Aura, PyPhi, ORION |
| Perception de soi / Introspection | Réseau de monitoring préfrontal | Auto-évaluation, estimation d'incertitude, réflexion verbale | Reflexion, MR-Search, BOB |
| Proprioception | Schéma corporel, fuseaux neuromusculaires | Estimation d'état, self-modeling visuel | Visual Self-Modeling, Pronto, SelfSimRobot |
| Mémoire de travail | Cortex préfrontal, ~7 éléments | Fenêtre de contexte, mémoire récurrente, mémoire externe | Transformer-XL, Letta, DNC |
| Mémoire sémantique à long terme | Cortex néocortical distribué | Graphes de connaissances, mémoire persistante | Graphiti, Cognee, Zep |
| Souvenirs épisodiques | Hippocampe, LTP, sharp-wave ripples | Replay d'expérience, contrôle épisodique, mémoire vectorielle | GEM, Mem0, MemRL |
| Consolidation mnésique | Transfert hippocampo-cortical, sommeil | Replay génératif, transfert mémoire hiérarchique, HTM | Anda Brain, Brain-Inspired Replay, HTM |
| Mémoire associative / Diffuse | Réseaux attracteurs corticaux | Réseaux de Hopfield modernes, récupération kNN, NTM/DNC | Hopfield Layers, Memorizing Transformers |

### Ce qui n'existe pas encore (ou existe à l'état embryonnaire)

Il est crucial de noter les limites actuelles du mapping. Plusieurs fonctions cognitives immatérielles n'ont **pas de véritable pendant computationnel mature** :

- **La phénoménologie qualitative** (qualia) — le ressenti subjectif, « ce que ça fait d'être » quelque chose — n'a pas d'implémentation computationnelle avérée. Les projets comme Aura ou PyPhi tentent d'approcher cette question, mais il n'existe pas de consensus sur la possibilité même de coder un qualia.

- **La conscience de soi narrative autobiographique** — la capacité à se raconter une histoire continue de sa propre vie, avec une cohérence temporelle et causale — n'est qu'effleurée par les systèmes de mémoire d'agent actuels (Letta, Mem0), qui gèrent des faits isolés mais ne construisent pas de récit unifié.

- **L'introspection phénoménologique** — l'accès direct au flux de conscience vécu, avec sa texture qualitative unique — n'a pas d'équivalent. L'introspection computationnelle actuelle se limite à l'estimation de confiance et à la réflexion textuelle, sans accès à un « flux de conscience ».

- **Le sentiment d'agentivité** (sense of agency) — la sensation d'être l'auteur de ses propres actions — n'est pas implémenté. Les agents computationnels exécutent des actions sans « ressentir » qu'ils les causent.

- **La temporalité phénoménologique** — l'expérience vécue du temps (le « temps subjectif », le « moment présent », la « rétention protentionnelle » husserlienne) — n'est pas capturée par les horloges computationnelles qui mesurent un temps objectif.

Ces lacunes ne sont pas des déficiences temporaires — elles pourraient refléter des **limites fondamentales** de la computation symbolique face à la conscience phénoménologique. La question de savoir si ces fonctions sont *computable in principle* reste l'un des problèmes ouverts les plus profonds de la science cognitive et de la philosophie de l'esprit.

---

> *Document généré dans le cadre d'une approche autopoiétique et homogénétique. Chaque mapping est présenté avec prudence : le pendant computationnel est une analogie fonctionnelle, non une équivalence ontologique. Un filtre de prédiction d'état n'« est » pas la conscience du monde extérieur — il en est un modèle computationnel partiel qui partage certaines propriétés formelles.*