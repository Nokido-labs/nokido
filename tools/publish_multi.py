"""tools/publish_multi.py — Multi-platform publish au go-public AGPLv3.

Source roadmap_multi_platform_publish. Mirror push parallele :
- GitHub (origin, principal)
- Codeberg (mirror EU/sovereignty-friendly)
- GitLab (optionnel - audience differente)
- Sourcehut (optionnel - minimaliste fans)
- HuggingFace Spaces (demo deployment if applicable)

Plus posts auto :
- Show HN draft
- Reddit /r/selfhosted /r/sysadmin posts
- Lobste.rs link
- awesome-* PR drafts

Usage : LAFORGE_PYTHON tools/publish_multi.py --branch alpha --check
        LAFORGE_PYTHON tools/publish_multi.py --branch alpha --push --remotes github,codeberg
        LAFORGE_PYTHON tools/publish_multi.py --miroirs-public [--cibles codeberg,gitlab] [--push]
        LAFORGE_PYTHON tools/publish_multi.py --vitrine-hf [--push]
Les deux derniers modes ne lisent JAMAIS l'atelier comme source de code : miroirs = clone du depot
public GitHub ; vitrine = deux fichiers ecrits pour le public, controles avant envoi.
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/deploy : publication multi-plateforme au go-public AGPLv3"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


REMOTES_CONFIG = {
    "github": {
        "url_template": "https://github.com/{owner}/{repo}",
        "default_owner": "user",
        "default_repo": "Nokido",
    },
    "codeberg": {
        "url_template": "https://codeberg.org/{owner}/{repo}",
        "default_owner": "user",
        "default_repo": "Nokido",
    },
    "gitlab": {
        "url_template": "https://gitlab.com/{owner}/{repo}",
        "default_owner": "user",
        "default_repo": "nokido",
    },
    "sourcehut": {
        "url_template": "https://git.sr.ht/~{owner}/{repo}",
        "default_owner": "user",
        "default_repo": "nokido",
    },
}


# ── MIROIRS DU DEPOT PUBLIC (owner 2026-10-13) ──────────────────────────────────────────────
# « C'est le depot nokido PUBLIC que je veux publier sur ces plateformes » ; « sur codeberg un
# NOUVEAU depot correspondant au public uniquement, pas le depot prive a rendre public ».
# Ce mode ne touche JAMAIS l'atelier (ROOT) : sa source est le depot public GitHub, clone sans
# authentification. Rien de plus que ce qui est deja public ne peut donc partir. Le mode
# historique ci-dessous (push_remote) pousse, lui, DEPUIS l'atelier : il ne sert pas aux miroirs.
SOURCE_PUBLIQUE = "https://github.com/Nokido-labs/nokido.git"
_DESCRIPTION = ("Nokido -- runtime d'organisme local-first. Miroir du depot public "
                "github.com/Nokido-labs/nokido")
MIROIRS_PUBLICS = {
    "codeberg": {"url": "https://codeberg.org/user/nokido-public.git", "hote": "https://codeberg.org",
                 "secret": "CODEBERG_TOKEN", "user": "user"},
    "gitlab": {"url": "https://gitlab.com/naarobb/nokido.git", "hote": "https://gitlab.com",
               "secret": "GITLAB_TOKEN", "user": "oauth2"},
    "sourceforge": {"url": "ssh://user@git.code.sf.net/p/nokido/code",
                    "cle_ssh": "~/.ssh/id_rsa", "secret_phrase": "SOURCEFORGE_SSH_PASSKEY"},
}
# `main` et les tags SEULEMENT : un clone de GitHub porte aussi refs/pull/*, que les autres forges refusent, et des
# branches JETABLES (essai/installation-complete, dependabot/*) reecrites a chaque essai -- mesure du 2026-10-14,
# publication 0.20.11 : SourceForge, Codeberg et GitLab ont refuse essai/** en non fast-forward (push rc=1 alors que
# main et le tag etaient bien partis). Rien de cela n'a sa place dans un miroir de version.
_REFSPECS = ["refs/heads/main:refs/heads/main", "refs/tags/*:refs/tags/*"]


def _secret(nom: str):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_secrets import get_secret
    return get_secret(nom)


def _env_et_cred(m: dict, tmp: Path) -> tuple:
    """(env, args git). Le jeton passe par l'ENVIRONNEMENT et un helper cible par HOTE, jamais par
    l'URL ni par argv : le hub journalise les args (motif de forge_push_sovereign._cred_args)."""
    import os
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    args: list = []
    if m.get("hote"):
        jeton = _secret(m["secret"])
        if not jeton:
            raise RuntimeError("aucun jeton %s au coffre" % m["secret"])
        env["NOKIDO_MIROIR_JETON"] = jeton
        args = ["-c", "credential.helper=", "-c",
                'credential.%s.helper=!f() { echo username=%s; echo "password=$NOKIDO_MIROIR_JETON"; }; f'
                % (m["hote"], m["user"])]
    elif m.get("cle_ssh"):
        cle = Path(os.path.expanduser(m["cle_ssh"]))
        if not cle.exists():
            raise RuntimeError("cle SSH ILLISIBLE pour ce compte : %s" % cle)
        env["NOKIDO_MIROIR_PHRASE"] = _secret(m["secret_phrase"]) or ""
        ask = tmp / "askpass.cmd"   # ne contient AUCUN secret : il relit l'environnement
        ask.write_text("@echo %NOKIDO_MIROIR_PHRASE%\n", encoding="ascii")
        env.update(SSH_ASKPASS=str(ask), SSH_ASKPASS_REQUIRE="force", DISPLAY="nokido:0",
                   GIT_SSH_COMMAND='ssh -i "%s" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new'
                   % cle)
    return env, args


