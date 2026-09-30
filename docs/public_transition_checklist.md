# Passage public — checklist (roadmap)

Ce que la nature **privée + gratuite** du dépôt bloque aujourd'hui, et qui devient
possible/obligatoire le jour où `user/nokido` passe public (ou GitHub Pro).
État de référence : 2026-08-21, `alpha` = branche par défaut/release, dépôt privé
tier gratuit.

## 🚀 LE JOUR J — séquence exacte (à ne PAS exécuter avant)

Décision owner 2026-08-29 : **rien n'est poussé publiquement pour l'instant**. Ce
bloc existe pour que la séquence ne soit pas reconstruite de mémoire le moment venu.

> ### ⚠️ MESURE 2026-08-30 — cette séquence ne peut PAS être jouée par un compte de service
>
> Deux contrôles du gate et la campagne UI exigent la **session owner**. Ce n'est pas un
> privilège à accorder : les deux causes sont mesurées, distinctes, et aucune ne se règle
> en changeant de `sandbox=`.
>
> - **`publication`** — sous `LaForgeTrusted`, `git ls-remote origin` rend `rc=128` et
>   « could not read Username » : ce compte n'a pas de credential GitHub. Et **sans
>   `GIT_TERMINAL_PROMPT=0` la commande PEND** jusqu'au timeout au lieu d'échouer — piège
>   déjà écrit dans la doctrine, re-payé ce jour-là. Joué côté owner, le contrôle mesure
>   vraiment : il a immédiatement désigné un HEAD absent du distant, fait qu'un `?????`
>   masquait complètement.
> - **`forge_ui_campaign`** — sous `LaForgeSbxOnline`, Firefox se lance (pid visible dans
>   le call log) puis `launch_persistent_context` expire à **180 s** sur
>   `RenderCompositorSWGL failed mapping default framebuffer` : pas de session graphique
>   pour un compte de service. **`sandbox="online"` ne suffit pas** — le piège documenté
>   ne couvrait que le loopback, pas le lancement du navigateur. Côté owner : 20 routes,
>   verdict CONFORME, **65 s**.
>   *(Note 2026-09-01 : la MESURE ci-dessus reste vraie, mais la SYNTAXE qu'elle cite
>   n'existe plus. `sandbox="online"` est REFUSE depuis `7ebea14b0` — c'etait une valeur
>   hors enum qui tombait dans la branche par defaut du dispatch et executait en
>   `NT AUTHORITY\SYSTEM`. L'egress se demande par `network=true`. Le constat « pas de
>   session graphique pour un compte de service » est inchange.)*
>
> - **`composition`** — `forge_release_lock` a d'abord sorti **5 des 6** sous-dépôts en
>   `non_verifie` (`modelcontextprotocol` et les quatre `netcfg-agent*`), ce qui vaut
>   `INDÉTERMINÉ` et non `DÉRIVE` (le module distingue les deux depuis le 29/08).
>
> **CORRECTION mesurée en fin de journée, et elle vaut d'être lue** : `publication` ET
> `composition` ont fini par **mesurer normalement** depuis `LaForgeTrusted` — `alpha =
> distant 69874aace8`, composition `CONFORME`. La cause du basculement n'est **pas établie**
> (vraisemblablement le credential store devenu disponible après plusieurs push réussis) ;
> on ne la donne donc pas pour acquise. Ce qu'il faut en retenir : **« ce compte ne peut pas »
> était trop fort — c'était « ce compte n'a pas pu, ce jour-là, dans cet état »**. Ne pas
> écrire un contrôle owner-only sur la foi d'un seul échec.
>
> **CONCLUSION, et elle annule tout ce bloc : AUCUN de ces contrôles n'exigeait une session
> owner.** `contrat UI armé` est resté indéterminé toute la journée parce qu'il appelait
> `gh api` sans jeton, et j'en ai conclu « `gh` n'est pas authentifié hors session owner ».
> Faux : **`gh` lit `GH_TOKEN` dans l'ENVIRONNEMENT**, le jeton est au coffre, et
> `forge_push_sovereign` sert déjà les siens à git par ce même chemin. Le contrôle est passé
> VERT dès qu'on le lui a donné (par l'env, jamais par la ligne de commande — le hub
> journalise les args de `run`).
>
> **La règle, trois fois payée le même jour** : un contrôle qui ne mesure pas n'est presque
> jamais un droit manquant, c'est un appel mal formé. Chercher la FORME avant de conclure à
> l'impossibilité — et ne jamais écrire « owner-only » sur la foi d'un échec.
>
> État de clôture 2026-08-30, **depuis un compte de service, sans aucune action owner** :
> les **12 contrôles verts**, dont `publication`, `composition`, `contrat UI armé`,
> `miroir a jour`, `secrets historique` (0 blob non inspecté) et `parcours UI` 20/20.
>
> Deux détails qui font perdre du temps sinon : `forge_public_mirror` **REFUSE** d'écraser
> une cible existante (d'où le `rm -rf` ci-dessous — préférer un renommage, il est
> réversible), et le verrou de composition s'émet **en dernier**, une fois les autres
> contrôles verts, sinon il fige une composition que rien n'atteste et le dit lui-même.

