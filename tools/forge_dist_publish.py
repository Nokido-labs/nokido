"""tools/forge_dist_publish.py — recurring publish of one version into the
persistent, SEPARATE distribution repo (nokido-dist). Idempotent, SemVer
tag, push to GitHub (cible verifiee) ; Codeberg en miroir OPT-IN.

Division of labour (anti-dup) :
  - launch_public_mirror.py  -> ONE-SHOT bootstrap (births the public repo,
    single clean-slate commit, eSoleau IP filing). Run ONCE.
  - forge_release_assets.py  -> the downloadable assets (source tarball +
    int8 RAG Knowledge Pack + SHA256SUMS) attached to a Release.
  - THIS                     -> the RECURRING version sync. Snapshot the
    curated beta tip into the persistent dist clone, commit vX.Y.Z on TOP of
    the previous version (history ACCUMULATES), tag, push both remotes.

Model : one commit + one SemVer tag per version. Users `git pull` to update ;
diffs/changelog work. Heavy assets stay OUT of git (attached to the Release).
The dist clone is a SEPARATE repo -> its pushes are NOT subject to the source
repo's egress gate.

Usage :
  LAFORGE_PYTHON tools/forge_dist_publish.py --version 0.1.0
  LAFORGE_PYTHON tools/forge_dist_publish.py --version 0.1.1 --push
  LAFORGE_PYTHON tools/forge_dist_publish.py --version 0.2.0 --with-assets --push
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import datetime as _dt
import tarfile
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent  # source repo (Nokido)
TMP = Path("C:/tmp") if sys.platform == "win32" else Path("/tmp")

# 2026-07-17 : repos RENOMMES laforge-dist -> nokido-dist des deux cotes (GitHub l'etait
# depuis le 08/07 ; Codeberg renomme ce jour via l'API, releases v0.1.0/v0.2.0 preservees).
# Les DEUX forges redirigent l'ancien nom (verifie : l'API Codeberg resout encore
# laforge-dist en 200) -- mais une redirection est un FILET, pas une adresse : elle meurt
# si quelqu'un recree un repo au vieux nom, et le push partirait alors ailleurs EN SILENCE.
# On pointe donc le nom canonique. Cf blackboard CLAUDE_ram_churn_boot_2026-07-17 pour la
# demonstration de ce qu'un lookup perime coute quand personne ne le voit.
DEFAULT_DIST_PATH = TMP / "nokido-dist"
# 2026-09-30 (owner) : la VITRINE publique est GitHub `Nokido-labs/nokido` (ex-nokido-dist,
# renomme ce jour, id 1276398399 inchange ; l'ancien nom redirige). L'atelier source est
# `Nokido-labs/nokido-private`. Le promoteur vise la VITRINE ; le dist-manifest ne nomme
# jamais l'atelier (SOURCE_PUBLIEE).
# 2026-09-20 (owner) : la cible VERIFIEE etait GitHub `Nokido-labs/nokido-dist`.
# Codeberg etait declare « primary (sovereign) » alors qu'il n'est PAS lisible
# depuis ce poste — mesure du jour : `git ls-remote` y demande une
# authentification (« could not read Username »), donc son etat reel est
# INDETERMINE : ni vide, ni porteur. Or `ensure_dist_repo` clone le PREMIER
# remote qui PORTE un historique : laisser une autorite qu'on ne sait pas lire
# en tete, c'est accepter qu'elle gagne le jour ou elle repond. Codeberg devient
# donc OPT-IN (`--with-codeberg`), miroir et non autorite.
#
# `Nokido-labs/nokido-dist` redirige vers `Nokido-labs/nokido` depuis le renommage
# (meme id 1276398399) : on ecrit l'identite CANONIQUE plutot que de dependre d'une
# redirection historique qui peut cesser un jour.
DIST_REPO_GITHUB = "Nokido-labs/nokido"
CODEBERG_URL = "https://codeberg.org/user/nokido-dist.git"   # miroir opt-in (nom Codeberg inchange)
# `source.repository` du dist-manifest.json, qui part AVEC la vitrine publique.
# 2026-09-30 : `Nokido-labs/nokido` y designerait la vitrine elle-meme (ou ce sha
# n'existe pas), et le nom de l'atelier prive n'a pas a y figurer. La preuve de
# provenance est `source.sha` + la certification CI, pas un nom de depot.
SOURCE_PUBLIEE = "atelier prive (non publie)"
DEFAULT_REMOTES = {
    "github": "https://github.com/%s.git" % DIST_REPO_GITHUB,  # cible VERIFIEE
}
# IDENTITE DE PUBLICATION — pseudonyme, jamais l'identite civile.
#
# Mesure du 2026-09-20 sur le distant : 4 commits publies sur 5 portaient
# l'identite civile, le seul correct (2026-07-09) ayant visiblement ete fait A
# LA MAIN. L'outil, lui, l'a toujours eue en dur -- donc chaque promotion
# outillee REGRESSE vers l'identite civile, et la convention ne tenait que
# lorsqu'un humain court-circuitait l'outil. Meme motif que le hostname trouve
# le meme soir : une regle appliquee a la main la ou l'outil fait l'inverse.
#
# Le commit ET le tag annote portent ces valeurs (deux sites, L701 et L724) :
# corriger l'un sans l'autre laisserait l'identite dans l'objet-tag.
AUTHOR_NAME = "user"
# Adresse PSEUDONYME. L'ancienne etait une adresse personnelle (mesuree : ni
# `noreply`, ni liee au pseudonyme), et elle est publiee dans les memes commits
# que l'identite civile. La forme `<handle>@users.noreply.github.com` est
# l'adresse de confidentialite standard de la forge : elle rattache l'auteur au
# compte sans exposer de boite reelle.
AUTHOR_EMAIL = "user@users.noreply.github.com"
# RETIREE le 2026-09-20 : adresse personnelle, remplacee par la ligne ci-dessus.
# Elle avait d'abord ete laissee APRES la nouvelle, donc Python gardait l'ancienne
# et le correctif ne changeait RIEN tout en se relisant comme correct.
# Elle demeure dans l'historique git : retirer de HEAD n'est pas un scrub.
# (Le commentaire la citait encore en clair : retire le 2026-09-30 -- un
# commentaire publie EST une publication.)
SEMVER = re.compile(r"^\d+\.\d+\.\d+([.\-+].+)?$")

# Documents ou un titulaire IDENTIFIABLE est requis (decision owner 2026-09-30) :
# le nom civil y reste. Partout ailleurs, sa presence REFUSE la publication.
IDENTITE_AUTORISEE = frozenset({
    "NOTICE", "docs/CLA.md", "COMMERCIAL.md", "COMMERCIAL.fr.md", "docs/COMMERCIAL_LICENSE.md",
})


_CRED_RE = re.compile(r"(https?://)[^/@\s]*@")


def _sans_secret(s: str) -> str:
    """Retire un credential d'une URL avant tout affichage.

    La sortie de ce script part dans un journal de job, archive ET indexe en
    RAG : une URL complete imprimee la-dedans est un secret publie (mesure
    2026-09-19). Depuis le 2026-09-20 la voie « PAT dans l'URL » est SUPPRIMEE
    (cf. `_refuser_credential_dans_url`) : ce filtre reste en defense en
    profondeur, pour qu'un futur glissement ne publie rien.
    """
    return _CRED_RE.sub(r"\1***@", s or "")


def _refuser_credential_dans_url(nom: str, url: str) -> None:
    """Un credential dans l'URL est INTERDIT, pas seulement decourage.

    Owner 2026-09-20 : cette voie est supprimee, pas rendue non-defaut. Un PAT
    place la finit dans `git remote`, dans `.git/config` et dans argv — trois
    endroits qu'on ne revoque pas, et dont deux survivent au processus. Le
    laisser possible, c'est accepter qu'un appel futur le reprenne par accident.
    """
    if _CRED_RE.search(url or ""):
        raise SystemExit(
            "[auth] REFUS : l'URL du remote %s porte un credential. Cette voie "
            "est SUPPRIMEE — le jeton passe par l'environnement du sous-processus "
            "git, jamais par l'URL (elle finirait dans .git/config et dans argv)."
            % nom)


# Le helper ne repond qu'a git, et il lit le jeton dans l'ENVIRONNEMENT : la
# ligne de commande porte le nom de la variable, JAMAIS sa valeur.
_GIT_CRED_HELPER = ('!f() { test "$1" = get || exit 0; echo username=x; '
                    'echo "password=$GH_TOKEN"; }; f')
# `credential.helper=` vide REINITIALISE la liste heritee avant d'ajouter la
# notre : sans ce premier `-c`, le gestionnaire du compte reste dans la chaine
# et retente un prompt qu'aucun job detache ne peut satisfaire (mesure du jour).
_GIT_AUTH = ["-c", "credential.helper=",
             "-c", "credential.helper=" + _GIT_CRED_HELPER]

# `safe.directory` sur TOUTES les commandes du clone dist, pas seulement sur
# celles du depot source. Mesure du 2026-09-20 : le clone est cree par le compte
# d'un job deporte (SID …-1008) tandis que la publication, qui exige des
# variables d'environnement qu'un `run_job` ne transmet pas, tourne sous un
# autre compte (…-1009). git refuse alors en « detected dubious ownership ».
#
# J'avais ecrit l'INVERSE dans un NR une heure plus tot — « les commandes du
# clone dist n'en ont pas besoin, il appartient au compte qui l'a clone ». Vrai
# tant qu'UN SEUL compte fait tout ; faux des que la chaine en traverse deux, ce
# que la porte de publication impose precisement. Une justification qui tient
# par coincidence se lit comme une regle.
_GIT_DIST = ["git", "-c", "safe.directory=*"]


def _jeton_github() -> str:
    """Jeton du COFFRE, en memoire du parent — fail-closed, et qui DIT pourquoi.

    ABSENT et ILLISIBLE sont distingues : un coffre qu'on n'a pas su lire n'est
    pas un coffre vide. Les deux refusent, mais pas pour la meme raison, et le
    remede n'est pas le meme.

    Pourquoi refuser plutot que continuer : sans credential, la lecture du
    remote echoue, le remote est classe ILLISIBLE, et c'est precisement l'etat
    ou un `git init` fabriquerait un historique ORPHELIN. Mieux vaut s'arreter
    ici, en nommant la cause, que trois etapes plus loin sur un symptome.
    """
    try:
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT / "app"))
        from forge_secrets import get_secret
    except Exception as e:  # noqa: BLE001
        raise SystemExit(
            "[auth] REFUS : coffre INJOIGNABLE (%s). Le depot dist est PRIVE : "
            "sans jeton, rien ne peut etre lu ni publie." % type(e).__name__)
    for cle in ("GH_TOKEN", "GITHUB_TOKEN"):
        try:
            jeton = get_secret(cle)
        except Exception as e:  # noqa: BLE001
            raise SystemExit("[auth] REFUS : coffre ILLISIBLE sur %s (%s)"
                             % (cle, type(e).__name__))
        if jeton:
            print("[auth] jeton lu au coffre (cle %s) — injecte en ENV, "
                  "jamais en URL ni en argv" % cle)
            return jeton
    raise SystemExit(
        "[auth] REFUS : aucun jeton (GH_TOKEN, GITHUB_TOKEN) dans le coffre. "
        "Le depot dist est PRIVE ; sans credential la lecture du remote echoue, "
        "et c'est exactement l'etat ou un `git init` fabriquerait un orphelin.")


def _env_git(base=None) -> dict:
    """Environnement des sous-processus git : jeton + aucun prompt possible."""
    env = dict(base if base is not None else os.environ)
    env["GH_TOKEN"] = _jeton_github()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    return env


def run(cmd, cwd=None, check=True, capture=False, env=None):
    print(f"  $ {_sans_secret(' '.join(cmd))}")
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env,
                       capture_output=capture, text=True, encoding="utf-8",
                       errors="replace")
    if check and r.returncode != 0:
        if capture:
            sys.stderr.write(_sans_secret((r.stdout or "") + (r.stderr or "")))
        raise SystemExit("command failed (%d): %s"
                         % (r.returncode, _sans_secret(' '.join(cmd))))
    return r


def _etat_distant(url: str):
    """('PORTE' | 'VIDE' | 'ILLISIBLE', detail) — un REFUS n'est pas un VIDE.

    Mesure 2026-09-19 : Codeberg refuse tant que le depot est prive (quota), le
    clone echoue, et l'ancien code lisait cet echec comme 'empty/absent remote'
    avant de faire `git init`. Resultat mesure : historique ORPHELIN dans
    C:/tmp/nokido-dist (merge-base rc=1, commit racine independant) qu'aucun push
    non force ne peut publier -- pendant que github/main portait bien v0.2.0.
    """
    # SONDE AUTHENTIFIEE ET NON INTERACTIVE.
    #
    # CORRECTION du 2026-09-20 : j'avais d'abord retire le credential helper en
    # ecrivant qu'« une lecture publique n'en a pas besoin ». C'etait FAUX —
    # `Nokido-labs/nokido-dist` est PRIVE. Ma lecture reussie depuis un autre
    # canal etait authentifiee par un gestionnaire d'identifiants en cache : je
    # n'avais pas eu a taper de mot de passe et j'en avais conclu qu'aucune
    # authentification n'avait eu lieu. Mesure qui tranche, meme compte, meme
    # URL : `git -c credential.helper= ls-remote` rend « could not read
    # Username ». Le manque n'etait donc pas une forme d'appel, c'etait un
    # CREDENTIAL.
    #
    # Le jeton vient du coffre et ne vit que dans l'ENV du sous-processus.
    r = run(["git", *_GIT_AUTH, "ls-remote", "--heads", url],
            check=False, capture=True, env=_env_git())
    if r.returncode != 0:
        return "ILLISIBLE", _sans_secret((r.stderr or r.stdout or "").strip())[:200]
    return ("VIDE" if not (r.stdout or "").strip() else "PORTE"), ""


def _sha_distant(url: str, ref: str):
    """sha de `ref` sur le distant, "" si absente, None si on n'a pas pu lire."""
    r = run(["git", *_GIT_AUTH, "ls-remote", url, ref], check=False,
            capture=True, env=_env_git())
    if r.returncode != 0:
        return None
    ligne = (r.stdout or "").strip().split("\n")[0].strip()
    return ligne.split("\t")[0] if ligne else ""


