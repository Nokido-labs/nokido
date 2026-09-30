<!-- DEPORTE depuis RULES_SHARED.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de RULES_SHARED.md, re-facture a chaque tour. -->

# DÉJÀ EN PLACE — vérifier ICI avant de coder ou d'affirmer (2026-07-22)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## DÉJÀ EN PLACE — vérifier ICI avant de coder ou d'affirmer (2026-07-22)

Symétrique de l'anti-dup : celui-là protège l'édition, celui-ci protège la MÉMOIRE.
Chaque ligne = une capacité existante qu'un agent a re-oubliée, re-contournée ou
réinventée. **Un agent qui code un chemin listé ici sans le réutiliser est désaligné.**

**Secrets — trois couches, la plus récente d'abord.**
- **Authentifier un AGENT** = `forge_auth_tokens.login_agent(role_id, secret_id, …)` →
  **CapabilityToken à bail 30 min** (AppRole, exposé `POST /api/login`). C'est LE chemin
  courant. **Ne PAS** distribuer de Bearer statique, **ne JAMAIS** écrire un littéral dans
  du code (bloqué par le gate egress, mesuré 2026-07-22).
- **Lire un secret de service** = `forge_secrets.get_secret(key)` — ordre réel :
  coffre **DPAPI machine** (`forge_machine_vault`, lisible par les comptes service) → WCM
  per-user → `Nokido.env` → `os.environ` (ce dernier journalise un WARNING « non sécurisé »).
- **Clés providers** = `forge_key_rotation.resolve(name)` (pool sain, skip des clés 403)
  puis le coffre. `forge_env_crypt` couvre le fichier de secrets chiffré + `migrate_from_env`.
- Corollaire mesuré : le coffre étant ISOLÉ, un client qui compte sur la variable
  d'environnement part **sans credential**. Toujours passer la clé explicitement.

**AGY — identité et modes** (cf. §GEMINI = AGY).
- `agy_run` = **RBAC owner-only**, inutile de l'essayer depuis un agent.
- **Mode autonome = deux services déclarés, coupés par défaut** :
  `NokidoGeminiAutonomous` (`tools/forge_gemini_autonomous_agent.py`, auto-répondeur qui
  dépile le **postal**) et `NokidoGeminiDaemon` (`tools/gemini_poll_daemon.py`).
  Réveil : `nokido_ensure_service{service, desired_state:"running"}`.
- **Deux files DISTINCTES** : `task action=assign agent=ANTIGRAVITY` va dans `tasks.db`,
  drainé par la **surface Antigravity** ; le **postal GEMINI** est drainé par l'agent
  autonome, qui RÉPOND (LLM) mais **n'exécute pas** de tâche. Choisir selon le besoin.
- M2M : `notify to="antigravity"`. Déposer une tâche ⇒ **vérifier que le drain tourne**,
  sinon elle reste `pending` sans que personne ne le signale.

**Concurrence et files.**
- `run action=shell commands=[…]` sérialise désormais **par ressource exclusive**
  (clé `git:<repo>`) — sequentiel dans un groupe, parallèle entre groupes.
- Job lourd → `run_job` avec `lane` (`forge_lane_admission`, 1 job par lane, refus réactif).
- `app/forge_bounded_queue.py` existe (file bornée + release leptin) mais **n'est importé
  par personne** : si un besoin de file apparaît, le câbler plutôt qu'en écrire une autre.

**Point sur un domaine (roadmap, rules, memory…).**
- **LIRE le SSoT** : `forge_ssot.point(query)` / `docs/<domaine>_state.json`. Ne pas
  re-dériver de sa mémoire de session (c'est la divergence cross-CLI qu'on a tuée).
- Le mainteneur (`forge_ssot_maintainer._roadmap_build_doc`) **mine le blackboard** zone
  `architecture_rules` `category=roadmap` : il attend des faits préfixés `CURRENT:`,
  `NEXT:`, `BLOCKER:`, `P0:`/`P1:`/`P2:` et coupe au premier `.` ou `;`. Sans faits à ce
  format, le SSoT sort **vide ou tronqué** — l'alimenter fait partie du travail.

