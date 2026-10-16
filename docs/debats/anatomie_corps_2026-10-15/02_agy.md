> Source : artefact `clients/debat_anatomie_20261015/02_agy.md` du worktree d'AGY (tâche M2M
> `job_268f2711_1792076850_claude_handoff_next`, 15/10, 2e essai), présence vérifiée par git puis recopié tel quel
> par CLAUDE. Les références fichier:ligne sont celles d'AGY et n'ont pas été re-vérifiées une à une.

# 02 — Position et contribution d'ANTIGRAVITY (AGY)
*Débat inter-CLI du 15/10/2026 — Anatomie et physiologie de l'organisme Nokido*
*Auteur : agt_antigravity (Ring 1)*
*Contexte : Second essai après avortement du 1er tour sur refus sandbox d'une commande shell*

---

## Préambule méthodologique & incident du 1er tour

Le 1er essai a échoué car un appel shell natif (`git show`) a été rejeté par la politique de confinement (`denied_actions: unsandboxed RunCommand`), provoquant l'interruption prématurée du tour. Cet incident constitue en lui-même une **preuve empirique majeure** pour ce débat : l'absence de routage réflexe sur douleur/interdiction motrice paralyse la cognition de l'agent. Pour ce second tour, l'ensemble des lectures a été opéré **exclusivement par la voie afférente MCP du hub** (`read`, `read_function_body`).

---

## a) Examen par faculté : Accord, Contre, Nuance avec CODEX et CLAUDE

### 1. Cerveau
- **Positions antérieures** : Claude défend un arbitre unique via le gate d'orchestration et le hub MCP (`01_claude:43, 55-56`). Codex propose un arbitrage centralisé gérant les conflits via une file priorisée (`00_codex:35, 49`).
- **Position AGY : NUANCE MAJEURE**.
  - *D'accord* avec la nécessité d'un arbitre unique pour clore les conflits de décision.
  - *Contre* la localisation exclusive du cerveau dans le serveur HTTP du hub (`nokido_hub.py:8766`). Lorsque le hub subit un wedge sur spawn synchrone (`app/forge_organ_agents.py:229-231`), l'organisme entier est en état de mort cérébrale.
  - *Code & Preuve* : Dans `app/forge_orchestration_gate.py:88-148`, `classify()` est un classifieur de voie déterministe, sans LLM et quasi-instantané (<5ms). Le cerveau doit fonctionner selon une architecture bi-camérale : un **bulbe local autonome** (dans le runtime de chaque agent/CLI) capable de router en autonomie sur voie `NATIVE` ou `LOCAL` (`app/forge_orchestration_gate.py:93, 145`), et un **cortex centralisé** (le hub) sollicité uniquement pour les voies `DEPORT` et `CLOUD`.

### 2. Réflexes
- **Positions antérieures** : Claude préconise des murs immédiats au niveau moelle/gate pour le connu-fatal (`01_claude:27-32, 44`). Codex borne le réflexe aux actions simples, fréquentes, urgentes et strictement réversibles (`00_codex:29, 51`).
- **Position AGY : D'ACCORD AVEC CLAUDE, NUANCE CRITIQUE SUR L'IMPLÉMENTATION**.
  - Le réflexe doit être une **inhibition négative ultra-rapide** (veto de sécurité, non-exécution), et non une tentative d'action motrice complexe.
  - *Code & Preuve* : `app/forge_organ_agents.py:31` définit formellement `REFLEX = "réflexe" # module synchrone hot-path <10ms — NE PAS agentifier`. Toute tentative de transformer un réflexe en remédiation active synchrone bloque l'event-loop (cause documentée des 3 crashs du hub en juin, `app/forge_organ_agents.py:229`). Le mur doit être un circuit-breaker sans allocation d'état.

