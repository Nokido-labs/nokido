#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_anon_push.py -- push ANONYMISE vers le remote public.

[PERIME 2026-08-29] -> l'anonymisation se fait desormais A LA SOURCE : l'identite
de l'agent n'est plus ecrite dans le message de commit mais posee en NOTE git
(`refs/notes/laforge-agent`, `.githooks/post-commit`), qui n'entre pas dans le hash
et ne part pas au push. Motif du changement : reecrire les commits au push donne des
sha differents du local, or le superrepo bumpe un gitlink qui doit exister au
distant -- il pointerait un commit absent et le submodule serait irrecuperable au
clone. Ce module reste ici pour un miroir SANS submodule, ou pour rejouer un
historique deja publie en clair ; il n'est plus le chemin de publication courant
(celui-ci est `forge_push_sovereign.py`).

Contrat owner 2026-08-28 : chaque agent s'IDENTIFIE dans le commit LOCAL (trailer
Co-Authored-By: <AGENT> et/ou Nokido-Agent: <AGENT>), mais le push public ANONYMISE
-- on ne montre pas sur GitHub quel agent a produit quel patch. Feinte SANS signature
(aucun GPG). Le LOCAL reste la verite tracee ; le remote n'est qu'un miroir anonyme.

Mecanique, SANS toucher alpha local : on rejoue base..<branche> sur un miroir en
(1) retirant les trailers d'identite agent des messages et (2) forcant author +
committer a l'identite OWNER generique (celle de `git config user.*`). commit-tree
ne signe pas. Un ref locale refs/anon-mirror/<branche> memorise le dernier tip local
rejoue ; le miroir part du tip DISTANT courant.

dry-run par defaut : montre ce qui serait anonymise, ne pousse RIEN.

Usage :
    forge_anon_push.py --branch alpha                 # dry-run
    forge_anon_push.py --branch alpha --apply          # construit le miroir + push
    forge_anon_push.py --branch alpha --remote origin
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "infra/deploy : push anonymise vers le remote public (PERIME 2026-08-29)"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# trailers d'identite agent a retirer au push (identite LOCALE seulement)
# Trailers d'identite LOCALE a retirer au push : LaForge-Agent-Name/Channel sont
# ceux que forge_git_gate (prepare-commit-msg) pose reellement ; Co-Authored-By /
# Nokido-Agent sont couverts au cas ou un commit y a echappe.
_TRAILER = re.compile(
    r"(?im)^\s*(co-authored-by|nokido-agent|laforge-agent-name|laforge-agent-channel)\s*:.*$")


_CRED_CACHE = None


def _cred_args_partages():
    """Jetons du coffre servis a git, empruntes a forge_push_sovereign.

    Anti-dup : ce module a deja resolu comment servir un token PAR HOTE sans jamais
    l'ecrire dans l'URL ni dans une cmdline que le hub journalise. Sans eux, tout
    acces distant echoue -- mesure 2026-08-29 : `ls-remote` rendait rc!=0 sous
    LaForgeTrusted, ce qui s'est d'abord lu a tort comme une absence de RESEAU alors
    que c'etait une absence d'AUTHENTIFICATION (le meme compte joignait GitHub via
    forge_push_sovereign a la minute suivante).
    """
    global _CRED_CACHE
    if _CRED_CACHE is None:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from nokido_agent.tools.forge_push_sovereign import _cred_args
            _CRED_CACHE = _cred_args()
        except Exception as e:  # noqa: BLE001 - degrade, mais JAMAIS en silence
            sys.stderr.write("[anon-push] jetons du coffre indisponibles (%s: %s) : "
                             "les acces distants se feront SANS authentification\n"
                             % (type(e).__name__, e))
            _CRED_CACHE = []
    return _CRED_CACHE