1. **Régénérer le miroir** — celui d'aujourd'hui sera périmé de plusieurs commits :
   ```
   rm -rf Nokido/sandbox/public_mirror_repo
   LAFORGE_PYTHON tools/forge_public_mirror.py --historique --apply --json
   ```
2. **Vérifier avant d'exposer** — ne jamais publier sur la foi du passage précédent :
   ```
   LAFORGE_PYTHON tools/forge_release_gate.py --public
   ```
   Attendu : `secrets historique` VERT (miroir propre), `checklist publique` VERT.
3. **Publier** (geste owner, la commande que l'outil ne fait jamais lui-même) :
   ```
   git -C Nokido/sandbox/public_mirror_repo push <remote-public> alpha:refs/heads/main
   ```
   Alternative minimale si l'on préfère un dépôt sans histoire :
   `git push <remote-public> refs/heads/public-snapshot:refs/heads/main`
4. **Réactiver Codeberg** — décommenter l'entrée de `forge_push_sovereign._REMOTES`,
   et repartir du **miroir**, jamais de l'atelier (c'est ce qui l'avait mis en dérive).
5. **Rejouer `gitleaks full_history`** — les GitHub Actions sont **gratuites sur un
   dépôt public**, donc le quota qui bloquait disparaît. C'est le filet large qui
   complète nos 12 motifs.
6. **Vérifier l'affichage du CLA** et le déclenchement de `cla.yml` sur une première
   PR externe (invérifiable tant que privé).

## Débloqué par le passage public (ou Pro)

- [ ] **Protéger `alpha` côté serveur.** Aujourd'hui `POST /rulesets` → `403
  « Upgrade to GitHub Pro or make this repository public »`. Une fois public :
  `LAFORGE_PYTHON tools/forge_repo_settings_audit.py --branch alpha
  --apply-protection` pose le ruleset anti-accident (`deletion` +
  `non_fast_forward`, **sans** `pull_request` ni `required_signatures` → push
  direct préservé). Refaire pour `beta`.
  - Vérifier après pose : `--branch alpha` (sans `--apply`) doit lister le
    ruleset dans `rulesets_visant_branche`.
- [x] **Commentaire faux corrigé** dans `tools/launch_public_mirror.py` (~L461,
  2026-08-21) : « Rulesets works on free tier » remplacé — sur dépôt privé,
  rulesets ET protection classique renvoient 403 (Pro requis) ; vrai seulement
  en public/Pro.
- [ ] **Signatures GPG** si l'on veut un jour `required_signatures` : les commits
  actuels ne sont pas signés (`-c user.name/email` inline). À configurer AVANT
  d'activer cette règle, sinon tout push est refusé.

- [ ] **Publier `docs/wiki/` en GitHub Wiki.** Bloqué en privé/gratuit (mesuré
  2026-08-21 : `PATCH has_wiki:true` → 200 mais la valeur reste `false` — les
  wikis privés exigent Pro, l'API ignore en silence). En public : activer le
  wiki puis pousser les 22 pages ×2 langues (`docs/wiki/`) vers
  `nokido.wiki.git`.

## Obligatoire AVANT de rendre public (sinon fuite irréversible)

- [x] **⚠️ SECRETS DANS L'HISTOIRE ANCIENNE (mesuré 2026-08-21).**
  ✅ **RÉSOLU 2026-08-29** — les 8 clés sont mortes chez le fournisseur (voir plus bas),
  ET il existe désormais un miroir à **histoire nettoyée** :
  `forge_public_mirror.py --historique --apply` clone le dépôt (la source n'est JAMAIS
  modifiée) et purge les chemins sensibles via `git filter-repo`.

  | Vérification du miroir produit | Résultat |
  |---|---|
  | Commits conservés | **4 884** (source : 4 927 ; les 43 écartés ne touchaient que des chemins purgés) |
  | Plus ancien commit | 2026-03-08 « feat: La Forge v13 — initial commit » |
  | `LaForge.env`, `.bak`, `- Copie.env`, `live_bridge.map` | **ABSENTS de tout l'historique** |
  | Scan secrets, limite de taille **levée** | **16 758 blobs, 0 non inspecté, 0 secret** |

  Deux options coexistent donc pour l'ouverture : le **snapshot** (1 commit orphelin)
  ou ce **miroir à histoire complète**, plus crédible pour un lecteur. Aucun des deux
  ne touche à l'atelier ; les gitlinks du superrepo continuent de pointer la source.

  Contexte d'origine : Le gate egress a BLOQUÉ le push des tags `archive/codeberg-pre-rebase` (mai) et `archive/hackathon-v17` (avril) : 14 findings dont `github_pat` dans `app/forge_sovereign_membrane.py` (probable **pattern de détection** de la membrane = faux positif), `google_api` dans `sandbox/live_bridge.map` (binaire runtime = **à vérifier, potentiellement réel**), `generic_secret` dans des tests/tools. ⚠️ Ces commits sont **DÉJÀ sur origin** via les branches `origin/alpha-codeberg-archive` et `origin/hackathon/v17-microsoft` → l'exposition existe déjà (contenue tant que privé). AVANT public : soit **scrubber l'historique** (git-filter-repo sur ces tokens), soit **ne pas publier ces branches** (mirror = `alpha` + `beta` seules). Trier réel vs faux-positif ; priorité `live_bridge.map`. Le tag `archive/main-2026-03-17` est GREEN (propre).
> ### ⚠️ MESURE 2026-08-29 — l'option « mirror = alpha + beta » NE PROTÈGE PAS
>
> Tri réel/faux-positif enfin fait (`tools/forge_history_secret_audit.py`, rejouable) :
>
> - **6 findings `github_pat` de `forge_sovereign_membrane.py` = FAUX POSITIFS**, prouvé.
>   Les 6 blobs portent la MÊME chaîne d'exemple : 36 car., 19 distincts, entropie 3,08.
> - **1 finding RÉEL** : `google_api` dans le blob `1e437b11be` de
>   `sandbox/live_bridge.map` — 27 distincts, entropie 4,65.
>
> **Ce blob est atteignable depuis `refs/heads/alpha`, `refs/heads/beta`,
> `origin/alpha` et `origin/beta`** (et depuis Codeberg). Donc l'alternative
> « ne pas publier les branches d'archive » est **INVALIDE** : le secret est dans
> l'histoire des branches publiables elles-mêmes. Deux conséquences :
> 1. la clé est **compromise** (elle est sur deux hébergeurs) → **rotation**, quelle
>    que soit la suite ; retirer un fichier ne dé-publie pas ce qui a été poussé ;
> 2. le miroir public doit être un **snapshot SANS historique** (commit orphelin),
>    pas un miroir de branches — ou un scrub `git-filter-repo` de `alpha` et `beta`.
>
> Les tags `archive/*` sont, eux, **restés locaux** (aucun n'est sur `origin`).

- [x] **Scan secrets sur TOUT l'historique**, pas seulement HEAD :
  ✅ **FAIT 2026-08-29, en local** (le PAT `actions:write` manque toujours, mais rien
  n'obligeait à attendre GitHub) : `tools/forge_history_scan_job.py --> run_job`,
  **18 353 blobs lus en 7,8 s**, 17 non inspectés (>4 Mo, comptés comme NON lus, pas
  comme propres). Rapport : `sandbox/history_scan.json`.

  > ### 🔴 **20 secrets réels, pas 1** — et pas ceux qu'on croyait
  >
  > | Fichier (dans l'histoire d'`alpha`/`beta`) | Types |
  > |---|---|
  > | `LaForge.env` | `google_api` + `github_pat`, plusieurs versions |
  > | `LaForge.env.bak` | `google_api` + `github_pat` |
  > | `LaForge - Copie.env` | `google_api` + `github_pat` |
  > | `sandbox/live_bridge.map` | `google_api` |
  >
  > Des fichiers d'environnement COMPLETS sont dans l'historique — la checklist n'en
  > mentionnait aucun. Aucun n'est dans l'arbre courant : le snapshot orphelin est vert.
  >
  > ### 🔎 Périmètre RÉEL après élargissement des motifs (2026-08-29)
  >
  > Le premier passage ne couvrait que 5 motifs. Élargi (openai, anthropic, hf, groq,
  > stripe, jwt, url-avec-mot-de-passe) : **9 valeurs distinctes** sur **cinq**
  > fournisseurs — Google, GitHub, **Groq, HuggingFace, OpenAI** — et pas seulement
  > dans les trois `.env` : aussi dans **sept dumps d'environnement**
  > (`sandbox/audit_env_git.json`, `diag2.json`, `diag_startup.json`, `env_bytes.txt`,
  > `env_fix_result.txt`, `env_verify.json`, `env_verify2.txt`) et dans
  > `sandbox/fix_codeberg_push.bat` (jeton dans une URL de push).
  >
  > ⚠️ Un motif « 32 caractères alphanumériques » a été RETIRÉ : il rendait 6 findings
  > dont 5 faux (fichiers de signature, dumps de conversation — tout hash matche).
  >
  > ### ✅ Ces clés ne sont PLUS en service (vérifié 2026-08-29)
  >
  > `tools/forge_secret_rotation_check.py` compare des EMPREINTES (SHA-256 tronqué),
  > jamais des valeurs. **Aucune des 9 ne correspond aux 45 secrets en service**
  > (coffre + environnement courant, 0 source illisible). Verdict : **ROTATIONNÉ**.
  >
  > ### ✅ Les 8 clés sont MORTES chez le fournisseur (testé 2026-08-29)
  >
  > `--tester-validite` interroge chaque fournisseur en LECTURE SEULE. Résultat :
  > **8 révoquées, 0 encore valide, 0 indéterminée**.
  >
  > | Fournisseur | Verdict |
  > |---|---|
  > | GitHub `…uNTJ` | HTTP 401 |
  > | Google `…ImI4` | HTTP 400 + « API key not valid » |
  > | Groq `…yehF` | HTTP 401 |
  > | HuggingFace `…THZH`, `…zCTL` | HTTP 401 |
  > | OpenAI `…7e41`, `…d32b` | HTTP 401 |
  > | Jeton de push Codeberg `…6a1@` | HTTP 401 |
  >
  > **Aucune action de rotation n'est due.** L'exposition subsiste dans l'historique,
  > mais elle ne porte plus que des valeurs mortes. Le snapshot orphelin reste le
  > chemin d'ouverture — il n'emporte de toute façon aucun de ces blobs.
  >
  > ⚠️ Une panne réseau ne vaut JAMAIS « révoquée » : la sonde rend `INDETERMINE`,
  > et un test verrouille ce comportement. Conclure l'inverse déclarerait close une
  > brèche ouverte.
  `tools/forge_ci_check.py --dispatch gitleaks.yml` (self-hosted, `full_history`)
  — nécessite un PAT avec `actions:write` (aujourd'hui absent → 403). Le gate
  egress local (`app/forge_git_egress.py`, profil `public` strict) est le second
  filet. Un secret présent dans un commit ancien reste exposé même s'il est
  retiré de HEAD.
- [x] **`wip/rescue-2026-06-11` / `RAG_plain_bak/` NE DOIT PAS partir en public.**
  ✅ **VÉRIFIÉ 2026-08-29** : `RAG_plain_bak/` ignoré (`.gitignore:401`), **0 fichier
  suivi** par git ; `wip/rescue-2026-06-11` **absente de tout remote** (aucune ref
  `refs/remotes/*` ne la porte). Rien à retirer, seulement à ne pas ajouter.
  Dumps de benchmarks (longmemeval, swebench), 3 blobs >100 Mo, possible données
  tierces. Local-only aujourd'hui (aucun remote) — le garder ainsi, ou backup
  hors-git. Ne jamais pousser vers le remote public.
- [x] **Trier les branches internes** — résolu PAR CONSTRUCTION, et le tri seul ne
  suffisait de toute façon pas (le secret vit dans `alpha`/`beta`).
  ✅ `tools/forge_public_mirror.py` fabrique un **commit orphelin** depuis un index
  temporaire : aucune branche n'est exposée, aucun objet ancien n'existe pour le
  clone. Vérifié 2026-08-29 : `refs/heads/public-snapshot` = `464171e3d878`,
  `parents=[]`, `rev-list --count` = **1**, `sandbox/` (172 fichiers) et `.claude/`
  (2) retirés, audit du snapshot **VERT** sur 3 434 blobs.
  L'outil ne pousse jamais : publier reste un geste owner explicite.
- [x] **CLA** : `docs/CLA.md` existe sur `alpha` (lien réparé vers `blob/alpha`).
  ✅ **VÉRIFIÉ 2026-08-29** : `docs/CLA.md` (7 964 o) et `.github/workflows/cla.yml`
  (4 244 o) présents ; workflow ARMÉ — `issue_comment[created]` +
  `pull_request_target[opened, closed, synchronize]`, `contributor-assistant@v2`.
  Reste seulement à confirmer l'affichage une fois public (non vérifiable avant).
  Vérifier qu'il s'affiche une fois public, et que le workflow `cla.yml`
  (contributor-assistant) est armé.
- [x] **Licence** : modèle dual AGPLv3 + commercial.
  ✅ **VÉRIFIÉ 2026-08-29** : `LICENSE` (AGPLv3, 34 523 o), `NOTICE` qui renvoie à
  `COMMERCIAL.md` — et ce fichier EXISTE (8 139 o, plus `COMMERCIAL.fr.md`). Le
  renvoi n'est pas un lien mort. Ancien libellé : vérifier `LICENSE` + entêtes
  avant exposition publique.

## Déjà en place (ne pas refaire)

- **Protection anti-accident d'`alpha` côté CLIENT** : active via
  `core.hooksPath=.githooks` → `pre-push` → `forge_git_egress._protection_branche`.
  `_BRANCHES_PROTEGEES = {main, alpha, beta, dist, hackathon/v17-microsoft}`
  bloque suppression + force-push + non-fast-forward sur cette machine (le seul
  poste qui pousse). Le serveur reste non protégé jusqu'au passage public.
- **Branche par défaut** = déjà `alpha` côté serveur (vérifié via l'API).
- **Repoint `main`→`alpha`** fait (`ci-selfhosted`, lien CLA), verrouillé par
  `tests/nr/test_workflow_refs_nr.py`.
- **Archives** : tags `archive/*` locaux (main, rescue, codeberg-pre-rebase,
  hackathon-v17). Rien supprimé, `gc` non lancé (décision owner : tout retrouvable).

## Outils prêts

- `tools/forge_repo_settings_audit.py` — `--branch X` audite
  (default/protection/rulesets/PR/webhooks) ; `--apply-protection` pose le ruleset
  anti-accident (403 tant que privé/gratuit). Gardé par
  `tests/nr/test_repo_settings_audit_nr.py`.
- `tools/launch_public_mirror.py` — pipeline de mirror public (⚠️ son
  `--protect-main` inclut `pull_request` + `required_signatures` : à NE PAS
  appliquer tel quel sur `alpha`, casserait le push direct).
