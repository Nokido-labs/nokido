# Passage en public — plan, gates et ordre d'exécution

> État mesuré le **2026-09-06**. Chaque ligne de ce document vient d'un appel d'API ou d'une
> lecture de fichier, jamais d'une supposition. Ce qui n'a pas pu être mesuré est **dit**.

---

## 0. La posture d'aujourd'hui, mesurée

| point | valeur mesurée | source |
|---|---|---|
| dépôt | `user/nokido`, **privé**, propriétaire = **compte personnel**, défaut `alpha` | `GET /repos/…` |
| **rulesets** | ❌ **`403 Upgrade to GitHub Pro or make this repository public`** | `GET /repos/…/rulesets` |
| **protection de branche** | ❌ même 403 | `GET /repos/…/branches/alpha/protection` |
| Actions | activées · `allowed_actions: all` · `sha_pinning_required: false` | `GET /actions/permissions` |
| jeton par défaut | ✅ `default_workflow_permissions: read` · `can_approve_pull_request_reviews: false` | `GET /actions/permissions/workflow` |
| workflows de forks | ✅ `run_workflows_from_fork_pull_requests: false` (et ni jetons d'écriture, ni secrets) | `GET /actions/permissions/fork-pr-workflows-private-repos` |
| runner | **self-hosted**, `DESKTOP-XXXX`, en ligne, labels `[self-hosted, Windows, X64, laforge]` | `GET /actions/runners` |
| secrets Actions | **1** : `LAFORGE_ADMIN_TOKEN` | `GET /actions/secrets` (noms seuls) |
| webhooks | **0** | `GET /repos/…/hooks` |
| Dependabot | actif · **221 alertes** (4 critiques, 88 hautes) · Secret Protection **non activé** | rappel de push + fiche posture |

**Conclusion de cette section : rulesets et protection de branche ne sont pas un choix
aujourd'hui — ils sont *refusés par le plan*.** Deux sorties, et une seule est gratuite :
passer en public, ou souscrire GitHub Pro. C'est exactement pourquoi ce plan existe.

---

## 1. Ce que le passage en public DÉBLOQUE, gratuitement

- **Rulesets** et **protection de branche** sur `alpha` — le palier 0 de la roadmap
  (« un verdict CI fermé par commit ») devient exécutable au lieu d'être déclaratif.
- **Secret scanning + push protection** : gratuits sur les dépôts publics. Aujourd'hui la
  fiche posture note « Secret Protection non activé », ce qui rend le scan MCP inutilisable.
- **CodeQL / code scanning** gratuit.
- **Minutes Actions** gratuites sur les runners GitHub-hosted — ce qui permet de **sortir les
  PR externes du runner self-hosted** (cf. gate 2), au lieu d'arbitrer contre un quota.

## 2. Ce que le passage en public EXPOSE — et qui est IRRÉVERSIBLE

**L'historique devient lisible en entier, par tout le monde, et pour toujours.** Un secret
retiré du HEAD reste dans les commits antérieurs ; un dépôt public est cloné, mis en cache et
indexé en quelques minutes. **Repasser en privé ne défait rien.**

Second effet : les **forks** deviennent possibles pour n'importe qui, donc les PR externes
aussi — et le CI primaire tourne sur un runner **self-hosted**, c'est-à-dire **la machine de
l'owner**, celle qui héberge le hub, les daemons et le coffre. La documentation GitHub est
explicite : sur un runner self-hosted, du code de PR non revu **s'exécute automatiquement**
dès que l'approbation est contournée ou accordée.

---

## 3. Les gates, dans l'ordre. Aucun ne se saute.

### GATE 1 — l'historique est propre, ou les secrets qui y ont vécu sont ROTATIONNÉS

C'est le seul gate dont l'échec est définitif. Règle, sans exception :
**tout secret ayant existé dans l'historique est COMPROMIS**, même supprimé depuis.

#### Ce que la mesure a trouvé — et son verdict

`LaForge.env` **a été committé** : ajouté le **2026-03-20**, retiré le **2026-03-21**, en
**16 révisions**. Un jour dans l'arbre, et **pour toujours** dans les 15 109 commits de
l'historique. Il déclarait **80 clés, dont 77 avec une valeur non vide**.

Vérification faite le 2026-09-06, **par empreinte** — aucune valeur n'a été affichée nulle
part : pour chaque secret, toutes les valeurs distinctes présentes dans le diff complet du
fichier ont été hachées et comparées au haché de la valeur **actuelle du coffre DPAPI**.

| clé | valeurs distinctes dans l'historique | verdict |
|---|---|---|
| `CODEBERG_TOKEN`, `FORGE_MCP_TOKEN`, `GEMINI_API_KEY`, `GITHUB_TOKEN`, `GROQ_API_KEY`, `KAGGLE_API_TOKEN`, `MCP_DEV_SECRET`, `MISTRAL_API_KEY` | 1 chacune | **rotationnées** — aucune empreinte ne correspond au coffre |
| `ANTHROPIC_API_KEY`, `LITELLM_API_KEY`, `LLAMACPP_API_KEY` | 0 (déclarées vides) | sans objet |

**✅ Verdict : 0 clé encore exposée.** L'owner l'affirmait ; c'est désormais mesuré.

#### Ce que cette mesure NE couvre PAS — et qui reste à faire

1. Elle porte sur **`LaForge.env` seul**. Un secret en dur ailleurs dans l'historique n'est pas
   couvert. → **balayage exhaustif** : `gitleaks.yml` sait déjà le faire — son entrée
   `full_history` bascule le mode de `dir` (arbre courant) à `git` (historique). Un scan en
   mode `dir` qui rend 0 **ne dit rien** de l'historique. Lancé le 2026-09-06 :
   `gh workflow run gitleaks.yml --ref alpha -f full_history=true`.
2. Elle compare au **coffre**. Une clé absente du coffre serait sortie `INDETERMINE` — aucune
   ne l'a été.
3. Restent exposés, sans être des secrets : `SSH_HOST`, `SSH_USER`, `SSH_PORT`,
   `PRIVATE_KEY_PATH` — de l'infrastructure, à traiter au **gate 3**.

⚠️ **Ne PAS réécrire l'historique pour « nettoyer »** : le superrepo pointe des `sha` par
gitlink ; une réécriture rendrait le submodule irrécupérable au clone (piège déjà consigné).
La bonne réponse à un secret historique est la **rotation** — elle a eu lieu.

**Critère de sortie :** rapport gitleaks en mode `git` (historique complet) à **0 finding**,
en plus du tableau ci-dessus. Le premier point est **fait** ; le second est **lancé**.

### GATE 2 — le runner self-hosted est hors de portée des PR externes

Aujourd'hui le risque est fermé **par le plan** (`run_workflows_from_fork_pull_requests: false`
ne vaut que pour les dépôts privés). En public, ce garde disparaît : il faut le remplacer.

