# Isolation du shell : Codex CLI, Copilot CLI, Cline

Item P1_profils_cli_codex_copilot_cline_20261024. Rédigé le 2026-10-25.

## Méthode et limites

- Pages officielles lues en entier via l'outil `crawl` (texte reçu et lu).
- Aucun fichier de profil utilisateur ni aucune config client n'a été lu.
  `%NOKIDO_DATA%\embeddings.db` n'a pas été interrogée.
- Règle : un levier absent d'une page lue est absent du tableau. Aucun drapeau n'est déduit.
- Limite : la page Codex `agent-approvals-security` et la référence CLI Cline ont été indexées en RAG
  (pages volumineuses). Les requêtes RAG ont expiré ou ont rendu du bruit non officiel.
  Je ne les ai donc pas lues. Les leviers Codex `sandbox_mode` et `approval_policy` sont cités
  par la tâche mais NON vérifiés ici. Ils restent hors tableau jusqu'à relecture de la page.
  Suite : lire ces deux pages en pagination, puis compléter les tableaux Codex et Cline CLI.

## Codex CLI

| Levier | Effet | URL consultée |
|---|---|---|
| `allow_managed_hooks_only = true` (au plus haut niveau de `requirements.toml`, sans effet dans `config.toml`) | Ignore les hooks utilisateur, projet et session. Seuls les hooks gérés (requirements et couches de config gérées) restent actifs. | https://raw.githubusercontent.com/openai/codex/main/docs/config.md |

Le même fichier renvoie vers https://developers.openai.com/codex/config-basic, `/config-advanced`
et `/config-reference`. Un autre fichier, `docs/sandbox.md`, renvoie vers
https://developers.openai.com/codex/security. Ces trois pages de détail ne sont pas lues.
Le tableau ne contient donc que ce qui est lu.

Profil recommandé : non établi. Il suppose la lecture de la page security.
À tester en profil jetable : `requirements.toml` géré avec `allow_managed_hooks_only = true`,
avec un hook géré Nokido. Vérifier que le hook est exécuté et qu'un hook de projet est ignoré.

## Copilot CLI

Source principale : https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/allowing-tools

| Levier | Effet | URL consultée |
|---|---|---|
| Comportement par défaut | Lecture seule autorisée automatiquement. Shell destructeur, édition de fichiers et URL demandent une approbation. | idem source principale |
| `--available-tools` | Désactive tous les outils hors liste. Le modèle ne les voit pas. | idem |
| `--excluded-tools` | Désactive seulement les outils cités. Ignorée si `--available-tools` est présent. | idem |
| `--allow-tool=<motif>` | Autorise sans invite. Ex. `shell(git:*)`, `shell(git commit)`, `write(...)`. | idem |
| `--deny-tool=<motif>` | Interdit. Prime toujours sur les autorisations, y compris `--allow-all` et les approbations enregistrées. | idem |
| `--allow-all-tools`, `--allow-all` / `--yolo` (= tools + paths + urls) | Permissif. L'enterprise peut les bloquer (Business/Enterprise). La doc déconseille de les mettre dans un alias. | idem |
| `--allow-all-paths`, `--allow-all-urls` | Cités comme composants de `--allow-all`. | idem |
| `/reset-allowed-tools` | Révoque les permissions de session et vide les approbations enregistrées du lieu courant. | idem |
| Persistance | Les options `--allow-tool` et `--deny-tool` valent pour la session seule. Les approbations « ne plus demander » vont dans `permissions-config.json`. Les URL approuvées vont dans `allowedUrls` de `settings.json`. | idem |
| Sandbox locale ou cloud | La page renvoie vers https://docs.github.com/en/copilot/concepts/about-cloud-and-local-sandboxes-for-github-copilot. Cette page n'est pas lue. | idem |

Les motifs `shell(...)` et `write(...)` renvoient à la référence
`/en/copilot/reference/copilot-cli-reference/cli-command-reference`, non lue.
Les motifs des exemples sont copiés tels quels de la page lue.
La liste des types d'outils n'est pas lue.

Profil recommandé à tester en profil jetable (exemple de la page, repris tel quel) :

```
copilot --available-tools='bash,edit,view,grep,glob' --allow-tool='shell(git:*)' --deny-tool='shell(git push)'
```

Vérifier : `git push` refusé, accès réseau impossible, aucun sous-agent.
Ajouter `--deny-tool` sur les motifs shell que Nokido interdit. Ne jamais utiliser `--yolo` ni `--allow-all`.

## Cline

Source : https://docs.cline.bot/features/auto-approve

| Levier | Effet | URL consultée |
|---|---|---|
| Auto Approve par catégorie | Évalué à chaque appel d'outil : lecture, édition, commande, navigateur, MCP. | https://docs.cline.bot/features/auto-approve |
| « Read all files » et « Edit all files » | Étendent seulement le réglage de base. Sans lui, ils n'ont aucun effet. | idem |
| « Execute safe commands » / « Execute all commands » | Les commandes sont sûres ou à approuver. Il n'y a pas de liste fixe : le modèle pose le drapeau `requires_approval`. Ce n'est donc pas une garantie. | idem |
| YOLO mode | Approuve tout, sans contrôle de sécurité. Dangereux. | idem |
| Défaut recommandé par la doc | Activer seulement « Read project files ». Laisser éditions, commandes, navigateur et MCP désactivés. S'appuyer sur les Checkpoints. | idem |

Point clé : le tri « commande sûre » dépend du modèle, pas d'une liste de refus. Ce n'est pas une
isolation. La page https://docs.cline.bot/cline-cli/cli-reference est indexée, non lue.
Les drapeaux de la CLI Cline sont donc hors tableau.

Profil recommandé à tester en profil jetable : tout désactivé sauf lecture du projet,
YOLO jamais activé, commandes toujours sur approbation. Vérifier qu'une commande
`rm -rf` ou `git push` déclenche bien une demande.

## Ce que Nokido peut imposer de son côté

Ces leviers sont propres à Nokido. Ils ne dépendent d'aucun drapeau client.

1. Lanceurs `nokido_*.py` : le seul chemin de lancement du client. Ils fixent le répertoire de
   travail sur un worktree jetable. Ils construisent la ligne de commande :
   pour Copilot, `--available-tools` et `--deny-tool` fixes ; jamais `--yolo` ni `--allow-all`.
   Ils refusent les arguments qui demandent un mode permissif.
2. Hub `run` gouverné : le shell passe par le hub, avec sandbox hors ligne par défaut et
   `network` explicite. L'exécution reste dans le bac qu'impose le hub, même si le client
   est permissif.
3. Hooks : pour Codex, hooks gérés via `requirements.toml` (voir le tableau Codex). Les autres
   clients n'ont pas de mécanisme de hook vérifié dans cette étude.
4. Processus : profil, `HOME` et répertoire de config jetables par session. Ne jamais pointer
   vers le profil réel de l'utilisateur. Supprimer le profil après la session.
5. Contrôle après coup : `git status` et `git diff` du worktree par l'exécuteur.
   Ce contrôle détecte, il n'empêche pas.

## Verdict

- Copilot CLI : leviers réels et vérifiés, avec priorité du refus. Meilleur candidat.
- Cline : approbation par catégorie seulement. L'isolation doit venir de Nokido.
- Codex : un seul levier vérifié (hooks gérés). `sandbox_mode` et `approval_policy` à vérifier
  avant d'écrire le profil.