def _git(args: list, env: dict, timeout: int = 900):
    return subprocess.run(["git", *args], env=env, capture_output=True, text=True, errors="replace",
                          timeout=timeout)


def _distant_sha(url: str, branche: str, env: dict, cred: list):
    """sha de la branche sur le DISTANT ; '' = depot joignable sans cette branche ; None = ILLISIBLE
    (depot absent, acces refuse ou reseau : le rc ne dit pas lequel, on ne choisit pas a sa place)."""
    r = _git([*cred, "ls-remote", url, "refs/heads/" + branche], env, timeout=120)
    if r.returncode:
        return None
    return (r.stdout.split() or [""])[0]


def _creer_cible(nom: str, m: dict, agir: bool) -> str:
    """Etat de la cible ; agir=True la cree EN PUBLIC si elle manque. Une cible qui existe en prive
    n'est PAS basculee : le rapport le dit et la visibilite reste une decision owner."""
    import requests
    from urllib.parse import quote
    if nom == "codeberg":
        h = {"Authorization": "token %s" % _secret(m["secret"])}
        chemin = m["url"].split("codeberg.org/", 1)[1].removesuffix(".git")
        r = requests.get("https://codeberg.org/api/v1/repos/" + chemin, headers=h, timeout=30)
        if r.status_code == 200:
            return "existe:prive" if r.json().get("private") else "existe:public"
        if not agir:
            return "absente(http %s)" % r.status_code
        r = requests.post("https://codeberg.org/api/v1/user/repos", headers=h, timeout=30,
                          json={"name": chemin.split("/")[1], "private": False, "auto_init": False,
                                "description": _DESCRIPTION})
        return "creee:public" if r.status_code == 201 else "refus_creation(http %s)" % r.status_code
    if nom == "gitlab":
        h = {"Authorization": "Bearer %s" % _secret(m["secret"])}
        chemin = m["url"].split("gitlab.com/", 1)[1].removesuffix(".git")
        r = requests.get("https://gitlab.com/api/v4/projects/" + quote(chemin, safe=""), headers=h, timeout=30)
        if r.status_code == 200:
            return "existe:%s" % r.json().get("visibility")
        if not agir:
            return "absente(http %s)" % r.status_code
        nom_projet = chemin.split("/")[1]
        r = requests.post("https://gitlab.com/api/v4/projects", headers=h, timeout=30,
                          json={"name": nom_projet, "path": nom_projet, "visibility": "public",
                                "initialize_with_readme": False, "description": _DESCRIPTION})
        return "creee:public" if r.status_code == 201 else "refus_creation(http %s)" % r.status_code
    return "hors_api"   # SourceForge : le projet se cree sur le site, par l'owner


def _miroiter(nom: str, m: dict, nu: Path, branche: str, sha: str, tmp: Path, agir: bool) -> dict:
    etat = {"cible": m["url"]}
    env, cred = _env_et_cred(m, tmp)
    etat["creation"] = _creer_cible(nom, m, agir)
    etat["avant"] = _distant_sha(m["url"], branche, env, cred)
    if not agir:
        etat["verdict"] = "A_JOUR" if etat["avant"] == sha else "A_BLANC"
        return etat
    # Ni --force ni --mirror : un miroir qui diverge le DIT au lieu d'ecraser l'historique distant.
    r = _git([*cred, "--git-dir", str(nu), "push", "--porcelain", m["url"], *_REFSPECS], env, timeout=1800)
    etat["push_rc"] = r.returncode
    if r.returncode:
        etat["push_err"] = r.stderr[-400:]
    etat["apres"] = _distant_sha(m["url"], branche, env, cred)
    etat["verdict"] = ("PUBLIE" if etat["apres"] == sha
                       else "ILLISIBLE" if etat["apres"] is None else "NON_PUBLIE")
    return etat


def miroirs_publics(cibles: list, agir: bool = False) -> dict:
    """Miroite le depot PUBLIC vers les cibles. A blanc par defaut ; agir=True cree les depots
    manquants EN PUBLIC puis pousse. Le verdict se lit sur le DISTANT apres coup, jamais sur un rc."""
    import os
    import tempfile
    rapport: dict = {"source": SOURCE_PUBLIQUE, "agir": agir, "cibles": {}}
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    with tempfile.TemporaryDirectory(prefix="nokido_miroir_") as d:
        tmp = Path(d)
        nu = tmp / "public.git"
        r = _git(["clone", "--bare", "--quiet", SOURCE_PUBLIQUE, str(nu)], env)
        if r.returncode:
            rapport["erreur"] = "clone du depot public impossible : " + r.stderr[-300:]
            return rapport
        branche = _git(["--git-dir", str(nu), "symbolic-ref", "--short", "HEAD"], env).stdout.strip() or "main"
        sha = _git(["--git-dir", str(nu), "rev-parse", "refs/heads/" + branche], env).stdout.strip()
        rapport.update(branche=branche, sha_public=sha)
        for nom in cibles:
            m = MIROIRS_PUBLICS.get(nom)
            if m is None:
                rapport["cibles"][nom] = {"verdict": "CIBLE_INCONNUE"}
                continue
            try:
                rapport["cibles"][nom] = _miroiter(nom, m, nu, branche, sha, tmp, agir)
            except Exception as e:  # noqa: BLE001 - une cible qui casse ne tait pas les autres : elle le DIT
                rapport["cibles"][nom] = {"verdict": "ILLISIBLE", "raison": "%s: %s" % (type(e).__name__, str(e)[:240])}
    return rapport