def ensure_dist_repo(dist: Path, remotes: dict) -> None:
    """Reutilise le clone, sinon clone le PREMIER remote qui PORTE un historique.

    `git init` n'est fait que si TOUS les remotes sont PROUVES vides. Un seul
    remote illisible suffit a refuser : initialiser par-dessus un historique
    qu'on n'a pas pu lire fabrique un orphelin, et l'orphelin ne se voit qu'au
    push, des semaines plus tard.
    """
    for _nom, _url in remotes.items():
        _refuser_credential_dans_url(_nom, _url)
    if not (dist / ".git").exists():
        if dist.exists():
            shutil.rmtree(dist)
        essais, repris = [], None
        for name, url in remotes.items():
            etat, detail = _etat_distant(url)
            if etat == "PORTE":
                # Meme forme que la sonde : depot PRIVE, jeton par l'ENV.
                rc = run(["git", *_GIT_AUTH, "clone", url, str(dist)],
                         check=False, env=_env_git()).returncode
                if rc == 0:
                    repris = name
                    break
                etat, detail = "ILLISIBLE", "clone rc=%d malgre des refs presentes" % rc
            essais.append((name, etat, detail))
        if repris is None:
            if any(e != "VIDE" for _n, e, _d in essais):
                raise SystemExit(
                    "[dist] REFUS : impossible de partir d'un historique connu.\n"
                    + "\n".join("    %-10s %-10s %s" % (n, e, d) for n, e, d in essais)
                    + "\n  Un remote ILLISIBLE n'est PAS un remote vide. `git init` ici "
                      "fabriquerait un historique orphelin, impossible a publier sans "
                      "--force. Rendre le remote lisible, ou le retirer de la liste.")
            print("[dist] tous les remotes sont PROUVES vides -> premiere publication")
            dist.mkdir(parents=True, exist_ok=True)
            run([*_GIT_DIST, "init", "-b", "main"], cwd=dist)
        else:
            print("[dist] historique repris depuis %s" % repris)
    for name, url in remotes.items():
        has = run([*_GIT_DIST, "remote", "get-url", name], cwd=dist,
                  check=False, capture=True).returncode == 0
        run([*_GIT_DIST, "remote", "set-url" if has else "add", name, url],
            cwd=dist)
    run([*_GIT_DIST, "fetch", "--all", "--tags"], cwd=dist, check=False)


def _appliquer_politique_publique(dist: Path) -> None:
    """Retire de l'arbre extrait TOUT chemin bloque par le profil public.

    POURQUOI C'EST ICI ET PAS AILLEURS. Le push de ce dist va vers un depot
    SEPARE (nokido-dist) : il n'est donc PAS soumis au gate egress du depot
    source (`forge_git_egress`), qui ne tourne que sur un push d'origin. Sans
    cette etape, `git archive` (export-ignore seul) recopierait des fichiers que
    la politique de publication interdit -- docs/ip, .agents, config env-
    specifique, seed, etc. -- et ils partiraient au public sans qu'aucun garde
    ne les voie. On applique donc ICI la MEME autorite, `blocked_paths` du profil
    public, avec le MEME `_path_blocked` que le gate : un seul juge.

    FAIL-CLOSED : politique illisible -> on refuse de publier (RuntimeError).
    """
    try:
        from nokido_agent.app import forge_git_egress as _eg
    except Exception:
        import sys as _s
        _s.path.insert(0, str(ROOT / "app"))
        import forge_git_egress as _eg  # type: ignore[no-redef]
    profil = (_eg.load_manifest().get("profiles") or {}).get("public")
    if not profil:
        raise RuntimeError("profil « public » absent du manifeste — publication refusee")
    motifs = profil.get("blocked_paths") or []
    # IP_CLEARANCE : documents LIBERES nommement (owner 2026-09-30).
    degages = set((profil.get("ip_clearance") or {}).keys())

    def _fichiers_hors_git():
        for racine, dossiers, fichiers in os.walk(dist):
            if ".git" in dossiers:
                dossiers.remove(".git")   # ne jamais descendre dans .git
            for nom in fichiers:
                ap = Path(racine) / nom
                yield ap, ap.relative_to(dist).as_posix()

    retires = 0
    par_regle: dict = {}
    for ap, rel in list(_fichiers_hors_git()):
        r = _eg._path_blocked(rel, motifs, degages)
        if r:
            ap.unlink()
            retires += 1
            cle = str(r if isinstance(r, str) else "?")
            par_regle[cle] = par_regle.get(cle, 0) + 1
    print(f"[politique] {retires} fichier(s) retire(s) par blocked_paths "
          f"(profil public) : {par_regle}")

    # Defense : plus AUCUN chemin bloque ne subsiste dans l'arbre a publier.
    restants = [rel for _ap, rel in _fichiers_hors_git()
                if _eg._path_blocked(rel, motifs, degages)]
    if restants:
        raise RuntimeError("chemins bloques survivants dans le dist : %s" % restants[:10])

    # Cap de taille du profil : un fichier trop gros ne part pas en silence.
    cap = int(profil.get("max_file_bytes") or 0)
    if cap:
        trop = [rel for ap, rel in _fichiers_hors_git() if ap.stat().st_size > cap]
        if trop:
            raise RuntimeError("fichier(s) au-dessus du cap public %d o : %s" % (cap, trop[:10]))