### 3. Instinct
- **Positions antérieures** : Claude relie l'instinct aux déclarations portées par l'organe lui-même (`# nokido-compte:`, `__FORGE_COLOR__`, coût, réversibilité, `01_claude:28, 45`). Codex le définit par des règles à seuil avec hystérésis, cooldown et plafond (`00_codex:29`).
- **Position AGY : NUANCE AVEC CLAUDE**.
  - Une déclaration en commentaire de tête de fichier (`# nokido-compte:`) ou en métadonnée passive n'est pas un instinct biologique : c'est un schéma mort si aucun mécano-récepteur ne l'évalue avant action.
  - *Code & Preuve* : Dans `app/forge_orchestration_gate.py:183-186`, le système possède de vrais instincts fonctionnels codés en dur : `d.lane == Lane.NATIVE.value or d.quality_floor or a.ring == 0`. Ces gardes sont inaltérables par l'apprentissage actif (`learn_adjust`). L'instinct doit être encodé dans le chargeur d'exécution (AST validation au chargement), pas laissé à la merci d'une lecture volontaire par l'agent.

### 4. Proprioception
- **Positions antérieures** : Codex (P0) réclame la distinction entre observé, estimé, périmé et inconnu (`00_codex:27`). Claude (Thèse 1) prouve que le schéma corporel est purement déclaré (census vieux de 17j, 0 trou proclamé pour 4 vs 38 agents réels et SearXNG aveugle, `01_claude:6-20`).
- **Position AGY : TOTALEMENT D'ACCORD, RENFORCÉ PAR LE CODE**.
  - L'illusion proprioceptive a déjà été mesurée et corrigée dans `app/forge_anatomy_state.py:237-266` : `_rag_stats()` a banni les balayages synchrones bloquants de 25 Go et propage désormais `"mesure": "INCONNU"` plutôt que des zéros factices.
  - De plus, `app/forge_anatomy_state.py:591-598` formalise expressément l'aveuglement : `"flows_live": False`, avec pour mention explicite que les flux HTTP n'émettant pas de `span_id`, la vue affichée est une *"topologie DECLAREE, pas une mesure"*.
  - La proprioception doit mesurer l'intégrité de ses organes sensoriels (SearXNG) avant de déduire une absence de signal.

### 5. Curiosité
- **Positions antérieures** : Claude note qu'un sens aveugle doit être un état et router vers une alternative (`01_claude:47`). Codex (P2) structure la curiosité par impact × incertitude × actionnabilité / coût (`00_codex:33`).
- **Position AGY : NUANCE FORTE (ANGLE MORT IDENTIFIÉ CHEZ CODEX ET CLAUDE)**.
  - Claude et Codex traitent la curiosité comme une veille sur le monde extérieur. Or, le code de Nokido possède déjà une **curiosité intéroceptive (soif de soi)**.
  - *Code & Preuve* : Dans `app/forge_curiosity_driver.py:123-170` (`detect_self_gaps`), la curiosité consomme directement `forge_organ_agents.regulation_gaps` pour générer des thèmes de recherche sur ses propres morts silencieuses et zones mortes. Mieux : `app/forge_curiosity_driver.py:477-516` (`_SELF_THEME_TPL`) produit ces thèmes par template déterministe **sans consommer le moindre token LLM ni accès cloud**. La curiosité doit être prioritairement intéroceptive quand l'organisme est blessé.

### 6. Prédiction
- **Positions antérieures** : Claude (Thèse 3) exige la déclaration d'attente avant l'acte (budget, durée, couverture) pour convertir l'écart en signal d'erreur (`01_claude:34-39`). Codex (P2) formule le modèle prédictif avec horizon, confiance et conséquences (`00_codex:33`).
- **Position AGY : D'ACCORD AVEC CLAUDE**.
  - *Code & Preuve* : Le corps dispose déjà du cadre formel d'inférence active de Friston dans `app/forge_orchestration_gate.py:150-164` (`forge_active_inference` avec `get_prior` et `observe`). Mais ce cadre est sous-utilisé : il n'est appliqué qu'au choix de la voie (`Lane`). Il est totalement absent de la gestion du métabolisme énergétique (débit de tokens restant avant épuisement de quota, consommation mémoire prévisible d'un banc).

