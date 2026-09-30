"""forge_prepush_cliquets.py -- joue au PRE-PUSH les cliquets-outils de la CI, sur le SHA POUSSE.

POURQUOI (owner 2026-09-26, « oui ajoute le »)
  La CI de reference sur f6b3613bb est tombee sur deux cliquets -- golden-rules (forge_key_rotation 3 -> 4) et
  duplication (3 groupes de clones) -- venus de commits faits des JOURS plus tot. Ils se jouent en secondes ; ils
  ne l'etaient qu'en CI complete (35 min), donc APRES coup, et un pre-controle pytest ne les voit pas. Ici ils
  arretent le push AVANT la publication, pour toute surface qui pousse par git (le hook est versionne,
  `core.hooksPath = .githooks`).

CE QU'IL JUGE : le SHA POUSSE, dans un worktree detache (`ci_local --only ... --reference <sha>`), JAMAIS l'arbre
  partage -- qui porte le travail NON commite des autres surfaces : le juger bloquerait un push pour les clones
  d'un autre agent, ou laisserait passer ce qui n'est pas pousse.

TROIS ETATS, jamais deux :
  OK          -> le push continue (le filtre d'egress juge ensuite) ;
  ROMPU       -> le push est BLOQUE, et les violations sont NOMMEES ;
  NON_MESURE  -> l'outil n'a pas pu juger : AVERTIT sans bloquer. Un garde neuf qui crie sur une panne d'infra
                 se fait desarmer ; la CI de reference reste le filet.

CE QU'IL NE FAIT PAS : aucun autre gate (pytest reste a la CI) ; aucune ecriture dans le depot.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : cliquets de la CI joues au pre-push sur le sha pousse"

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATES = ("golden-rules", "duplication")
OK, ROMPU, NON_MESURE = "OK", "ROMPU", "NON_MESURE"
_BORNE_S = 900


def _python() -> str:
    """Interpreteur de reference du depot ; repli DIT sur l'interpreteur courant."""
    try:
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT / "app"))
        from forge_python_bin import LAFORGE_PYTHON  # noqa: PLC0415

        return str(LAFORGE_PYTHON)
    except Exception as exc:  # noqa: BLE001 -- repli annonce, jamais silencieux
        print("[pre-push] forge_python_bin illisible (%s) -- repli sur %s"
              % (type(exc).__name__, sys.executable), file=sys.stderr, flush=True)
        return sys.executable


def shas_a_verifier(stdin_text: str) -> list:
    """Lignes git pre-push « <ref locale> <sha local> <ref distante> <sha distant> » -> shas LOCAUX a juger,
    dans l'ordre, sans doublon. Une suppression de branche (sha local nul) ne pousse aucun code : ignoree."""
    vus = []
    for ligne in (stdin_text or "").splitlines():
        champs = ligne.split()
        if len(champs) != 4:
            continue
        sha = champs[1]
        if set(sha) == {"0"}:
            continue
        if sha not in vus:
            vus.append(sha)
    return vus


def commande(sha: str, python: str | None = None) -> list:
    cmd = [python or _python(), str(ROOT / "tools" / "ci_local.py")]
    for gate in GATES:
        cmd += ["--only", gate]
    return cmd + ["--reference", sha]


def classer(sortie: str) -> str:
    """Verdict lu sur la SORTIE de ci_local (son resume), jamais sur un code de retour seul."""
    texte = sortie or ""
    if "Tous les gates bloquants passent" in texte:
        return OK
    if "CLIQUET ROMPU" in texte or "bloquant(s) en" in texte:  # « N gate(s) bloquant(s) en echec »
        return ROMPU
    return NON_MESURE


def _lancer(cmd: list):
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=_BORNE_S)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return None, "borne de %d s atteinte" % _BORNE_S
    except OSError as exc:
        return None, "lancement impossible : %s" % type(exc).__name__


def main(stdin_text: str | None = None, lancer=None) -> int:
    texte = sys.stdin.read() if stdin_text is None else stdin_text
    lancer = lancer or _lancer
    code = 0
    for sha in shas_a_verifier(texte):
        rc, sortie = lancer(commande(sha))
        etat = classer(sortie)
        if etat == OK:
            print("[pre-push] cliquets %s VERTS sur %s" % (" + ".join(GATES), sha[:12]), file=sys.stderr, flush=True)
        elif etat == ROMPU:
            code = 1
            # ci_local reimprime la « derniere sortie » du gate prefixee de « │ » : sans ce filtre chaque
            # violation sortait deux fois (preuve chemin reel du 26/09 sur f6b3613bb).
            lignes = []
            for l in sortie.splitlines():
                l = l.strip()
                if l.startswith("│") or not ("CLIQUET ROMPU" in l or l.startswith("+ ")) or l in lignes:
                    continue
                lignes.append(l)
            print("[pre-push] PUSH BLOQUE : cliquet(s) rompu(s) sur %s\n  %s\n  Rejouer : tools/ci_local.py "
                  "--only golden-rules --only duplication --reference %s"
                  % (sha[:12], "\n  ".join(lignes[:30]) or "(detail dans la sortie de ci_local)", sha),
                  file=sys.stderr, flush=True)
        else:
            print("[pre-push] cliquets NON MESURES sur %s (rc=%s) : %s -- push NON bloque, la CI reste le filet"
                  % (sha[:12], rc, " ".join(sortie.split())[-300:]), file=sys.stderr, flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
