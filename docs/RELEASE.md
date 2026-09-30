# Release — chaîne de distribution Nokido

Deux pistes distinctes (dual-license). **Rien n'est public tant que ce n'est pas
explicitement déclenché** — aucun workflow ne part sur un push normal.

---

## Track A — Open core → PyPI (AGPLv3, source visible)

`pip install nokido-agent`. Source visible (but de l'AGPL). Automatisé par
`.github/workflows/release.yml` : tag `v*` → `uv build` → **Trusted Publishing
(OIDC)**, zéro token PyPI stocké.

> ⚠️ Le nom canonique est `nokido-agent` (`pyproject.name`) — c'est ce nom que le
> wheel porte et sous lequel PyPI le recevra. Cette doc a longtemps dit
> `laforge-agent`, hérité du renommage LaForge→Nokido : `pip install laforge-agent`
> n'aurait installé rien du tout. **Action owner sur pypi.org restante** : le
> pending publisher OIDC doit être créé pour le projet `nokido-agent`, pas
> `laforge-agent` — sinon la première publication est refusée (le nom du wheel ne
> correspond pas au projet déclaré).

### Préparation AVANT passage public (à faire une fois)

Décision owner 2026-08-21 : la release part de `user/nokido` (le repo actuel,
où vit déjà `release.yml`). Le pending publisher pointe donc `repo=nokido`, PAS
`Nokido-public` ni `nokido-dist`. Le sdist reste lisible sur PyPI même si le
dépôt Git est privé.

1. **PyPI — pending publisher** (sur pypi.org, compte gratuit + 2FA). Le projet
   n'existe pas encore : un *pending publisher* le créera au 1er upload.
   `Settings → Publishing → Add a pending publisher` :
   - PyPI Project Name : `nokido-agent`
   - Owner : `user` · Repository name : `nokido`  *(minuscule, le vrai nom)*
   - Workflow filename : `release.yml`
   - Environment name : `pypi`
   - → GitHub s'authentifiera via OIDC, aucun secret à stocker.
2. **GitHub — environnement `pypi`** : Settings → Environments → New environment
   → `pypi`. **Restreindre** : *Deployment branches and tags* → **Selected** →
   règle **Tag** `v*`. L'env porte `id-token:write` (le pouvoir de publier) : le
   limiter aux tags `v*` empêche une branche quelconque d'y accéder. Aucun secret,
   aucune variable. Actions débloquées (billing).
3. **Essai à blanc TestPyPI** (recommandé — une version publiée sur PyPI ne peut
   JAMAIS être ré-uploadée) : pending publisher symétrique sur test.pypi.org
   (projet `nokido-agent`, owner `user`, repo `nokido`, workflow `release.yml`,
   environment `testpypi`) + environnement GitHub `testpypi`.
   ⚠️ Restriction de l'env `testpypi` DIFFÉRENTE de `pypi` : le smoke tourne par
   `workflow_dispatch` sur une BRANCHE (`alpha`), pas sur un tag. Sa règle de
   déploiement doit donc être **Branch `alpha`**, PAS **Tag `v*`** — sinon GitHub
   refuse avant même l'OIDC (« Branch alpha is not allowed to deploy to testpypi »).
   Seul `pypi` (déclenché par tag) prend la règle **Tag `v*`**.
   Puis Actions → *Release to PyPI* → **Run workflow** (depuis `alpha`) : publie sur
   TestPyPI, jamais sur PyPI (le job `publish` est gardé `if: github.event_name == 'push'`).
4. **`pyproject.urls`** : Homepage/Repository/Issues/Documentation cohérents avec
   le dépôt réel.
5. **Légal** : dépôt INPI eSoleau via `tools/launch_public_mirror.py --esoleau-zip`
   si passage à un mirror public plus tard (le `--push` refuse sans reçu).

### Publier (le jour J)

```bash
# 1. bump version (pyproject) si besoin, commit
# 2. tag = version (la garde release.yml refuse un mismatch)
git tag v0.18.0 && git push origin v0.18.0
# 3. release.yml : uv build -> twine check -> publish OIDC. C'est tout.
```

---

## Track B — B2B propriétaire → obfusqué (jamais sur PyPI public)

Un `.whl` standard = **source en clair** (`unzip` → tout lisible). La protection
vient de `tools/build_dist.py` :

```bash
LAFORGE_PYTHON tools/build_dist.py --backend pyarmor --mode groups   # bytecode obfusqué
LAFORGE_PYTHON tools/build_dist.py --backend nuitka  --module app/X.py  # binaire natif
```

→ `dist_laforge/` (gitignoré). Distribution : **index privé** (`pypiserver` /
GitHub Packages) OU `.whl` livré directement OU déploiement Docker + clé licence.
**Jamais** via `release.yml` (qui ne publie que le source AGPLv3).

CI : job `build-dist` dans `ci-selfhosted.yml` (workflow_dispatch, runner privé).

---

## CI / gates — état actuel

Actions GitHub-hosted **bloquées** (billing, repo privé). Filets en place :

| Filet | Quand | Couvre |
|---|---|---|
| **`tools/ci_local.py`** | local, pre-push (`--fast`) | flake8 critique + ruff + bandit + pytest pur + pip-audit + gitleaks |
| **`ci-selfhosted.yml`** | runner self-hosted (gratuit) | idem + intégration (services up) + build-dist |
| `ci.yml` / `eco-shield` / `gitleaks` | GitHub-hosted (mort tant que billing) | repartira au déblocage / public |

Installer le runner self-hosted (fallback) :
`pwsh tools/setup_selfhosted_runner.ps1 -Token <token>` (token : Settings →
Actions → Runners → New self-hosted runner).

---

## Checklist pré-publication (rappel)

- [ ] Actions débloquées (billing) **ou** runner self-hosted en ligne **ou** repo public.
- [ ] `ci_local.py` vert (flake8 critique + pytest).
- [ ] `pyproject` : version bumpée, urls → repo public, `uvx twine check dist/*` OK.
- [ ] PyPI pending publisher configuré (owner/repo/workflow/environment).
- [ ] eSoleau déposé (reçu PDF) avant tout push public.
- [ ] Bearers hub rotés, `.gitleaks` vert (pas de secret dans le snapshot public).