# ── VITRINE HUGGING FACE (owner 2026-10-13, proposition pair_8daf71b4897c23d8) ────────────────
# Un Space STATIQUE qui presente Nokido et renvoie au depot public ; pas une copie du code, pas un
# depot « model ». Deux fichiers exactement, ecrits pour le public dans vitrine/hf_space/, controles
# avant envoi : aucun motif local ou prive, aucun lien hors liste. Le sha public y est injecte.
VITRINE_HF = {"repo_id": "user/nokido", "secret": "HF_TOKEN", "source": ROOT / "vitrine" / "hf_space",
              "fichiers": ("README.md", "index.html"), "rendu": "https://user-nokido.static.hf.space"}
_LIENS_PERMIS = ("https://github.com/Nokido-labs/nokido", "https://pypi.org/project/nokido-agent",
                 # miroirs du depot public (13/10) : la vitrine les liste, comme les forges renvoient a GitHub
                 "https://codeberg.org/user/nokido-public", "https://gitlab.com/naarobb/nokido",
                 "https://sourceforge.net/projects/nokido", "https://sourceforge.net/p/nokido")
_FUITES = re.compile(r"(?<!\w)[A-Za-z]:[\\/]|/(?:Users|home)/|\b(?:10|127)\.\d+\.\d+\.\d+|\b192\.168\."
                     r"|\b172\.(?:1[6-9]|2\d|3[01])\.|[\w.+-]+@[\w-]+\.[a-z]{2,}|nokido-private|sandbox[\\/]",
                     re.I)


def fuites_vitrine(textes: dict) -> list:
    """Motifs qui ne doivent jamais quitter le poste, et liens hors liste blanche."""
    out = []
    for nom, t in textes.items():
        out += ["%s: motif local ou prive %r" % (nom, m.group(0)) for m in _FUITES.finditer(t)]
        out += ["%s: lien hors liste %s" % (nom, u) for u in re.findall(r"https?://[^\s\"'<>)]+", t)
                if not u.startswith(_LIENS_PERMIS)]
    return out


def vitrine_hf(agir: bool = False) -> dict:
    import os
    import requests
    v = VITRINE_HF
    rapport: dict = {"cible": "huggingface:space/" + v["repo_id"], "agir": agir}
    r = _git(["ls-remote", SOURCE_PUBLIQUE, "refs/heads/main"], dict(os.environ, GIT_TERMINAL_PROMPT="0"), timeout=120)
    sha = (r.stdout.split() or [""])[0] if r.returncode == 0 else ""
    if not sha:
        rapport.update(verdict="ILLISIBLE", raison="sha du depot public illisible")
        return rapport
    rapport["sha_public"] = sha
    presents = sorted(p.name for p in v["source"].iterdir() if p.is_file())
    if presents != sorted(v["fichiers"]):
        rapport.update(verdict="REFUSE", raison="source = exactement %s ; trouve %s" % (list(v["fichiers"]), presents))
        return rapport
    textes = {n: (v["source"] / n).read_text(encoding="utf-8").replace("{{SHA_PUBLIC}}", sha[:12])
              for n in v["fichiers"]}
    fuites = fuites_vitrine(textes)
    if fuites:
        rapport.update(verdict="REFUSE", fuites=fuites)
        return rapport
    from huggingface_hub import CommitOperationAdd, HfApi
    import hashlib
    api = HfApi(token=_secret(v["secret"]))
    # La marque porte le sha public ET l'empreinte du CONTENU : une vitrine retouchee sur un sha inchange
    # (ajout des miroirs, 13/10) ne repartait jamais, la marque du sha seul etant deja presente.
    empreinte = hashlib.sha256("".join(textes[n] for n in v["fichiers"]).encode("utf-8")).hexdigest()[:8]
    marque = "@ %s (contenu %s)" % (sha[:12], empreinte)

    def dernier_titre():
        try:
            c = api.list_repo_commits(v["repo_id"], repo_type="space")
            return c[0].title if c else ""
        except Exception as e:  # noqa: BLE001 - absent OU refuse : ILLISIBLE, pas « vide »
            rapport["lecture"] = type(e).__name__
            return None

    rapport["avant"] = dernier_titre()
    if agir:
        api.create_repo(v["repo_id"], repo_type="space", space_sdk="static", private=False, exist_ok=True)
        if marque not in (rapport["avant"] or ""):
            api.create_commit(v["repo_id"], repo_type="space", commit_message="Vitrine Nokido -- github.com/"
                              "Nokido-labs/nokido " + marque, operations=[CommitOperationAdd(
                                  path_in_repo=n, path_or_fileobj=textes[n].encode("utf-8")) for n in v["fichiers"]])
        rapport["apres"] = dernier_titre()
    distant = rapport.get("apres", rapport["avant"])
    try:   # le rendu PUBLIC, pas seulement le depot : la page servie doit porter le sha
        page = requests.get(v["rendu"], timeout=30)
        rapport["rendu_http"], rendu = page.status_code, page.status_code == 200 and sha[:12] in page.text
    except requests.RequestException as e:
        rapport["rendu_http"], rendu = type(e).__name__, False
    if distant is None:
        rapport["verdict"] = "ILLISIBLE"
    elif marque in distant:
        rapport["verdict"] = "PUBLIE" if rendu else "PUBLIE_RENDU_NON_VU"
    else:
        rapport["verdict"] = "NON_PUBLIE" if agir else "A_BLANC"
    return rapport


