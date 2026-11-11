# Relecture croisée des rendus A2A et tests_verts (07/11/2026)

## 1. Rendu 1 : Façade A2A (`tools/forge_a2a_server.py` & `tests/nr/test_a2a_tier1_nr.py`)
- **Identité et Slot** : `admission()` délègue à `_verificateur()` (`verifier_slot`), ignore `X-Agent-Name`, refuse `FORGE_MCP_TOKEN`/`FORGE_A2A_TOKEN`. Fail-closed effectif sur exception ou slot manquant.
- **Cloisonnement & Fuites** : Clé interne `(agent, tid)`. `_introuvable` uniformisé (-32001). `_vue()` n'expose que la liste blanche `id`, `contextId`, `status{state, timestamp}`, `metadata{attempt, cause_echec, empreinte}`.
- **Intégrité taskId & Annulation** : `taskId` inconnu rejeté (-32001). Tâche terminale protégée contre reprise (-32602). Registre `MAX_TACHES` n'évince que les terminales. Annulation idempotente et effective.
- **NR** : Ancien `or True` retiré, test du streaming basé sur la réponse RPC. Contrat d'identité déclarative renforcé, `disabled = true` préservé.

## 2. Rendu 2 : Juge `tests_verts` (`tools/forge_task_executor.py` & NR)
- **Origine du verdict** : Rejeu réel subprocess pytest avec parsing JUnit XML strict.
- **Liste blanche & 4 issues** :
  - `VERT` uniquement si `ko == 0`, `tot - ign > 0`, `rc == 0` et JUnit valide.
  - `ROUGE` si `ko > 0`.
  - `ILLISIBLE` si 0 test exécuté, XML manquant/corrompu, rc != 0 avec 0 échec JUnit, timeout, test hors worktree/absent, ou contrat sans test.
- **Garde RAM & Confinement** : Confinement worktree vérifié via `relative_to`, interruption sur palier RAM critique/détresse.
- **Traitement ILLISIBLE** : `_MARQUE_ILLISIBLE` force l'échec sans tomber côté vert ni dans les motifs vides/réussis.

RAS sur les deux rendus : architecture robuste, conforme aux exigences et fail-closed.