Trois mesures, cumulatives :

1. **Les PR externes ne touchent pas le self-hosted.** Le déclencheur `pull_request` de
   `ci-selfhosted.yml` reste borné aux branches internes — il l'est déjà par
   `if: github.event_name != 'pull_request' || startsWith(github.head_ref, 'dependabot/')`.
   Une PR de fork a un `head_ref` qui ne peut pas satisfaire cette condition depuis un fork.
2. **Les PR externes tournent sur GitHub-hosted.** `ci.yml` (matrice 3 OS) est aujourd'hui en
   `workflow_dispatch` pour économiser le quota — en public le quota est gratuit : le
   rebrancher sur `pull_request` devient le bon chemin pour les contributions externes.
3. **Approbation obligatoire** : `Require approval for all external contributors`
   (Settings → Actions → General). ⚠️ La doc prévient : les réglages « premiers
   contributeurs » se contournent en faisant accepter une faute de frappe.

**Critère de sortie :** aucun job `runs-on: [self-hosted]` atteignable par une PR de fork,
vérifié en lisant les déclencheurs ET les `if:` de chaque job.

### GATE 3 — ce que le dépôt révèle de la machine

Un dépôt public est aussi une carte. Exemples déjà présents :
`PYBIN: %USERPROFILE%/miniforge3/envs/laforge_py314/python.exe` (nom de compte, arborescence),
les chemins `C:\laforge-runner\`, les ports de la flotte, `docs/CLI_ATTACK_SURFACE.md`.

Rien de cela n'est un secret ; tout cela réduit le travail d'un attaquant. **Critère de
sortie :** une passe de revue où chaque exposition est soit retirée, soit assumée par écrit.

---

## 4. À poser LE JOUR du passage, dans cet ordre

1. **Ruleset sur `alpha`** (préférer un ruleset à une protection de branche : plusieurs
   peuvent s'empiler, l'état d'application se change sans supprimer la règle, et tout le monde
   peut les lire) :
   - `pull_request` requis, 1 approbation, **rejet des approbations obsolètes** au nouveau push ;
   - **statuts requis** : `gates`, `build-dist`, `integration`, `ui-acceptance` —
     ⚠️ **jamais `notify-verdict`** (ex-`notify-failure`, élargi le 2026-09-20 pour
     rendre compte AUSSI en succès) : il tourne désormais **toujours**, donc il serait
     vert même sur un run où rien n'a été jugé. La raison de l'exclure a changé, pas
     la consigne — un statut requis doit **juger**, pas **rapporter** ;
   - **commits signés** requis ;
   - historique **linéaire** ;
   - force-push et suppression **bloqués** ;
   - dérogation : personne, ou l'owner seul, et **écrite**.
   - ⚠️ La doc impose des **noms de job uniques entre workflows** pour les statuts requis :
     `gates` existe dans `ci-selfhosted.yml` — vérifier qu'aucun autre workflow ne réutilise
     ce nom, sinon le statut devient ambigu et bloque les PR.
2. **Push ruleset** : bloquer par extension et par taille les fichiers qui n'ont rien à faire
   dans l'historique (`*.env`, `*.pem`, `*.key`, `*.dat`, dumps, bases). Un push ruleset
   s'applique à **tout le réseau de forks** — c'est la barrière la plus utile en public.
3. **Secret scanning + push protection** : activer les deux.
4. **CodeQL** : activer le scan par défaut.
5. **Actions** : passer `allowed_actions` de `all` à une politique restreinte, et activer
   **`sha_pinning_required`** — ⚠️ cela exige d'**épingler d'abord** toutes les actions au SHA,
   sinon chaque workflow casse. Inventaire actuel des tierces à épingler :
   `contributor-assistant/github-action@v2` (reçoit un jeton **write** via `pull_request_target`),
   `gitleaks/gitleaks-action@v2`, `docker/setup-qemu-action@v3`, `docker/setup-buildx-action@v3`,
   `docker/login-action@v3`, `docker/metadata-action@v5`, `docker/build-push-action@v6`,
   `astral-sh/setup-uv@v5`, `pypa/gh-action-pypi-publish@release/v1`.
6. **`.github/dependabot.yml`** : absent aujourd'hui (la configuration vit dans l'interface).
   Le poser avec groupement et planning, et y ajouter l'écosystème `github-actions`.
7. **Webhooks** : aucun aujourd'hui. Si un jour il y en a : secret obligatoire, `insecure_ssl`
   à `0`, et jamais d'URL pointant la machine de l'owner.

## 5. Le point le plus dangereux du dépôt aujourd'hui, en public comme en privé

`.github/workflows/cla.yml` se déclenche sur **`pull_request_target`** avec, au niveau du
workflow, `actions: write`, `contents: write`, `pull-requests: write`, `statuses: write`, et
confie `GITHUB_TOKEN` à une action tierce **non épinglée**. `pull_request_target` s'exécute
dans le contexte de la **base**, avec un jeton d'écriture et l'accès aux secrets, **quelles que
soient les règles d'approbation** — la doc le dit noir sur blanc. Il tourne sur
`ubuntu-latest`, donc pas sur la machine, mais un tag mutable qui reçoit un jeton d'écriture
sur le dépôt reste le pire couple de la liste.

**À faire avant le passage en public :** épingler cette action à un SHA complet, et descendre
ses permissions au niveau du **job** au lieu du workflow (le job `issue_comment` n'a pas besoin
de `contents: write`).

---

## 6. Ce qui est DÉJÀ en place, mesuré — à ne pas refaire

- **OIDC / Trusted Publishing PyPI** : `release.yml` utilise `id-token: write` avec
  `environment: pypi`, **aucun jeton PyPI stocké**. C'est la forme recommandée, elle est déjà là.
- **Jeton par défaut en lecture seule**, et Actions interdites de créer ou approuver des PR.
- **Workflows de forks désactivés** (tant que le dépôt est privé).
- **`persist-credentials: false`** sur tous les `checkout` du workflow self-hosted, ajouté le
  2026-09-06 : par défaut checkout écrit le jeton dans `.git/config` du workspace
  (`extraheader` + `AUTHORIZATION`, vérifié sur
  `C:\laforge-runner\_work\nokido\nokido\.git\config`). Sur un runner **éphémère** la machine
  disparaît ; ici elle **persiste**, donc la fenêtre est réelle. Aucun job ne pousse.
- **`permissions: contents: read`** déclaré au niveau du workflow self-hosted.
- **PR Dependabot enfin soumises aux gates**, bornées aux branches `dependabot/**`.

## 7. Signatures — REPORTÉ au passage public, pour le collaboratif (owner, 2026-09-07)

Décision owner : on ne touche pas à ces trois réglages **aujourd'hui**, et on les **rouvre au
passage public**, parce que c'est le collaboratif qui leur donne leur sens — vérifier qui
signe n'a d'intérêt que quand plusieurs personnes poussent.

**Ce qui est ACQUIS et prouvé le 2026-09-06/07** (ne pas le refaire, cf.
`signature_commits_chaine_complete_jamais_utilisee_2026-09-06`) : la chaîne SSH est complète
et fonctionnelle. Clé ed25519 déclarée sur GitHub (id `1129932`), **empreinte identique** à
`~/.ssh/id_ed25519.pub`, `.gitconfig` owner complet, `allowed_signers` avec
`namespaces="git"`. Preuve d'exécution : `git tag -s` puis `git tag -v` rend
`Good "git" signature`. **Il n'y a rien à installer.**

| réglage | pourquoi PAS maintenant | ce qui doit être vrai pour l'activer |
|---|---|---|
| **Vigilant mode** | marquerait **400/400** commits `Unverified` | tous les commits publiés signés, ou l'historique assumé comme non signé |
| **Require signed commits** (branche protégée) | **bloquerait tout commit d'agent** sur `alpha` | les agents ont un chemin de signature, ou ils ne poussent plus directement |
| **Rebase and merge** | GitHub **recrée** le commit → signature perdue (vise les PR Dependabot) | politique de merge arrêtée : merge commit / squash, ou rebase local puis push |

⚠️ **La contrainte structurelle à ne pas oublier le jour venu** : la clé privée vit dans le
profil owner, **hors ACL des comptes du hub**. Aucun réglage ne fera signer un agent avec
elle. Exiger la signature sur `alpha` revient donc à **interdire aux agents de pousser
directement** — ce qui est peut-être exactement ce qu'on voudra en collaboratif, mais c'est
une décision de flux, pas un réglage de sécurité anodin.

✅ **Ce qui reste faisable sans rien casser, dès maintenant** : signer les **tags de
release**. La preuve publique se pose alors par version, sans confier de clé à la surface la
moins gouvernée. La provenance fine par agent reste portée par la note
`refs/notes/laforge-agent` (609 notes), qui est **locale par conception**.
