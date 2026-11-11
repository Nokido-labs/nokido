---
name: forge-m2m-agy
description: "À utiliser pour faire travailler AGY (Antigravity) ou lui parler sans copier-coller : déléguer une tâche, lui demander un avis ou un artefact, vérifier qu'il a répondu, comprendre pourquoi il se tait."
---

# forge-m2m-agy — travailler avec AGY sans redécouvrir

Voie prouvée de bout en bout le 14/10 (`job_92340852…`, `job_53238598…`). **Annexe** à lire dès qu'une tâche AGY échoue ou se tait : `docs/skills/forge-m2m-agy/references/pieges.md` (racine Nokido, outil `read` du hub) : pièges payés, courrier, modèles, surfaces détaillées.

## Surfaces

| surface | rôle | draine |
|---|---|---|
| `NokidoTaskExecutorAntigravity` | **seule surface qui EXÉCUTE** : `agy` en mode agent, sous `--sandbox`, dans un worktree | `tasks.db`, agent=ANTIGRAVITY |
| `NokidoGeminiAutonomous` | répondeur postal : conversation → texte ; `HANDOFF_NEXT` ou `artefact_attendu` → tâche ANTIGRAVITY, résultat relayé | postal GEMINI |
| session AGY de l'owner | acquitte à la lecture : second consommateur | boîte ANTIGRAVITY |

`agy_run` : owner seul. `NokidoGeminiDaemon` : coupé. `ask(provider="gemini_cli")` rend un TEXTE, pas un agent.

## Déléguer

```
task action=assign agent=ANTIGRAVITY intent=HANDOFF_NEXT description="RESERVE A ANTIGRAVITY ..."
```

La description dit, dans cet ordre :
1. `RESERVE A ANTIGRAVITY` en tête (sinon réaffectable), puis `taille: S|M|L` (effort bas sauf L) ;
2. **quoi lire** : `read` / `read_function_body` du hub, chemins ABSOLUS, fonctions et lignes nommées, jamais un fichier entier ; jamais de shell (refusé sous `--sandbox`, AGY s'arrête sans livrer) ; « si un outil t'est refusé, écris quand même ce que tu as pu lire » ;
3. **quoi produire** : un artefact à chemin relatif dans son worktree ; pour un avis, « lecture seule sauf ton fichier de réponse » ;
4. **dernière ligne** : `{"intent":"OK_DONE","pointer_ref":"<chemin de l'artefact>"}`.

- Gratuit d'abord.
- Si le délégué tiers ne fournit aucune valeur mesurée (rendu vide, repli local sans lecture de fichiers, RED non observé, ou cause non établie après 2 rendus), confier la tâche à **ANTIGRAVITY** avec consigne ciblée fonction+ligne et effort bas.

Session < ~20 min (plafond 24 min 30) : un calcul long part en `run_job`. Message ≤ 30 000 caractères : au-delà, pointer un fichier. Base à mesurer : chemin ABSOLU de la base vivante. Veille : `forge_job_watch_cli.py --task <id>`. Le résultat revient en `task_result` à l'émetteur.

## Vérifier

- statut `tasks.db` = `done` (pas `completed`) ;
- résultat commençant par `[effet observe] commits produits : N ; fichiers non commites : M` ;
- **l'artefact, par git, jamais l'`OK_DONE` seul** : `git log --all -1 --format=%h -- <chemin>`, puis `git show <commit>:<chemin>` ; non committé : `git -c safe.directory=* -C "<racine>/nokido_worktrees/antigravity" status --short` ;
- scorecard `UNRATED` : normal pour un avis. NR écrit par AGY : le rejouer sur alpha avant tout redémarrage.

## Si AGY se tait

`hub action=whoami` → `tasks_unclaimed` par agent. Tâche `pending` : `NokidoTaskExecutorAntigravity` tourne-t-il ? Relance annoncée, jamais en silence. `[REPONSE VIDE]` : souvent un quota, réaffecter. Puis l'annexe.

## Hors champ

- Débat mesuré entre agents, axes, faux verts : skill `forge-m2m-debat-mesure`.
- Pairs web (Gemini web, ChatGPT web) : aucun accès au code ; ChatGPT écrit au hub, message en quarantaine, l'owner tranche (`tools/forge_pair_quarantaine.py --approuver|--rejeter`).
- Courrier à AGY : annexe ; pour du travail, préférer la tâche. Format M2M : `RULES_SHARED.md`.