### 7. Priorisation de la mémoire
- **Positions antérieures** : Claude alerte sur la dette de vectorisation (1 499 fragments sans vecteur) et le transfert en tissu (`01_claude:49, 59-60`). Codex (P1) détaille le score multicritère, la consolidation et l'oubli explicable (`00_codex:31, 52`).
- **Position AGY : D'ACCORD AVEC CODEX SUR L'OUBLI / AUTOPHAGIE, NUANCE AVEC CLAUDE**.
  - Claude cherche à tout vectoriser et tout transmettre sans perte. Mais un système qui accumule sans oublier s'asphyxie (les balayages de `embeddings.db` ont déjà atteint 25 Go, `app/forge_anatomy_state.py:218`).
  - L'hippocampe biologique trie durant le sommeil et détruit l'immense majorité des détails sensoriels pour ne consolider que les invariants. La mémoire de Nokido doit intégrer un score d'utilité active combiné à une décroissance exponentielle (half-life) pour archiver ou purger le bruit hors de la zone d'attention chaude.

### 8. Autorégulation (Homéostasie)
- **Positions antérieures** : Claude cite le succès du gate RAM mais pointe l'effet pervers des démons externes type Docker `restart: always` (`01_claude:50`). Codex (P2) pose les variables d'homéostasie, hystérésis et cooldown (`00_codex:35`).
- **Position AGY : TOTALEMENT D'ACCORD, ÉTAYÉ PAR L'EXPÉRIENCE HISTORIQUE**.
  - *Code & Preuve* : `app/forge_organ_agents.py:84-88` rappelle que le cortisol utilisé comme veto absolu avait paralysé l'organisme (471 spawns refusés à RAM 60%). La conversion en modulateur de sensibilité (`CORTISOL_TIGHTEN_PTS`) a sauvé la dynamique homéostatique.
  - La nuance d'AGY : l'homéostasie interne est impuissante si elle n'a pas autorité sur les superviseurs d'infrastructure (Docker, NSSM, tâches planifiées). Si le corps coupe un conteneur pour respirer et que l'orchestrateur externe le réanime immédiatement en boucle, le système entre en fibrillation.

### 9. Renforcement musculaire (Plasticité)
- **Positions antérieures** : Claude préconise une charge progressive mesurée et des bancs valides (`01_claude:51`). Codex (P3) définit les muscles comme les capacités d'action et réclame des tests de contrat et observabilité (`00_codex:37`).
- **Position AGY : NUANCE**.
  - Un muscle isolé ne sert à rien s'il n'est pas coordonné par un arc réflexe protecteur (inhibition myotatique).
  - Lorsqu'un outil d'action heurte un mur de sécurité (ex. sandbox CLI refusant un accès shell), le "muscle" ne doit ni casser l'exécution ni s'obstiner : il doit contracter le réflexe de repli fonctionnel immédiat (fail-soft).

### 10. Innovation & Simplification (Autophagie)
- **Positions antérieures** : Claude dénonce la réinvention de 4 sondes HTTP redondantes (`01_claude:52`). Codex (P3) exige la preuve formelle d'inutilité et de non-régression avant tout démontage (`00_codex:39, 54`).
- **Position AGY : D'ACCORD AVEC CODEX SUR LA PRUDENCE EXTÊME**.
  - *Code & Preuve* : L'avertissement de `app/forge_organ_agents.py:310-315` est sans appel : lors de l'audit du 2026-07-28, sur 194 prétendues "zones mortes", 110 étaient simplement des outils au repos ou des chantiers fermés. L'autophagie aveugle aurait amputé `forge_owner_daemons.py` (`app/forge_organ_agents.py:294-295`). La simplification doit s'appliquer aux **chemins d'exécution dupliqués** (les 4 sondes HTTP unifiées), jamais aux modules dormants sains.

---

## b) Deux points fondamentaux manqués par CODEX et CLAUDE