# ── INTEGRATION DES FORGES MIROIRS (owner 13/10 : « bonne integration sur codeberg gitlab et sourceforge » ; rubriques
# GitLab « au besoin ») ──────────────────────────────────────────────────────────────────────────────────────────────
# Un miroir n'est pas un second projet : fiche qui renvoie a la source de reference, fonctions qui n'y ont pas de sens
# FERMEES (Auto DevOps et CI/CD -- la CI de reference est celle de GitHub ; tickets et MR renvoyes vers GitHub pour ne
# pas eclater le support), WIKI miroite depuis le wiki public apres le MEME juge de secrets que le code. Chaque reglage
# est RELU sur le distant. Mesure du 13/10 : appliquee a la main une premiere fois (C:/tmp/miroirs), ici rendue rejouable.
WIKI_SOURCE = "https://github.com/Nokido-labs/nokido.wiki.git"
DESCRIPTION_MIROIR = ("Nokido -- local-first runtime for an artificial organism. Read-only mirror of "
                      "https://github.com/Nokido-labs/nokido : issues and contributions there.")
TOPICS_MIROIR = ["local-first", "mcp", "ai-agents", "rag", "multi-agent", "python", "agpl"]
# Surface REDUITE (owner 13/10 « securise un max ») : tout ce qu'un miroir n'utilise pas est ferme -- demandes
# d'acces, registre de conteneurs, paquets, snippets, environnements, feature flags, infrastructure, monitor,
# exigences. Releases et wiki restent ouverts (alignes sur GitHub). Mesure du 13/10 : tous ces acces etaient ouverts.
# CI/CD (owner 13/10 « set up CI/CD ») : builds ACTIFS -- la pipeline part des que le depot public porte
# .gitlab-ci.yml (verification seule, cf. ce fichier) ; variables surchargeables par les seuls mainteneurs, journaux
# publics (aucun secret n'y passe). Auto DevOps reste ferme : il fabriquerait une pipeline que personne n'a ecrite.
FICHE_GITLAB = {"description": DESCRIPTION_MIROIR, "topics": TOPICS_MIROIR, "auto_devops_enabled": False,
                "builds_access_level": "enabled", "public_jobs": True, "restrict_user_defined_variables": True,
                "issues_access_level": "disabled",
                "merge_requests_access_level": "disabled", "wiki_access_level": "enabled",
                "request_access_enabled": False, "container_registry_access_level": "disabled",
                "packages_enabled": False, "snippets_access_level": "disabled",
                "environments_access_level": "disabled", "feature_flags_access_level": "disabled",
                "infrastructure_access_level": "disabled", "monitor_access_level": "disabled",
                "requirements_access_level": "disabled"}
# Protections : main pousse par le seul proprietaire SANS force, tags de version proteges (un tag v* reecrit sur un
# miroir serait une release falsifiee). 30/40 = Developer/Maintainer chez GitLab.
TAGS_PROTEGES = "v*"
# Tickets : l'onglet de chaque miroir RENVOIE vers GitHub (tracker externe) -- un seul support, la source.
TICKETS_GITHUB = "https://github.com/Nokido-labs/nokido/issues"
TRACKER_GITLAB = {"project_url": TICKETS_GITHUB, "issues_url": TICKETS_GITHUB + "/:id",
                  "new_issue_url": TICKETS_GITHUB + "/new"}
FICHE_CODEBERG = {"description": DESCRIPTION_MIROIR, "website": "https://github.com/Nokido-labs/nokido",
                  "has_issues": True, "has_pull_requests": False, "has_wiki": True, "has_projects": False,
                  "has_releases": True,
                  "external_tracker": {"external_tracker_url": TICKETS_GITHUB,
                                       "external_tracker_format": TICKETS_GITHUB + "/{index}",
                                       "external_tracker_style": "numeric"}}


def fiche_conforme(voulu: dict, relu: dict) -> list:
    """Champs divergents. Les topics se comparent en ENSEMBLE insensible a la casse : GitLab rend « RAG » pour « rag »,
    dans son ordre -- les comparer en liste faisait crier FAIL sur une fiche conforme (13/10)."""
    ecarts = []
    for k, v in voulu.items():
        r = relu.get(k)
        if isinstance(v, dict):   # sous-objet (tracker externe) : le serveur ajoute ses champs, on compare les notres
            if any((r or {}).get(sk) != sv for sk, sv in v.items()):
                ecarts.append(k)
        elif isinstance(v, list):
            if {str(x).lower() for x in v} != {str(x).lower() for x in (r or [])}:
                ecarts.append(k)
        elif r != v:
            ecarts.append(k)
    return ecarts


