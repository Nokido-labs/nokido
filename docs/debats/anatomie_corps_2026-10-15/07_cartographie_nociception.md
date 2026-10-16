# 07 — Cartographie de la nociception (préalable à la preuve A)

Décision owner du 15/10 : la première boucle à prouver est la **boucle nociceptive et métabolique** ; contrainte de
Codex (`06`) : aucun nouvel organe avant la carte des lecteurs, écrivains et boucles. Cette carte est mesurée par
`git grep` sur `app/`, `tools/`, `proxy_deno/`, `config/` le 15/10 au soir (CLAUDE). **Non vu** : lanceurs et tâches
planifiées hors dépôt.

## Écrivains — qui émet un refus
- **64 fichiers** portent un signal de refus, avec un vocabulaire hétérogène : `GATE_DENIED`, `M2M_REFUSED`,
  `ERR_RBAC_DENY`, `BUDGET_EXCEEDED`, `RATE_LIMIT`, `QUOTA_*`, `ERR_TIMEOUT`… Les plus denses : `forge_quota_manager`
  (8), `forge_endocrine` (7), `forge_task_executor` (7), `forge_econome`, `forge_trust_domains`,
  `forge_quota_alert_daemon` (5 chacun).
- Le refus le plus fréquent, celui du hub, est une **chaîne libre** : `return f"GATE_DENIED: {_v.deny_reason()}"`
  (`tools/nokido_hub.py:1423`). Il voyage dans un `result` JSON-RPC **réussi** (`forge_veille_gap_recover.py:148`).
- Le vocabulaire typé existe déjà sans être employé ici : intents d'erreur M2M (`config/m2m_intents.json` :
  `ERR_RBAC_DENY`, `ERR_TIMEOUT`, `BUDGET_EXCEEDED`, `NEED_HUMAN_APPROVAL`…).

## Lecteurs — qui le reçoit
Au moins **12 récepteurs** détectent le refus du hub **par sous-chaîne**, chacun avec sa liste maison :
`forge_rag_via_hub._MARQUES_REFUS`, `forge_supervisor_ctl._REFUS_HUB`, `forge_coagulation`, `forge_organ_pulse`,
`forge_rescue`, `forge_task_executor` (l. 1351), `forge_veille_gap_recover`, `forge_rss_watcher`, `forge_install_acceptance`,
`nokido_launcher`, `nokido_tray`, `forge_autonomous_loops` (l. 2636). Chaque nouveau récepteur réinvente la
détection ; un refus dont le texte change devient un succès silencieux.

## Boucles — ce qui existe déjà
- **Canal algédonique S3→S5** (niveau SYSTÈME) : `forge_homeostasis_orchestrator._algedonic_signals` →
  `forge_viable_system.algedonic_to_police` → `forge_critical_events` / videur ; plafond de tirs par fenêtre
  (`forge_epistemic_daemon._tir_algedonique_autorise`, `sandbox/algedonique_tirs.json`). Il traite la santé des
  services, **pas** les refus par appel.
- **Aucune boucle** ne compte les refus répétés d'un même couple (barrière, agent) : `forge_rss_watcher` recevait
  `GATE_DENIED` **à chaque cycle depuis le 07/10** (« 0 chunks ingérés », constaté dans son propre commentaire).
- **Aucune mesure** « refus suivi d'un repli réussi ».

## Extension proposée (sans nouvel organe)
1. **Signal typé à la source** : le hub rend ses refus dans une enveloppe stable (`intent` M2M d'erreur existant,
   `barriere`, `motif`, `repli_suggere`) au lieu d'une chaîne libre ; la chaîne actuelle reste en tête pour les
   12 récepteurs (compatibilité), qui migrent un par un vers un seul détecteur partagé.
2. **Compteur par (barrière, agent) sur fenêtre** (débit par comptage, jamais moyenne all-time — règle du 30/07).
3. **Raccord au canal algédonique existant** : un `refus_recurrent` lu par `_algedonic_signals`, sous le même
   plafond par fenêtre.
4. **Métrique de la preuve A** : refus suivis d'un repli réussi / refus, par barrière.
