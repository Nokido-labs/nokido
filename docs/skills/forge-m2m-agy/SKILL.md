---
name: forge-m2m-agy
description: >
  À utiliser pour faire travailler AGY (Antigravity) ou lui parler sans copier-coller :
  déléguer une tâche, lui demander un avis ou un artefact, vérifier qu'il a répondu,
  comprendre pourquoi il se tait. Donne la voie prouvée (tâche ANTIGRAVITY, exécuteur,
  artefact jugé), la carte de ses surfaces et les pièges déjà payés.
---

# forge-m2m-agy — travailler avec AGY sans redécouvrir

Écrite le 15/10 sur demande de l'owner : chaque session redécouvrait la même chose.
Tout ce qui suit a été prouvé de bout en bout le 14/10 (tâches `job_92340852…` et
`job_53238598…`). Ce qui n'a pas été mesuré est marqué INCONNU.

## Carte des surfaces AGY

| surface | ce qu'elle fait | ce qu'elle draine |
|---|---|---|
| `NokidoTaskExecutorAntigravity` | lance `agy` en mode agent (`--sandbox --mode accept-edits`, runAs interactive) dans le worktree `nokido_worktrees/antigravity` (branche `agent/antigravity`). **La seule surface qui EXÉCUTE.** | `tasks.db`, agent=ANTIGRAVITY |
| `NokidoGeminiAutonomous` (`forge_gemini_autonomous_agent`) | répondeur postal. Conversation → répond en texte. Travail (`HANDOFF_NEXT` ou champ `artefact_attendu`) → dépose une tâche ANTIGRAVITY en tant que GEMINI, répond le n° de tâche, relaie le résultat (`relayer_resultats`, suivi `sandbox/gemini_auto_taches.json`, abandon DIT à 24 h). | postal GEMINI |
| session AGY interactive de l'owner | lit la boîte et **acquitte à la lecture, sans `claimed_by`** : second consommateur | boîte ANTIGRAVITY |
| `NokidoGeminiDaemon` | déclaré, coupé par défaut | — |
| outil MCP `agy_run` | RBAC owner-only | — |
| provider `gemini_cli` | `agy.exe` sur l'abonnement owner : `ask(provider="gemini_cli")` rend un TEXTE, pas un agent | — |

Modèle d'AGY CLI = celui choisi par l'owner avec `/model` (14/10 : Gemini 3.8 Flash High).
Les modèles forts du web (argon) ne sont pas disponibles dans le CLI.

## Déléguer un travail : la voie prouvée

```
task action=assign agent=ANTIGRAVITY intent=HANDOFF_NEXT description="<consignes>"
```

La description dit, dans cet ordre :
1. **quoi lire**, par pointeurs, avec l'outil `read` du hub sur l'arbre principal : le
   worktree d'AGY peut porter des fichiers anciens (le 14/10, ses skills dataient) ;
2. **quoi produire** : un artefact DANS son worktree (chemin relatif) ;
3. **le périmètre** : « lecture seule sauf ton fichier de réponse » quand c'est un avis ;
4. **la ligne finale exigée** : `{"intent":"OK_DONE","pointer_ref":"<chemin de l'artefact>"}`.

Le juge de l'exécuteur lit ce `pointer_ref` final ; le résultat revient à l'émetteur
en `task_result` (boîte de session). Durées mesurées : avis sur 28 skills en 9 min,
preuve simple en 1 min. Message accepté jusqu'à 30 000 caractères (`_extract_message`,
coupe DITE au-delà) : au-delà, écrire le dossier dans un fichier et le pointer.

**Vérifier, dans cet ordre :**
- le statut dans `tasks.db` vaut `done` (et non `completed`) ;
- le résultat commence par `[effet observe] commits produits : N ; fichiers non
  commites : M`, mesuré par l'exécuteur : l'artefact reste NON committé dans le worktree ;
- **l'artefact lui-même, par git** :
  `git -c safe.directory=* -C "<racine>/nokido_worktrees/antigravity" status --short`,
  puis le lire. Jamais l'`OK_DONE` seul. Un Glob a nié le 14/10 un fichier que git voyait.
- un scorecard `UNRATED` (« aucun bloc de code à vérifier ») est normal pour un avis.

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

## Savoir si AGY draine

- `hub action=whoami` → `tasks_unclaimed` par agent (il écrit « personne ne draine »).
- Une tâche qui reste `pending` : vérifier que `NokidoTaskExecutorAntigravity` tourne.
  Relancer un service = l'annoncer (règle de coordination), jamais en silence.
- Après une modification du répondeur ou de l'exécuteur, le service tourne l'ANCIEN
  code tant qu'il n'est pas relancé.

## Pièges payés

1. **Répondeur qui promettait sans exécuter** (`[GEMINI-AUTO·fort:groq]` « je te remets
   l'artefact ») : choix local-first du 27/08. Réparé (`8f5349b50`). S'il revient, le
   service tourne un vieux code.
2. **Session interactive ouverte → tout différé.** Réparé (`26a2668c8`).
3. **Deux consommateurs sur la boîte ANTIGRAVITY** : la session interactive acquitte à
   la lecture. D'où la tâche directe pour du travail.
4. **Invite UAC « ExeBox » à chaque lancement d'agy** par l'exécuteur (`--sandbox`,
   décision owner du 02/10 : ne pas reproposer sans fait nouveau). INCONNU : ce que
   devient la tâche si personne ne valide l'invite.
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

## Ce que cette skill ne couvre pas

- Débat mesuré entre agents (arène, axes admis sur mesure, faux verts du juge) :
  skill `forge-m2m-debat-mesure`. Pour un simple avis d'AGY, une tâche suffit.
- Pairs web (Gemini web, ChatGPT web) : aucun accès au code aujourd'hui. ChatGPT écrit
  au hub par son connecteur MCP ; son message arrive en quarantaine et l'owner
  l'approuve ou le rejette (`tools/forge_pair_quarantaine.py --approuver|--rejeter`).
- Format des messages : protocole M2M v1.4.1 (`RULES_SHARED.md`, `config/m2m_intents.json`).