def _egress():
    """`forge_git_egress`, importable QUEL QUE SOIT l'ordre des appels.

    Mesure du 2026-10-14 (publication 0.20.11) : `--integration-forges` est mort en
    `ModuleNotFoundError: nokido_agent` -- on inserait ROOT/app dans sys.path, or le paquet se resout depuis ROOT.
    Le 13/10 la meme commande passait parce qu'un appel anterieur (`_secret`) avait deja insere ROOT dans le
    meme processus : une dependance d'ORDRE, invisible tant que le premier appel restait le meme.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from nokido_agent.app import forge_git_egress as eg
    return eg


def wiki_public_verifie(tmp: Path) -> dict:
    """Clone nu du wiki public + juge de secrets (profil public) sur TOUTES les versions de tous ses fichiers."""
    import os
    eg = _egress()
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    nu = tmp / "wiki.git"
    r = _git(["clone", "--bare", "--quiet", WIKI_SOURCE, str(nu)], env)
    if r.returncode:
        return {"verdict": "ILLISIBLE", "raison": r.stderr[-300:]}
    sha = _git(["--git-dir", str(nu), "rev-parse", "refs/heads/master"], env).stdout.strip()
    profil = (eg.load_manifest().get("profiles") or {}).get("public")
    rouges, lus = [], 0
    for ligne in _git(["--git-dir", str(nu), "rev-list", "--objects", "--all"], env).stdout.splitlines():
        parts = ligne.split(" ", 1)
        if len(parts) != 2:
            continue
        b = subprocess.run(["git", "-c", "safe.directory=*", "--git-dir", str(nu), "cat-file", "-p", parts[0]],
                           capture_output=True)
        try:
            texte = b.stdout.decode("utf-8")
        except UnicodeDecodeError:  # muet-ok : binaire, hors portee d'un scan de texte
            continue
        lus += 1
        if eg.scan_files({parts[1]: texte}, profil)[0] == eg.pg.Severity.RED:
            rouges.append(parts[1])
    return {"verdict": "PASS" if not rouges else "FAIL", "sha": sha, "scannes": lus, "rouges": rouges, "nu": nu}


def _pousser_wiki(nu: Path, cible: str, m: dict, tmp: Path, amorce=None) -> dict:
    """Pousse master du wiki public sur la branche du wiki distant. Force SEULEMENT si le distant ne porte que
    l'amorce (1 commit) ou un ancetre de notre historique : jamais d'ecrasement d'un wiki redige ailleurs."""
    env, cred = _env_et_cred(m, tmp)
    r = _git([*cred, "ls-remote", cible], env)
    if (r.returncode or not r.stdout.strip()) and amorce:
        amorce()   # Forgejo ne cree le depot wiki qu'a la premiere page
        r = _git([*cred, "ls-remote", cible], env)
    branches = [l.split()[1] for l in r.stdout.splitlines() if len(l.split()) == 2
                and l.split()[1].startswith("refs/heads/")] or ["refs/heads/main"]
    specs = []
    for b in branches:
        court = b.split("/")[-1]
        _git([*cred, "--git-dir", str(nu), "fetch", "--quiet", cible, "+%s:refs/distant/%s" % (b, court)], env)
        n = _git(["--git-dir", str(nu), "rev-list", "--count", "refs/distant/" + court], env).stdout.strip()
        ancetre = _git(["--git-dir", str(nu), "merge-base", "--is-ancestor", "refs/distant/" + court,
                        "refs/heads/master"], env).returncode == 0
        specs.append(("+" if n == "1" or ancetre else "") + "refs/heads/master:" + b)
    p = _git([*cred, "--git-dir", str(nu), "push", cible, *specs], env)
    apres = _git([*cred, "ls-remote", cible], env).stdout
    return {"push_rc": p.returncode, "erreur": p.stderr[-300:] if p.returncode else "",
            "distant": {l.split()[1]: l.split()[0][:12] for l in apres.splitlines() if len(l.split()) == 2}}


def _notes_miroir(rel: dict) -> str:
    """Notes de la release GitHub + fichiers SERVIS PAR GITHUB avec leur sha256 : le miroir ne duplique aucun binaire
    (une seule source d'artefacts, rien a desynchroniser) et l'empreinte permet de verifier sans le croire."""
    lignes = [(rel.get("body") or "").strip(), "",
              "---", "Mirror of %s — files are served by GitHub, verify them with their sha256:" % rel.get("html_url")]
    for a in rel.get("assets", []):
        lignes.append("- [%s](%s) `%s`" % (a["name"], a["browser_download_url"], (a.get("digest") or "").replace(
            "sha256:", "sha256 ")))
    return "\n".join(lignes)


LOGO_GITHUB = "https://avatars.githubusercontent.com/u/327888127?v=4&s=400"   # avatar de l'organisation Nokido-labs


def logo_miroirs(api_gl: str, gl: dict, api_cb: str, cb: dict, agir: bool) -> dict:
    """Le MEME logo que l'organisation GitHub sur chaque miroir (identite unique). Pose si absent, puis relu."""
    import base64

    import requests
    image = requests.get(LOGO_GITHUB, timeout=30).content
    if agir:
        if not requests.get(api_gl, headers=gl, timeout=30).json().get("avatar_url"):
            requests.put(api_gl, headers=gl, timeout=60, files={"avatar": ("nokido.jpg", image, "image/jpeg")})
        if not requests.get(api_cb, headers=cb, timeout=30).json().get("avatar_url"):
            requests.post(api_cb + "/avatar", headers=cb, timeout=60, json={"image": base64.b64encode(image).decode()})
    return {"gitlab": bool(requests.get(api_gl, headers=gl, timeout=30).json().get("avatar_url")),
            "codeberg": bool(requests.get(api_cb, headers=cb, timeout=30).json().get("avatar_url"))}


