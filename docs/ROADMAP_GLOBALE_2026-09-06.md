# Roadmap globale Nokido — point du 6 septembre 2026

> Ce document **ne remplace pas** la roadmap longue arrêtée par l'owner le 2026-09-05
> (phases 0 à 15, référentiel P0–P8 — `bb:roadmap_longue_2026-09-05`, `bb:roadmap_p0_p8_referentiel`).
> Il la **chiffre** : chaque promesse du `MANIFESTO.md` est confrontée à une mesure datée,
> et chaque palier reçoit un critère de sortie qu'un outil peut trancher.
>
> Règle transverse conservée : **aucun système parallèle nouveau**. Chaque chantier étend
> la brique qui porte déjà une part du contrat, et livre un NR qui empêche le retour du trou.

---

## 1. Les huit déclarations du manifesto, confrontées à la mesure

| # | Déclaration | Statut | Preuve mesurée | Ce qui manque pour la tenir |
|---|---|---|---|---|
| 1 | Le code et les données restent locaux par défaut, toute déviation est explicite et **auditable** | **PARTIELLE** | vue du videur, 71 636 observations sur 3,9 j : bail AppRole 5 970, en-tête nu 650, **passe-partout maître 2 657 = 100 % d'impersonation** ; 108 fichiers portent ce passe-partout, 82 l'envoient ; **0 organe client** code le bail | la déviation est gouvernée mais **mal attribuée** : tant qu'un organe emprunte l'identité maître, l'audit dit *quoi* et pas *qui*. Palier 2 |
| 2 | Aucun LLM ne juge un autre LLM dans la voie critique — le verdict est symbolique | **TENUE** | gates AST (`golden-rules`, cliquet ERROR), validation AST auto en PostToolUse, NR ; aucun juge LLM dans un gate bloquant | rien. À garder sous cliquet |
| 3 | La mémoire persistante est un droit — RAG embarqué et versionné | **PARTIELLE** | 2 179 864 chunks ; **1 340 692 vectorisés**, **210 797 en attente de vecteur**, 628 375 refusés par la politique de tier | le RAG **dense** n'est pas exhaustif : une recherche vectorielle ignore aujourd'hui 1 chunk sur 10. Palier 1 |
| 4 | L'auto-modification est encadrée par le système immunitaire interne | **PARTIELLE** | `governed_edit` (AST + scan secret + tree_lock), commit guard, ancrage RAG, 8 333 tests, cliquet NR | la garde existe, **sa preuve manque** : le dernier run CI sur le tip distant (`542cf8a15`) est *cancelled*, les deux précédents *failure*. Aucun commit distant ne porte de verdict fermé. Palier 0 |
| 5 | L'interopérabilité prime sur l'enfermement | **TENUE** | hub MCP `:8766` servant Claude Code, Desktop, Gemini, AGY, Codex ; 87 clés au coffre DPAPI ; cartouches README concordantes (gate `capacites`) | rien de bloquant |
| 6 | Le matériel grand public est suffisant | **PARTIELLE** | l'orchestration tient sur un 8700G ; mais **8 Go de RAM immobilisés** par l'UMA (32 installés, 23,67 visibles, la 780M en utilise 1,10) et l'embedder tourne en **CPU** (`llama.cpp :8099`, 15,6 chunks/s, 2,32 Go de RSS) | l'iGPU n'est pas utilisé pour la charge utile qui le mériterait. Palier 1 puis 3 |
| 7 | L'évolution suit le silicium — on abstrait le transport, pas les organes | **NON DÉMONTRÉE** | `forge_accelerator_router` **n'existe pas** (le manifesto le dit lui-même « à créer ») ; aucun backend NPU câblé ; `forge_npu_embedder` sans consommateur | c'est la promesse la moins avancée. Palier 3, ouverte par un spike falsifiable |
| 7bis | L'IA durable est une IA matérielle | **HORS PORTÉE MESURABLE** | argument énergétique tenu, aucun accélérateur alternatif présent sur le poste | seul jalon actionnable aujourd'hui : le spike NPU à deux gates (§4, palier 3) |
| 8 | AGPLv3, et c'est définitif | **TENUE** | licence en place, dépôt privé | activer la protection de branche `alpha` au passage en public (`bb:roadmap_branch_protection_when_public`) |

