# forge-m2m-agy — annexe : surfaces détaillées, courrier, modèles, pièges payés

Lue à la demande (`read` du hub), depuis toute surface. Union, le 5/11, des trois copies de la skill, qui avaient divergé :
chacune portait des pièges absents des autres.

## Carte détaillée des surfaces

| surface | ce qu'elle fait | ce qu'elle draine |
|---|---|---|
| `NokidoTaskExecutorAntigravity` | lance `agy` en mode agent (`--sandbox --mode accept-edits`, runAs interactive) dans le worktree `nokido_worktrees/antigravity` (branche `agent/antigravity`). **La seule surface qui EXÉCUTE.** | `tasks.db`, agent=ANTIGRAVITY |
| `NokidoGeminiAutonomous` (`forge_gemini_autonomous_agent`) | répondeur postal. Conversation → répond en texte. Travail (`HANDOFF_NEXT` ou champ `artefact_attendu`) → dépose une tâche ANTIGRAVITY en tant que GEMINI, répond le n° de tâche, relaie le résultat (`relayer_resultats`, suivi `sandbox/gemini_auto_taches.json`, abandon DIT à 24 h). | postal GEMINI |
| session AGY interactive de l'owner | lit la boîte et **acquitte à la lecture, sans `claimed_by`** : second consommateur | boîte ANTIGRAVITY |
| `NokidoGeminiDaemon` | déclaré, coupé par défaut | — |
| outil MCP `agy_run` | RBAC owner-only | — |
| provider `gemini_cli` | `agy.exe` sur l'abonnement owner : `ask(provider="gemini_cli")` rend un TEXTE, pas un agent | — |

## Modèles

Modèle d'AGY CLI = celui choisi par l'owner avec `/model` (14/10 et 30/10 : Gemini 3.8 Flash High).
30/10 : Antigravity CLI 1.4.11, abonnement Google AI Pro ; `agy models` : gemini-4-argon-{low,medium,high},
gemini-3.8-flash-{low,medium,high}, claude-opus-5-5-*, claude-sonnet-5-5-*, gpt-oss-120b-medium ; `--effort`
low|medium|high|xhigh|max. L'exécuteur POSE désormais `--model` et `--effort` par taille (table
`forge_palier_effort`, 48f4d6274) : le `/model` de l'owner ne s'applique plus aux tâches déléguées.
Les modèles forts du web (argon) ne sont pas disponibles dans le CLI.

## Écrire à AGY par courrier

Courrier à GEMINI :
`{"intent":"HANDOFF_NEXT","pointer_ref":"<ssot>","confidence":1.0,"artefact_attendu":"<chemin>"}`.
Le répondeur le transforme en tâche, même si la session interactive est ouverte (seule
la conversation est alors différée). Sans `HANDOFF_NEXT` ni `artefact_attendu`, c'est une
conversation : réponse en texte, rien d'exécuté.

- Accusé : `track(mail_id)['accuse_reception']`, jamais `status='delivered'`.
- Retour attendu : un courrier vers CLAUDE qui porte `tasks.db:<id>`.
- **Pour du travail, préférer la tâche directe** : un maillon de moins, et pas de
  second consommateur qui avale le courrier.

Après une modification du répondeur ou de l'exécuteur, le service tourne l'ANCIEN code tant qu'il n'est pas relancé.

## Pièges payés