def releases_miroirs(api_gl: str, gl: dict, api_cb: str, cb: dict, agir: bool) -> dict:
    """Chaque release publiee de GitHub existe sur GitLab et Codeberg (meme tag, notes, liens, sha256). Relu ensuite."""
    import requests
    from urllib.parse import quote
    rels = [r for r in requests.get("https://api.github.com/repos/Nokido-labs/nokido/releases", timeout=30).json()
            if isinstance(r, dict) and not r.get("draft")]
    out = {"github": sorted(r["tag_name"] for r in rels), "gitlab": {}, "codeberg": {}}
    for rel in rels:
        tag, notes = rel["tag_name"], _notes_miroir(rel)
        url_gl = api_gl + "/releases/" + quote(tag, safe="")
        if requests.get(url_gl, headers=gl, timeout=30).status_code == 404 and agir:
            liens = [{"name": a["name"], "url": a["browser_download_url"], "link_type": "package"}
                     for a in rel.get("assets", [])]
            requests.post(api_gl + "/releases", headers=gl, timeout=30, json={
                "tag_name": tag, "name": rel.get("name") or tag, "description": notes, "assets": {"links": liens}})
        out["gitlab"][tag] = requests.get(url_gl, headers=gl, timeout=30).status_code == 200
        url_cb = api_cb + "/releases/tags/" + quote(tag, safe="")
        if requests.get(url_cb, headers=cb, timeout=30).status_code == 404 and agir:
            requests.post(api_cb + "/releases", headers=cb, timeout=30, json={
                "tag_name": tag, "name": rel.get("name") or tag, "body": notes, "draft": False,
                "prerelease": bool(rel.get("prerelease"))})
        out["codeberg"][tag] = requests.get(url_cb, headers=cb, timeout=30).status_code == 200
    out["verdict"] = "ALIGNE" if all(out["gitlab"].values()) and all(out["codeberg"].values()) else "ECARTS"
    return out


def protections_relues(api_gl: str, gl: dict, api_cb: str, cb: dict) -> dict:
    """Protections RELUES sur le distant : main sans force push, tags v* proteges, sur chaque forge."""
    import requests
    pb = requests.get(api_gl + "/protected_branches", headers=gl, timeout=30).json() or []
    pt = requests.get(api_gl + "/protected_tags", headers=gl, timeout=30).json() or []
    bp = requests.get(api_cb + "/branch_protections", headers=cb, timeout=30).json() or []
    tp = requests.get(api_cb + "/tag_protections", headers=cb, timeout=30).json() or []
    gl_main = any(b.get("name") == "main" and not b.get("allow_force_push") for b in pb)
    cb_main = any((b.get("rule_name") or b.get("branch_name")) == "main" and b.get("enable_push_whitelist")
                  and not b.get("enable_force_push") for b in bp)
    return {"gitlab": {"main": gl_main, "tags": any(t.get("name") == TAGS_PROTEGES for t in pt)},
            "codeberg": {"main": cb_main, "tags": any(t.get("name_pattern") == TAGS_PROTEGES for t in tp)}}


def integrer_forges(agir: bool = False) -> dict:
    """Fiches GitLab et Codeberg conformes et wiki miroite ; a blanc, seuls les ecarts sont rapportes."""
    import base64
    import tempfile
    from urllib.parse import quote

    import requests
    out: dict = {"agir": agir}
    tmp = Path(tempfile.mkdtemp(prefix="integration_forges_"))
    wiki = wiki_public_verifie(tmp)
    out["wiki_source"] = {k: v for k, v in wiki.items() if k != "nu"}
    gl = {"Authorization": "Bearer %s" % _secret("GITLAB_TOKEN")}
    api_gl = "https://gitlab.com/api/v4/projects/" + quote("naarobb/nokido", safe="")
    cb = {"Authorization": "token %s" % _secret("CODEBERG_TOKEN")}
    api_cb = "https://codeberg.org/api/v1/repos/user/nokido-public"
    if agir:
        requests.put(api_gl, headers=gl, json=FICHE_GITLAB, timeout=30)
        requests.patch(api_cb, headers=cb, json=FICHE_CODEBERG, timeout=30)
        requests.put(api_cb + "/topics", headers=cb, json={"topics": TOPICS_MIROIR}, timeout=30)
        requests.put(api_gl + "/integrations/custom-issue-tracker", headers=gl, json=TRACKER_GITLAB, timeout=30)
        if not any(t.get("name") == TAGS_PROTEGES for t in requests.get(api_gl + "/protected_tags", headers=gl,
                                                                         timeout=30).json() or []):
            requests.post(api_gl + "/protected_tags", headers=gl, timeout=30,
                          json={"name": TAGS_PROTEGES, "create_access_level": 40})
        if not requests.get(api_cb + "/branch_protections", headers=cb, timeout=30).json():
            requests.post(api_cb + "/branch_protections", headers=cb, timeout=30, json={
                "rule_name": "main", "enable_push": True, "enable_push_whitelist": True,
                "push_whitelist_usernames": ["user"], "enable_force_push": False})
        if not requests.get(api_cb + "/tag_protections", headers=cb, timeout=30).json():
            requests.post(api_cb + "/tag_protections", headers=cb, timeout=30,
                          json={"name_pattern": TAGS_PROTEGES, "whitelist_usernames": ["user"]})
    out["protections"] = protections_relues(api_gl, gl, api_cb, cb)
    trk = requests.get(api_gl + "/integrations/custom-issue-tracker", headers=gl, timeout=30)
    out["gitlab_tickets_vers_github"] = bool(trk.ok and trk.json().get("active")
                                             and (trk.json().get("properties") or {}).get("project_url") == TICKETS_GITHUB)
    out["releases"] = releases_miroirs(api_gl, gl, api_cb, cb, agir)
    out["logo"] = logo_miroirs(api_gl, gl, api_cb, cb, agir)
    relu_cb = requests.get(api_cb, headers=cb, timeout=30).json()
    relu_cb["topics"] = (requests.get(api_cb + "/topics", headers=cb, timeout=30).json() or {}).get("topics")
    for nom, voulu, relu in (("gitlab", FICHE_GITLAB, requests.get(api_gl, headers=gl, timeout=30).json()),
                             ("codeberg", dict(FICHE_CODEBERG, topics=TOPICS_MIROIR), relu_cb)):
        ecarts = fiche_conforme(voulu, relu)
        out[nom] = {"fiche": "CONFORME" if not ecarts else ("ECARTS" if not agir else "NON_CONFORME"),
                    "ecarts": ecarts}
    if agir and wiki["verdict"] == "PASS":
        sha = wiki["sha"][:12]

        def amorce_cb():
            requests.post(api_cb + "/wiki/new", headers=cb, timeout=30, json={
                "title": "Home", "message": "amorce du wiki miroir",
                "content_base64": base64.b64encode(b"Mirror of the public Nokido wiki.").decode()})

        for nom, cible, m, amorce in (
                ("gitlab", "https://gitlab.com/naarobb/nokido.wiki.git",
                 {"hote": "https://gitlab.com", "secret": "GITLAB_TOKEN", "user": "oauth2"}, None),
                ("codeberg", "https://codeberg.org/user/nokido-public.wiki.git",
                 {"hote": "https://codeberg.org", "secret": "CODEBERG_TOKEN", "user": "user"}, amorce_cb)):
            w = _pousser_wiki(wiki["nu"], cible, m, tmp, amorce)
            w["verdict"] = "PUBLIE" if sha in w["distant"].values() else "NON_PUBLIE"
            out[nom]["wiki"] = w
    elif agir:
        out["wiki_refuse"] = "wiki public non verifie (%s) : rien n'est pousse" % wiki["verdict"]
    return out