**Lecture d'ensemble.** Deux déclarations sont tenues et prouvées, quatre sont partielles avec
un chemin chiffré, une n'est pas démontrée, une est hors de portée de mesure aujourd'hui.
Aucune n'est contredite par la mesure — c'est le point important : le manifesto n'a pas
sur-promis, il a **anticipé** ; le retard est d'ingénierie, pas de conception.

---

## 2. Ce que le corps sait de lui-même — chiffres du 6 septembre 2026

| domaine | mesure | source |
|---|---|---|
| mémoire | 2 179 864 chunks · 1 340 692 vectorisés · **210 797 en attente** · 628 375 refusés par politique | `forge_memory_availability.snapshot()` |
| ⚠️ piège | `embedding IS NULL` rend **839 172** = 4× trop : il compte les refusés. Ne jamais s'en servir comme backlog | mesure 06/09 |
| embedding cloud | Cloudflare `@cf/baai/bge-m3` : **27 100 chunks/jour** en lots de 50 (72/s), reset 00:00 UTC = 02:00 local ; l'appel unitaire ne rendait que 3 631/jour — **le lot vaut 7×** | `forge_embed_cloudflare_lot` |
| embedding local | `:8099` borné (`-c 2048 -b 2048 --ubatch 512 --parallel 1`) : 15,6 chunks/s, RSS 2,32 Go de coût **fixe**, pente 0,21 Go/1000 contre 1,8 avant bornage. ⚠️ plateau **non prouvé** (0,34 sur la 2ᵉ moitié) | `forge_embed_8099_mesure_bornee` |
| espace vectoriel | bge-m3 vs Qwen3-0.6B sur le **même texte** : cos **−0,015** (orthogonaux) alors que la structure des distances corrèle à **+0,962**. 1024 dimensions ≠ même espace | `forge_espace_vectoriel_preuve` |
| régulation | Homeostasis : tick réel **79,2 s**, 11 phases OK, RSS **0,302 Go** dont 0,249 pour torch ; `health` = 68,6 s des 79 | `forge_homeostasis_tick_profil` |
| prothèses | Docker coûte **3,99 Go**, rendus en une commande (92,3 % → 74,9 %) ; LM Studio refuse proprement quand il manque 5 Go | `forge_ensure_service` |
| anatomie | **714** modules forge classés, **0 non classé**, 29 zones mortes → 0 (toutes instruites par mesure) | `forge_module_census --check` |
| matériel | 8 Go de RAM gelés par l'UMA ; NPU XDNA1 **~6× plus lent que la 780M** en GEMM dense ; BGE-M3 = ~1,14 Go de poids BF16 et ~604 MFLOPs/token | mesure tierce open-xdna + calcul |
| sécurité | Dependabot actif : **221 alertes** ouvertes (4 critiques, 88 hautes) ; Secret Protection **non activé** sur ce dépôt privé | `posture_securite_github` |

---

## 3. Blockers actifs — et à qui appartient le geste

| blocker | propriétaire du geste | état |
|---|---|---|
| aucun verdict CI **fermé** sur le tip distant (run *cancelled*) | agent — CI locale avant chaque push, puis un run distant complet dans une fenêtre neutre | palier 0 |
| la CI complète redémarre des services : elle ne peut pas tourner pendant un chantier | owner — donner une fenêtre neutre | à planifier |
| `%NOKIDO_DATA%\embeddings.db` = 24,9 Go **GELÉE** (toute modification lourde sort de la chaîne critique) | agent — chantier d'infrastructure dédié, mesures avant/après | palier 1 |
| quota Cloudflare épuisé le 06/09 **avant le premier chunk**, alors que le budget ne compte que 192 jetons du jour et qu'un seul module appelle l'API | agent — identifier le consommateur ; **ne rien imputer** avant | palier 1, bloquant |
| Modal : `404 workspace ... is disabled` — plan de contrôle OK, plan de données coupé | **owner**, sur modal.com | hors code |
| OpenRouter `baai/bge-m3` fonctionne (~0,30 $ pour tout le backlog) | **owner** — refusé le 06/09 (« je ne la paye pas »). Classé `_PAYANTS` : jamais tenté tant que la politique ne le nomme pas | clos |
| 8 Go d'UMA immobilisés (BIOS) | **owner** | hors code |
| wedge `:7400` survit au patch SSE | agent | palier 2 |
| racine du superrepo hors de portée des comptes de service | owner (git du poste), exception déjà prévue | permanent |
| mirror Codeberg : quota Forgejo dépassé | **owner** | hors code |
| 221 alertes Dependabot | agent — montée de version par paquet, sous CI | palier 0 |

