# Audit des prompts — Claude Code CLI 2.1.299 → 2.1.310

Date : 2026-10-27  
Portée : audit en lecture seule des consignes et textes persistants demandés. Aucun fichier source n’a été modifié. Les diffs ci-dessous sont des propositions.

## Résultat du changelog

**Changements INCONNUS, page à ré-ingérer.** La recherche demandée sur `rag_fts` pour la source `claude_code_docs:code.claude.com/docs/en/changelog.md` et les versions 2.1.300–2.1.310 n’a pas fourni de résultat exploitable dans le délai du hub (recherche interrompue après plus de deux minutes). L’outil MCP `rag` disponible n’expose qu’une recherche sémantique `topic`, pas un paramètre `MATCH`; je n’ai donc ni exécuté un `LIKE`, ni parcouru `rag_chunks`, ni assimilé l’absence de résultat à « aucun changement ». L’impact spécifique du changement CLI sur les prompts reste **UNKNOWN** jusqu’à ré-ingestion et recherche de la plage.

## Méthode et limites

Lecture via le hub des consignes et fichiers demandés, avec relevé des lignes. Les chemins `CLAUDE.md` racine, `Nokido/CLAUDE.md`, `Nokido/RULES_SHARED.md`, les hooks, le catalogue MCP et la mémoire locale ont été contrôlés. Le rapport ne propose aucun changement de comportement avant vérification du changelog. Les gains sont des ordres de grandeur de caractères sérialisés évitables par tour, hors coût variable des outils et sans prétendre mesurer les tokens du tokenizer.

## Constats et diffs proposés

### 1. Versionnement CLI non vérifié — À DISCUTER

**Constat.** La source de changelog demandée n’a pas livré la plage 2.1.300–2.1.310 (résultat indisponible, non preuve d’absence). Aucune adaptation spécifique à un changement de CLI ne peut être justifiée pour l’instant.

**Gain estimé :** 0 caractère/tour déterminable.  
**Diff proposé :** aucun changement de prompt à ce stade. Ré-ingérer `code.claude.com/docs/en/changelog.md`, puis rechercher précisément les versions 2.1.300 à 2.1.310 avec `rag_fts MATCH` avant de réviser ce point.

### 2. Règles de workflow répétées entre CLAUDE.md racine et CLAUDE.md Nokido — SÛR

**Constat.** Le fichier racine délègue déjà au socle partagé (`CLAUDE.md` racine, lignes 13–24), mais réénonce ensuite des règles de consultation, de lecture, de hooks et d’économie des tokens (`CLAUDE.md` racine, lignes 39–57). `Nokido/CLAUDE.md` renvoie à plusieurs reprises à `RULES_SHARED.md`; les rappels « resident est re-envoyé à CHAQUE tour » apparaissent en lignes 26, 82, 100, 170, 181, 199, 217, 228 et 239. Le socle explique déjà le coût de réinjection et les workflows communs (`Nokido/RULES_SHARED.md`, lignes 171–175, 206–229). Cela augmente le texte système sans apporter un nouvel invariant à chaque occurrence.

**Gain estimé :** environ 1 000–1 800 caractères/tour en supprimant les redites identifiées, sans supprimer les règles propres à Claude ni les références vers les documents détaillés.

**Diff proposé :** dans `Nokido/CLAUDE.md`, remplacer les répétitions du rappel sur le noyau résident par une seule note introductive en tête de section; dans `CLAUDE.md` racine, conserver le renvoi au socle et ne garder que les écarts Claude réellement spécifiques (commandes/hooks). Ne pas supprimer les listes de capacités déportées ni leurs liens SSoT.

### 3. Cohérence des règles sur les sous-agents — À DISCUTER

**Constat.** `Nokido/RULES_SHARED.md`, lignes 206–220, formule l’interdiction des sous-agents Claude comme règle générale, puis inclut des formulations plus récentes permettant des sous-agents sur des modèles gratuits « dès que c’est possible ». `Nokido/tools/forge_tool_gate.py`, lignes 301–303 et 419–441, décrit une exception d’essai Claude conditionnée à un interrupteur local et garde l’ancienne règle comme défaut. La mémoire locale porte une décision owner du 27/10 : essai clos après deux appels, aucun Agent Claude même interrupteur armé (mémoire `~/.claude/projects/C--Users-user-Script-python-IA/memory/MEMORY.md`, ligne 1). Cette décision locale récente est plus stricte que le texte versionné et peut ne pas être chargée de façon durable par les autres surfaces.

**Gain estimé :** 0–250 caractères/tour; bénéfice principal = retirer une ambiguïté de décision, pas réduire beaucoup de texte.

**Diff proposé :** après confirmation/émission de la décision owner vers la source versionnée, remplacer les exceptions ambiguës par une règle datée et unique qui distingue explicitement Agent Claude, sous-agents gratuits d’autres fournisseurs et jobs locaux `run_job`. Conserver la mémoire locale comme index bref vers la règle versionnée, plutôt que comme seule autorité.

### 4. Règle « tout texte visible en français » absente des instructions versionnées — SÛR

