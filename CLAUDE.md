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

Autorite : census `sandbox/workspace/organ_map_full.json`. Detail : [`docs/CLAUDE_CARTE_CAPACITES.md`](docs/CLAUDE_CARTE_CAPACITES.md). Resumes des sections DEPORTEE : [`docs/CLAUDE_RESUMES_DEPORTES.md`](docs/CLAUDE_RESUMES_DEPORTES.md).

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

`pre_flight` est un garde BINAIRE (DLP mord : `safe_task` VIDE) ; le redacteur est `redact_text` / `redact_tool_output`. Detail : [`docs/CLAUDE_CADRAGE_LLM_EXTERNES.md`](docs/CLAUDE_CADRAGE_LLM_EXTERNES.md).

## 6. Fin de session

Le hook Stop ecrit le resume de session : ne pas le dupliquer. Verifier seulement
ce qui reste a publier : `git log --oneline origin/alpha..alpha`.

---

## 6.bis Planning Mode + <think> Gate — regle d engagement — DEPORTEE

Intent ambigu ou action irreversible : reconnaissance ciblee, plan en 1-3 phrases, validation si irreversible ; sinon executer. Detail : [`docs/CLAUDE_PLANNING_MODE.md`](docs/CLAUDE_PLANNING_MODE.md).

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
6. **Anti-dup strict** : RULES_SHARED.md › Anti-dup prefiltrant.
   Le 12/08, quatre « manques » etaient des modules deja livres —
   `forge_dev_mode`, `forge_vm_dns`, `forge_llm_ondemand`, `forge_access_switches`.

---

## 7. Regles d or (persistees dans rag_fts, cherchables)

1. JAMAIS de SQL LIKE primitif pour RAG - utiliser rag_fts, ou l'outil `rag` du hub (jamais `RAGEngine` dans un script : il charge tout)
2. Anti-dup : RULES_SHARED.md › Anti-dup prefiltrant
3. JAMAIS d INSERT INTO rag_chunks sans id explicite (TEXT PRIMARY KEY)
4. JAMAIS d envoi cloud sans SemanticFirewall.pre_flight + .post_flight
5. anchor_solution apres une decision architecturale : le RAG est la memoire des autres agents
6. Documenter les liens entre modules co-modifies
7. tqdm sur les boucles longues des scripts generes via task assign
8. JAMAIS nssm restart LaForgeMCP direct — LaForge-Master :8765 est
    proprietaire exclusif du hub. Crash loop = conflit port 8766. Toujours
    passer par LaForge-Master ou redemarrer les 2 ensembles.
9. Agir via le hub : outils MCP du hub Nokido. Sonder le hub lui-meme :
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

Etat reel d un service : `proxy_deno/core/services.toml` et hub `whoami` (la table deportee est HISTORIQUE). Detail : [`docs/CLAUDE_STACK_SERVICES_HISTORIQUE.md`](docs/CLAUDE_STACK_SERVICES_HISTORIQUE.md).

## 10. Cartographie anatomique (biomimetisme structurel) — DEPORTEE

Tout nouveau `forge_*.py` declare son organe (`__FORGE_COLOR__`) ; diagnostic = skill `forge-anatomy`. Detail : [`docs/CLAUDE_CARTOGRAPHIE_ANATOMIQUE.md`](docs/CLAUDE_CARTOGRAPHIE_ANATOMIQUE.md).

## 11. Contrainte d execution Python (LAFORGE_PYTHON) — DEPORTEE

`LAFORGE_PYTHON = ~/miniforge3/python.exe`, jamais `python` brut ; pytest avec `PYTHONNOUSERSITE=1`. Detail : [`docs/CLAUDE_CONTRAINTE_PYTHON.md`](docs/CLAUDE_CONTRAINTE_PYTHON.md).

## 12. Economie de tokens

Voir `docs/token_economy.md` — regles completes (Bash interdit, batch,
caveman, providers par use-case, signaux d alarme).

---

## 13. Protocole ZMQ brain_worker :5557 — DEPORTEE

:5557 est DISABLED ; embedder vivant :8099 (`forge_embed_router`), ne pas rebrancher :5557 en croyant reparer. Archive : [`docs/CLAUDE_PROTOCOLE_ZMQ_5557.md`](docs/CLAUDE_PROTOCOLE_ZMQ_5557.md).

## 16. CHANTIER EN COURS (Septembre 2026) : L'EPISTEMIC DRIVE — DEPORTEE

Paradigme a NE PAS coder sans ordre explicite, a integrer dans toute reflexion sur le RAG, le Swarm, l'endocrinien. Detail : [`docs/CLAUDE_EPISTEMIC_DRIVE.md`](docs/CLAUDE_EPISTEMIC_DRIVE.md).

## 17. STRATÉGIE BUSINESS & BENCHMARKS (Septembre 2026) — DEPORTEE

Vehicule de benchmark PUBLIC (tokens, latence, cout, resilience, energie). Detail : [`docs/CLAUDE_STRATEGIE_BENCHMARKS.md`](docs/CLAUDE_STRATEGIE_BENCHMARKS.md).