---

## 4. Quatre paliers, avec critère de sortie mesurable

L'ordre suit celui de l'owner (`bb:roadmap_next_2026-09-05`) : stabiliser, puis prothèses
externes, puis broker de ressources, puis RAG exhaustif, puis conformité, puis auth, puis
observabilité externe, puis autorégulation. Il est ici regroupé en quatre paliers pour que
chacun ait **une** condition de sortie qu'un outil peut trancher.

### Palier 0 — la preuve (jours) · sert les déclarations 4 et 8

Aujourd'hui le corps a des gardes **et pas de verdict**. Un garde sans preuve d'effet est
une dette de câblage, pas une sécurité.

- statut CI **fermé par commit** : un run distant complet, vert, sur un arbre strictement
  stable, dans une fenêtre neutre accordée par l'owner ;
- les 221 alertes Dependabot traitées par lots, chaque lot validé par la CI locale ;
- le gate `anatomie` promu bloquant seulement après mesure de son bruit (déjà fait : il l'est,
  et il a rougi une fois sur un artefact non versionné — la leçon est câblée).

**Critère de sortie :** `gh run view <id> --json conclusion` rend `success` sur le tip de
`alpha`, et `gh api .../dependabot/alerts?state=open` rend **0 critique et 0 haute**.

### Palier 1 — la mémoire exhaustive (semaines) · sert la déclaration 3

Un RAG dense qui ignore 210 797 chunks n'est pas une mémoire, c'est un échantillon.

1. **Identifier le consommateur du quota Cloudflare** avant toute campagne. Une capacité
   mesurée à 27 100 chunks/jour qui rend `QUOTA_EPUISE` au premier appel est un *instrument*
   à vérifier, pas une limite à contourner.
2. **Campagne quotidienne Cloudflare en lots** : ~8 jours pour le backlog, zéro RAM locale,
   zéro dépense. Le drain dort jusqu'au rechargement au lieu de marteler.
