<!-- DEPORTE depuis CLAUDE.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de CLAUDE.md, re-facture a chaque tour. -->

# 6.bis Planning Mode + <think> Gate — regle d engagement

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## 6.bis Planning Mode + <think> Gate — regle d engagement

Inspire de Devin AI (dualite PLANNING/STANDARD) + Claude Code 2.0
(TodoWrite avant action multi-etapes). S applique a TOUT client LLM qui
touche un etat persistant (commit, push, kill, restart, secret, ACL,
ingest production, suppression).

### Phase PLANNING (par defaut quand intent ambigu OU action irreversible detectee)
1. Reconnaissance : `rag_fts` sur domaine + `read_function_body` cibles
   + Grep impacts en aval.
2. Bloc `<think>` explicite : enoncer **objectif**, **hypotheses**, **risques**, **rollback**.
3. Annoncer le plan a l utilisateur (1-3 phrases max — caveman).
4. Attendre validation utilisateur SI irreversible (cf. regle "Confirmer l irreversible").

### Phase EXECUTE (autorisee apres planning OU si action trivialement reversible)
1. Tool calls (parallele si independants — regle existante).
2. Mise a jour memoire / RAG apres decision architecturale (anchor_solution).
3. Rapport terse (1-2 phrases : ce qui a change + suite).

### Mappage code
- `app/forge_handoff.py::Agent.mode` in {"PLANNING","EXECUTE"} (defaut EXECUTE).
- `Agent.plan_first()` retourne une copie immuable avec `mode="PLANNING"`.
- `_llm_round()` injecte `PLANNING_PREFIX` dans le system prompt quand
  `agent.mode == "PLANNING"` — gate `<think>` AVANT toute action.
- Tests : `tests/test_forge_handoff_planning_mode.py` (5 cas).

### Quand declencher `plan_first()`
- Avant un `make_transfer_tool(target)` qui pointe vers un agent ayant
  des outils sensibles (commit, push, restart, suppression, ACL).
- Apres detection d intent ambigu par `forge_nlu` ou triage Agent.
- Sur demande explicite utilisateur ("plan d abord", "reflechis avant").

---

