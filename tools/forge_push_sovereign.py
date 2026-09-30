"""forge_push_sovereign.py — pousse une branche vers GitHub + Codeberg en lisant les
tokens AU VAULT. Dry-run par defaut.

POURQUOI CET OUTIL
  La memoire disait "push = SEUL user (creds git caches)". C'est vrai du CREDENTIAL
  HELPER (per-user, seul user l'a) -- mais incomplet : GITHUB_TOKEN et CODEBERG_TOKEN
  sont AU COFFRE, donc n'importe quel compte qui lit le vault peut pousser.

  Reste le vrai piege, celui qui a motive ce fichier : le hub JOURNALISE les args de
  `run` (cf tool.run.arg.code dans les stats d'usage). Un token colle dans une ligne de
  commande atterrit dans l'audit log, donc dans le RAG -- une fuite permanente pour un
  gain de 10 secondes. Ici le token ne quitte JAMAIS le process : lu au vault, injecte
  dans l'URL du sous-process git, jamais imprime, jamais ecrit dans .git/config.

CE QU'IL NE FAIT PAS
  - Aucun --no-verify : l'egress gate (git_secrets) tourne. S'il bloque, il bloque, et
    c'est SON diagnostic qu'il faut lire, pas le garde qu'il faut contourner.
  - Aucun --force : un push non fast-forward doit etre une decision humaine.
  - Aucun set-url : le token ne doit pas se retrouver persiste dans .git/config.

Usage : run action=trusted_script path=tools/forge_push_sovereign.py
        script_args="--branch alpha"            (dry-run : montre le retard)
        script_args="--branch alpha --push"     (pousse pour de vrai)

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `refspec` — Rend (refspec, None) ou (None, motif). Sans `sha` : `<br>:<br>`, historique.
"""

__FORGE_COLOR__ = "infra/deploy : push souverain vers GitHub et Codeberg, jetons du coffre"  # organe declare le 2026-09-06 (audit de raccordement)
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# 2026-08-02 -- SANS ceci, git ATTEND un prompt qui ne viendra jamais. L'auth par
# credential helper marche sous `trusted_script` (mesure du 17-07 ci-dessus) mais PAS
# sous `run_job online` : mesure de ce soir, `ls-remote` a pendu jusqu'au timeout, et
# `push` est sorti en **rc 128 avec stdout ET stderr VIDES** -- ce qui se lit comme
# « le hub ne peut pas pousser » alors que c'est seulement l'auth qui manque a CE compte.
# Un echec qui se nomme vaut infiniment mieux qu'une attente muette.
_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="echo")

ROOT = Path(__file__).resolve().parent.parent
# Depot CIBLE du push. Par defaut celui qui porte ce script, mais le super-depot
# `nokido-workspace` doit etre pousse lui aussi -- et le pousser a la main
# exposerait le token dans les args de `run`, que le hub JOURNALISE : exactement
# la fuite que ce fichier existe pour empecher. D'ou `--repo`, plutot qu'un
# contournement (mesure 2026-08-19).
_REPO = ROOT
sys.path.insert(0, str(ROOT))

# remote -> (nom du secret au vault, user d'auth attendu par la forge)
TARGETS = {
    "origin": ("GITHUB_TOKEN", "x-access-token"),
    # HORS SERVICE 2026-08-29 (decision owner) : le miroir Codeberg refuse tout
    # push (Forgejo « Quota exceeded », depot archive) et son rejet non-fast-
    # forward polluait CHAQUE publication. Un bruit permanent dans une sortie
    # qu'on lit pour y reperer des anomalies finit par masquer les vraies.
    # A REACTIVER au passage public, en repartant du snapshot -- pas de l'atelier.
    # "codeberg-nokido": ("CODEBERG_TOKEN", "user"),
}


_CRED: list = []


