# Enquête et remédiation des exceptions muettes — `app/forge_mcp_registry.py`

**Date** : 2026-10-30  
**Cible** : `app/forge_mcp_registry.py`  
**Règle de conformité** : `tools/forge_git_gate.py` (lignes 280-319, détection AST des handlers muets sans trace)  
**Agent** : `agt_antigravity` (Ring 1)

---

## 1. Synthèse globale

| Métrique | Avant remédiation | Après remédiation | Variation |
|---|---|---|---|
| **Total handlers muets (`pass` / `continue` non documentés)** | **50** | **0** | **-50 (100% remédiés)** |
| **Handlers tracés (`logger.debug` avec conséquence explicite)** | 0 | 39 | +39 |
| **Handlers déclarés intentionnels (`# muet-ok : <raison>`)** | 0 | 11 | +11 |
| **Handlers non conformes au gate AST** | 50 | **0** | **0 avertissement gate** |

### Règles de remédiation appliquées :
1. **Zéro altération comportementale** : Aucun flux d'exécution modifié (aucun `return`, `raise` ou saut de boucle introduit) ; le `pass` ou `continue` d'origine est rigoureusement préservé.
2. **Format de log normalisé** :
   ```python
   logger.debug("[<composant>] <quoi> (%s) | consequence: <consequence REELLE en clair>", type(e).__name__, exc_info=True)
   ```
   - Spécifieur `%s` obligatoirement lié à `type(e).__name__` (ou nom d'exception local sans collision de scope).
   - `exc_info=True` systématique pour traçabilité complète du diagnostic.
   - Aucun caractère d'ellipse `...` dans la conséquence : impact explicite sur le système documenté pour chaque site.
3. **Sites intentionnellement silencieux (`# muet-ok`)** :
   - Strictement réservés aux nettoyages `best-effort` de fichiers/dossiers temporaires (en bloc `finally` ou post-opération), aux balayages de flux (lignes non-JSON ripgrep, fichiers non décodables) ou aux modules optionnels absents (`ImportError` fail-open).
   - Commentaire explicite `# muet-ok : <raison précise>` positionné sur la ligne du handler ou de son corps.
4. **Préservation des scopes imbriqués** :
   - Utilisation de `e_pub` ou `e_log` pour éviter le masquage ou la suppression (`del e`) de variables d'exceptions englobantes réutilisées en aval (`return str(e)`).

---

## 2. Inventaire exhaustif des 50 sites remédiés

| # | Ligne initiale | Ligne finale | Décision | Justification & Message / Raison |
|---|---|---|---|---|
| 1 | 451 | 451 | `log` | `logger.debug("[profiler] enregistrement metriques impossible (%s) \| consequence: metriques d'execution perdues pour cet appel", type(e).__name__, exc_info=True)` |
| 2 | 468 | 469 | `log` | `logger.debug("[registry] resolution base repli data impossible (%s) \| consequence: conservation du chemin embeddings.db par defaut", type(e).__name__, exc_info=True)` |
| 3 | 928 | 930 | `log` | `logger.debug("[intention_gate] evaluation intention impossible (%s) \| consequence: appel autorise en fail-open sans validation de scope", type(e).__name__, exc_info=True)` |
| 4 | 947 | 950 | `log` | `logger.debug("[recon_breaker] ecriture log C:/tmp/recon_breaker.log impossible (%s) \| consequence: trace locale de reconnaissance non persistee", type(e).__name__, exc_info=True)` |
| 5 | 956 | 960 | `log` | `logger.debug("[recon_breaker] ecriture erreur breaker dans log impossible (%s) \| consequence: diagnostic d'echec breaker non persiste sur disque", type(e_log).__name__, exc_info=True)` |
| 6 | 1048 | 1053 | `log` | `logger.debug("[rag_hint] recherche lecon RAG impossible (%s) \| consequence: indice contextuel non injecte pour cet outil", type(e).__name__, exc_info=True)` |
| 7 | 1122 | 1128 | `muet-ok` | `# muet-ok : forge_access_switches optionnel ou absent, fail-open voulu` |
| 8 | 1223 | 1229 | `log` | `logger.debug("[m2m_envelope] recuperation enveloppe impossible (%s) \| consequence: messages en attente non ajoutes au resultat", type(e).__name__, exc_info=True)` |
| 9 | 1280 | 1287 | `log` | `logger.debug("[event_bus] publication violation secret impossible (%s) \| consequence: audit bus non emis pour cette violation", type(e_pub).__name__, exc_info=True)` |
| 10 | 1297 | 1305 | `log` | `logger.debug("[event_bus] publication erreur handler impossible (%s) \| consequence: audit bus non emis pour l'echec de cet outil", type(e_pub).__name__, exc_info=True)` |
| 11 | 1531 | 1540 | `muet-ok` | `# muet-ok : ligne ripgrep non-JSON ignoree dans le flux` |
| 12 | 1547 | 1556 | `muet-ok` | `# muet-ok : fichier illisible ignore lors du balayage de repli regex` |
| 13 | 1787 | 1796 | `log` | `logger.debug("[compact_agents] lecture tools_compact.txt impossible (%s) \| consequence: liste des agents compacts restreinte a la variable d'environnement", type(e).__name__, exc_info=True)` |
| 14 | 3014 | 3024 | `log` | `logger.debug("[netcfg_proxy] lecture token dans Nokido.env impossible (%s) \| consequence: requete proxy netcfg envoyee sans authentification bearer", type(e).__name__, exc_info=True)` |
| 15 | 3196 | 3207 | `log` | `logger.debug("[docker_tools] parsing definition outil docker impossible (%s) \| consequence: outil docker ignore de la liste exposee", type(e).__name__, exc_info=True)` |
| 16 | 3442 | 3454 | `muet-ok` | `# muet-ok : suppression du fichier temporaire best-effort en cas d'erreur d'ecriture` |
| 17 | 3524 | 3536 | `muet-ok` | `# muet-ok : suppression du fichier temporaire best-effort en cas d'erreur d'ecriture` |
| 18 | 3577 | 3589 | `muet-ok` | `# muet-ok : fichier journal disparu ou inaccessible pendant le listage` |
| 19 | 4102 | 4114 | `muet-ok` | `# muet-ok : suppression du script temporaire en best-effort dans finally` |
| 20 | 4167 | 4179 | `muet-ok` | `# muet-ok : suppression du script temporaire oracle en best-effort` |
| 21 | 4176 | 4188 | `log` | `logger.debug("[oracle] publication evenement ORACLE_INVOKED impossible (%s) \| consequence: invocation oracle non tracee sur le bus swarm", type(e).__name__, exc_info=True)` |
| 22 | 4312 | 4325 | `log` | `logger.debug("[intention_journal] enregistrement intention run impossible (%s) \| consequence: intention d'execution non consignee dans le journal d'audit", type(e).__name__, exc_info=True)` |
| 23 | 4419 | 4433 | `log` | `logger.debug("[job_runner] notification fin de job dans INBOX impossible (%s) \| consequence: agent destinataire non notifie de la fin d'execution du job", type(e).__name__, exc_info=True)` |
| 24 | 4458 | 4473 | `muet-ok` | `# muet-ok : suppression du code_file temporaire en best-effort apres lecture` |
| 25 | 5019 | 5034 | `log` | `logger.debug("[videur] resolution dynamique des boites aux lettres impossible (%s) \| consequence: repli sur la table des destinataires statiques", type(e).__name__, exc_info=True)` |
| 26 | 5132 | 5148 | `log` | `logger.debug("[videur] enrichissement regex agents impossible (%s) \| consequence: routage base uniquement sur la liste d'agents par defaut", type(e).__name__, exc_info=True)` |
| 27 | 5383 | 5400 | `log` | `logger.debug("[token_meter] calcul consommation tokens impossible (%s) \| consequence: metriques de consommation absentes du rapport whoami", type(e).__name__, exc_info=True)` |
| 28 | 5611 | 5629 | `log` | `logger.debug("[postal] releve courrier secretaire impossible (%s) \| consequence: messages en attente non recuperes pour le prompt systeme", type(e).__name__, exc_info=True)` |
| 29 | 6077 | 6096 | `log` | `logger.debug("[task_assign] lecture fichier contexte impossible (%s) \| consequence: contenu du fichier contexte non transmis a l'assignataire", type(e).__name__, exc_info=True)` |
| 30 | 6242 | 6262 | `log` | `logger.debug("[m2m_protocol] validation protocole M2M impossible (%s) \| consequence: resultat de sous-tache accepte sans conformite structurelle", type(e).__name__, exc_info=True)` |
| 31 | 6275 | 6296 | `log` | `logger.debug("[quality_gate] verification qualite du resultat impossible (%s) \| consequence: validation automatique de la tache sans controle qualite", type(e).__name__, exc_info=True)` |
| 32 | 6321 | 6343 | `log` | `logger.debug("[dep_manager] verification des dependances impossible (%s) \| consequence: passage a l'etape suivante sans validation des prerequis", type(e).__name__, exc_info=True)` |
| 33 | 6453 | 6476 | `log` | `logger.debug("[rag] indexation du resultat de tache dans rag_chunks impossible (%s) \| consequence: livrable de tache non memorise dans le RAG", type(e).__name__, exc_info=True)` |
| 34 | 7000 | 7024 | `log` | `logger.debug("[clarification] analyse de clarification impossible (%s) \| consequence: transmission du message sans enrichissement de contexte", type(e).__name__, exc_info=True)` |
| 35 | 7141 | 7166 | `muet-ok` | `# muet-ok : valeur de quota non convertible ou absente laissee telle quelle` |
| 36 | 7257 | 7282 | `log` | `logger.debug("[audit_db] audit acces base RAG impossible (%s) \| consequence: acces a embeddings.db non trace dans le journal d'audit", type(e).__name__, exc_info=True)` |
| 37 | 7499 | 7525 | `log` | `logger.debug("[rag_bm25] incrementation access_count impossible (%s) \| consequence: statistiques de popularite de chunk non mises a jour", type(e).__name__, exc_info=True)` |
| 38 | 7778 | 7805 | `log` | `logger.debug("[rag_cache] decodage vecteur json impossible (%s) \| consequence: chunk omis du cache de similarite vectorielle", type(e).__name__, exc_info=True)` |
| 39 | 8130 | 8158 | `log` | `logger.debug("[rag_dense] recuperation candidats bm25 impossible (%s) \| consequence: recherche dense executee sans fusion hybride", type(e).__name__, exc_info=True)` |
| 40 | 8205 | 8234 | `log` | `logger.debug("[rag_dense] reranking cross-encoder impossible (%s) \| consequence: ordre des chunks base uniquement sur le score bi-encoder", type(e).__name__, exc_info=True)` |
| 41 | 8405 | 8435 | `log` | `logger.debug("[console_exec] ecriture audit console_exec_audit.jsonl impossible (%s) \| consequence: commande console non historisee dans le journal", type(e).__name__, exc_info=True)` |
| 42 | 8442 | 8473 | `log` | `logger.debug("[secret_guard] import sanitize_shell_command impossible (%s) \| consequence: assainissement de commande ignore avant execution console", type(e).__name__, exc_info=True)` |
| 43 | 8767 | 8799 | `muet-ok` | `# muet-ok : suppression du dossier temporaire de sandbox en best-effort dans finally` |
| 44 | 8901 | 8933 | `log` | `logger.debug("[cognitive_router] estimation complexite ou selection modele impossible (%s) \| consequence: metadonnees cognitives non injectees dans le payload", type(e).__name__, exc_info=True)` |
| 45 | 9287 | 9320 | `log` | `logger.debug("[skill] lecture des competences en base impossible (%s) \| consequence: bascule sur le dossier local de competences", type(e).__name__, exc_info=True)` |
| 46 | 9310 | 9344 | `log` | `logger.debug("[skill] lecture du contenu de la competence en base impossible (%s) \| consequence: contenu de competence non charge", type(e).__name__, exc_info=True)` |
| 47 | 9570 | 9605 | `log` | `logger.debug("[loop_orchestrate] insertion etat boucle impossible (%s) \| consequence: etat de boucle de tache non persiste en base", type(e).__name__, exc_info=True)` |
| 48 | 9600 | 9636 | `log` | `logger.debug("[loop_orchestrate] mise a jour resultat boucle impossible (%s) \| consequence: statut final de la boucle non mis a jour en base", type(e).__name__, exc_info=True)` |
| 49 | 9976 | 10013 | `log` | `logger.debug("[markdown_parser] decodage arguments json impossible (%s) \| consequence: arguments conserves sous forme de chaine brute", type(e).__name__, exc_info=True)` |
| 50 | 10001 | 10039 | `log` | `logger.debug("[registry_boot] prechauffage cache dense impossible (%s) \| consequence: cache a froid au premier appel de recherche", type(e).__name__, exc_info=True)` |

---

## 3. Validation et conformité Gate

- **Contrôle AST (`verifier_except_muets`)** : Exécuté via AST parsing (`ast.walk`), validant 0 handler muet résiduel sur l'intégralité du fichier.
- **Vérification de syntaxe** : Le module `app/forge_mcp_registry.py` se compile et parse sans aucune erreur syntaxique.
- **Intégrité fonctionnelle** : Tous les tests existants et comportements nominaux sont préservés à l'identique.
