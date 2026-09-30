"""forge_bump_superrepo.py — reaccroche le pointeur de submodule du superrepo.

POURQUOI CET OUTIL
  Le superrepo enregistre un SHA par submodule. Tant qu'il n'est pas rafraichi, un
  clone frais ne recupere PAS le travail commite dans le submodule. Mesure du
  2026-07-24 : 44 commits d'avance non repercutes, ecart jamais signale par personne
  jusqu'a ce que forge_delivery_integrity le detecte.

  Le bump ne peut pas se faire depuis le compte sandbox : ecrire a la racine du
  superrepo renvoie `E_ACCESSDENIED`. D'ou ce script, a lancer en compte privilegie :
      run action=trusted_script path=tools/forge_bump_superrepo.py
      script_args="--commit"        (sans --commit : dry-run)

CE QU'IL NE FAIT PAS
  - Aucun `git add -A` : le superrepo porte l'uncommitted d'AUTRES surfaces (cowork,
    Gemini, netcfg-agent). On stage UNIQUEMENT les chemins de submodule en drift.
  - Aucun push : publier reste une decision distincte (cf forge_push_sovereign.py).
  - Aucune ecriture si rien n'a derive : pas de commit vide.

Anti-dup : la DETECTION du drift vit deja dans app/forge_delivery_integrity.py
(_scan_submodule_drift, plumbing ls-tree robuste aux submodules casses). On la
REUTILISE, on ne la reecrit pas.
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/deploy : reaccroche le pointeur de submodule du superrepo"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # le submodule LaForge
SUPERREPO = ROOT.parent
sys.path.insert(0, str(ROOT))

IDENTITY = ("user", "naarobb@gmail.com")


def say(txt: str = "") -> None:
    """ASCII pur : le stdout d'un run_job est en cp1252, un caractere large y tue
    le process et emporte le message qu'on cherchait (cf forge_push_sovereign)."""
    sys.stdout.buffer.write((txt + "\n").encode("ascii", "replace"))
    sys.stdout.flush()


def _auth():
    """Jetons du coffre + env durci, EMPRUNTES a `forge_push_sovereign`.

    Ce module a deja resolu le probleme (helper inline cible par hote, jeton
    passe par l'ENVIRONNEMENT et jamais par la ligne de commande — le hub
    journalise les args de `run`). Le reimplementer ici garantirait qu'ils
    divergent le jour ou l'un des deux est corrige.
    """
    try:
        from nokido_agent.tools import forge_push_sovereign as fps
        return fps._cred_args(), dict(fps._ENV)
    except Exception as e:  # noqa: BLE001
        say("  [auth] forge_push_sovereign indisponible (%s) — git partira SANS "
            "credential, ls-remote et push echoueront sur un depot prive"
            % type(e).__name__)
        import os as _os
        return [], dict(_os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="echo")