# ---------------------------------------------------------------------------
# Generisation des chemins owner -> variables d'environnement.
# Le depot de REFERENCE n'est JAMAIS touche : ce transform s'applique au
# SNAPSHOT dist (clone separe), APRES blocked_paths, avant commit/push.
# Convention (owner 2026-09-15) : variables d'env -- elles s'expansent dans les
# lanceurs .bat/.ps1, et restent des placeholders lisibles dans .py/.md.
# ---------------------------------------------------------------------------
# ordre = specificite DECROISSANTE ; separateurs \, / et \\ captes par [\\/]+
# Limite AVANT un nom de machine : pas de lettre ni de chiffre juste avant (un
# `_` ou un `-` comptent comme limite -- `\b` ne voyait pas `user_DESKTOP-...`), OU
# un echappement litteral `\n` / `\t` / `\r` (lookbehind de largeur fixe 2).
_AVANT_NOM = r"(?:(?<=\\[ntr])|(?<![A-Za-z0-9]))"
_GEN_SUBS = [
    (re.compile(r"C:[\\/]+Users[\\/]+user[\\/]+Script python IA[\\/]+Nokido", re.I), "%NOKIDO_ROOT%"),
    (re.compile(r"C:[\\/]+Users[\\/]+user[\\/]+Script python IA", re.I), "%NOKIDO_WORKSPACE%"),
    (re.compile(r"C:[\\/]+Users[\\/]+user", re.I), "%USERPROFILE%"),
    (re.compile(r"\bV:[\\/]", re.I), "%NOKIDO_DATA%\\"),
    (re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"), "localhost"),
    (re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "localhost"),
    (re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"), "localhost"),
    (re.compile(r"\bNaarob\b", re.I), "user"),
    # Le NOM DE MACHINE, trouve dans l'arbre PUBLIE par la verification J' du
    # 2026-09-20 : 4 fichiers du dist portaient le hostname reel, alors que
    # d'autres portaient deja `DESKTOP-…` ou `DESKTOP-XXXX`. La regle existait
    # donc dans les tetes et avait ete appliquee A LA MAIN par endroits, jamais
    # outillee — c'est la forme la plus trompeuse d'une convention : elle a
    # l'air tenue partout ou on regarde.
    #
    # MOTIF generique et non litteral : inscrire le hostname ici le ferait
    # entrer dans la source publiee (comme `user` y est deja), et ne
    # couvrirait que CETTE machine. Un motif couvre aussi la suivante.
    # `(?!XXXX)` : le motif recomptait son propre remplacant a chaque passe.
    # `_AVANT_NOM` : un echappement LITTERAL (`\n`, `\t`, `\r` ecrits dans un JSON
    # serialise) colle son `n`/`t`/`r` au nom -- `\b` n'y voit alors aucune limite.
    # Mesure du 2026-09-30 : perf_history/ami_py312_baseline.json portait
    # `\\n\\tDESKTOP-.../user`, rate par la generisation ET la defense residuelle.
    (re.compile(_AVANT_NOM + r"DESKTOP-(?!XXXX\b)[A-Z0-9]{4,}\b"), "DESKTOP-XXXX"),
    # La MEME machine en minuscules : `whoami` rend `desktop-xxxxxxx\compte`.
    # Mesure du 2026-09-30 : v0.20.2 publiee le portait dans 9 fichiers, le motif
    # majuscule seul le laissait passer. Insensible a la casse mais BORNE a la
    # forme des noms generes par Windows (7 caracteres dont un chiffre) : sans
    # borne, `Claude-Desktop-03052026` ou `claude-desktop-stdio` seraient reecrits.
    (re.compile(_AVANT_NOM + r"desktop-(?=[a-z0-9]{0,6}\d)[a-z0-9]{7}\b", re.I), "desktop-xxxx"),
    # SID d'une machine/compte local (S-1-5-21-<3 blocs>-<rid>) : l'identifie autant
    # que son nom (meme ligne, meme fichier, meme date). Les SID bien connus
    # (S-1-5-18, S-1-5-32-544...) ne designent aucune machine et restent intacts.
    (re.compile(r"\bS-1-5-21-\d{6,10}-\d{6,10}-\d{6,10}(?:-\d+)?\b"), "S-1-5-21-XXXX"),
]
# apres coup, plus AUCUN de ces marqueurs ne doit subsister en clair (defense)
_GEN_RESIDUEL = re.compile(
    r"C:[\\/]+Users[\\/]+user|\bV:[\\/]|\bNaarob\b|\b192\.168\.\d{1,3}\.\d{1,3}\b|"
    r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b|"
    r"(?:(?<=\\[ntr])|(?<![A-Za-z0-9]))desktop-(?=[a-z0-9]{0,6}\d)[a-z0-9]{7}\b|"
    r"\bS-1-5-21-\d{6,10}-\d{6,10}-\d{6,10}", re.I)
_GEN_BIN_EXT = {
    ".gif", ".png", ".jpg", ".jpeg", ".webm", ".webp", ".ico", ".pdf", ".zip",
    ".gz", ".tar", ".7z", ".db", ".sqlite", ".npz", ".npy", ".prof", ".pyc",
    ".pyd", ".dll", ".so", ".exe", ".bin", ".woff", ".woff2", ".ttf", ".mp4", ".jar",
}
_GEN_NOTE = (
    "# Chemins & variables d'environnement\n\n"
    "Ce depot public est generalise : les chemins specifiques a la machine\n"
    "d'origine sont remplaces par des variables d'environnement, a definir\n"
    "pour votre poste.\n\n"
    "| Variable | Role | Exemple |\n"
    "|---|---|---|\n"
    "| `%NOKIDO_ROOT%` | racine du depot Nokido | `C:\\Nokido` ou `~/nokido` |\n"
    "| `%NOKIDO_WORKSPACE%` | dossier parent (workspace) | `C:\\dev` |\n"
    "| `%NOKIDO_DATA%` | stockage donnees (embeddings, RAG) | `D:\\NokidoData` |\n"
    "| `%USERPROFILE%` | profil utilisateur (natif Windows) | `C:\\Users\\vous` |\n\n"
    "Les lanceurs `.bat`/`.ps1` expansent ces variables au runtime. Dans le\n"
    "code Python et la doc, ce sont des placeholders a adapter (ou via\n"
    "`os.path.expandvars`).\n"
)


def generiser_texte(txt: str) -> tuple[str, int]:
    """Remplace les marqueurs machine par des variables d'env. Pur, testable."""
    n = 0
    for rx, repl in _GEN_SUBS:
        # remplacement par CALLABLE : le template re interprete '\' (bad escape
        # sur %NOKIDO_DATA%\). Un callable rend la chaine LITTERALE.
        txt, k = rx.subn(lambda _m, _r=repl: _r, txt)
        n += k
    return txt, n


def _generiser_chemins_owner(dist: Path) -> None:
    """Generise le SNAPSHOT dist (repo source INTACT). Applique APRES
    blocked_paths. Fail-closed si un chemin owner absolu subsiste en clair."""
    def _fichiers_hors_git():
        for racine, dossiers, fichiers in os.walk(dist):
            if ".git" in dossiers:
                dossiers.remove(".git")
            for nom in fichiers:
                yield Path(racine) / nom

    modifies = occ = 0
    binaires_marques: list = []
    for ap in _fichiers_hors_git():
        if ap.suffix.lower() in _GEN_BIN_EXT:
            try:
                if b"user" in ap.read_bytes():
                    binaires_marques.append(ap.relative_to(dist).as_posix())
            except Exception:
                pass
            continue
        try:
            txt = ap.read_text(encoding="utf-8")
        except Exception:
            continue                       # non-texte non liste : on laisse
        if "\x00" in txt:
            continue
        neuf, k = generiser_texte(txt)
        if k:
            ap.write_text(neuf, encoding="utf-8")
            modifies += 1
            occ += k
    (dist / "PATHS.md").write_text(_GEN_NOTE, encoding="utf-8")
    print(f"[generisation] {modifies} fichier(s), {occ} marqueur(s) machine "
          f"-> variables d'env ; note PATHS.md ecrite")
    if binaires_marques:
        print("[generisation] AVERTISSEMENT binaires marques (non transformables) : "
              f"{binaires_marques}")

    residuels: list = []
    for ap in _fichiers_hors_git():
        rel = ap.relative_to(dist).as_posix()
        # Le CHEMIN aussi. Mesure du 2026-09-30 : 3 sorties Cython suivies sous
        # `app/build_cython/Users/<owner>/...` sont parties dans v0.20.2 et
        # v0.20.3 -- seuls les CONTENUS etaient lus. Un nom de fichier ne se
        # generise pas (il casserait les references) : il se REFUSE, et la
        # correction passe par blocked_paths.
        mp = _GEN_RESIDUEL.search(rel)
        if mp:
            residuels.append([rel, "nom de fichier"])
            continue
        if ap.suffix.lower() in _GEN_BIN_EXT or ap.name == "PATHS.md":
            continue
        try:
            txt = ap.read_text(encoding="utf-8")
        except Exception:
            continue
        if "\x00" in txt:
            continue
        m = _GEN_RESIDUEL.search(txt)
        if m:
            residuels.append([ap.relative_to(dist).as_posix(), m.group(0)])
    if residuels:
        raise RuntimeError("chemins owner residuels apres generisation : %s"
                           % residuels[:10])


# Workflows qui PARTENT dans le dist, malgre l'export-ignore de
# `.github/workflows/` : le dist est l'EDITEUR TestPyPI (owner 2026-09-30), il
# doit donc porter son workflow de publication. Liste BLANCHE : la CI
# self-hosted et le reste de `.github/workflows/` restent hors du dist.
# installation-complete.yml (2026-10-07) : acceptation de l'installation complete sur runners heberges vierges.
WORKFLOWS_DIST = (".github/workflows/release.yml", ".github/workflows/installation-complete.yml")


def _embarquer_workflows_dist(rev: str, dist: Path) -> None:
    """Rapporte les workflows de `WORKFLOWS_DIST` depuis `rev` — le SHA PROMU,
    jamais le worktree : l'archive et le workflow doivent decrire le meme
    commit. Un workflow absent de `rev` fait echouer la promotion (check=True) :
    un editeur sans workflow de publication ne publierait rien, en silence."""
    for rel in WORKFLOWS_DIST:
        r = run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "show",
                 f"{rev}:{rel}"], capture=True)
        cible = dist / rel
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(r.stdout, encoding="utf-8", newline="")
        print(f"[sync] workflow embarque : {rel}")