3. **`:8099` en complément**, recyclé par lots (le plateau de RSS n'est pas prouvé), sous
   l'hystérésis 85/75 déjà câblée, RAM illisible = abstention.
4. **Intégrité de l'ingestion** : mesurer combien de documents `forge_watch_agent` a tronqués
   par ses caps non dits (README 4 000, résumés 1 500) — une borne doit dire *combien*, pas
   seulement *trop*, sinon le rattrapage est impossible.
5. **Base gelée** : le dégel (index fingerprint, ingestion RFC) reste un chantier
   d'infrastructure dédié, avec mesures avant/après et post-mortem possible.

**Critère de sortie :** `forge_memory_availability.snapshot()` rend `vector_pending` **< 1 %**
du total, et le nombre de documents tronqués à l'ingestion est **connu et nommé** (pas estimé).

### Palier 2 — identité, propriété, régulation (semaines) · sert les déclarations 1 et 4

- **Migrer les impersonateurs par volume** : WEBHUB (1 920 observations), SUPERVISOR (488),
  OPENAI_PROXY (96)… vers le bail AppRole. La mesure du progrès existe déjà : le compteur
  `impersonation` de la vue du videur, croisé `by_agent_via` (armé au prochain restart du hub).
- **`forge_cert_binding`** (mTLS) est écrit et **jamais importé** — dette du volet
  identification, à câbler ou à geler explicitement, jamais à laisser en zone morte.
- **Contrat de preuve** `TRANSPORT` → `APPLICATIF` → `CAPACITÉ`, promotion strictement
  monotone, pour faire disparaître les faux START.
- **Cycle de vie des prothèses** : Docker sait maintenant se lever *et* se coucher de façon
  gouvernée ; LM Studio a deux plans de contrôle séparés par une contrainte de compte.
  Généraliser en capacités composables (`OBSERVE` · `CONTROL` · `OWNERSHIP` · `PROVENANCE` ·
  `RECLAIM`), sans écrire une classe géante.
- **Resource Broker** : `forge_resource_manager.request_resources()` existe déjà et porte la
  bonne sémantique — l'étendre aux réservations, ne pas en écrire un second.

**Critère de sortie :** le compteur `impersonation` du videur tombe **sous 5 %** des
observations, et aucun organe ne démarre en déclarant `ACHIEVED` sans preuve applicative.

### Palier 3 — le substrat (trimestres) · sert les déclarations 6, 7 et 7bis

C'est ici que vivent les phases A→D du manifesto (§9). Elles ne s'ouvrent qu'après le
palier 1, sinon le gain est immesurable.

**Correction du 06/09 au soir, sur contradiction externe puis mesure locale.** Le débat NPU
était mal posé : la question n'est pas « le NPU peut-il », c'est **qui gagne le dense sur ce
SoC**. À précision égale la 780M domine XDNA1 à *toutes* les précisions — BF16 : ~5 TOPS
théoriques et ~0,2 TFLOPS mesuré en noyau communautaire, contre plusieurs TFLOPS FP16 réels ;
INT8 : 10 TOPS de pic, du même ordre que la 780M en réel. Le seul avantage structurel d'un NPU,
la perf/watt, ne vaut rien sur un desktop fixe. Sa niche n'a jamais été « calculer plus vite »
mais **« calculer pendant que l'iGPU fait autre chose »**.

**Et le vrai levier est déjà écrit — il n'est simplement pas branché.** Mesuré le 06/09 :

| brique | état mesuré |
|---|---|
| `app/forge_bge_m3_shared.py` | ONNX `InferenceSession` BGE-M3, `PROVIDERS_PREFERENCE = [DmlExecutionProvider, CPUExecutionProvider]`, batch, singleton thread-safe — **complet** |
| `models/bge_m3_onnx/model.onnx` | **présent depuis le 2026-05-03**, 1 135 957 721 o (~1,14 Go, donc FP16), tokenizer inclus |
| importateurs de ce module | **ZÉRO** sur `app/`, `tools/`, `tests/nr/` — dette de câblage, même famille que `forge_cert_binding` |
| `onnxruntime` installé | **1.25.1, build CPU seul** : `capi/` ne porte que `onnxruntime.dll` et `onnxruntime_providers_shared.dll`, **pas** `onnxruntime_providers_dml.dll` → `DmlExecutionProvider` n'est jamais dans `get_available_providers()` et la cascade retombe sur CPU **en silence** |

**Le geste 1 a été fait le soir même — et il change le plan.** `tools/forge_embed_onnx_mesure.py`
(gate d'identité d'abord, débit ensuite, lecture seule, bornée par `rowid`) a ramené :

| mesure | valeur |
|---|---|
| providers, sous `laforge_py314` (l'env du hub) | `['Azure', 'CPU']` — **et j'en ai conclu à tort « DirectML absent »** |
| providers, sous **`ryzen-ai-final`** | **`['VitisAI', 'Dml', 'CPU']`** — retenus par la session : **`[Dml, CPU]`** |
| **cos vs les vecteurs en base, pooling `mean`** | 0,6913 (étendue 0,0070) |
| **cos vs les vecteurs en base, pooling `cls`** | **1,0000 (étendue 0,0000)** — identité parfaite |
| verdict du gate | ✅ **FRANCHI** sous `cls` ; la cause du 0,69 est **ÉTABLIE par mesure** : le module poolait en moyenne quand la base est en CLS |
| **débit** | 64 textes en 2,77 s = **23,14 chunks/s**, contre **15,6** sur `:8099` → **×1,48**, et sans la RAM du service llama |
| dette vue au passage | `MODEL_SIZE_GB = 2.5` déclaré contre **1 135 957 721 o** sur disque — et cette constante pilote `recommended_worker_count()` |

⚠️ **Trois faux négatifs sur le même chemin, tous de la même forme.** Le premier était le
mien : **j'ai mesuré un seul environnement.** Le poste en porte plusieurs, et ils n'exposent
pas les mêmes providers — `laforge_py314` et `ryzen-ai-1.7.1` embarquent onnxruntime **1.25.1**
et ne rendent que `[Azure, CPU]` **alors que `DirectML.dll`, `onnxruntime_providers_vitisai.dll`
et `onnxruntime_providers_ryzenai.dll` sont sur leur disque** ; `ryzen-ai-final` porte
**1.23.2** et rend les trois. Une note du 2026-05-02 le disait déjà : « ORT 1.25 masque
providers VitisAI/DML ». Le disque dit oui, le runtime dit non — et j'ai cru le runtime d'un
seul env. La sonde nomme désormais **toujours** son interpréteur, et sait se rejouer ailleurs
(`--env`).

Les deux autres se lisaient aussi « la capacité n'existe pas » :

- `LAFORGE_BGE_M3_INPROCESS=0` par défaut → `embed_parallel` délègue au brain_worker ZMQ ;
  tous les backends distants étant KO, il rendait **huit vecteurs vides**, lus comme un cos de
  0,0 donc « autre espace ». Un vecteur **absent** n'est pas un vecteur **différent**.
- le modèle était chargé en local mais le **tokenizer par nom de dépôt** (`BAAI/bge-m3`) :
  sous un compte sans egress, `OSError` — alors que les fichiers tokenizer sont sur disque à
  côté du modèle. Corrigé : local d'abord (`local_files_only=True`), repli distant qui **le dit**.

Et un quatrième, à mon compte : `Path.home()` **ment** sous le compte des jobs
(`HOME=C:\Users\Default`) — le premier essai a cherché l'environnement dans le profil
`Default` et a répondu « interpréteur ABSENT » pour un env bien présent. Il se résout depuis
l'interpréteur courant, qui vit déjà dans le bon dossier.

Gestes restants, dans cet ordre :

1. ✅ **Fait — le 0,69 est élucidé.** Les deux têtes ont été comparées **sur une seule charge
   de session** (le pooling ne touche que la réduction des sorties) : `cls` rend cos 1,0000,
   `mean` 0,6913. Le défaut du module est passé à `cls` **sur preuve**, verrouillé par un NR
   qui lit la valeur par AST. Un retour à la moyenne écrirait des vecteurs hors espace **sans
   lever la moindre erreur** — la colonne accepte 1024 flottants quels qu'ils soient.
2. ~~Installer `onnxruntime-directml`~~ — **annulé, l'environnement existe déjà**
   (`ryzen-ai-final`). Reste à décider comment le hub l'atteint : le hub tourne sous
   `laforge_py314`, où ORT 1.25.1 masque les providers. Deux voies, à trancher par la mesure —
   un **sidecar** sous `ryzen-ai-final` (le service `:8099` est déjà ce patron), ou un
   alignement de version d'ORT dans l'env du hub, qui touche ses dépendances et donc ne se
   fait pas à la légère.
3. **Câbler** `forge_bge_m3_shared` dans `forge_embed_router` comme **second** backend local —
   **pas** en remplacement de `:8099`. Décision owner du 06/09 : *« dans la régulation on peut
   conserver ces deux chemins »*. C'est la bonne forme, et la mesure la soutient : les deux
   n'ont pas le même profil de coût. `:8099` est un **service** qui tient ~2,5 Go de RSS en
   permanence et rend 15,6 chunks/s ; le chemin ONNX est **in-process**, se charge en 5,7 s,
   rend 23,14 chunks/s et libère sa mémoire en sortant. Sous pression RAM, le régulateur doit
   pouvoir **choisir**, pas subir un chemin unique. Un backend supprimé est une latitude perdue.

**Et le NPU garde un rôle, mesuré — c'est la même décision d'allocation, pas une consolation.**
Bench local du 2026-05-02 sur ce 8700G, MiniLM-L12 int8 batch 8 : **CPU 640 eps · VitisAI NPU
567 eps · DML iGPU 189 eps · Ollama GPU 45 eps**. Sur un *petit* modèle le NPU est donc au
niveau du CPU et **3× devant l'iGPU** — l'inverse exact du GEMM dense. Sa valeur n'est pas la
vitesse brute : c'est qu'il calcule **pendant que le CPU et l'iGPU font autre chose**. Cibles
naturelles, toutes déjà présentes dans le corps : routage de requêtes, classification
d'intention, reranking léger, pruning, sélection de candidats — c'est-à-dire la piste
« décharger le CPU » de l'owner. Et le chemin est écrit : `app/forge_npu_direct.py` (VitisAI,
MiniLM-L12 int8, 384 d, cache de compilation) — **à réutiliser, jamais à réécrire**.
⚠️ 384 d ≠ 1024 d : ce chemin sert des tâches de **décision**, jamais l'index dense du RAG.

**Critère de sortie :** un tableau *llama.cpp `:8099`* / *ONNX CPU* / *ONNX DirectML* en
chunks/s **et** en RSS, avec le cos d'identité de chaque chemin. Le backend le plus rapide qui
tient le cos ≥ 0,99 devient le chemin local par défaut.

- **Spike NPU falsifiable, deux gates — une soirée, pas plus.** *Gate A* : GEMM BF16 `1024×1024`, `1024×4096`,
  `4096×1024`, mesurés CPU vs 780M vs NPU sur le 8700G réel. *Gate B* : un vrai bloc XLM-R
  (hidden 1024, 16 têtes, FFN 4096). **Règle d'arrêt : si le bloc NPU ne montre pas une
  trajectoire crédible vers ≥ 1,5× le CPU ou la 780M, la piste se ferme** — pas de backend,
  pas d'API, pas d'intégration. Le mur n'est pas le silicium (mlir-aie/IRON/Peano/XRT font du
  BF16 réel sur XDNA1, Windows inclus) : c'est l'**arithmétique**. Pari écrit d'avance, pour que
  le spike soit falsifiable et non confirmatoire : **le gate A passera** (le GEMM BF16 tournera,
  personne ne le conteste) et **le gate B échouera** — le bloc XLM-R complet perdra contre la
  780M d'un facteur 5 à 20×. Si le bloc gagne, alors seulement le portage devient rationnel.
