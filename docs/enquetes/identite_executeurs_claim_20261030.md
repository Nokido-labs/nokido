# Enquête — Identité des exécuteurs NokidoTaskExecutor* lors du claim et classement « sujet non prouvé »

Date : 2026-10-30
Environnement : Windows 11 (PowerShell / chemins `C:\...`)

## Question fermée
Avec quel jeton et quel sujet chaque exécuteur `NokidoTaskExecutor*` (`tools/forge_task_executor.py`) se présente-t-il au hub quand il réclame une tâche, et pourquoi le contrôle de réclamation le classe-t-il « sujet non prouvé » ?

---

## Tableau Affirmation / Preuve / État

| Affirmation | Preuve (fichier:ligne + extrait court) | État |
|---|---|---|
| Chaque service `NokidoTaskExecutor*` dans `services.toml` porte l'environnement `NOKIDO_IDENTITE = "TASK_EXECUTOR"` (ou aucun pour l'instance générique). | `proxy_deno/core/services.toml:1695` (`env = { PYTHONNOUSERSITE = "1", PYTHONIOENCODING = "utf-8" }`), `1732` (`env = { ..., NOKIDO_IDENTITE = "TASK_EXECUTOR" }`), `1754`, `1778`, `1797`, `1818`, `1837`, `1855`, `1870`, `1885`, `1900`, `1915`, `1930` | PROUVÉ |
| Lors du chargement du jeton par `_load_token()`, l'exécuteur tente d'abord `_jeton_de_la_brique()` (`jeton_pour("TASK_EXECUTOR")`), puis les secrets d'environnement/coffre `FORGE_TOKEN_TASK_EXECUTOR`, puis `FORGE_MCP_TOKEN`. | `tools/forge_task_executor.py:119-129` (`def _jeton_de_la_brique(): ... return jeton_pour("TASK_EXECUTOR") or ""`), `tools/forge_task_executor.py:132-183` (`def _load_token(): ... _brique = _jeton_de_la_brique() ... _self = _gs("FORGE_TOKEN_TASK_EXECUTOR") ... tok = _gs("FORGE_MCP_TOKEN")`) | PROUVÉ |
| Lorsque l'exécuteur s'adresse au hub (`_hub_call`), il envoie dans les en-têtes HTTP `X-Agent-Name: TASK_EXECUTOR` et `Authorization: Bearer <token>`, quel que soit l'agent passé sur la ligne de commande via `--agent`. | `tools/forge_task_executor.py:186-210` (`headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "X-Agent-Name": "TASK_EXECUTOR"}`) | PROUVÉ |
| Cependant, la réclamation d'une tâche (`_reclamer`) ne passe PAS par un appel HTTP au hub ni par une introspection de jeton ; elle est exécutée localement en SQLite direct sur `tasks.db` via la fonction `_reclamer(conn, task_id, agent_tache, identite, enforce)`. | `tools/forge_task_executor.py:1035-1058` (`cur = conn.execute("UPDATE tasks SET status='running', updated_at=?, progress_at=? WHERE id=? AND status='pending' AND upper(agent)=?", ...)`), `tools/forge_task_executor.py:5667-5674`, `tools/forge_task_executor.py:5708-5714` | PROUVÉ |
| L'identité passée au contrôle de réclamation est générée en mémoire par `_identite_executeur(agent_filter)` au lancement de la boucle (`run_loop`), sans vérifier ni valider aucun jeton. | `tools/forge_task_executor.py:1004-1012` (`ident = {"sub": (agent_filter or "TASK_EXECUTOR").upper(), "act": "TASK_EXECUTOR", "prouve": False, "pourquoi": "sujet DECLARE par --agent, preuve par jeton d'instance verifie au hub non cablee"}`) | PROUVÉ |
| Le dictionnaire d'identité d'exécuteur a son booléen `prouve` codé en dur à `False` car la vérification de jeton d'instance au hub n'est pas câblée. | `tools/forge_task_executor.py:1008-1009` (`ident = {..., "prouve": False, "pourquoi": "sujet DECLARE par --agent, preuve par jeton d'instance verifie au hub non cablee"}`) | PROUVÉ |
| Le contrôle d'autorisation `_autoriser_reclamation` rejette immédiatement tout sujet dont `ident.get("prouve")` n'est pas vrai avec le motif `identite NON PROUVEE (sujet <sub or '?'}) pour une tache <ag> : UNKNOWN n'est pas OUI`. | `tools/forge_task_executor.py:1021-1032` (`if not ident.get("prouve"): return False, f"identite NON PROUVEE (sujet {sub or '?'}) pour une tache {ag} : UNKNOWN n'est pas OUI"`) | PROUVÉ |
| Côté hub (`app/forge_videur.py`), si l'exécuteur s'authentifiait au hub avec un jeton maître (`FORGE_MCP_TOKEN`), le hub marquerait également `sujet_prouve = False` et émettrait le motif « jeton maitre, sujet non prouve » car le porteur du maître n'authentifie pas le sujet déclaré en en-tête. | `app/forge_videur.py:284-287` (`elif via == "master_token" and agent not in ("MASTER", "MASTER_TOKEN"): sortie["acteur"] = "classe:porteur_maitre" ... sortie["sujet_prouve"] = False`), `app/forge_videur.py:388-389` (`elif via == "master_token": via_ev, decision, motif = "master_token", "accepte", "jeton maitre, sujet non prouve"`) | PROUVÉ |
| Le refus effectif du claim ne s'applique que si `LAFORGE_CLAIM_ENFORCE=1` ; en son absence, `_claim_enforce()` renvoie `False` et `_reclamer` passe outre le refus en consignant `[claim][observe] refuserait ...`. | `tools/forge_task_executor.py:1015-1018` (`return os.environ.get("LAFORGE_CLAIM_ENFORCE", "") == "1"`), `tools/forge_task_executor.py:1040-1044` (`if not ok: if enforce: ... return False; log.info(...)`) | PROUVÉ |
| Le contenu exact et les valeurs secrètes des jetons (`FORGE_TOKEN_*`, `FORGE_MCP_TOKEN`, DPAPI, etc.) sont protégés au coffre et hors de portée de lecture/divulgation. | `HORS_PORTEE` (valeurs des secrets au coffre non lues ni affichées) | PROUVÉ |

