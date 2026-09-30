# CLAUDE.md — Protocole de session pour LLMs travaillant sur Nokido

Point d entree obligatoire pour tout LLM (Claude, Gemini, Cline, Roo, Codex,
etc.) qui ouvre une session de travail sur Nokido. Ce fichier documente
les outils internes et les reflexes a avoir AVANT toute action.

Nokido est le cerveau central. Toute intelligence accumulee doit y revenir
sous forme d entree RAG indexee. Toute intelligence existante doit y etre
consultee avant creation.

---

## 1. Debut de session

Le hook SessionStart injecte deja les lecons recentes, les ancres RAG et la
roadmap : ne pas les relire a la main. Avant d'agir sur un domaine, suivre
l'ordre de consultation de RULES_SHARED.md (`introspect`, puis
`forge_retrieval_sweep`), lire les modules qu'il designe, et ETENDRE un module
existant plutot que d'en creer un second.

---

## 2. Carte des capacites Nokido (a connaitre par coeur) — DEPORTEE

Cette section pesait **7225 caracteres, 24% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/CLAUDE_CARTE_CAPACITES.md`](docs/CLAUDE_CARTE_CAPACITES.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- La carte qui fait AUTORITE est le census sandbox/workspace/organ_map_full.json (source versionnee par exception), PAS cette liste d une cinquantaine de modules figee au 2026-05-07 ni une vue narrative derivee.
- Avant d affirmer qu un module n existe pas ou d en creer un : introspect, puis tools/forge_retrieval_sweep.py <terme> -- il cherche les outils par leur NOM, la ou chercher le seul CONTENU echoue.

## 3. Anti-duplication checklist

AVANT de creer un fichier `app/forge_*.py`, OBLIGATOIREMENT :

1. Suivre la procedure de RULES_SHARED.md › Anti-dup prefiltrant ; etendre
   l'existant des qu'il couvre le besoin.
2. Si creation justifiee : ajouter un header `__FORGE_COLOR__` + commentaire
   expliquant pourquoi les modules existants ne conviennent PAS
3. anchor_solution() avec le raisonnement complet

Exemple vecu (2026-04-24, commit e1309ed) : forge_pii_detector.py cree
puis supprime car SemanticFirewall + SovereignMembrane + NoiseGuardian
couvraient deja tout. 9 KB et 4 heures de travail perdues.

---

## 4. Pattern d ancrage apres chaque bloc logique

```python
from forge_self_correction import anchor_solution, anchor_error

# Apres une decision / pattern valide
anchor_solution(
    problem="Description courte du probleme ou contexte",
    solution="Ce qui a ete fait et pourquoi, inclure noms de fichiers exacts",
    example="Commande ou extrait de code reutilisable",
    domain="rag",  # ou systeme, security, llm, etc.
)