def git(*args, env=None, check=False):
    e = dict(os.environ if env is None else env)
    # Sans ceci git ATTEND un prompt qui ne viendra jamais : `ls-remote` PEND et un
    # push sort en rc 128 SANS message (RULES_SHARED). Mesure 2026-08-29 : c'est
    # exactement ce qui faisait echouer _tip_distant, et l'echec a ete impute au
    # RESEAU puis a l'AUTHENTIFICATION avant d'etre enfin mesure -- deux causes
    # inventees pour une ligne manquante deja ecrite dans la doctrine.
    e.setdefault("GIT_TERMINAL_PROMPT", "0")
    r = subprocess.run(["git", "-c", "safe.directory=*", *_cred_args_partages(),
                        "-C", ROOT, *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=e, timeout=120)
    if check and r.returncode != 0:
        raise RuntimeError("git %s : %s" % (" ".join(args), r.stderr.strip()))
    return r.returncode, r.stdout, r.stderr


def _identite_owner():
    _, n, _ = git("config", "user.name")
    _, e, _ = git("config", "user.email")
    return (n.strip() or "owner"), (e.strip() or "owner@localhost")


def _message_anonyme(sha):
    _, msg, _ = git("show", "-s", "--format=%B", sha)
    lignes = [l for l in msg.splitlines() if not _TRAILER.match(l)]
    while lignes and not lignes[-1].strip():
        lignes.pop()
    return "\n".join(lignes) + "\n", msg


def _commits(base, tip):
    rc, out, _ = git("rev-list", "--reverse", "%s..%s" % (base, tip))
    return [s for s in out.split() if s] if rc == 0 else []


def _tip_distant(branche, remote):
    """Tip REEL du distant, retenu seulement s'il est un ancetre du local.

    La ref de suivi `<remote>/<branche>` MENT : un push lance par un job ne peut pas
    ecrire refs/remotes/, donc elle reste figee. Mesure 2026-08-29 : base calculee a
    9aaaa85d05 alors que le distant etait a cc707b9313, soit 21 commits DEJA PUBLICS
    reproposes a l'anonymisation. `ls-remote` est la seule autorite sur le distant.

    L'ancestralite est requise : quand le distant est un miroir anonymise, ses sha
    n'existent pas en local et seule la ref miroir sait ou l'on s'etait arrete.
    """
    rc, out, err = git("ls-remote", remote, "refs/heads/%s" % branche)
    if rc != 0 or not out.strip():
        return None, "ls-remote a echoue (rc=%s) %s" % (rc, (err or "").strip()[:120])
    tip = out.split()[0]
    rc, _, _ = git("merge-base", "--is-ancestor", tip, branche)
    if rc != 0:
        return None, ("le tip distant %s n'est pas un ancetre du local "
                      "(distant deja anonymise ?)" % tip[:10])
    return tip, "ls-remote"


def _base_locale(branche, remote):
    """Dernier tip local deja rejoue (ref miroir), sinon tip distant REEL, sinon repli."""
    ref = "refs/anon-mirror/%s" % branche
    rc, out, _ = git("rev-parse", "--verify", ref)
    if rc == 0:
        return out.strip(), ref
    tip, motif = _tip_distant(branche, remote)
    if tip:
        return tip, "ls-remote"
    rc, out, _ = git("merge-base", branche, "%s/%s" % (remote, branche))
    if rc == 0 and out.strip():
        # Repli sur une ref de suivi possiblement PERIMEE : le dire, ne jamais le taire
        # (un silence ici fait republier des commits deja en ligne). Le motif est
        # RAPPORTE, jamais devine : la premiere version de cet avertissement accusait
        # le reseau sans l'avoir mesure.
        sys.stderr.write(
            "[anon-push] base issue de %s/%s (ref de suivi, non verifiee) : %s "
            "-- le nombre de commits peut etre SURESTIME\n" % (remote, branche, motif)
        )
        return out.strip(), "merge-base(ref suivi, non verifiee)"
    return None, None


def run(branche="alpha", remote="origin", apply=False):
    an, ae = _identite_owner()
    base, _ = _base_locale(branche, remote)
    if not base:
        return {"ok": False, "raison": "aucune base (ni ref miroir ni %s/%s)" % (remote, branche)}
    commits = _commits(base, branche)
    apercu = []
    for sha in commits:
        anon, brut = _message_anonyme(sha)
        retires = [l.strip() for l in brut.splitlines() if _TRAILER.match(l)]
        apercu.append({"sha": sha[:10], "sujet": brut.splitlines()[0][:70],
                       "trailers_retires": retires})
    rapport = {"branche": branche, "remote": remote, "base": base[:10],
               "identite_push": "%s <%s>" % (an, ae), "n_commits": len(commits),
               "apercu": apercu, "applique": False}
    if not commits:
        rapport["note"] = "rien a anonymiser (miroir a jour)"
        return rapport
    if not apply:
        rapport["note"] = "DRY-RUN : rien pousse. Relancer avec --apply."
        return rapport

    # construire le miroir : rejouer chaque commit avec commit-tree (author/committer
    # = owner, message anonymise, dates d'origine preservees). Aucune signature.
    rc, tip_distant, _ = git("rev-parse", "%s/%s" % (remote, branche))
    parent = tip_distant.strip()
    for sha in commits:
        anon, _ = _message_anonyme(sha)
        _, tree, _ = git("rev-parse", "%s^{tree}" % sha)
        _, ad, _ = git("show", "-s", "--format=%aI", sha)
        env = dict(os.environ, GIT_AUTHOR_NAME=an, GIT_AUTHOR_EMAIL=ae,
                   GIT_COMMITTER_NAME=an, GIT_COMMITTER_EMAIL=ae,
                   GIT_AUTHOR_DATE=ad.strip(), GIT_COMMITTER_DATE=ad.strip())
        p = subprocess.run(["git", "-c", "safe.directory=*", "-C", ROOT, "commit-tree",
                            tree.strip(), "-p", parent, "-m", anon],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=120)
        if p.returncode != 0:
            rapport["note"] = "commit-tree echoue sur %s : %s" % (sha[:10], p.stderr.strip())
            return rapport
        parent = p.stdout.strip()
    # push du miroir -> branche distante, et memorisation du tip local rejoue
    rc, out, err = git("push", remote, "%s:refs/heads/%s" % (parent, branche))
    if rc != 0:
        rapport["note"] = "push echoue : %s" % (err or out).strip()[:200]
        return rapport
    git("update-ref", "refs/anon-mirror/%s" % branche, commits[-1])
    rapport["applique"] = True
    rapport["miroir_tip"] = parent[:10]
    rapport["note"] = "miroir anonyme pousse -> %s/%s" % (remote, branche)
    return rapport


def main():
    ap = argparse.ArgumentParser(description="Push anonymise (identite agent locale, retiree au push)")
    ap.add_argument("--branch", default="alpha")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    import json
    print(json.dumps(run(a.branch, a.remote, a.apply), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