---

## Causes prouvées

1. **Jeton et sujet présentés au hub** :
   - Tous les services `NokidoTaskExecutor*` (que ce soit `NokidoTaskExecutorAgy`, `NokidoTaskExecutorAntigravity`, `NokidoTaskExecutorCodex`, `NokidoTaskExecutorOpencode*`, etc.) portent dans leur environnement `NOKIDO_IDENTITE = "TASK_EXECUTOR"` (`proxy_deno/core/services.toml`).
   - Quand ils effectuent des appels vers le hub (`_hub_call` dans `tools/forge_task_executor.py:186-210`), ils présentent systématiquement l'en-tête `X-Agent-Name: TASK_EXECUTOR` avec le jeton chargé pour `TASK_EXECUTOR` (jeton court de `jeton_pour("TASK_EXECUTOR")`, ou statique `FORGE_TOKEN_TASK_EXECUTOR`, ou fallback `FORGE_MCP_TOKEN`).
   - Si le jeton de repli utilisé est le jeton maître `FORGE_MCP_TOKEN`, le hub (`app/forge_videur.py:284-289`) classe systématiquement la requête comme `via="master_token"`, `acteur="classe:porteur_maitre"`, `sujet_prouve=False`, avec le motif d'audit `jeton maitre, sujet non prouve` (`app/forge_videur.py:389`).

2. **Cause du classement « sujet non prouvé » lors du claim** :
   - La réclamation d'une tâche ne passe même pas par le hub : elle s'exécute directement en local dans la base SQLite `tasks.db` (`tools/forge_task_executor.py:1049-1058`).
   - L'exécuteur évalue la réclamation via `_autoriser_reclamation(agent_tache, identite)` où `identite` provient directement de `_identite_executeur(agent_filter)` (`tools/forge_task_executor.py:1004-1012`).
   - Dans `_identite_executeur`, le sujet `sub` est positionné sur la valeur de l'argument `--agent` (ex: `ANTIGRAVITY`, `WORKER_CODE`, `CODEX`, etc., ou `TASK_EXECUTOR` par défaut), mais le champ `"prouve"` est **codé en dur à `False`** :
     `"prouve": False, "pourquoi": "sujet DECLARE par --agent, preuve par jeton d'instance verifie au hub non cablee"`.
   - Par conséquent, `_autoriser_reclamation` constate `not ident.get("prouve")` et classe **100 % des réclamations** comme non prouvées : `identite NON PROUVEE (sujet ...) pour une tache ... : UNKNOWN n'est pas OUI`.

---

## Plus petit correctif proposé (NON APPLIQUÉ)

### Fichier
`tools/forge_task_executor.py`

### Fonctions
`_identite_executeur(agent_filter: str | None)` et mécanisme de validation de jeton d'instance.

### Ce qui change
1. Au lieu d'assigner arbitrairement `"prouve": False` dans `_identite_executeur`, l'exécuteur doit obtenir et prouver son identité de service via la brique d'authentification (`forge_agent_credential.jeton_pour(sub)` ou échange RFC 8693 / validation auprès du endpoint de vérification du hub / introspection RFC 7662 avec DPoP, sans jamais recourir à `trusted_script` depuis le bac à sable).
2. Si le jeton obtenu pour l'agent cible `sub = (agent_filter or "TASK_EXECUTOR").upper()` est un CapabilityToken valide et vérifié auprès du hub attestant que le détenteur possède l'autorité pour `sub` (ou délégation autorisée avec acteur `TASK_EXECUTOR`), assigner `"prouve": True` avec la preuve associée (`token_jti` ou empreinte attestée).

### NR qui le prouverait
`tests/nr/test_task_executor_claim_identite_prouvee_nr.py` :
- Instancier un exécuteur avec `--agent <AGENT>` et un jeton d'agent valide provisionné.
- Vérifier que `_identite_executeur(agent_filter)` résout un jeton prouvé (`ident["prouve"] is True`).
- Configurer `LAFORGE_CLAIM_ENFORCE=1`.
- Réclamer une tâche assignée à `<AGENT>` via `_reclamer` et vérifier que `_reclamer` renvoie `True` (succès du claim en mode enforce), au lieu d'un refus `[claim] REFUS ... : identite NON PROUVEE`.