1. **Répondeur qui promettait sans exécuter** (`[GEMINI-AUTO·fort:groq]` « je te remets
   l'artefact ») : choix local-first du 27/08. Réparé (`8f5349b50`). S'il revient, le
   service tourne un vieux code.
2. **Session interactive ouverte → tout différé.** Réparé (`26a2668c8`).
3. **Deux consommateurs sur la boîte ANTIGRAVITY** : la session interactive acquitte à
   la lecture. D'où la tâche directe pour du travail.
4. **Invite UAC « ExeBox » : RÉGLÉE** (owner 5/11 : « je ne l'ai plus depuis longtemps »). Ne plus
   la citer comme cause d'une tâche AGY silencieuse.
4bis. **Veille d'une tâche : `forge_job_watch_cli.py --task <id>`.** Avec `--job`, elle reste muette
   alors que la tâche est finie (5/11). Artefact commité sur une branche de tâche : commit par
   `git log --all -1 --format=%h -- <chemin>`, lecture par `git show <commit>:<chemin>`.
5. **Relais de débat pris pour tout** : `pat_m2m_debate_relay` relançait backtest et
   arène sur n'importe quelle réponse d'un pair. Filtré par sujet
   (`_sujet_antiregression`, `2d301289e`).
6. **`completed` attendu, `done` écrit** : un suivi qui attend le mauvais mot attend
   pour toujours.
7. Le répondeur ne répond plus aux notifications `task.*` : elles sont à l'exécuteur.
8. **Sous `--sandbox`, toute commande shell est REFUSÉE** (`denied_actions: unsandboxed RunCommand`), et AGY
   s'arrête alors SANS écrire son artefact (15/10 : 31 s, réponse vide, `[NON LIVRE]`). La consigne doit dire :
   lire UNIQUEMENT par l'outil MCP `read` / `read_function_body` du hub, écrire avec son outil d'édition, et
   « si un outil t'est refusé, écris quand même ce que tu as pu lire ». Ne jamais lui proposer `git show`.
9. **`read_file` d'AGY REFUSE tout chemin RELATIF** (30/10, 4/4 tâches mortes : `actions refusees par le bac :
   read_file`, sans chemin). Sonde `docs/enquetes/sonde_lecture_agy_20261030.md` : « must be an absolute path » en
   relatif, lecture OK en absolu sous le worktree de tâche (`.git` compris). Ce n'était PAS le bac. La consigne de
   l'exécuteur (`_consigne_agy`) impose désormais la lecture en chemin absolu ; dans une consigne à AGY, donner les
   chemins en ABSOLU. Sortie brute conservée : `sandbox/jobs/agy_<tâche>.json` (e330915a5).
9bis. **CAUSE RÉELLE (30/10, mesurée)** : lancé avec `--add-dir <worktree de tâche>`, le PROJET d'agy restait son
   worktree habituel → en headless, toute lecture hors projet est refusée (la règle `read_file(...\**)` n'y change
   rien). L'exécuteur lance désormais agy DANS le worktree de tâche avec `--new-project` (patron « Worktree mode »
   de Codex) : lecture et écriture au bon endroit, sans règle.
10. **Sonde ou tâche propre à AGY réaffectée à un autre agent** (job_ce55a33f → WORKER_CODE → CODEX, 30/10) : la
    réaffectation écrase le résultat et brûle le dernier recours. Commencer la description par
    `RESERVE A ANTIGRAVITY` (`_reservee_a`, tools/forge_task_executor.py) : jamais réaffectée.
11. **Coût** (owner 30/10 : « AGY je le paye aussi ») : une petite tâche en `--effort high` avec lecture d'un
    fichier de 9 000 lignes = 405 k tokens, 10 min. Toute consigne déclare `taille: S|M|L` (effort bas sauf L,
    `_effort_agy(desc)`) et nomme la fonction + le numéro de ligne à lire, jamais « lis le fichier ».
12. **Le NR d'AGY peut être FAUX et son code aussi (30/10, parallélisme de l'exécuteur).** Son test lançait
    `run_loop` dans un thread (`signal.signal` y lève), inventait le schéma de `tasks.db` (`claimed_by`), remplaçait
    `_db` sans `row_factory`, et son 2e test passait À VIDE ; dessous, `_delegations_en_vol += 1` sans `global` =
    UnboundLocalError à la PREMIÈRE délégation (a9ec862f9). Redémarrer l'exécuteur sur ce code aurait arrêté AGY.
    Règle : rejouer son NR sur alpha AVANT tout redémarrage ; un NR prouve qu'il a TRAVERSÉ le chemin (compteur d'appels).
13. **Agent inconnu = tâche orpheline muette.** `task assign agent=OPENCODE` est accepté, mais aucun exécuteur ne
    porte ce nom (`OPENCODE_DEFAUT2..5`, `_GPTOSS`, `_NEMOTRON`, `_GLM` : `services.toml`). Lire le `--agent` du
    service avant d'assigner.
14. **Coût** : tâche M sur `forge_task_executor.py` (288 Ko) = 338 k tokens + 11,6 M relus en cache. Consigne :
    `read_function_body` sur les fonctions nommées, jamais le fichier entier.

- **Travail laissé non committé** (21/10, deux fois) : la tâche rend FAILURE « fichiers non commités : 1 » alors
  que le code est juste. Vérifier la base (`git diff --quiet <base> -- <fichier>` sur alpha), puis transférer
  `git -C <worktree> diff -- <fichier> | git -C <dépôt> apply`, et jouer les NR avant de committer.
- **Une mesure déléguée lit la base VIDE de son worktree** (21/10 : « 1 tâche en 30 jours » contre 390) : donner
  le chemin ABSOLU de la base vivante, exiger le nombre de lignes lues, recouper la population avant d'accepter.
- **Réponse vide** (`[REPONSE VIDE]`, rien produit) : souvent un quota épuisé ; réaffecter, ne pas relancer à
  l'identique.
- **Plafond de session : 24 min 30** (`print_timeout`, rc=3, tâche `job_1388adca…` du 4/11) : la consigne demandait
  5 × 1 800 s de solveur, 338 k tokens dépensés pour 0 solveur lancé. Pas de travail de plus de ~20 min dans une
  session AGY : un calcul long part en job détaché (`run action=run_job`), AGY n'en lit que le résultat.