def check_remote_exists(remote_name: str) -> bool:
    """Verify git remote configured."""
    try:
        result = subprocess.run(
            ["git", "remote"], cwd=ROOT, capture_output=True, text=True, timeout=10
        , errors="replace")
        return remote_name in result.stdout.split()
    except Exception:
        return False


def push_remote(remote: str, branch: str, force_with_lease: bool = False) -> dict:
    """Push branch to remote. Returns dict with result."""
    if not check_remote_exists(remote):
        return {"remote": remote, "ok": False, "error": "remote not configured"}

    cmd = ["git", "push"]
    if force_with_lease:
        cmd.append("--force-with-lease")
    cmd.extend([remote, branch])

    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60, errors="replace")
        ok = result.returncode == 0
        return {
            "remote": remote,
            "ok": ok,
            "stdout": result.stdout[:500],
            "stderr": result.stderr[:500],
        }
    except Exception as e:
        return {"remote": remote, "ok": False, "error": str(e)}


def gen_show_hn_post(version: str = "0.1") -> str:
    """Generate Show HN post draft."""
    return f"""Show HN: Nokido – Autonomous sovereign AI OS (local-first, AGPLv3)

After 18 months of building, releasing {version} of Nokido: an autonomous
AI operating system designed for sovereignty.

Key differentiators vs OpenHands / AutoGPT / SuperAGI :
- 100% local-first (no cloud telemetry, BGE-M3 embedding local)
- Multi-LLM cascade (Cerebras + Groq + Mistral free tiers + Ollama)
- Veille autonome closed-loop (detect knowledge gaps -> generate themes ->
  ingest papers from OpenAlex/arxiv -> embed)
- LAN observability via netcfg-agent
- TUI Textual v3 + Web HTMX dashboard
- Anti-saturation framework (Job Objects, CPU throttle)
- Sovereign memory architecture (LeCun JEPA + MemGPT-style hierarchical)

Stack : Python 3.14 + Deno 2 + Rust ONNX + Go dispatcher.

GitHub : https://github.com/Nokido-labs/nokido
Demo video : [TODO]

Looking for feedback on architecture, security model, and use cases.
"""


def gen_reddit_post(subreddit: str = "selfhosted") -> str:
    """Reddit post template."""
    return f"""# Nokido - Local-first AI OS with autonomous web monitoring

Just released Nokido (AGPLv3), an AI operating system focused on
self-hosting + sovereignty.

What it does :
- Monitors your interests autonomously (define themes, agent ingests papers)
- LAN observability (devices, services, vulns) via netcfg-agent
- TUI for ops + Web dashboard
- Multi-LLM cascade (free tier cloud + local Ollama fallback)
- All data stays local (BGE-M3 embeddings, FAISS index, SQLite WAL)

Install : docker-compose up
Repo : https://github.com/Nokido-labs/nokido

Target use-cases :
- Self-hosters who want AI ops automation without sending data to OpenAI
- Security teams who need LAN visibility + threat intelligence
- Researchers who want closed-loop knowledge ingestion

Would love feedback from /r/{subreddit} community.
"""


def gen_lobsters_post() -> dict:
    return {
        "title": "Nokido: Autonomous local-first AI OS with closed-loop knowledge ingestion",
        "url": "https://github.com/Nokido-labs/nokido",
        "tags": ["ai", "selfhosted", "python", "security", "agpl"],
    }