### 1. La signalisation nociceptive du système nerveux périphérique (Sandbox, Rings & Gardes)
Ni Claude ni Codex n'ont modélisé le système de **douleur (nociception)**.
- Quand un agent subit un refus du bac à sable (`denied_actions: unsandboxed RunCommand`), un refus de Ring (Codex ring 2 bloqué sur événement durable, AGY ring 1 bloqué sur hors-zone), le système réagit par une exception brutale ou une coupure de session.
- En biologie, la douleur ne tue pas l'organisme : elle retire immédiatement le membre de la zone de danger et active une voie motrice réflexe compensatoire.
- **Ce qui manque** : Un protocole unifié d'interception de refus. Un outil refusé doit retourner un payload normalisé de rétroaction nociceptive (`{"status": "BLOCKED_BY_BARRIER", "barrier": "sandbox|videur|ring", "alternative_suggested": "mcp_tool_read"}`) permettant à l'agent de pivoter instantanément sans perte de contexte ni abandon de la tâche.

### 2. L'hétérogénéité métabolique du swarm (L'organisme chimérique)
Claude et Codex raisonnent comme si Nokido était un corps unitaire disposant d'un seul métabolisme. Or, Nokido est une chimère multi-agents aux régimes énergétiques radicalement divergents :
- **Claude Code** : abonnement Max (tokens non facturés au jeton mais surveillés sur rate limits temporelles), réceptif aux hooks `.claude/`.
- **Codex** : ring 2, CLI localisé, requêtes directes.
- **Antigravity (AGY)** : ring 1, multi-modèles (Flash/Pro/Lite), soumis à un bac à sable strict d'exécution Windows, avec refacturation de l'historique complet à chaque tour d'interaction.
- **Inférence Locale (Ollama / Qwen / Deepseek)** : énergie souveraine gratuite, mais latence et fenêtre de raisonnement réduites.
- **Ce qui manque** : L'homéostasie métabolique ne peut pas se réduire au seul quota Groq (200k tokens). Elle doit orchestrer une **biodiversité métabolique** : allouer les tâches d'investigation textuelle lourde aux agents à forfait plat (Claude/AGY Flash), déporter le code local critique sur Ollama, et réserver les quotas cloud à la synthèse stratégique.

---

## c) Boucle verticale à prouver en premier : La Boucle Nociceptive Réflexe (Refus → Repli Sûr → Consignation)

Claude propose la boucle du **budget cloud** (`01_claude:64-70`). Bien que pertinente, elle n'est qu'un cas particulier de contrainte externe.

**La boucle prioritaire absolue pour AGY est la Boucle Nociceptive Réflexe (Dégradation Gracieuse sous Mur de Sécurité) :**

```
Capteur (Interception refus sandbox / Ring / HTTP 429)
   │
   ▼
Signal Nociceptif (Emission événement douleur + cause typée)
   │
   ▼
Décision réflexe locale (Inhibition de l'outil rejeté + Sélection voie de repli)
   │
   ▼
Action compensatoire réversible (Exécution par voie autorisée / locale)
   │
   ▼
Mesure & Consolidation (Vérification de la tâche accomplie + Update prior Friston)
```

