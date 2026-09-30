---
name: forge-workflow-autopsy
description: Diagnostic des workflows/pipelines AUTONOMES stalles ou morts dans Nokido (daemons, veille, workers, chaines producteur->consommateur). Declencher quand un job est "completed" mais rien ne se passe en aval, des entrees sont coincees a un statut (unverified/queued/pending/reviewed), un backlog gonfle, un daemon ne tourne plus (heartbeat fige), une capacite "qui marchait avant" ne marche plus, "c'est casse mais les tests passent", une etape autonome n'a aucun effet observable, ou l'utilisateur dit "verifie le workflow autonome / la veille / le worker / le pipeline tourne vraiment ?". Specialise forge-systematic-debugging pour les PIPELINES : verifie consumer-vivant, vocab producteur/consommateur, backlog, dependance, angle-mort du health-check.
---

# forge-workflow-autopsy - autopsie d'un workflow autonome stalle

Un pipeline autonome peut etre "vert" (jobs `completed`) tout en etant **mort en aval** : le producteur ecrit, le consommateur ne consomme pas. Deux incidents Nokido ont prouve le pattern (biblio + KEYSTONE Ph2). Checklist d'autopsie, dans l'ordre.

## 1. Le CONSUMER est-il vivant ?
Le producteur tourne, le consommateur est mort -> backlog silencieux.
- Heartbeat frais ? `sandbox/<worker>.heartbeat` (age en secondes ; fige = mort).
- PID present ? Service declare dans `proxy_deno/core/services.toml` ? (sinon rien ne le maintient -> il re-meurt au prochain restart).
- **Incident:** le biblio worker etait mort depuis 2026-05-03 (~53 jours) -> 583 entrees stranded, jamais drainees.

## 2. VOCAB producteur <-> consommateur aligne ? (le piege #1, recurrent)
Le producteur ECRIT un statut/type, le consommateur en ATTEND un autre -> intersection vide -> stall total et silencieux.
- Comparer exactement : quel `status`/`type`/`task_type` le producteur ecrit, vs ce que le consommateur LIT/poll (`WHERE status=...`).
- **Incidents:** biblio -> `forge_biblio_core` insere `status='unverified'`, le worker poll `status='queued'` -> jamais vu. KEYSTONE Ph2 -> `best()` vocab (`code/veille/lint`) != ROUTING (`security_audit/architecture/critical_code`) -> degenere.
- Fix minimal : aligner (consommateur lit les DEUX vocab, OU producteur ecrit le bon).

## 3. BACKLOG ? Distribution par statut.
`SELECT status, COUNT(*) FROM <table> GROUP BY status` -> des entrees qui s'empilent a UN stade = le drain de ce stade est casse. Regarder la DATE du plus vieux coince = quand ca a casse (souvent correle a un commit/rename de vocab).

## 4. La DEPENDANCE est-elle UP ?
Le consommateur depend souvent d'un service externe (SearXNG/Docker/Ollama/embed/llamacpp) -> s'il est down, le consommateur echoue silencieusement (retry/error, pas de progres). `nokido_ensure_service{service, desired_state=running}` verifie + releve.

## 5. Le HEALTH-CHECK voit-il le probleme ? (angle-mort)
Si le detecteur de sante verifie le MAUVAIS statut (ex: alerte sur `queued>50` alors que le backlog est en `unverified`), il est aveugle -> personne n'alerte, le probleme dort. Etendre le check au vrai statut.

## Remedes (non-destructif, dans cet ordre)
1. **Aligner le vocab** (le moins de churn ; cause racine la plus frequente).
2. **Revive le consommateur** + le cabler en **service permanent** (`services.toml`) pour qu'il ne re-meure pas silencieusement.
3. **Drainer le backlog** (re-process via le consommateur repare ; statut->statut, jamais supprimer).
4. **Tuer l'angle-mort** du health-check (qu'il voie le vrai statut).

Reference : memoire `keystone_ph2_vocab_mismatch_2026-06-24` + fix biblio commits `a1049136` (vocab) / `11b2661f` (service permanent). Jumeau de `forge-systematic-debugging` (methode generale 4-phases) ; ce skill = la grille SPECIFIQUE aux pipelines autonomes (producteur/consommateur/daemon).