# Apres une erreur / fausse piste
anchor_error(
    error_msg="Message ou nature de l erreur (courte)",
    context="Ou et comment c est arrive",
    solution="Ce qui a corrige ou la lecon a retenir",
    domain="systeme",
)
```

Les deux fonctions font automatiquement :
- INSERT dans rag_chunks avec id deterministe sha256(source+text)[:16]
- Sync dans rag_fts pour retrieval immediat via bm25()
- Append markdown dans logs/lessons_learned.md

---

## 5. Protocole cadrage des LLMs externes — DEPORTEE

Cette section pesait **2040 caracteres, 10% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/CLAUDE_CADRAGE_LLM_EXTERNES.md`](docs/CLAUDE_CADRAGE_LLM_EXTERNES.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- `pre_flight` est un garde BINAIRE et jamais un redacteur : des que le DLP mord il rend `ok=False` et un `safe_task` VIDE (mesure 2026-09-12 — une IP · un email · un chemin Windows suffisent). Suivre l'ancienne consigne envoyait donc un PROMPT VIDE au modele en silence. Le redacteur reel est `redact_text(texte)` et pour une sortie d'outil `redact_tool_output(texte · outil)`.
- Chaine complete : `fw.pre_flight(...)` puis l'appel LLM puis `fw.post_flight(reponse ...)` puis `fw.restore(reponse · mapping)`. Pour des donnees sensibles STRUCTUREES : `SovereignMembrane(mission_id=...).wrap()` avant l'envoi et `.unwrap(reponse · tool_calls=...)` au retour.

## 6. Fin de session

Le hook Stop ecrit le resume de session : ne pas le dupliquer. Verifier seulement
ce qui reste a publier : `git log --oneline origin/alpha..alpha`.

---

## 6.bis Planning Mode + <think> Gate — regle d engagement — DEPORTEE

Cette section pesait **1709 caracteres, 10% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/CLAUDE_PLANNING_MODE.md`](docs/CLAUDE_PLANNING_MODE.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- Intent ambigu ou action irreversible detectee (commit · push · kill · restart · secret · ACL · ingest production · suppression) : reconnaissance ciblee, puis annonce du plan en 1-3 phrases (objectif · risques · retour arriere), puis attente de validation si irreversible. Sinon, executer.
- Mappage code : `app/forge_handoff.py::Agent.mode` dans PLANNING ou EXECUTE (defaut EXECUTE) ; `Agent.plan_first()` rend une copie immuable en PLANNING ; `_llm_round()` injecte `PLANNING_PREFIX` dans le system prompt. Tests : `tests/test_forge_handoff_planning_mode.py`. Declencher `plan_first()` avant un transfert vers un agent porteur d'outils sensibles ou sur demande explicite de l'owner.

## 6.ter Consignes owner PERMANENTES (inscrites le 2026-08-12)

Ces six consignes ont ete prononcees puis perdues : la passe de verification
(`tools/forge_intent_verifier.py`) les a retrouvees dans le corpus de
conversations sans AUCUNE trace dans le depot. Une consigne qui n'est ecrite
nulle part n'existe pas — elle est gravee ici pour cesser de se reperdre.

1. **JAMAIS d'acces aux fonctions du BIOS depuis Windows.** Carte mere ASUS.
   Interdit permanent, sans exception ni « juste pour lire ».
2. **TOUJOURS verifier le CONTENU, pas le `rc`.** Vecu trois fois le 12/08 :
   `rc=0` alors que le gate avait ete SAUTE, `/health` repondant `ok` avec V:
   non monte, `total_inserted: 0` pris pour un succes. Un code de retour dit
   qu'un programme s'est termine, pas qu'il a fait son travail.
3. **Rien n'est supprime en base.** Marquer `[PERIME]` / `[RESOLU]` avec un
   pointeur vers ce qui remplace. Le schema `rag_chunks` porte deja
   `superseded_by` / `active` / `retraction_status` pour cela.
4. **Security by design** : verifier AVANT de concevoir, pas apres avoir code.
5. **Docker est DYNAMIQUE, pas permanent.** Il s'eteint quand personne ne le
   reclame (`docker.release`) et se REVEILLE a la demande (`sandbox/docker.wanted`,
   TTL 900 s, lu par `forge_docker_keeper`). Ne PAS desarmer la boucle
   d'extinction : le defaut a corriger est toujours un reveil trop lent, jamais
   l'extinction elle-meme. Meme patron pour `llama.wanted`, `embed.wanted`,
   `rerank.wanted`, `snn.wanted`.
6. **Anti-dup strict** : savoir si ca EXISTE avant d'en coder un (cf. section 3).
   Le 12/08, quatre « manques » etaient des modules deja livres —
   `forge_dev_mode`, `forge_vm_dns`, `forge_llm_ondemand`, `forge_access_switches`.

---

## 7. Regles d or (persistees dans rag_fts, cherchables)

1. JAMAIS de SQL LIKE primitif pour RAG - utiliser rag_fts ou RAGEngine.search
2. JAMAIS de creation de module app/forge_*.py sans query rag_fts prealable
3. JAMAIS d INSERT INTO rag_chunks sans id explicite (TEXT PRIMARY KEY)
4. JAMAIS d envoi cloud sans SemanticFirewall.pre_flight + .post_flight
5. TOUJOURS anchor_solution apres decision architecturale
6. TOUJOURS documenter les liens entre modules co-modifies
7. TOUJOURS tqdm sur toutes boucles longues dans scripts generes via task assign
8. JAMAIS nssm restart LaForgeMCP direct — LaForge-Master :8765 est
    proprietaire exclusif du hub. Crash loop = conflit port 8766. Toujours
    passer par LaForge-Master ou redemarrer les 2 ensembles.
9. Agir via le hub : outils mcp__laforge-sovereign-hub__*. Sonder le hub lui-meme :
    Bash + curl vers :8766 (un seul segment) -- jamais un `run` qui interroge :8766,
    le hub s'attendrait lui-meme.
10. Code Python de plus de quelques lignes : l'ecrire HORS du depot (C:/tmp/...),
    puis le lancer par `run` (court) ou `run_job` (long). Dans le depot, toute ecriture
    passe par `governed_edit` : Write natif y est refuse par forge_tool_gate.
11. JAMAIS d['result'] sur reponse hub — toujours .get('result') car hub
    retourne {'error': '...'} sans cle result sur exception
12. "POINT SUR <domain>" (roadmap, et futurs memory/rules/...) — LIRE le SSoT
    AVANT de repondre : `forge_ssot.point(query)` (ou `docs/<domain>_state.json`).
    Source unique STRUCTUREE (state determinist capte + roadmap) -> reponse
    UNIFORME cross-CLI. Ne PAS re-deriver de la memoire de session (= la
    divergence qu'on a tuee). Le portier (forge_knowledge_concierge.plan) route
    deja "point/statut/ou en est" -> extra['ssot_domain']. Maintainer auto =
    schtask LaForge-SSoTMaintainer (5min) + hook POST_COMMIT.

---

## 8. Stack services active (au 2026-05-07) — DEPORTEE

Cette section pesait **2273 caracteres, 10% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/CLAUDE_STACK_SERVICES_HISTORIQUE.md`](docs/CLAUDE_STACK_SERVICES_HISTORIQUE.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- La source de verite des services est proxy_deno/core/services.toml (flags enabled, hot-reload /supervisor/reload). La table deportee est datee du 2026-05-07 et etait DEJA marquee HISTORIQUE : elle ne dit plus l etat reel.
- Etat REEL d un service : hub action=whoami (services_degraded) ou le TOML. Un port qui repond ne prouve pas qu un modele est charge -- TRANSPORT n est pas CAPACITE.

## 10. Cartographie anatomique (biomimetisme structurel) — DEPORTEE

Cette section pesait **8636 caracteres, 23% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/CLAUDE_CARTOGRAPHIE_ANATOMIQUE.md`](docs/CLAUDE_CARTOGRAPHIE_ANATOMIQUE.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- La **carte organe→module** qui fait autorite n'est pas la table narrative :
  c'est le census `sandbox/workspace/organ_map_full.json`, regenere par
  `LAFORGE_PYTHON tools/forge_module_census.py`. La section deportee en donne
  la vue humaine, jamais la source.
- Tout nouveau `forge_*.py` **declare son organe** (`__FORGE_COLOR__`, dans les
  12 000 premiers caracteres, en debut de ligne) — sinon il ressort `non classe`
  et personne ne surveille sa regulation. Gate CI : `forge_module_census --check`.
- Diagnostic organe → pathologie → remede = skill `forge-anatomy` ; capacites et
  etat vivant par organe = `app/forge_organ_agents.py` (`census` / `gaps` / `probe`).

## 11. Contrainte d execution Python (LAFORGE_PYTHON) — DEPORTEE

Cette section pesait **1939 caracteres, 10% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/CLAUDE_CONTRAINTE_PYTHON.md`](docs/CLAUDE_CONTRAINTE_PYTHON.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- `LAFORGE_PYTHON = ~/miniforge3/python.exe` — JAMAIS `python` ni `python3` brut. Source de verite : `app/forge_python_bin.py::LAFORGE_PYTHON` (override par la variable `LAFORGE_PYTHON_BIN`).
- Dans le code Nokido : `from forge_python_bin import LAFORGE_PYTHON · run_python` plutot qu'un `subprocess.run(['python' ...])`. Pour pytest : `PYTHONNOUSERSITE=1` — sinon le user-site charge un `anyio` corrompu et les tests se bloquent (incident 2026-04-29). Le tool MCP `run action=python` est deja propre : il utilise l'interpreteur du hub.

## 12. Economie de tokens

Voir `docs/token_economy.md` — regles completes (Bash interdit, batch,
caveman, providers par use-case, signaux d alarme).

---

## 13. Protocole ZMQ brain_worker :5557 — DEPORTEE

Cette section pesait **2611 caracteres, 12% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/CLAUDE_PROTOCOLE_ZMQ_5557.md`](docs/CLAUDE_PROTOCOLE_ZMQ_5557.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- Le port :5557 est DISABLED depuis le 2026-06-03 (BGE-M3 ONNX bad allocation). L embedder VIVANT est :8099 NokidoLlamaEmbed, atteint par forge_embed_router (embed et embed_batch_fast) -- ne jamais rebrancher :5557 en croyant reparer.
- La section deportee est une ARCHIVE utile SI :5557 est un jour repare, pas une consigne courante. DISABLED_BY_POLICY n est pas RESOURCE_UNAVAILABLE.

## 16. CHANTIER EN COURS (Septembre 2026) : L'EPISTEMIC DRIVE — DEPORTEE

Cette section pesait **1352 caracteres, 8% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/CLAUDE_EPISTEMIC_DRIVE.md`](docs/CLAUDE_EPISTEMIC_DRIVE.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- Paradigme arrete le 2026-09-06 et a NE PAS coder sans ordre explicite — mais a integrer dans toute reflexion sur le RAG · le Swarm · l'endocrinien. Details en docs/ROADMAP.md section Px.
- Soif epistemique : le systeme detecte ce qu'il ne SAIT pas (UNKNOWN · BLIND_SPOT) et formule des questions candidates ; l'enquete n'est lancee que si le budget metabolique le permet ; une anomalie (attendu different de observe) genere un EPISTEMIC_EVENT ; le statut CONTESTED declenche la boucle et la connaissance empirique l'emporte sur la documentation statique ; la dette epistemique se resout en sommeil paradoxal (`forge_circadian.py`).

## 17. STRATÉGIE BUSINESS & BENCHMARKS (Septembre 2026) — DEPORTEE

Cette section pesait **1079 caracteres, 6% de ce fichier**, et le noyau
resident est re-envoye a CHAQUE tour. Elle vit desormais dans
[`docs/CLAUDE_STRATEGIE_BENCHMARKS.md`](docs/CLAUDE_STRATEGIE_BENCHMARKS.md) — **rien n'a ete supprime**.

Ce qui reste vrai et n'a pas besoin d'etre relu pour agir :

- Positionnement acte le 2026-09-06 : Nokido n'est pas qu'un framework — c'est un vehicule de benchmark PUBLIC pour l'orchestration multi-agent et l'Edge AI (SWE-bench · BFCL · Terminal-Bench) compare aux modeles isoles. Metriques visees : tokens · latence · cout · resilience · consommation energetique.
- Attendu cote technique : preparer un BENCHMARKS.md exhaustif · rendre la telemetrie et l'audit exportables en metriques standardisees · cadrer la prochaine phase de roadmap sur la Qualification et la Mesure. Demarchage vise : partenaires d'infrastructure en echange de credits compute ou API.