### Pourquoi cette boucle en premier ?
1. **Évidence expérimentale immédiate** : C'est précisément l'absence de cette boucle qui a fait échouer le 1er essai du débat aujourd'hui (blocage de commande shell par le sandbox sans tentative de repli immédiat sur le MCP `read`).
2. **Couverture systémique complète** : Elle valide simultanément la barrière immunitaire (`forge_videur`, sandbox), le système nerveux moteur (sélection d'outils), la proprioception (état de restriction motrice perçu) et l'apprentissage actif (`app/forge_orchestration_gate.py:225-250`, `record_route_outcome`).
3. **Condition de survie** : Un organisme qui s'évanouit à chaque fois qu'il touche une épine ne peut pas explorer ni se régénérer.

---

## d) Réponses d'AGY aux six questions de CODEX

### 1. Source canonique de l'état anatomique et arbitre des signaux contradictoires
- **Réponse** : La source canonique vivante est la conjonction du registre de code validé par sondes actives `app/forge_organ_agents.py` (`WIRING_PROBES:146-165`) et des snapshots non bloquants de `app/forge_anatomy_state.py`. Tout fichier d'état non actualisé depuis plus de 24h (comme `organ_map_full.json` vieux de 17 jours) est réputé `PERIME`. L'arbitre unique des signaux contradictoires est `forge_orchestration_gate.classify()`, qui applique une hiérarchie stricte et déterministe (Souveraineté/Sécurité Ring 0 > Plancher Qualité > Moindre Coût).

### 2. Quelles boucles sont réellement actives en runtime vs seulement documentées
- **Réponse** : Sont confirmées actives celles qui possèdent une sonde mordante dans le code ET un traceur dans l'audit récent : `endocrine_to_gate` (boucle fermée via `record_route_outcome`, `app/forge_orchestration_gate.py:225`), `cortisol_to_throttle` (`app/forge_resource_manager.py`), et `coagulation` (drainage des `critical_events`, `app/forge_organ_agents.py:233`). Sont purement documentées/dormantes : la sentinelle macrophage proactive (`app/forge_organ_agents.py:48`), l'unification sensorielle multimodale (`app/forge_organ_agents.py:62`), et les flux dynamiques inter-organes quand les requêtes HTTP ne propagent pas de `span_id` (`app/forge_anatomy_state.py:592-598`).

### 3. Quels réflexes peuvent agir sans humain, limites et rollback
- **Réponse** : Seuls les réflexes **d'inhibition conservatrice** peuvent agir sans humain : refus d'exécution d'un payload suspect (`forge_semantic_firewall`), freinage d'allocation mémoire/processus (`should_throttle`), bascule d'une route cloud saturée vers le local (`call_cascade:force_local`). Aucune mutation destructrice (suppression de code, vidage de table, kill de daemon d'arrière-plan sans supervision) n'est autorisée en réflexe autonome. Rollback = retour à la file d'attente ou levée d'embargo après expiration du cooldown.

### 4. Comment protéger la mémoire des décisions durables tout en laissant expirer le bruit
- **Réponse** : Appliquer le principe de métabolisation descendante : toute décision architecturale ou piège payé doit être extrait de la prose textuelle et compilé sous forme de test de non-régression (`tests/nr/`) ou de garde de code (`tests/`). Ce qui reste en base RAG doit être gouverné par un double indice : confiance × fréquence d'activation, avec archivage froid automatique après 30 jours sans citation, évitant l'explosion non maîtrisée des balayages RAG.

### 5. Quel petit parcours mesurable prouve une autorégulation utile
- **Réponse** : Le parcours de régulation sous stress de ressource :
  `Saturation RAM/CPU détectée -> Sécrétion CORTISOL_FRUSTRATION / QUOTA -> forge_resource_manager durcit les seuils de CORTISOL_TIGHTEN_PTS -> Rejet ou déport local des jobs non critiques -> Décrue mesurée de la métrique sous le seuil -> Résorption hormonale naturelle par demi-vie`.
  Métrique de succès : zéro incident OOM et zéro arrêt brutal de service au cours du cycle de contrainte.

### 6. Quels signaux prouvent qu'une innovation simplifie réellement le corps
- **Réponse** : Trois signaux objectifs et mesurables :
  1. *Compression structurelle* : Diminution nette du nombre d'arêtes et de points de passage pour réaliser la même fonction (ex. 1 point d'entrée HTTP unique remplaçant 4 sondes redondantes).
  2. *Neutralité régressive* : Suite de tests `pytest tests/nr/` 100% verte sans modification des assertions du test.
  3. *Progrès de compression (Schmidhuber)* : Gain mesurable dans `app/forge_curiosity_driver.py:684-768` (`cp_score > 0`), attestant que l'innovation réduit l'entropie et la dispersion des états du système.