def _git_distant(sub, *a: str, timeout: int = 120):
    """git sur un SUBMODULE, avec les credentials du coffre. Rend "" si illisible.

    CE QUI A ETE PAYE (2026-09-07). Le controle « le sha est-il publie ? » appelait
    `forge_delivery_integrity._git`, qui lance git avec l'environnement HERITE, sans
    `env=`. Sur un depot PRIVE, `ls-remote` sort donc vide quel que soit le compte —
    et le garde refusait de bumper « distant illisible » depuis les TROIS comptes du
    hub. Le module allait pourtant chercher les jetons dans `_auth()` deux fonctions
    plus haut, et ne les passait pas a cet appel-la.

    Un garde qui exige une lecture qu'il n'authentifie jamais ne protege rien : il
    interdit. Troisieme incarnation du symptome « sortie vide, conclusion tiree »
    documente dans `git()` — celle-ci au moins DIT « illisible » au lieu d'affirmer
    « aucun drift », donc elle bloque au lieu de mentir.
    """
    cred, env = _auth()
    r = subprocess.run(
        ["git", "-c", "safe.directory=*", *cred, "-C", str(sub), *a],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=env,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def git(*a: str, timeout: int = 120, arbre: bool = False):
    """Invoque git sur le superrepo par --git-dir / --work-tree, PAS par -C.

    Mesure 2026-09-03 : `-C <racine>` change le repertoire COURANT, ce que
    `LaForgeTrusted` ne peut pas faire — son ACE sur la racine est `(RX)` NON
    heritee. Resultat : `ls-tree` rendait une chaine VIDE, rc=0, et l'outil
    concluait « aucun drift » alors que le gitlink etait en retard de 30
    commits. Le diagnostic imprimait pourtant `out=''` : la source parlait,
    personne ne la lisait.

    Or ce meme compte a `(OI)(CI)(M)` sur le `.git` du superrepo ET l'egress :
    en le nommant par `--git-dir`, il lit le depot et peut publier. Aucune ACL
    a elargir — c'etait la mauvaise FORME, pas une capacite absente.

    `--work-tree` n'est ajoute QUE pour les commandes qui TOUCHENT l'arbre de travail
    (`add`, `commit`), via `arbre=True`. Mesure 2026-09-04 : le passer sur une LECTURE
    alors que le repertoire courant est hors de l'arbre fait appliquer par git un
    pathspec implicite tire du CWD — `ls-tree HEAD Nokido` sort alors VIDE avec rc=0,
    et l'outil conclut « aucun drift » sur un pointeur retarde de 47 commits. C'est la
    DEUXIEME incarnation du symptome corrige le 2026-09-03, avec une cause differente :
    le remede d'alors (passer de `-C` a `--git-dir --work-tree`) avait introduit
    celle-ci. Meme sortie vide, meme conclusion fausse, autre origine.
    """
    cred, env = _auth()
    arbre_args = ["--work-tree", str(SUPERREPO)] if arbre else []
    return subprocess.run(
        ["git", "-c", "safe.directory=*",
         "-c", f"user.name={IDENTITY[0]}", "-c", f"user.email={IDENTITY[1]}",
         *cred,
         "--git-dir", str(SUPERREPO / ".git"),
         *arbre_args, *a],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=env,
    )


def publier(branche: str = "alpha"):
    """Pousse le superrepo. A n'appeler QU'APRES publication du submodule.

    Un gitlink qui designe un commit absent du distant rend le submodule
    irrecuperable au clone : l'ordre n'est pas une preference, c'est une
    condition. Le verdict se lit sur le DISTANT — le code de retour de git
    ment dans les deux sens (rc=1 sur un push reussi quand `wincredman` ne
    peut pas memoriser le jeton).
    """
    avant = git("ls-remote", "origin", f"refs/heads/{branche}")
    tip_avant = (avant.stdout or "").split()[0] if avant.stdout.strip() else None
    if avant.returncode != 0 and not tip_avant:
        return {"ok": False, "etat": "DISTANT ILLISIBLE",
                "detail": (avant.stderr or "")[:300]}

    r = git("push", "origin", branche, timeout=300)
    apres = git("ls-remote", "origin", f"refs/heads/{branche}")
    tip_apres = (apres.stdout or "").split()[0] if apres.stdout.strip() else None
    local = git("rev-parse", branche).stdout.strip()

    return {"ok": bool(tip_apres) and tip_apres == local,
            "rc_push_non_fiable": r.returncode,
            "tip_avant": tip_avant, "tip_apres": tip_apres, "local": local,
            "bruit": [l for l in (r.stderr or "").splitlines()
                      if l.strip()][-4:]}


def _phase_publication(branche: str) -> int:
    """Publie le superrepo et lit le verdict sur le DISTANT.

    Extraite de `main` le 2026-09-19 : elle y etait inline derriere un
    `if args.push: ... return`, place AVANT la detection de drift. Consequence
    mesuree : `--commit --push` ne commitait RIEN et annoncait pourtant
    « PUBLIE », parce que sans commit « local == distant » est vrai
    trivialement. Un verdict qui ne sait pas distinguer FAIT de RIEN A FAIRE
    n'est pas un verdict.
    """
    # Diagnostic AVANT le verdict : « DISTANT ILLISIBLE » sans la sortie de
    # git n'apprend rien et fait deviner. On imprime ce que git a dit.
    for sonde in (("rev-parse", "HEAD"), ("--version",)):
        p = git(*sonde)
        say("  [%s] rc=%s out=%r err=%r"
            % (" ".join(sonde), p.returncode,
               (p.stdout or "").strip()[:70], (p.stderr or "").strip()[:150]))
    r = publier(branche)
    if r.get("detail"):
        say("  detail : %s" % r["detail"])
    say("distant avant : %s" % r.get("tip_avant"))
    say("distant apres : %s" % r.get("tip_apres"))
    say("local         : %s" % r.get("local"))
    for l in r.get("bruit", []):
        say("  | %s" % l[:150])
    if r["ok"]:
        say("PUBLIE — le distant porte le meme commit que le local.")
        return 0
    say("NON PUBLIE (ou non verifiable) : %s"
        % r.get("etat", "le distant ne porte pas le commit local"))
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Bump des pointeurs de submodule")
    ap.add_argument("--commit", action="store_true", help="committer (sinon dry-run)")
    ap.add_argument("--message", default="")
    ap.add_argument("--push", action="store_true",
                    help="publier le superrepo (APRES le submodule ; verdict lu "
                         "sur le distant, jamais sur le code de retour de git)")
    ap.add_argument("--branche", default="alpha")
    args = ap.parse_args()

    # `--push` SEUL reste une publication pure (cas legitime : le commit existe
    # deja). Avec `--commit`, on COMMITE D'ABORD : sinon le push publie l'arbre
    # inchange et son verdict « local == distant » est vrai sans rien prouver.
    if args.push and not args.commit:
        return _phase_publication(args.branche)

    try:
        from nokido_agent.app import forge_delivery_integrity as di
    except ImportError as e:
        say(f"ERREUR: detection indisponible ({e})")
        return 2

    drifts = di._scan_submodule_drift()
    if not drifts:
        # « Rien trouve » et « je ne peux pas regarder » ne sont PAS la meme chose.
        # Mesure 2026-07-24 : depuis LaForgeTrusted le scan rendait 0 drift alors que
        # le compte sandbox en voyait un (44 commits) — un scanner muet se lit comme
        # un scanner rassurant. On DIT donc ce qu'on a pu observer.
        say("aucun drift rapporte — diagnostic :")
        say(f"  superrepo         : {SUPERREPO}")
        # `exists()` seul MENT ici : il rend True sur un fichier dont la lecture
        # est refusee. On dit lequel des deux etats on observe.
        try:
            (SUPERREPO / ".gitmodules").read_text(encoding="utf-8", errors="replace")
            _gm = "lisible"
        except FileNotFoundError:
            _gm = "ABSENT"
        except OSError as _e:
            _gm = "existe mais ILLISIBLE (%s) — la liste vient de l'arbre git" % type(_e).__name__
        say(f"  .gitmodules       : {_gm}")
        say(f"  di.SUPERREPO      : {di.SUPERREPO}")
        v = git("--version")
        say(f"  git joignable     : rc={v.returncode} {(v.stdout or v.stderr or '').strip()[:60]}")
        # La sonde interrogeait le chemin « LaForge », nom d'AVANT le renommage du
        # projet : elle sortait donc vide quoi qu'il arrive, et son « out='' » se
        # lisait comme un signe de panne alors qu'il ne disait rien. On lit l'arbre
        # complet et on montre les gitlinks REELS, qui sont l'objet du diagnostic.
        probe = git("ls-tree", "HEAD")
        entrees = (probe.stdout or "").strip().splitlines()
        liens = [l for l in entrees if l.startswith("160000")]
        say(f"  ls-tree HEAD      : rc={probe.returncode} entrees={len(entrees)}"
            f" gitlinks={len(liens)} err={(probe.stderr or '').strip()[:60]!r}")
        for ligne in liens[:10]:
            say("      " + ligne.strip()[:110])
        # Les echecs git que le scanner a AVALES. Sans eux, « aucun drift » et
        # « je n'ai pas pu lire » rendent le meme ecran — c'est ce qui a fait
        # refaire ce diagnostic trois fois. Une liste vide ici est elle-meme une
        # information : le scanner a bien lu, il n'a simplement rien trouve.
        echecs = getattr(di, "DERNIERS_ECHECS_GIT", None)
        if echecs is None:
            say("  echecs git        : NON INSTRUMENTE (forge_delivery_integrity ancien)")
        elif not echecs:
            say("  echecs git        : aucun — le scanner a REELLEMENT pu lire")
        else:
            say("  echecs git avales : %d" % len(echecs))
            for e in echecs[-6:]:
                say("      " + e[:130])
        # Les DEUX valeurs que le scanner compare, par submodule. Trois rondes de
        # diagnostic ont porte sur « a-t-il pu lire ? » sans jamais montrer CE
        # qu'il a lu : quand la lecture reussit et que le verdict reste faux, la
        # seule sonde utile est la comparaison elle-meme.
        # La liste vient de l'ARBRE GIT, jamais de `.gitmodules` : sous
        # LaForgeTrusted ce fichier est illisible (PermissionError) alors que
        # `exists()` y rend True. Lire le fichier ici faisait planter la sonde
        # de diagnostic elle-meme, juste apres avoir affiche « .gitmodules : True ».
        _paths, _err = di._submodules_declares()
        say("  comparaison reelle par submodule :")
        if _err:
            say("      INDETERMINE : %s" % _err)
            _paths = []
        for _p in sorted(set(_paths)):
            _p = _p.strip()
            _sub = SUPERREPO / _p
            _g = _sub / ".git"
            _kind = ("dossier" if _g.is_dir() else "fichier" if _g.is_file()
                     else "INVISIBLE (%s)" % di._pourquoi_invisible(_sub))
            _rec = di._git(SUPERREPO, "ls-tree", "HEAD", _p)
            _real = di._git(_sub, "rev-parse", "HEAD")
            _m = re.search(r"\b([0-9a-f]{40})\b", _rec or "")
            say("      %-22s .git=%-10s pointeur=%s head=%s %s"
                % (_p[:22], _kind[:10],
                   (_m.group(1)[:8] if _m else "ILLISIBLE"),
                   ((_real or "")[:8] or "ILLISIBLE"),
                   "" if (_m and _real and _m.group(1) == _real) else "<-- DIFFERENT"))
        say("  -> si git est injoignable ou l'arbre VIDE, l'absence de drift n'est PAS")
        say("     une preuve que le pointeur est a jour. Un arbre non vide avec des")
        say("     gitlinks listes ci-dessus, en revanche, est une observation REELLE.")
        return 0

    paths = []
    for f in drifts:
        say(f"[drift] {f['target']}: {f['detail']}")
        # On ne STAGE que ce qu'on a pu MESURER. Un `submodule_illisible` dit
        # « je n'ai pas pu regarder » : le bumper reviendrait a reaccrocher le
        # pointeur sur un etat INCONNU — precisement l'erreur que ce scanner
        # denonce, commise par l'outil qui le consomme. Mesure 2026-09-04 :
        # sous LaForgeTrusted, cinq submodules sur six sortent illisibles ; les
        # stager aurait fige cinq pointeurs au hasard pour en corriger un.
        if f.get("kind") == "submodule_non_bumpe":
            paths.append(f["target"])

    if not paths:
        say("")
        say("AUCUN drift MESURE — les entrees ci-dessus sont des ILLISIBLES.")
        say("Rien a stager : on ne reaccroche pas un pointeur qu'on n'a pas lu.")
        return _phase_publication(args.branche) if args.push else 0

    if not args.commit:
        say("")
        # Inatteignable avec --push : `--push` sans `--commit` est sorti plus haut
        # en publication pure. Ici, ni l'un ni l'autre n'est demande.
        say("DRY-RUN. Relancer avec --commit pour reaccrocher le pointeur.")
        return 0

    # `git add` est INUTILISABLE ici, dans les deux formes possibles :
    #   - chemin ABSOLU du submodule -> « fatal: in unpopulated submodule 'Nokido' » :
    #     git veut alors indexer le CONTENU du submodule, ce qui exige qu'il soit
    #     peuple POUR CE COMPTE. LaForgeTrusted lit le `.git` du superrepo, pas
    #     forcement l'interieur de chaque submodule (cinq sur six lui sont
    #     illisibles) ;
    #   - chemin RELATIF -> resolu depuis le CWD, hors de l'arbre pour ce compte,
    #     qui ne peut pas s'y placer (son ACE sur la racine n'est pas heritee).
    #
    # `update-index --cacheinfo` ecrit le gitlink DIRECTEMENT dans l'index. C'est
    # du plumbing : il ne touche ni le working tree ni le submodule, et n'a besoin
    # que du `.git` — precisement ce que ce compte sait lire. Mesure 2026-09-04.
    for f in drifts:
        if f.get("kind") != "submodule_non_bumpe":
            continue
        cible = f["target"]
        sub = SUPERREPO / cible
        sha = di._git(sub, "rev-parse", "HEAD")
        if not sha:
            say("ERREUR: HEAD de %s illisible — on ne fige PAS un pointeur non lu" % cible)
            return 2
        # Le gitlink ne doit JAMAIS designer un commit absent du distant : un
        # clone frais ne pourrait pas resoudre le submodule, qui devient
        # irrecuperable. Ce module ENONCAIT la condition dans sa docstring
        # (« l'ordre n'est pas une preference, c'est une condition ») sans
        # jamais la VERIFIER : il bumpait sur le HEAD local, publie ou non.
        # Mesure 2026-09-04 : le bump a fige un commit non pousse, une minute
        # apres que le meme outil ait rappele la regle.
        ligne = _git_distant(sub, "ls-remote", "origin", "refs/heads/alpha")
        tip = ligne.split()[0] if ligne else None
        if not tip:
            say("ERREUR: distant de %s illisible — on ne bumpe pas a l'aveugle "
                "(un gitlink invalide casse le clone, l'inaction ne casse rien)" % cible)
            return 2
        if sha != tip:
            # `_git` rend "" quand rc==0 (donc ancetre) et None sinon : le doute
            # profite au refus, parce que les deux erreurs n'ont pas le meme cout.
            if di._git(sub, "merge-base", "--is-ancestor", sha, tip) is None:
                say("ERREUR: %s HEAD %s n'est PAS publie (distant %s) — pousser le "
                    "submodule AVANT de reaccrocher le superrepo" % (cible, sha[:8], tip[:8]))
                return 2
            say("  note : %s a de l'avance locale ; on fige %s, qui EST publie"
                % (cible, sha[:8]))
        r = git("update-index", "--cacheinfo", "160000,%s,%s" % (sha, cible))
        if r.returncode != 0:
            say("ERREUR update-index %s rc=%s: %s"
                % (cible, r.returncode, (r.stderr or "").strip()[:250]))
            return r.returncode
        say("  index : %s -> %s" % (cible, sha[:8]))

    # Ne rien committer si le staging est vide (pointeur deja a jour entre-temps).
    if git("diff", "--cached", "--quiet", arbre=True).returncode == 0:
        say("rien de stage — pointeur deja a jour, pas de commit vide")
        return _phase_publication(args.branche) if args.push else 0

    # Le hook du SUPERREPO refuse un sujet de plus de 80 caracteres -- contrainte
    # ABSENTE du submodule, ou les sujets longs passent. Mesure 2026-08-30 : ce
    # script fabriquait 127 caracteres, si bien que l'outil DEDIE au bump etait
    # refuse par le depot qu'il sert, et le pointeur restait en drift. Sujet borne,
    # detail en second -m. Un --message explicite reste sous la responsabilite de
    # l'appelant : on ne le reecrit pas dans son dos.
    if args.message:
        sujet, corps = args.message, ""
    else:
        sujet = "chore(sm): bump gitlink " + ", ".join(paths)
        if len(sujet) > 80:
            sujet = "chore(sm): bump gitlink de %d submodule(s)" % len(paths)
        corps = "\n".join("%s : %s" % (f["target"], f["detail"]) for f in drifts)
        corps += ("\n\nUn clone frais ne recupere PAS le travail commite dans un "
                  "submodule tant que le superrepo pointe l'ancien sha. Ecart "
                  "detecte par forge_delivery_integrity._scan_submodule_drift.")
    r = git(*(["commit", "-m", sujet] + (["-m", corps] if corps else [])), arbre=True)
    say(f"commit rc={r.returncode}")
    for line in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-10:]:
        say("  | " + line[:150])
    if r.returncode != 0:
        return r.returncode
    # L'ordre est une CONDITION, pas une preference : on ne publie que ce qui
    # vient d'etre commite, et le verdict se lit sur le distant.
    return _phase_publication(args.branche) if args.push else 0


if __name__ == "__main__":
    raise SystemExit(main())