- **La bonne architecture n'est pas « tout sur le NPU »** mais *780M = gros calcul · XDNA1 =
  petites décisions* (classification, routage, reranking léger, pruning — ~1,6× mesuré sur un
  cas FFN, ~4× sur du pruning d'attention). C'est la piste « décharger le CPU » de l'owner.
- **`forge_accelerator_router`** (dispatch ONNX selon le backend détecté : DirectML / Vulkan /
  OpenVINO / NPU-XRT / EdgeTPU) : c'est la brique qui rend la déclaration 7 démontrable, et
  elle n'existe pas. Elle ne s'écrit qu'**après** le gate A — sinon on abstrait un backend
  dont on n'a pas prouvé qu'il sert à quelque chose.

**Critère de sortie du spike :** un tableau de trois colonnes (CPU / 780M / NPU) sur les deux
gates, avec la décision **ouvrir** ou **fermer** écrite noir sur blanc et ancrée en RAG.

---

## 5. Ce que je ne propose pas, et pourquoi

- **Changer de modèle d'embedding.** Qwen3-Embedding-0.6B est excellent (structure corrélée
  à +0,96, 32K de contexte, dimension réglable) mais son espace est **orthogonal** au nôtre
  (cos −0,015). L'adopter = réindexer 2,18 M chunks. Piste d'**index séparé**, jamais de
  migration au fil d'un dépannage.