def _cred_args() -> list:
    """Sert les jetons DU COFFRE a git, cible PAR HOTE, sans toucher a l'URL.

    Mesure 2026-08-02 : le credential helper de Windows rend « Invalid username or token »
    sous LaForgeTrusted comme sous run_job -- la note du 17-07 (« l'auth fonctionne deja
    depuis le sandbox ») ne vaut plus. Les jetons sont AU COFFRE : on les sert par un
    helper inline et on les passe par l'ENVIRONNEMENT, jamais par la ligne de commande,
    car le hub JOURNALISE les args de `run` (le piege qui a motive ce fichier).

    On NE touche toujours PAS a l'URL : l'injection de token y casse le pre-push de
    `.githooks` (mesure du 17-07 conservee plus bas). Le helper est cible par HOTE pour
    qu'un jeton ne parte jamais vers la mauvaise forge.
    """
    out: list = []
    try:
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as exc:
        say("[cred] coffre injoignable (%s) : on tentera l'auth native" % type(exc).__name__)
        return out
    for host, var, secret, user in (
        ("https://github.com", "GH_TOKEN", "GITHUB_TOKEN", "x-access-token"),
        ("https://codeberg.org", "CB_TOKEN", "CODEBERG_TOKEN", "user"),
    ):
        try:
            tok = get_secret(secret)
        except Exception:
            tok = None
        if not tok:
            say("[cred] %s : aucun jeton au coffre -> auth native" % host)
            continue
        _ENV[var] = tok
        out += ["-c", 'credential.%s.helper=!f() { echo username=%s; echo "password=$%s"; }; f'
                % (host, user, var)]
    return out


def git(*a, **kw):
    return subprocess.run(["git", "-c", "safe.directory=*"] + _CRED + ["-C", str(_REPO)] + list(a),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=kw.get("timeout", 180), env=_ENV)


def say(txt: str = "") -> None:
    """Imprime en ASCII PUR, quoi qu'il arrive.

    2026-07-17, mesure : le stdout d'un run_job est en cp1252. La sortie de git,
    decodee avec errors='replace', contient des U+FFFD -> print() leve
    UnicodeEncodeError -> le script MEURT apres le push, en emportant le message
    d'erreur qu'on cherchait. Trois diagnostics perdus a cause de ca : on ne voyait
    que 'rc=128' sans un mot. Le gotcha est deja documente dans
    forge_llama_keeper.py:214 ("ASCII PUR ... = keeper mort. Deja vecu").
    Un message ne vaut RIEN s'il tue le process qui le porte.
    """
    sys.stdout.buffer.write((txt + "\n").encode("ascii", "replace"))
    sys.stdout.flush()


def _ci_github_rouges(br: str, sha: str) -> None:
    """Apercu (decision owner 2026-09-26) : le dernier run GitHub TERMINE de la branche
    a-t-il des tests rouges, et chacun a-t-il un commit dans le sha qu'on va certifier ?

    GitHub ne juge un sha qu'une fois publie ; un test dont le verdict depend du poste
    passe en local et rougit la-bas (test_tpm_acl_gouvernee_nr, 26/09). On le lit donc
    AVANT la CI complete locale. Observation seule : rien n'est bloque, tout est DIT.
    """
    try:
        import forge_ci_check as cc
        url = git("remote", "get-url", "origin").stdout.strip()
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
        if not m:
            say("[ci-github] ILLISIBLE : origin n'est pas un depot GitHub (%s)" % url[:80])
            return
        r = cc.couverture_des_rouges(
            m.group(1), br, sha,
            lambda base, s, f: git("log", "--format=%h %s", "%s..%s" % (base, s), "--", f)
            .stdout.strip().splitlines())
    except Exception as exc:  # noqa: BLE001 — un apercu ne tue pas le push ; il le DIT
        say("[ci-github] ILLISIBLE : %s: %s -- etat GitHub NON verifie" % (type(exc).__name__, exc))
        return
    say("[ci-github] dernier run termine de %s : %s (run %s, head %s) -> %s"
        % (br, r.get("conclusion"), r.get("run"), r.get("head"), r.get("etat")))
    if r.get("raison"):
        say("            raison : %s" % r["raison"])
    if r.get("en_cours_plus_recents"):
        say("            %d run(s) plus recent(s) en cours : ce verdict peut deja etre depasse"
            % r["en_cours_plus_recents"])
    for rouge in r.get("rouges", []):
        say("            ROUGE %s::%s" % (rouge["fichier"], rouge["test"]))
        for c in rouge["commits"][:5]:
            say("              correctif candidat : %s" % c[:120])
        if not rouge["commits"]:
            say("              AUCUN commit ne touche ce test depuis le run rouge : correctif NON"
                " PROUVE (il peut vivre dans le code teste) -- verifier avant la CI complete")
    for job in r.get("jobs_sans_test", []):
        say("            JOB ROUGE sans test nomme : %s (%s)%s" % (
            job.get("job"), job.get("conclusion"),
            " -- journal indisponible : %s" % job["journal_indisponible"]
            if job.get("journal_indisponible") else ""))
    print()