def _verifier_identite_civile(dist: Path, motifs=None) -> None:
    """Fail-closed : l'identite civile de l'owner hors `IDENTITE_AUTORISEE` refuse
    la publication -- contenus ET noms de fichiers.

    Mesure du 2026-09-30, avant le passage en public : 28 fichiers du dist la
    portaient, dont du code (motifs de caviardage, identifiant Kaggle en dur) --
    aucun garde ne la cherchait. Les motifs viennent de la liste PRIVEE
    (`forge_git_egress.identites_privees`), jamais du code publie. Liste vide ou
    illisible -> refus : sans elle, rien ne garantit que le nom ne part pas.
    """
    if motifs is None:
        try:
            from nokido_agent.app import forge_git_egress as _eg
        except Exception:
            sys.path.insert(0, str(ROOT / "app"))
            import forge_git_egress as _eg  # type: ignore[no-redef]
        motifs = _eg.identites_privees()
        if not motifs:
            raise RuntimeError("[identite] liste privee vide ou illisible (config/identites_privees.txt) "
                               ": publication refusee")
    trouves = []
    for racine, dossiers, fichiers in os.walk(dist):
        if ".git" in dossiers:
            dossiers.remove(".git")
        for nom in fichiers:
            ap = Path(racine) / nom
            rel = ap.relative_to(dist).as_posix()
            if rel in IDENTITE_AUTORISEE:
                continue
            if any(m.search(rel) for m in motifs):
                trouves.append(rel + " (nom de fichier)")
                continue
            if ap.suffix.lower() in _GEN_BIN_EXT:
                continue
            try:
                txt = ap.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):  # muet-ok : non-texte, deja couvert par le cap et les binaires
                continue
            if any(m.search(txt) for m in motifs):
                trouves.append(rel)
    print(f"[identite] {len(trouves)} fichier(s) portant l'identite civile hors documents juridiques")
    if trouves:
        raise RuntimeError("identite civile hors documents juridiques : %s" % trouves[:15])


def _scanner_secrets(dist: Path) -> None:
    """Fail-closed : un signal ROUGE (secret) sur un fichier du dist refuse la
    publication. MEME juge que le gate egress (`forge_git_egress.scan_files`),
    profil public et sa liste blanche `secret_allow` (fixtures epinglees par
    chemin + label).

    Owner 2026-09-30 : dist « pleinement fonctionnel, pas bride » -- la politique
    ne bloque plus config/clients, cline_mcp_settings, jea, seed... Le push du dist
    ne passe PAS par le gate egress (depot separe) : sans ce scan, un jeton dans
    une config rouverte partirait sans qu'aucun garde ne le voie. Les signaux
    JAUNES (entropie, fuite hote/IP) sont COMPTES, pas bloquants : empreintes et
    polices en produisent a foison. Aucune valeur n'est affichee, seuls les chemins.
    """
    try:
        from nokido_agent.app import forge_git_egress as _eg
    except Exception:
        sys.path.insert(0, str(ROOT / "app"))
        import forge_git_egress as _eg  # type: ignore[no-redef]
    profil = (_eg.load_manifest().get("profiles") or {}).get("public")
    if not profil:
        raise RuntimeError("profil « public » absent du manifeste — publication refusee")
    rouges, jaunes, lus = [], 0, 0
    for racine, dossiers, fichiers in os.walk(dist):
        if ".git" in dossiers:
            dossiers.remove(".git")
        for nom in fichiers:
            ap = Path(racine) / nom
            if ap.suffix.lower() in _GEN_BIN_EXT:
                continue
            try:
                txt = ap.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):  # muet-ok : non-texte, hors portee d'un scan de texte
                continue
            rel = ap.relative_to(dist).as_posix()
            lus += 1
            pire, _constats = _eg.scan_files({rel: txt}, profil)
            if pire == _eg.pg.Severity.RED:
                rouges.append(rel)
            elif pire == _eg.pg.Severity.YELLOW:
                jaunes += 1
    print(f"[secrets] {lus} fichier(s) texte scannes : {len(rouges)} ROUGE(s), "
          f"{jaunes} jaune(s) (entropie / hote, non bloquants)")
    if rouges:
        raise RuntimeError("secret(s) dans le dist, publication refusee : %s" % rouges[:15])


def sync_snapshot(branch: str, dist: Path) -> None:
    """Replace dist working tree with the curated beta snapshot (export-ignore
    PUIS blocked_paths du profil public -- le push dist contourne le gate egress)."""
    for entry in dist.iterdir():
        if entry.name == ".git":
            continue
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    tar_tmp = TMP / "_dist_snapshot.tar"
    print(f"[sync] git archive {branch} (honors export-ignore)")
    # `-c safe.directory=*` : SANS lui, cette commande meurt en « detected
    # dubious ownership » des qu'elle tourne sous un compte qui n'est pas le
    # proprietaire du depot -- c'est-a-dire dans TOUT job detache. Mesure du
    # 2026-09-19 : rc=128, et la construction du dist s'arretait la, si bien
    # que le gate de scrub du profil public ne pouvait meme pas etre MESURE.
    #
    # La portee est volontairement locale a cet appel (`-c`), jamais `--global`
    # : on leve la garde de git pour lire CE depot, pas pour la machine.
    run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "archive", "--format=tar", branch,
         "-o", str(tar_tmp)])
    with tarfile.open(tar_tmp) as t:
        t.extractall(dist, filter="data")
    tar_tmp.unlink()
    # AVANT la politique publique : le workflow embarque se juge comme tout
    # autre fichier (chemins bloques, cap de taille).
    _embarquer_workflows_dist(branch, dist)
    _appliquer_politique_publique(dist)
    _generiser_chemins_owner(dist)
    _verifier_identite_civile(dist)
    _scanner_secrets(dist)


def _nom_du_paquet(source_sha: str | None = None) -> str | None:
    """Nom du paquet declare dans le `pyproject.toml` de la SOURCE promue."""
    return _version_declaree("pyproject.toml", r'^name\s*=\s*"([^"]+)"', source_sha)


def _sha_du_depot(chemin: Path) -> str | None:
    """HEAD d'un depot, ou None — jamais '' pour dire « inconnu »."""
    r = run(["git", "-c", "safe.directory=*", "-C", str(chemin), "rev-parse", "HEAD"],
            capture=True, check=False)
    sha = (r.stdout or "").strip()
    return sha if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", sha) else None


def _revision_du_promoteur() -> str:
    """Avec QUEL promoteur la promotion a ete faite — pour la REJOUER.

    Ce n'est PAS une condition de certification du produit : le promoteur n'est
    pas le sujet promu (owner 2026-09-20). Un arbre de promoteur MODIFIE est
    signale : une promotion faite depuis du code non commite n'est pas rejouable,
    et le taire laisserait croire l'inverse.
    """
    sha = _sha_du_depot(ROOT)
    if sha is None:
        return "ILLISIBLE"
    sale = run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "status",
                "--porcelain", "--untracked-files=no"], capture=True, check=False)
    return sha + ("+arbre_modifie" if (sale.stdout or "").strip() else "")