def gen_awesome_pr() -> dict:
    """Awesome-list PR snippet."""
    return {
        "awesome-selfhosted": {
            "category": "AI / LLM",
            "entry": "- [Nokido](https://github.com/Nokido-labs/nokido) - "
            "Sovereign local-first AI OS with autonomous web monitoring + LAN observability. "
            "(`Source code`)[https://github.com/Nokido-labs/nokido] `AGPL-3.0` `Docker/Python`",
        },
        "awesome-llm": {
            "category": "Agentic Systems",
            "entry": "- [Nokido](https://github.com/Nokido-labs/nokido) - Closed-loop knowledge ingestion + multi-LLM cascade routing. `AGPL-3.0`",
        },
    }


def dry_run_check(branch: str, remotes: list[str]) -> dict:
    """Pre-flight check : verify branch exists, remotes configured, no unstaged."""
    checks = {}
    # Branch exists locally
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True, timeout=5
        , errors="replace")
        current = result.stdout.strip()
        checks["current_branch"] = current
        checks["target_branch_matches"] = current == branch
    except Exception as e:
        checks["branch_check_err"] = str(e)

    # Remotes configured
    for r in remotes:
        checks[f"remote_{r}"] = check_remote_exists(r)

    # Unstaged changes
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=5
        , errors="replace")
        checks["unstaged_files"] = len(result.stdout.strip().splitlines())
        checks["clean_working_tree"] = result.stdout.strip() == ""
    except Exception as e:  # noqa: BLE001 - l'etat de l'arbre ILLISIBLE n'est pas « propre » : le dire
        checks["clean_working_tree"] = False
        checks["arbre_illisible"] = "%s: %s" % (type(e).__name__, str(e)[:200])

    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="alpha")
    ap.add_argument("--check", action="store_true", help="Dry-run pre-flight check")
    ap.add_argument("--push", action="store_true", help="Actually push (default dry-run)")
    ap.add_argument("--remotes", default="github,codeberg", help="Comma-separated remotes")
    ap.add_argument("--force-with-lease", action="store_true")
    ap.add_argument(
        "--gen-posts", action="store_true", help="Generate post drafts (Show HN/Reddit/etc.)"
    )
    ap.add_argument("--miroirs-public", action="store_true",
                    help="Miroiter le depot PUBLIC (jamais l'atelier) ; a blanc sauf --push")
    ap.add_argument("--cibles", default=",".join(MIROIRS_PUBLICS),
                    help="Cibles des miroirs, separees par des virgules")
    ap.add_argument("--integration-forges", action="store_true",
                    help="fiches GitLab/Codeberg conformes + wiki miroite ; a blanc sauf --push")
    ap.add_argument("--vitrine-hf", action="store_true",
                    help="Space Hugging Face statique (vitrine/hf_space) ; a blanc sauf --push")
    args = ap.parse_args()

    if args.integration_forges:
        rapport = integrer_forges(agir=args.push)
        print(json.dumps(rapport, indent=2, ensure_ascii=False, default=str))
        bons = ("CONFORME",)
        protegees = all(all(v.values()) for v in rapport.get("protections", {}).values())
        ok = (all(rapport.get(n, {}).get("fiche") in bons for n in ("gitlab", "codeberg")) and protegees
              and rapport.get("releases", {}).get("verdict") == "ALIGNE") if args.push else True
        sys.exit(0 if ok else 1)

    if args.vitrine_hf:
        rapport = vitrine_hf(agir=args.push)
        print(json.dumps(rapport, indent=2, ensure_ascii=False))
        sys.exit(0 if rapport.get("verdict") in ("PUBLIE", "A_BLANC") else 1)

    if args.miroirs_public:
        rapport = miroirs_publics([c.strip() for c in args.cibles.split(",") if c.strip()], agir=args.push)
        print(json.dumps(rapport, indent=2, ensure_ascii=False))
        bons = ("PUBLIE", "A_JOUR") if args.push else ("PUBLIE", "A_JOUR", "A_BLANC")
        sys.exit(0 if "erreur" not in rapport
                 and all(c.get("verdict") in bons for c in rapport["cibles"].values()) else 1)

    remotes = [r.strip() for r in args.remotes.split(",")]

    if args.gen_posts:
        print("=== Show HN ===")
        print(gen_show_hn_post())
        print("\n=== Reddit /r/selfhosted ===")
        print(gen_reddit_post("selfhosted"))
        print("\n=== Lobste.rs ===")
        print(json.dumps(gen_lobsters_post(), indent=2))
        print("\n=== Awesome-list PRs ===")
        print(json.dumps(gen_awesome_pr(), indent=2))
        return

    if args.check:
        checks = dry_run_check(args.branch, remotes)
        print(json.dumps(checks, indent=2))
        return

    if args.push:
        # Mandatory pre-flight
        checks = dry_run_check(args.branch, remotes)
        if not checks.get("clean_working_tree", False):
            print(f"REFUSE push : unstaged_files={checks.get('unstaged_files', 0)}")
            sys.exit(1)
        results = []
        for r in remotes:
            res = push_remote(r, args.branch, args.force_with_lease)
            results.append(res)
            status = "OK" if res.get("ok") else "FAIL"
            print(
                f"[{status}] {r}: {res.get('stderr', '')[:200] if not res.get('ok') else 'pushed'}"
            )
        print(json.dumps(results, indent=2))
        return

    ap.print_help()


if __name__ == "__main__":
    main()