def refspec(br: str, sha=None):
    """Rend (refspec, None) ou (None, motif). Sans `sha` : `<br>:<br>`, historique.

    Avec `sha` (2026-09-23) : pousser EXACTEMENT le sha que la CI a certifie,
    meme si la branche a avance depuis -- la CI avait certifie `fd499fa24`
    pendant que `alpha` pointait deja sur un commit non certifie. Le sha doit
    etre un ANCETRE de la branche : le distant avance alors en fast-forward
    jusqu'a un point que la branche contient deja, et un sha etranger ou
    posterieur est REFUSE -- ce n'est jamais un moyen de reecrire l'historique.
    """
    if not sha:
        return "%s:%s" % (br, br), None
    plein = git("rev-parse", "--verify", "--quiet", "%s^{commit}" % sha).stdout.strip()
    if not plein:
        return None, "sha %r inconnu dans %s" % (sha, _REPO)
    if git("merge-base", "--is-ancestor", plein, br).returncode != 0:
        return None, "sha %s n'est pas un ancetre de '%s' : refus" % (plein[:12], br)
    return "%s:refs/heads/%s" % (plein, br), None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default=None,
                    help="pousser CE sha (ancetre de la branche), p. ex. le sha certifie par la CI")
    ap.add_argument("--branch", default="alpha")
    ap.add_argument("--push", action="store_true", help="pousser reellement (sinon dry-run)")
    ap.add_argument("--repo", default=None,
                    help="depot a pousser (defaut : celui qui porte ce script)")
    args = ap.parse_args()
    # Les deux `global` sont declares ICI, avant toute affectation. Les placer
    # plus bas donnerait « name '_REPO' is assigned to before global
    # declaration » — une erreur de COMPILATION que `ast.parse` ne voit pas, et
    # que le hook de validation AST laisse donc passer (mesure 2026-08-19).
    global _REPO, _CRED
    br = args.branch
    if args.repo:
        _REPO = Path(args.repo).resolve()
    _CRED = _cred_args()

    # Un push de 60-90 commits depasse le cap de 120s des appels hub -> il DOIT partir en
    # run_job detache (regle 3 : deporter le long). Mais run_job n'a pas de script_args.
    # D'ou ce marqueur, motif deja employe par Nokido (sandbox/m2m_mode.txt,
    # tools_compact.txt) : consomme AU DEMARRAGE (unlink immediat) pour qu'il ne puisse
    # jamais armer un second push par oubli.
    # Le marqueur porte DEUX lignes : la branche, puis le depot (optionnel).
    # MESURE 2026-08-19 : le super-depot `nokido-workspace` doit etre pousse lui
    # aussi, mais son `.git` n'accorde AUCUN droit a `LaForgeTrusted` -- seul
    # `LaForgeSbxOffline` en a (icacls). `trusted_script --repo` rendait donc un
    # `rev-parse` VIDE et un « remote inconnu », sans jamais dire pourquoi.
    # CORRECTION 2026-08-20 : la suite de cette note disait que le marqueur +
    # `run_job online` reglait le cas. C'est FAUX, mesure des deux cotes le
    # meme jour sur le super-depot :
    #   - `online=true`  -> `rev-parse` VIDE, remotes inconnus (pas de droit)
    #   - `online=false` -> branche lue, remote trouve, echec RESEAU seul
    # Les deux comptes sont donc complementaires et aucun ne suffit : celui qui
    # a le reseau n'a pas le `.git`, celui qui a le `.git` n'a pas le reseau.
    # Publier le super-depot demande une decision owner (ACL, ou push manuel).
    # Le marqueur reste le bon canal pour un push LONG du sous-module.
    marker = ROOT / "sandbox" / "push_sovereign.armed"
    if marker.exists():
        try:
            lignes = marker.read_text(encoding="utf-8").strip().splitlines()
            br = (lignes[0].strip() if lignes and lignes[0].strip() else br)
            if len(lignes) > 1 and lignes[1].strip():
                _REPO = Path(lignes[1].strip()).resolve()
                print("[marqueur] depot cible : %s" % _REPO)
        except Exception:
            pass
        try:
            marker.unlink()
        except Exception:
            pass
        args.push = True
        print("[marqueur] push ARME pour '%s' (marqueur consomme)" % br)

    # Plus aucune lecture de vault : l'auth passe par le credential helper de git, qui
    # fonctionne depuis le sandbox (mesure 2026-07-17). Exiger un token ici ferait
    # echouer le push la ou il marche.
    head = git("rev-parse", "--short", br).stdout.strip()
    print("branche %s = %s" % (br, head))
    spec, motif = refspec(br, args.sha) if head else (None, None)
    if head and not spec:
        say("[FATAL] %s -- rien pousse." % motif)
        return 5
    if args.sha:
        print("sha pousse = %s (certifie), refspec %s" % (spec.split(":")[0][:12], spec))
    if not head:
        # FAUX-VERT MESURE 2026-08-20 : sous un compte sans droit sur le `.git`
        # vise, git rend une sortie VIDE et un stderr VIDE. Tous les remotes
        # passaient alors en « inconnu -> skip » et le script rendait rc=0.
        # Un push qui n'a rien pousse ne doit JAMAIS rendre 0 : c'est ce
        # faux-vert qui a fait croire le super-depot publie alors qu'il ne
        # l'etait pas. On s'arrete ici, en NOMMANT la cause probable.
        say("[FATAL] '%s' illisible dans %s -- droits insuffisants sur le .git ?"
            % (br, _REPO))
        return 3
    print()
    if not args.push:
        _ci_github_rouges(br, spec.split(":")[0])

    rc_all = 0
    traites = 0
    for remote, (secret_name, user) in TARGETS.items():
        url = git("remote", "get-url", remote).stdout.strip()
        if not url:
            print("[%s] remote inconnu -> skip" % remote)
            continue
        traites += 1
        ahead = git("rev-list", "--count",
                    "%s/%s..%s" % (remote, br, spec.split(":")[0])).stdout.strip()
        print("[%s] %s" % (remote, url))
        print("       retard connu localement : %s commits" % (ahead or "?"))

        # 2026-07-17 -- NE PAS injecter de token dans l'URL. Mesure : pousser vers une URL
        # BRUTE renvoie rc=128 MUET (stderr vide), alors que le remote NOMME passe (rc=0,
        # egress YELLOW -> OK). Cause : core.hooksPath=.githooks porte un pre-push qui
        # resout `origin/<meme-branche>` pour sa base de diff (cf commit 8e64957d) ; avec
        # une URL, git lui passe l'URL la ou il attend un NOM de remote -> il casse.
        # L'injection de token CASSAIT donc l'egress gate -- elle fabriquait le probleme
        # qu'elle croyait resoudre.
        # Et elle etait INUTILE : l'auth fonctionne deja depuis le sandbox (ls-remote et
        # push --dry-run s'authentifient seuls). La memoire "push = SEUL user, creds
        # git caches" est PERIMEE : ni token ni shell owner ne sont necessaires.
        if not args.push:
            r = git("push", "--dry-run", remote, spec, timeout=300)
            say("       DRY-RUN rc=%d" % r.returncode)
            for line in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-8:]:
                say("       | " + line[:150])
            print()
            continue

        r = git("push", remote, spec, timeout=900)
        out = (r.stdout or "") + (r.stderr or "")
        say("       rc=%d" % r.returncode)
        for line in out.strip().splitlines()[-25:]:
            say("       | " + line[:150])
        if r.returncode != 0:
            # Un MIROIR en echec (Codeberg « Quota exceeded », blocage connu et deja en
            # roadmap) ne doit pas faire echouer une publication REUSSIE vers origin :
            # un code de sortie qui crie a faux se fait ignorer, et c'est alors le vrai
            # echec qu'on ne verra plus. L'echec du miroir reste ECRIT, il n'est pas tu.
            if remote == "origin":
                rc_all = r.returncode
            else:
                say("       [miroir KO] %s -- publication vers origin NON affectee" % remote)
        print()

    if not traites:
        # Meme regle : aucun remote atteint = rien n'a ete publie. Le dire par
        # le code de sortie, pas seulement dans un log que personne ne relit.
        say("[FATAL] aucun remote traite dans %s -- rien n'a ete pousse." % _REPO)
        return 4
    if not args.push:
        print("Relancer avec --push pour publier.")
    return rc_all


if __name__ == "__main__":
    raise SystemExit(main())