def _lire_certification(dossier, source_sha: str) -> dict:
    """Preuves de certification de S, PAR PORTEE — chacune dit ce qu'elle etablit.

    Mesure 2026-09-20 : le registre de generation annonce « toutes les suites
    FOURNIES sont vertes » et n'en contient QU'UNE (`ruff critique`). Les 10 909
    tests vivent dans les JUnit. Un champ unique `ci_proof_hash` aurait donc
    herite d'un libelle qui promet bien plus que sa charge.

    REFUSE si des registres existent mais qu'aucun ne porte sur S : une preuve
    qui n'est pas celle de la source promue ne certifie pas cette source.
    """
    import hashlib
    import json as _json
    if not dossier:
        return {"etat": "ABSENTE",
                "motif": "aucun --certification fourni : cette promotion n'est "
                         "adossee a aucune preuve lisible",
                "generation_proof": None, "junit_proof": None}
    # Un chemin RELATIF se resout contre la RACINE du depot, comme tous les
    # autres chemins declaratifs de cet outil (`pyproject.toml`,
    # `.git-publish-rules.json`). Sans cette regle, le meme argument marchait a
    # la main et echouait en job detache, dont le repertoire courant n'est pas
    # la racine — mesure du 2026-09-20. Le refus NOMME les deux chemins : « non
    # trouve » sans dire OU l'on a cherche n'est pas un diagnostic.
    d = Path(dossier)
    if not d.is_absolute():
        d = ROOT / d
    if not d.is_dir():
        raise SystemExit(
            "[certification] dossier introuvable.\n"
            "  demande : %s\n  resolu  : %s\n"
            "  (un chemin relatif est resolu contre la racine du depot)"
            % (dossier, d))

    def emp(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    # On parcourt TOUS les registres, sans s'arreter au premier qui correspond.
    # Avec un `break`, la liste des illisibles ne couvrait que ceux examines
    # AVANT la correspondance : un denominateur partiel qui se lit comme complet
    # (trouve par son propre NR, 2026-09-20). Le balayage complet permet en
    # outre de voir si PLUSIEURS registres pretendent porter sur la meme source.
    registres = sorted(d.glob("generations/GEN-*.json"))
    gen, registres_illisibles, correspondants = None, [], []
    for f in registres:
        try:
            o = _json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            # Un registre CORROMPU se NOMME. Le commentaire precedent disait
            # « compte plus bas » — il ne l'etait pas : la promesse tenait dans
            # le commentaire et nulle part dans le code.
            registres_illisibles.append("%s (%s)" % (f.name, type(ex).__name__))
            continue
        if (o.get("depot") or {}).get("sha") == source_sha:
            correspondants.append(f.name)
            if gen is None:
                gen = {"fichier": f.name, "sha256": emp(f),
                       "statut": o.get("statut"),
                       "suites_declarees": sorted((o.get("tests") or {}).keys()),
                       "PORTEE": "identite du commit, proprete de l'arbre et "
                                 "environnement ; les suites LISTEES ici, pas plus"}
    if registres and gen is None:
        raise SystemExit(
            "[certification] REFUS : %d registre(s) de generation presents, "
            "AUCUN ne porte sur %s%s. Une preuve qui n'est pas celle de la "
            "source promue ne certifie pas cette source."
            % (len(registres), source_sha[:12],
               (" — dont ILLISIBLES : %s" % ", ".join(registres_illisibles))
               if registres_illisibles else ""))

    tot = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    lus, illisibles = [], []
    for f in sorted(d.glob("**/*junit*.xml")):
        try:
            tete = f.read_text(encoding="utf-8", errors="replace")[:1500]
        except OSError as e:
            illisibles.append("%s (%s)" % (f.name, type(e).__name__))
            continue
        mm = re.search(r"<testsuite\b[^>]*", tete)
        if not mm:
            illisibles.append("%s (pas de <testsuite>)" % f.name)
            continue
        vals = {}
        for k in tot:
            r2 = re.search(k + r'="(\d+)"', mm.group(0))
            vals[k] = int(r2.group(1)) if r2 else 0
            tot[k] += vals[k]
        lus.append(dict(fichier=f.name, sha256=emp(f), **vals))
    junit = None
    if lus:
        junit = {"rapports": lus, "collectes": tot["tests"],
                 "executes": tot["tests"] - tot["skipped"], "skipped": tot["skipped"],
                 "failures": tot["failures"], "errors": tot["errors"],
                 "illisibles": illisibles,
                 "PORTEE": "comptes de tests de CE run ; ne dit rien des gates "
                           "non-test"}
    return {"etat": "LUE" if (gen or junit) else "ABSENTE",
            "dossier": str(d), "generation_proof": gen, "junit_proof": junit,
            "registres_lus": len(registres),
            "registres_illisibles": registres_illisibles,
            "registres_correspondants": correspondants,
            "NON_COUVERT": [
                "les gates non-test (lint, secrets, licence, anatomie...) ne "
                "sont pas comptes ici : leur verdict vit dans le journal de CI",
                "un rapport absent du dossier n'est pas un rapport vert",
            ]}


def write_dist_manifest(chemin, *, depot_source, source_sha, version, dist_commit,
                        certification, assets_manifest, profil,
                        lot_demande="INCONNU") -> Path:
    """Relie S -> preuves -> D -> artefacts. Ecrit APRES D, jamais avant.

    Les empreintes d'artefacts ne sont PAS recalculees : elles viennent du
    RELEASE_MANIFEST produit par le build, donc de valeurs OBSERVEES. Recalculer
    ici ferait un second instrument la ou il en faut un seul.
    """
    import json as _json
    arts, art_etat = {}, "LU"
    if not Path(assets_manifest).exists():
        # ABSENT n'est pas ILLISIBLE : sans --with-assets, aucun artefact n'a
        # ete construit. Les confondre ferait chercher une panne la ou il n'y a
        # qu'une etape non demandee.
        art_etat = "ABSENT (aucun artefact construit : --with-assets non demande)"
    else:
        try:
            rm = _json.loads(Path(assets_manifest).read_text(encoding="utf-8"))
            arts = {a["name"]: a.get("sha256") for a in (rm.get("assets") or [])}
        except (OSError, ValueError, KeyError, TypeError) as e:
            art_etat = "ILLISIBLE(%s)" % type(e).__name__

    # Derniere defense : un build CORRECT mais issu du MAUVAIS paquet. On ne
    # refuse que sur une version LUE et DIFFERENTE — un nom qui ne porte aucune
    # version n'est pas une incoherence, c'est une absence, et on la DIT.
    portent, muets = {}, []
    for nom in arts:
        v = re.search(r"[-_](\d+\.\d+\.\d+)", nom)
        (portent.__setitem__(nom, v.group(1)) if v else muets.append(nom))
    divergents = {n: v for n, v in portent.items() if v != version}
    if divergents:
        raise SystemExit(
            "[manifest] REFUS : artefact(s) portant une AUTRE version que "
            "--version %s : %s. Publier ainsi livrerait un paquet sous une "
            "identite qui n'est pas la sienne." % (version, divergents))

    m = {
        "schema": 1,
        "source": {"repository": depot_source, "sha": source_sha},
        "package": {"name": _nom_du_paquet(source_sha),
                    "version": _version_du_paquet(source_sha),
                    "version_demandee": version,
                    "lues_depuis": "source.sha"},
        "certification": certification,
        "promotion": {"promoter_revision": _revision_du_promoteur(),
                      "profile": profil,
                      "promu_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                      "NOTE": "le promoteur n'est pas le sujet promu : cette "
                              "revision sert a REJOUER la promotion, elle ne "
                              "certifie rien du produit"},
        "dist": {"commit": dist_commit, "tag": "v%s" % version},
        "artifacts": {"etat": art_etat, "source": str(assets_manifest),
                      "sha256": arts, "sans_version_dans_le_nom": muets,
                      "lot_demande": lot_demande},
        "NON_VERIFIE": [
            "metadonnees internes des artefacts (aucun wheel/sdist n'est "
            "produit ici) : le lien paquet<->artefact repose sur le nom et sur "
            "l'identite lue dans source.sha",
        ],
    }
    dest = Path(chemin)
    dest.write_text(_json.dumps(m, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print("[manifest] dist-manifest.json : S=%s -> D=%s (%d artefact(s), "
          "certification=%s)"
          % (source_sha[:12], (dist_commit or "INCONNU")[:12], len(arts),
             certification.get("etat")))
    return dest


def commit_version(dist: Path, version: str, source_sha: str | None = None) -> bool:
    """Stage all + commit vX.Y.Z. Idempotent : skip if no changes."""
    # `--force` : la source suit certains fichiers MALGRE son .gitignore (census
    # organ_map_full.json, 10 outils tools/_*). `add -A` seul les ecartait EN
    # SILENCE a chaque promotion (13 fichiers, mesure 2026-09-30). Le snapshot
    # est deja cure (politique publique, generisation, gardes) : tout part.
    run([*_GIT_DIST, "add", "-A", "--force"], cwd=dist)
    if run([*_GIT_DIST, "diff", "--cached", "--quiet"], cwd=dist,
           check=False).returncode == 0:
        print(f"[commit] no changes vs current dist tip -> skip (idempotent)")
        return False
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": AUTHOR_NAME, "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": AUTHOR_NAME, "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
    })
    # Le message NOMME la source. Il disait « the beta development tip » — une
    # cible mouvante, donc un commit dist qui ne disait pas de quoi il etait la
    # photographie.
    msg = (f"v{version} — Nokido distribution snapshot\n\n"
           f"Curated snapshot of source {source_sha or 'INCONNU'} "
           f"(export-ignore applied). Heavy assets (source tarball, int8 RAG "
           f"Knowledge Pack) are attached to the Release for tag v{version}.")
    run([*_GIT_DIST, "commit", "-m", msg], cwd=dist, env=env)
    return True


def tag_version(dist: Path, version: str) -> bool:
    """Create tag vX.Y.Z. Idempotent : skip if it already exists."""
    tag = f"v{version}"
    exists = run([*_GIT_DIST, "tag", "-l", tag], cwd=dist,
                 capture=True).stdout.strip()
    if exists:
        print(f"[tag] {tag} already exists -> skip (idempotent)")
        return False
    env = os.environ.copy()
    env.update({"GIT_AUTHOR_NAME": AUTHOR_NAME, "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
                "GIT_COMMITTER_NAME": AUTHOR_NAME, "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL})
    run([*_GIT_DIST, "tag", "-a", tag, "-m", f"{tag} public release"],
        cwd=dist, env=env)
    return True


def push_remotes(dist: Path, remotes: dict, version: str, do_push: bool) -> None:
    tag = f"v{version}"
    if do_push:
        # PORTE FAIL-CLOSED (owner 2026-09-15) : pas de push public sans decision BREVET/IP
        # enregistree ET double confirmation owner (forge_publication_gate).
        from forge_publication_gate import porte_publique
        _ok_gate, _motif_gate = porte_publique()
        if not _ok_gate:
            raise SystemExit(_motif_gate)
    if not do_push:
        print("\n[push] DRY (no --push). Would push to :")
        for name in remotes:
            print(f"  git -C {dist} push {name} HEAD:main && "
                  f"git -C {dist} push {name} {tag}")
        return
    local = run([*_GIT_DIST, "rev-parse", "HEAD"], cwd=dist,
                capture=True).stdout.strip()
    verdicts = []
    for name, url in remotes.items():  # codeberg first (primary), then github
        print(f"[push] -> {name}")
        _env = _env_git()
        # Le push DIT pourquoi il echoue. Mesure du 2026-09-20 : lance sans
        # capture ni rapport, il a echoue en silence, et comme la verification
        # distante a echoue pour la MEME cause reseau, le verdict ILLISIBLE ne
        # permettait plus de distinguer « le push a rate » de « je n'ai pas pu
        # verifier ». Deux causes distinctes derriere un seul mot : c'est ce
        # qu'on passe la journee a separer ailleurs.
        for _ref in ("HEAD:main", tag):
            _r = run([*_GIT_DIST, *_GIT_AUTH, "push", name, _ref], cwd=dist,
                     check=False, capture=True, env=_env)
            if _r.returncode != 0:
                print("  [push] %s %s ECHEC rc=%d : %s"
                      % (name, _ref, _r.returncode,
                         _sans_secret((_r.stderr or _r.stdout or "").strip())[:300]))
        # Le rc d'un push MENT dans les deux sens (mesure 2026-08-29 : rc=1 sur un
        # push REUSSI, credential store incapable de persister le jeton). Le verdict
        # se lit sur le DISTANT, et un push rejete en non-fast-forward passait
        # jusqu'ici pour un succes faute de le lire.
        sha = _sha_distant(url, "refs/heads/main")
        if sha is None:
            verdicts.append((name, "ILLISIBLE", "ls-remote refuse : publication NON PROUVEE"))
        elif sha == local:
            verdicts.append((name, "PUBLIE", sha[:12]))
        else:
            verdicts.append((name, "NON PUBLIE",
                             "distant=%s local=%s" % ((sha or "(vide)")[:12], local[:12])))
    print("\n[push] verdict lu sur le DISTANT :")
    for n, e, d in verdicts:
        print("    %-10s %-11s %s" % (n, e, d))
    if not any(e == "PUBLIE" for _n, e, _d in verdicts):
        raise SystemExit("[push] ECHEC : aucun remote ne porte le commit local. "
                         "Un push sans verdict distant se lit comme un succes ; "
                         "il ne l'est pas.")


def _resoudre_sha(rev: str) -> str:
    """Resout une revision en sha CONCRET, UNE seule fois, fail-closed.

    H' (owner 2026-09-20) : la source d'une promotion est un SHA, jamais une
    branche. `git archive beta` photographie « la pointe au moment ou on
    regarde » — deux promotions du meme nom peuvent livrer deux contenus, et le
    manifeste ne pourrait rattacher l'artefact a rien de stable. On resout donc
    la revision une fois, puis TOUT le reste (archive, identite, build) parle de
    ce sha-la.
    """
    r = run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
             "rev-parse", "--verify", "%s^{commit}" % rev],
            capture=True, check=False)
    sha = (r.stdout or "").strip()
    if r.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit(
            "[source] revision INTROUVABLE ou ambigue : %r. Une promotion part "
            "d'un sha RESOLU, jamais d'un nom qui peut bouger sous elle." % rev)
    return sha


def _version_declaree(chemin, motif: str, source_sha: str | None = None) -> str | None:
    """Version lue dans un fichier declaratif, par TEXTE.

    Avec `source_sha`, la lecture se fait dans l'ARBRE DE CE COMMIT (`git show`)
    et non dans le depot de travail : l'identite du paquet doit venir de la
    SOURCE QU'ON PUBLIE, pas de ce qui traine a cote. Sans ce point, on pouvait
    tagger la version du worktree sur une archive faite depuis un autre commit.

    Rend None si le fichier est illisible ou si le motif ne trouve rien --
    absent et illisible ne se confondent pas avec « incoherent ».
    """
    if source_sha:
        r = run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "show",
                 "%s:%s" % (source_sha, str(chemin).replace("\\", "/"))],
                capture=True, check=False)
        if r.returncode != 0:
            return None
        texte = r.stdout or ""
    else:
        try:
            texte = (ROOT / chemin).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    trouve = re.search(motif, texte, re.M)
    return trouve.group(1) if trouve else None