**Constat.** La mémoire Claude contient la consigne explicite de l’owner : tout texte visible (messages, questions, résumés), même injecté par un hook, doit être en français (`MEMORY.md`, ligne 31). Cette formulation n’apparaît pas dans les passages correspondants des deux CLAUDE.md ni du socle commun consultés. La règle existe donc dans la mémoire locale, mais n’est pas garantie par les consignes versionnées. Les chaînes de code/commentaires en anglais ne sont pas automatiquement du texte visible; seuls les `additionalContext` et textes affichés à l’owner sont concernés.

**Gain estimé :** 0 caractère net si une ligne est ajoutée; effet attendu = réduire les sorties anglaises et les rappels correctifs, non réduire le prompt.

**Diff proposé :** ajouter une règle d’une ligne dans le point d’entrée versionné partagé (ou la référence de politique commune) : « Tout texte présenté à l’owner, y compris les questions, notifications et résumés injectés par un hook, est rédigé en français. » Ajouter aux hooks concernés une vérification ciblée des chaînes d’interface; ne pas traduire les identifiants, commandes ou contenus cités nécessaires.

### 5. Rappels de hook à chaque tour et politique durable — À DISCUTER

**Constat.** Le gate Claude ajoute du contexte non bloquant à certains appels via `additionalContext` (`Nokido/tools/forge_tool_gate.py`, lignes 479–480, 657–669). Le code mentionne aussi le filtrage de rappels par session (`forge_tool_gate.py`, lignes 678–686), signe que certains rappels répétés sont déjà filtrables. Le rappel « le hook ne consomme pas de tokens » et l’instruction de ne pas refaire son travail sont dans `CLAUDE.md` racine, lignes 52–55, tandis que les comportements concrets sont gérés par les hooks. Les consignes identifient également le hook SessionStart comme injecteur de leçons/ancres/roadmap (`Nokido/CLAUDE.md`, ligne 15).

**Gain estimé :** 100–500 caractères/tour selon fréquence d’injection et longueur du rappel; non mesuré en trace d’exécution dans cet audit.

**Diff proposé :** pour chaque `additionalContext` récurrent, vérifier si sa règle peut être émise une fois en SessionStart et supprimer les nudges répétitifs non bloquants ou les filtrer par session. Garder les refus de sécurité et les instructions d’action contextuelles au moment où elles s’appliquent. Ne pas convertir une garde effective en simple rappel.

### 6. Taille de la mémoire locale au-dessus du seuil — À DISCUTER

**Constat.** `~/.claude/projects/C--Users-user-Script-python-IA/memory/MEMORY.md` mesure 17 268 octets, soit 268 octets au-dessus d’un seuil de 17 000 octets (≈16,9 Kio). Son contenu est un index de liens, avec notamment les règles de français et de sous-agents (`MEMORY.md`, lignes 1 et 31). L’audit confirme le dépassement numérique, sans mesurer ici le nombre réel de tokens facturés ni l’ordre de chargement des cartes liées.

**Gain estimé :** jusqu’à 268 octets/tour si le fichier entier est injecté; taille réellement chargée par tour **UNKNOWN**.

**Diff proposé :** compacter les entrées redondantes ou anciennes en conservant leurs références de détail, puis mesurer la taille réellement injectée au démarrage et par tour. Ne pas supprimer les décisions récentes ou déplacer la règle de langue sans d’abord l’ancrer dans une source versionnée.

### 7. Descriptions du catalogue MCP — SÛR (constat, pas une demande de traduction exhaustive)

**Constat.** Le registre `Nokido/app/forge_mcp_registry.py` est volumineux et construit les schémas/descriptions d’outils; les déclarations sont dispersées dans le fichier (plusieurs milliers de lignes, descriptions générées selon les outils). L’outil MCP exposé à cet audit fournit lui-même des descriptions d’outils Nokido rédigées en français. La recherche a repéré des descriptions/fallbacks générés, mais pas de preuve suffisante pour attribuer tout texte anglais du registre à une description présentée à l’owner : certaines chaînes sont des valeurs techniques, exemples ou descriptions de connecteurs.

**Gain estimé :** non quantifiable sans comparer les descriptions effectivement publiées par `tools/list` avec leur exposition à Claude; aucun nombre avancé.

**Diff proposé :** extraire à l’exécution le seul ensemble de descriptions réellement exposé au client Claude et classifier les textes visibles. Traduire les descriptions d’usage destinées à l’owner en français, garder les noms de champs, exemples de code et termes API inchangés. Ne pas modifier le registre sur la base d’une simple recherche lexicale.

## Ordre recommandé

1. Ré-ingérer le changelog et auditer les versions 2.1.300–2.1.310 avant toute conclusion de compatibilité CLI.
2. Aligner la règle des sous-agents avec la décision owner du 27/10 et la versionner.
3. Ajouter la règle de langue à la source persistante commune; contrôler les injections visibles des hooks.
4. Réduire les répétitions CLAUDE.md et mesurer le contexte réellement injecté, puis compacter la mémoire locale si le fichier entier est chargé.
5. Auditer les descriptions MCP à partir de la liste réellement publiée plutôt qu’à partir de chaînes isolées du registre.

## Périmètre des modifications

Ce document est le seul livrable créé. Aucun code, prompt source, hook, mémoire locale, base RAG ou configuration n’a été modifié. Le rapport est proposé pour commit par l’exécuteur; aucun `git add` ni `git commit` n’a été exécuté ici.