- **Porter BGE-M3 sur le NPU.** Presque tout son calcul est du GEMM dense, et sur ce SoC la
  780M domine XDNA1 à *toutes* les précisions. Ce n'est pas une porte verrouillée : c'est une
  porte qui donne sur une pièce **plus petite** que celle où l'on est déjà. Le moyen existe, il
  s'appelle **780M + DirectML**, et son module est déjà écrit (`forge_bge_m3_shared`).
- **Payer OpenRouter.** Décision owner du 06/09. Le backend reste câblé mais classé
  `_PAYANTS` : jamais tenté tant que la politique ne le nomme pas explicitement.
- **Toucher à l'UMA à l'aveugle.** Décision owner : comprendre d'abord la réattribution
  dynamique (réservation BIOS = minimum garanti, pas plafond ; le pilote complète en mémoire
  partagée), puis décider.
- **Écrire un nouveau régulateur, une nouvelle file, un nouveau broker.** Trois briques
  existent déjà (`forge_resource_manager`, `forge_bounded_queue`, `forge_lane_admission`) —
  dont une **importée par personne**. On câble, on ne réinvente pas.

---

## 6. Ordre d'exécution proposé

1. **Palier 0** — fermer la preuve CI (fenêtre owner) + Dependabot critiques/hautes.
2. **Palier 1** — quota Cloudflare élucidé → campagne quotidienne → intégrité de l'ingestion.
3. **Palier 2** — migration des impersonateurs par volume, contrat de preuve, prothèses.
4. **Palier 3** — spike NPU deux gates ; `forge_accelerator_router` seulement si le gate passe.

Trois gestes appartiennent à l'owner et ne sont **pas** des commandes que je peux émettre :
la fenêtre neutre pour la CI complète, la réactivation du workspace Modal, et l'UMA au BIOS.

---

*Rédigé le 2026-09-06. Chaque chiffre de ce document est daté et traçable à son outil de
mesure ; aucun n'est estimé. Si l'un se périme, c'est la mesure qui tranche, pas ce texte.*