def _version_du_paquet(source_sha: str | None = None) -> str | None:
    """Version declaree dans le `pyproject.toml` de la SOURCE promue."""
    return _version_declaree("pyproject.toml", r'^version\s*=\s*"([^"]+)"',
                             source_sha)


def _version_du_module(source_sha: str | None = None) -> str | None:
    """`__version__` du paquet -- TROISIEME source, et celle que la preuve IMPRIME.

    `verify-testpypi` affiche `nokido_agent.__version__` comme preuve de ce qui a
    ete reellement installe. Si elle diverge du pyproject, la preuve montre une
    version que l'artefact ne porte pas.
    """
    return _version_declaree(
        Path("nokido_agent") / "__init__.py", r'^__version__\s*=\s*"([^"]+)"',
        source_sha)


def _verifier_version_du_paquet(demandee: str, source_sha: str | None = None) -> None:
    """Le tag pose doit == la version EMPAQUETEE, sinon on publie un mensonge.

    Mesure 2026-09-19 : cet outil taguait `v0.20.2` pendant que `pyproject.toml`
    restait a `0.20.1`. Le paquet publie aurait donc porte 0.20.1 sous un tag
    0.20.2 -- et comme PyPI REFUSE de republier une version existante, la chaine
    aurait servi l'ANCIEN artefact en le presentant comme le nouveau. Seul le
    controle du sha256 servi rattrapait ce faux vert, tout en bout de chaine.

    Le workflow `release.yml` porte deja ce garde (« le tag v* doit ==
    pyproject.version ») : il manquait ICI, du cote qui FABRIQUE le snapshot.
    Un contrat tenu d'un seul cote n'est pas un contrat.
    """
    # TROIS portes, pas une : le tag, le pyproject, et le `__version__` que la
    # preuve d'installation IMPRIME. Mesure 2026-09-19 : apres avoir ferme la
    # divergence tag<->pyproject, j'en avais ouvert une pyproject<->__version__,
    # attrapee par `test_version_unique_nr`. Un garde ne vaut que par le nombre
    # de portes qu'il tient.
    sources = {
        "pyproject.toml": _version_du_paquet(source_sha),
        "nokido_agent/__init__.py": _version_du_module(source_sha),
    }
    illisibles = [nom for nom, v in sources.items() if v is None]
    if illisibles:
        print("[version] NON VERIFIABLE pour %s : coherence non prouvee "
              "(ce n'est pas une preuve de coherence)" % ", ".join(illisibles))
    divergentes = {nom: v for nom, v in sources.items() if v is not None and v != demandee}
    if divergentes:
        detail = " ; ".join(f"{nom} declare {v}" for nom, v in divergentes.items())
        raise SystemExit(
            f"[version] INCOHERENT : --version {demandee} mais {detail}.\n"
            f"  Publier ainsi taguerait v{demandee} sur un paquet qui porte autre chose.\n"
            f"  Aligner CHAQUE source ci-dessus, puis relancer."
        )
    lues = [nom for nom, v in sources.items() if v is not None]
    print("[version] tag v%s == %s" % (demandee, " == ".join(lues) or "(aucune source lisible)"))


def _codeberg_token():
    """Jeton Codeberg, lu par le coffre.

    Mesure 2026-09-19 : la version precedente appelait `get_secret` AVANT de
    l'importer, et cet appel etait HORS du `try` qui suit -- donc `NameError`
    systematique, jamais attrape. La fonction n'a jamais pu rendre un jeton.
    Invisible a la relecture (le code se lit comme un repli), invisible a l'AST :
    seul un appel reel leve. Meme famille que le piege `os`/`_os` du 18/09.
    L'import vient donc AVANT l'usage, et le repli reste explicite.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as e:
        print(f"[codeberg-release] token lookup failed: {e}")
        return None
    return get_secret("CODEBERG_TOKEN") or get_secret("FORGE_TOKEN_CODEBERG")


def codeberg_release(version, assets_dir, codeberg_url):
    """Create (or reuse) the Gitea release for the tag + upload every asset.
    Idempotent : skips assets already attached. Parity with the GitHub release."""
    try:
        import requests
    except ImportError:
        print("[codeberg-release] 'requests' absent -> skip (pip install requests)")
        return
    tok = _codeberg_token()
    if not tok:
        print("[codeberg-release] no token (vault/env) -> skip")
        return
    m = re.search(r"codeberg\.org/([^/]+)/([^/.]+)", codeberg_url)
    if not m:
        print(f"[codeberg-release] cannot parse owner/repo from {codeberg_url}")
        return
    owner, repo = m.group(1), m.group(2)
    base = "https://codeberg.org/api/v1"
    h = {"Authorization": "token " + tok}
    tag = f"v{version}"
    try:  # API-created repos may have the Releases unit OFF -> /releases 404
        requests.patch(f"{base}/repos/{owner}/{repo}", headers=h,
                       json={"has_releases": True}, timeout=30)
    except Exception:
        pass
    r = requests.get(f"{base}/repos/{owner}/{repo}/releases/tags/{tag}", headers=h, timeout=30)
    if r.status_code == 200:
        rel = r.json()
        print(f"[codeberg-release] {tag} exists (id {rel['id']})")
    else:
        body = f"Nokido {tag} - code tarball + int8 RAG Knowledge Pack + SHA256SUMS"
        r = requests.post(f"{base}/repos/{owner}/{repo}/releases", headers=h, timeout=30,
                          json={"tag_name": tag, "name": tag, "body": body})
        if r.status_code not in (200, 201):
            print(f"[codeberg-release] create failed {r.status_code}: {r.text[:200]}")
            return
        rel = r.json()
        print(f"[codeberg-release] created {tag} (id {rel['id']})")
    rel_id = rel["id"]
    existing = {a.get("name") for a in (rel.get("assets") or [])}
    adir = Path(assets_dir)
    if not adir.exists():
        print(f"[codeberg-release] no assets dir {adir}")
        return
    for f in sorted(adir.iterdir()):
        if not f.is_file():
            continue
        if f.name in existing:
            print(f"[codeberg-release] {f.name} already attached -> skip")
            continue
        with open(f, "rb") as fh:
            up = requests.post(
                f"{base}/repos/{owner}/{repo}/releases/{rel_id}/assets",
                headers=h, params={"name": f.name},
                files={"attachment": (f.name, fh)}, timeout=120,
            )
        print(f"[codeberg-release] upload {f.name} -> {up.status_code}")


def build_assets(version: str, rev: str, out_dir, skip_pack=False, depot=None) -> None:
    """Construit les artefacts DANS le lot que le manifeste va lire.

    Defaut mesure le 2026-09-20 : `forge_release_assets` ecrit par defaut dans
    `C:/tmp/laforge-release/v<version>` tandis que le promoteur lit
    `C:/tmp/nokido-release/v<version>`. Les artefacts partaient donc AILLEURS
    que la ou on les cherche, et le manifeste aurait declare « ABSENT
    (--with-assets non demande) » — ce qui est FAUX : ils existaient, hors de
    portee. Un chemin par defaut divergent ne casse rien bruyamment : il produit
    un mensonge poli. On passe donc `--out` explicitement.

    `rev` + `depot` : l'asset source se tire de D dans le clone dist, jamais de S
    dans la source (mesure 2026-09-30 : le tarball de S contournait la politique
    publique et la generisation -- docs/ip/** et 421 fichiers a marqueurs).
    """
    print("[assets] building via forge_release_assets -> %s" % out_dir)
    cmd = [sys.executable, str(ROOT / "tools" / "forge_release_assets.py"),
           "--version", version, "--branch", rev, "--out", str(out_dir)]
    if depot is not None:
        cmd += ["--repo", str(depot)]
    if skip_pack:
        cmd.append("--skip-pack")
    run(cmd)


def _construire_wiki(dist: Path) -> None:
    """Le wiki GitHub lit un AUTRE depot (`<depot>.wiki.git`) : il se reconstruit ici, depuis le COMMIT
    du dist, dans un clone local du wiki. Rien n'est pousse (canal git de la session). Un echec se DIT
    et n'annule pas la promotion : le dist est deja commite, le wiki n'en est qu'une vue."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "forge_wiki_github", Path(__file__).with_name("forge_wiki_github.py"))
    mod = importlib.util.module_from_spec(spec)
    sortie = TMP / "nokido-wiki-build"
    try:
        spec.loader.exec_module(mod)
        rc = mod.main(["--dist", str(dist), "--sortie", str(sortie)])
    except (SystemExit, OSError, subprocess.SubprocessError) as e:
        print("[wiki] NON construit : %s -- le wiki public garde sa version precedente" % e)
        return
    if rc:
        print("[wiki] construit AVEC des defauts (voir ci-dessus) : relire avant de publier")


def _module_readme_pip():
    """tools/forge_readme_pip.py, charge a cote du promoteur (stdlib seule)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "forge_readme_pip", Path(__file__).with_name("forge_readme_pip.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _version_pypi_servie(paquet: str, hors_ligne: bool) -> str | None:
    """Ce que PyPI SERT, lu AVANT toute mutation du clone dist.

    Decision owner 2026-10-01 : le README du dist annonce `pip install` des que
    PyPI sert une version, et le fait correspondre a chaque distribution. PyPI
    illisible = promotion REFUSEE : ecrire « pas encore publie » sur un index
    qu'on n'a pas pu lire transformerait « non mesure » en « rien ». `hors_ligne`
    garde le bloc de la source tel quel, et le DIT (rend None).
    """
    mod = _module_readme_pip()
    if hors_ligne:
        print("[pip] --pip-hors-ligne : bloc pip de la source garde tel quel, "
              "NON aligne sur PyPI")
        return None
    servie = mod.version_servie(paquet)
    if servie == mod.ILLISIBLE:
        raise SystemExit("[pip] PyPI illisible : le bloc pip du README ne peut pas "
                         "etre aligne. Relancer, ou --pip-hors-ligne pour promouvoir "
                         "en le DISANT.")
    print("[pip] PyPI sert %s pour %s" % (servie, paquet))
    return servie


def _verifier_negations_pip(source_sha: str, paquet: str, servie: str | None) -> None:
    """Refuse la promotion si un README de la source NIE `pip install` alors que PyPI sert une version.

    Owner 2026-10-06 : le README publie de 0.20.8 annoncait « From PyPI » en tete et « `pip install`
    is not supported yet » plus bas. Le bloc de la source reste a `version=none` (c'est le promoteur
    qui l'aligne sur PyPI) : le gate de la CI ne pouvait donc PAS voir la contradiction, qui n'existe
    qu'apres alignement. On la juge ici, AVANT toute mutation, sur les README lus au sha promu avec
    le bloc simule a la version servie. Illisible = refus dit, jamais un vert."""
    if servie is None:
        return
    mod = _module_readme_pip()
    r = run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "ls-tree", "-r", "--name-only",
             source_sha, "--", "README.md", "docs/i18n"], capture=True, check=False)
    if r.returncode != 0:
        raise SystemExit("[pip] arbre de %s illisible : README non verifies, promotion refusee"
                         % source_sha[:12])
    fautes = []
    for chemin in (r.stdout or "").split():
        if not re.search(r"(^|/)README[^/]*\.md$", chemin):
            continue
        s = run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "show", "%s:%s" % (source_sha, chemin)],
                capture=True, check=False)
        if s.returncode != 0:
            fautes.append("%s : illisible" % chemin)
            continue
        texte = s.stdout or ""
        if mod.lire(texte) is None:
            continue
        simule = mod._RE_BLOC.sub(lambda _m: mod.bloc(paquet, servie), texte, count=1)
        statut, note = mod.coherence(simule, paquet)
        if statut == mod.DIVERGE:
            fautes.append("%s : %s" % (chemin, note))
    if fautes:
        raise SystemExit("[pip] PyPI sert %s %s, mais des README de la source le contredisent :\n  %s"
                         % (paquet, servie, "\n  ".join(fautes)))
    print("[pip] aucun README ne nie pip une fois aligne sur %s" % servie)


def _aligner_bloc_pip(dist: Path, paquet: str, servie: str | None) -> None:
    """Regenere le bloc pip de chaque README du dist sur la version servie."""
    if servie is None:
        return
    for p in _module_readme_pip().ecrire(dist, paquet, servie):
        print("[pip] bloc aligne sur %s : %s" % (servie, p.relative_to(dist)))


# Cartouches du dist (2026-10-02, owner : « le cartouche CI ne s'affiche plus »). Le README de la
# SOURCE pointe son cartouche CI vers le workflow self-hosted de la source (bloque hors du dist :
# une PR publique ferait tourner du code sur le poste owner) et annonce la branche alpha. Sur le
# dist, ce workflow n'existe pas et la branche est main : GitHub rendait « workflow introuvable ».
# Le dist montre donc SON workflow (release.yml) -- et jamais le nom du depot prive.
# Proprietaire quelconque : les traductions portaient encore l'ancien `user/Nokido` (redirige vers
# le depot prive) -- un motif lie a `Nokido-labs` les laissait passer telles quelles dans le dist.
_RE_CARTOUCHE_CI = re.compile(
    r"https://github\.com/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+/actions/workflows/ci-selfhosted\.yml"
    r"(?P<badge>/badge\.svg(?:\?branch=[\w.-]+)?)?")


def _adapter_cartouches(dist: Path) -> int:
    """Cartouche CI -> release.yml du dist, badge de branche alpha -> main. Rend le nombre de README
    modifies ; un README illisible est SAUTE et dit, jamais reecrit a moitie."""
    def _rempl(m):
        cible = "https://github.com/%s/actions/workflows/release.yml" % DIST_REPO_GITHUB
        return cible + ("/badge.svg" if m.group("badge") else "")

    n = 0
    # Traductions : docs/i18n/README.<langue>.md (le format reel) et docs/i18n/<langue>/README*.md.
    for p in (sorted(dist.glob("README*.md")) + sorted(dist.glob("docs/i18n/README*.md"))
              + sorted(dist.glob("docs/i18n/*/README*.md"))):
        try:
            texte = p.read_text(encoding="utf-8")
        except OSError as e:
            print("[cartouches] %s illisible (%s) : saute" % (p.relative_to(dist), type(e).__name__))
            continue
        neuf = _RE_CARTOUCHE_CI.sub(_rempl, texte).replace("badge/branch-alpha-", "badge/branch-main-")
        if neuf != texte:
            p.write_text(neuf, encoding="utf-8")
            n += 1
            print("[cartouches] %s : CI -> release.yml du dist, branche -> main" % p.relative_to(dist))
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="SemVer e.g. 0.1.0")
    # Plus de defaut : une promotion NOMME sa source. `beta` en defaut faisait
    # partir la chaine de « la pointe d'une branche au moment ou on regarde »,
    # donc d'une cible mouvante — et rien, en aval, ne pouvait rattacher
    # l'artefact a un commit precis. Le nom reste `--branch` par compatibilite,
    # mais toute revision est acceptee et RESOLUE en sha.
    ap.add_argument("--branch", "--source", dest="branch", default=None,
                    help="revision source a promouvoir (sha, tag ou branche) — "
                         "resolue en sha concret, obligatoire")
    ap.add_argument("--dist-path", default=str(DEFAULT_DIST_PATH))
    ap.add_argument("--certification", default=None, metavar="DOSSIER",
                    help="dossier d'artefacts de la CI qui a certifie la source "
                         "(registres de generation + rapports JUnit). Son "
                         "absence est DITE dans le manifeste, jamais tue.")
    ap.add_argument("--source-repo", default=SOURCE_PUBLIEE,
                    help="libelle de la source promue dans le manifeste PUBLIC "
                         "(jamais le nom d'un depot prive)")
    ap.add_argument("--codeberg-url", default=CODEBERG_URL)
    ap.add_argument("--with-codeberg", action="store_true",
                    help="ajouter Codeberg comme miroir. Hors de ce drapeau il "
                         "n'est NI clone NI pousse : son etat est INDETERMINE "
                         "(authentification requise), et un remote qu'on ne "
                         "sait pas lire ne fait pas autorite.")
    ap.add_argument("--github-url", default=DEFAULT_REMOTES["github"])
    ap.add_argument("--skip-rag-pack", action="store_true",
                    help="ne pas construire le Knowledge Pack RAG int8 (derive "
                         "d'une base de plusieurs dizaines de Go). Le lot "
                         "REELLEMENT demande est inscrit au manifeste : une "
                         "livraison partielle se DIT.")
    ap.add_argument("--with-assets", action="store_true",
                    help="also build the downloadable assets")
    ap.add_argument("--push", action="store_true",
                    help="actually push to both remotes (outward — explicit)")
    ap.add_argument("--pip-hors-ligne", action="store_true",
                    help="ne pas interroger PyPI : le bloc pip du README garde "
                         "l'etat de la source, et la promotion le DIT")
    args = ap.parse_args()

    if not SEMVER.match(args.version):
        raise SystemExit(f"invalid SemVer: {args.version}")

    if not args.branch:
        raise SystemExit(
            "[source] --branch/--source est OBLIGATOIRE : une promotion part "
            "d'une revision NOMMEE, jamais d'un defaut implicite.")
    # UNE resolution, puis tout parle du meme sha : archive, identite, build.
    source_sha = _resoudre_sha(args.branch)
    print("[source] %s -> %s" % (args.branch, source_sha))
    _verifier_version_du_paquet(args.version, source_sha)
    # TOUTES les entrees se valident AVANT la moindre mutation. Sans ce point,
    # un `--certification` errone n'echouait qu'APRES `commit_version`, donc
    # apres avoir efface l'arbre du clone dist et pose un commit : on decouvrait
    # l'erreur d'entree une fois le mal fait.
    certification = _lire_certification(args.certification, source_sha)
    print("[certification] %s" % certification.get("etat"))
    paquet = _nom_du_paquet(source_sha) or "nokido-agent"
    pypi_servie = _version_pypi_servie(paquet, args.pip_hors_ligne)
    _verifier_negations_pip(source_sha, paquet, pypi_servie)

    dist = Path(args.dist_path)
    remotes = {"github": args.github_url}
    if args.with_codeberg:
        remotes["codeberg"] = args.codeberg_url
    else:
        print("[dist] Codeberg NON inclus : etat INDETERMINE (ls-remote y "
              "demande une authentification). --with-codeberg pour l'ajouter.")

    print(f"=== publish v{args.version} (from {args.branch} = {source_sha[:12]}) -> {dist} ===")
    ensure_dist_repo(dist, remotes)
    sync_snapshot(source_sha, dist)
    _aligner_bloc_pip(dist, paquet, pypi_servie)
    _adapter_cartouches(dist)
    committed = commit_version(dist, args.version, source_sha)
    tagged = tag_version(dist, args.version)
    # D n'existe qu'APRES le commit : le manifeste est ecrit ENSUITE, avec des
    # valeurs observees (D reel, empreintes reelles), jamais avec des valeurs
    # preparees. Il est un ASSET de release et non un fichier du commit — sinon
    # il devrait contenir le sha du commit qui le contient.
    dist_commit = _sha_du_depot(dist)
    _lot = TMP / "nokido-release" / f"v{args.version}"
    _lot.mkdir(parents=True, exist_ok=True)
    # Les ARTEFACTS d'abord, le manifeste ENSUITE. Ma premiere version ecrivait
    # le manifeste avant `build_assets` : `artifacts` y aurait toujours ete
    # ABSENT, et le champ aurait impute cette absence a « --with-assets non
    # demande » alors que le lot allait etre construit trois lignes plus bas.
    # Un manifeste se compose de valeurs OBSERVEES : il vient donc APRES D ET
    # APRES les empreintes, jamais avant l'un des deux.
    _lot_demande = "aucun (--with-assets non demande)"
    if args.with_assets:
        _lot_demande = "code" if args.skip_rag_pack else "code + rag_pack"
        build_assets(args.version, dist_commit, _lot, args.skip_rag_pack, depot=dist)
    write_dist_manifest(
        _lot / "dist-manifest.json",
        depot_source=args.source_repo,
        source_sha=source_sha,
        version=args.version,
        dist_commit=dist_commit,
        certification=certification,
        assets_manifest=_lot / "RELEASE_MANIFEST.json",
        lot_demande=_lot_demande,
        # Le profil est LU dans les regles de publication, pas declare par un
        # drapeau : un champ qu'on affirme sans le mesurer ne vaut rien.
        profil=_version_declaree(".git-publish-rules.json",
                                 r'"default_profile"\s*:\s*"([^"]+)"'))
    push_remotes(dist, remotes, args.version, args.push)
    _construire_wiki(dist)
    if args.push and args.with_assets:
        if "codeberg" in remotes:
            codeberg_release(args.version, TMP / "nokido-release" / f"v{args.version}",
                             remotes["codeberg"])
        else:
            print("[codeberg-release] IGNORE : Codeberg absent des remotes "
                  "(--with-codeberg non demande)")

    print("\n" + "=" * 64)
    print(f"  done : committed={committed} tagged={tagged} pushed={args.push}")
    print(f"  dist repo : {dist}")
    if not args.push:
        print("  re-run with --push to publish to Codeberg + GitHub")
    print("  then attach assets to the Release :")
    print(f"    gh release create v{args.version} {TMP}/nokido-release/"
          f"v{args.version}/* --repo {DIST_REPO_GITHUB} --title v{args.version}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
