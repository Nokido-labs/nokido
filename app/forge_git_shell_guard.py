# -*- coding: utf-8 -*-
"""Souverainete git/gh et filtre anti-injection pour shells (hub et bash_guard).

__FORGE_COLOR__ = 'immunitaire/garde'
Date: 2026-11-08

Porte les regles souveraines git/gh et la normalisation/descente pour toute
commande shell executee par le hub ou filtree par tools/bash_guard.py.
Pur Python stdlib sans dependance externe lourde.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/garde"

import re
import shlex
import sys
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES CENTRALISEES GIT / GH (source unique)
# ─────────────────────────────────────────────────────────────────────────────

_GIT_OPTS_A_VALEUR = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--config-env"}
_GIT_CONFIG_SENSIBLE = (
    "alias.",
    "core.hookspath",
    "core.sshcommand",
    "core.gitproxy",
    "core.fsmonitor",
    "protocol.ext",
)
_REFUS_PUSH = (
    "git push direct : voie unique tools/forge_push_sovereign.py en run_job "
    "(pre-push forge_git_egress), sur GO owner. --dry-run reste permis."
)
_REFUS_HOOKS = "contournement des crochets git (pre-commit, pre-push) : interdit."
_GH_GROUPES_LECTURE = {"pr", "issue", "run", "repo", "release", "workflow", "gist", "label", "cache"}
_GH_VERBES_LECTURE = {"view", "list", "diff", "checks", "status", "watch", "", "--help", "-h"}
_REFUS_GH = (
    "gh hors lecture : seules les lectures passent (view, list, diff, checks, status, watch ; "
    "api en GET). Une ecriture GitHub est un geste owner. "
    "CI : hub demander_ordre ordre=ci-lancer cible=<workflow>.yml@<ref>"
)


# Levier (c), mesure 9/11 : un diff/show nu rapatrie tout le patch (CRLF compris) dans le
# contexte du client, refacture a chaque tour. La forme bornee reste permise : jamais couper l'acces.
_GIT_DIFF_BORNE = ("--stat", "--shortstat", "--numstat", "--name-only", "--name-status", "--summary",
                   "--dirstat", "--no-patch", "--quiet", "--exit-code", "--check", "-s")
_REFUS_DIFF_NU = ("git diff/show non borne : le patch entier entre dans le contexte. Forme permise : "
                  "--stat (ou --name-only/--shortstat) d'abord, puis le diff cible `-- <fichier>`, "
                  "ou le blob `git show <rev>:<chemin>` ; ajouter --ignore-cr-at-eol si CRLF.")


def _refus_git(args: list) -> str | None:
    """Analyse les arguments d'une commande git et renvoie un motif de refus ou None."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        opt = args[i]
        if opt == "-c":
            valeur = (args[i + 1] if i + 1 < len(args) else "").lower()
            if any(valeur.startswith(s) for s in _GIT_CONFIG_SENSIBLE) or "core.hookspath" in valeur:
                return _REFUS_HOOKS
        elif opt.lower().startswith(("-c", "--config-env")):
            valeur = opt.split("=", 1)[1].lower() if "=" in opt else opt[2:].lower()
            if any(valeur.startswith(s) for s in _GIT_CONFIG_SENSIBLE) or "core.hookspath" in valeur:
                return _REFUS_HOOKS
        i += 2 if opt in _GIT_OPTS_A_VALEUR else 1
    sous = args[i].lower() if i < len(args) else ""
    reste = args[i + 1:]
    # stdout vers un fichier (`> p.patch`, voie d'integration) : rien n'entre dans le contexte.
    vers_fichier = any(re.match(r"^1?>>?(?!&)", t) for t in reste)
    chemin_cible = vers_fichier or ("--" in reste and reste.index("--") < len(reste) - 1)
    if "--" in reste:
        reste = reste[: reste.index("--")]
    if sous in ("diff", "show") and not chemin_cible:
        opts = [t.lower().split("=", 1)[0] for t in reste if t.startswith("-")]
        blob = sous == "show" and any(":" in t for t in reste if not t.startswith("-"))
        if not blob and not any(o in _GIT_DIFF_BORNE for o in opts):
            return _REFUS_DIFF_NU
    options = [t.lower() for t in reste if t.startswith("-")]
    positionnels = [t.lower() for t in reste if not t.startswith("-")]
    if any(t.startswith("--no-ve") and "--no-verify".startswith(t.split("=")[0]) for t in options):
        return _REFUS_HOOKS
    # -n vaut --no-verify pour commit et am (seul, ou groupe : -an, -nm).
    if sous in ("commit", "am") and any(re.fullmatch(r"-[a-z]*n[a-z]*", t) for t in options):
        return _REFUS_HOOKS
    if sous == "push" or (sous in ("lfs", "subtree") and positionnels[:1] == ["push"]):
        essai = any(t.startswith("--dry") or re.fullmatch(r"-[a-z]*n[a-z]*", t) for t in options)
        return None if sous == "push" and essai else _REFUS_PUSH
    if sous == "config" and len(positionnels) >= 2 and any(
        t.startswith(_GIT_CONFIG_SENSIBLE) for t in positionnels
    ):
        return _REFUS_HOOKS
    return None


def _refus_gh(args: list) -> str | None:
    """Analyse les arguments d'une commande gh et renvoie un motif de refus ou None."""
    if not args:
        return None
    groupe = args[0].lower()
    if groupe in ("--version", "version", "--help", "-h", "help", "status", "search"):
        return None
    if groupe == "auth":
        return None if [t.lower() for t in args[1:2]] == ["status"] else _REFUS_GH
    if groupe == "api":
        reste = [t.lower() for t in args[1:]]
        if "graphql" in reste:
            return _REFUS_GH
        for j, t in enumerate(reste):
            if t.startswith(("-f", "--field", "--raw-field", "--input")):
                return _REFUS_GH
            if t in ("-x", "--method"):
                if (reste[j + 1] if j + 1 < len(reste) else "") != "get":
                    return _REFUS_GH
            elif t.startswith(("-x", "--method=")) and not t.endswith("get"):
                return _REFUS_GH
        return None
    verbe = args[1].lower() if len(args) > 1 else ""
    return None if groupe in _GH_GROUPES_LECTURE and verbe in _GH_VERBES_LECTURE else _REFUS_GH


def refus_git_gh(seg: str) -> str | None:
    """Motif de refus d'un segment git ou gh ; None s'il n'est pas concerne ou s'il est permis."""
    try:
        jetons = shlex.split(seg.strip())
    except ValueError:
        # Guillemet non ferme : analyse douteuse, on tranche sur le texte brut, cote refus.
        return _REFUS_PUSH if re.match(r"\s*(git|gh)\b", seg, re.I) and re.search(
            r"\bpush\b|--no-ve|\b(create|delete|merge|edit)\b", seg, re.I) else None
    if not jetons:
        return None
    programme = jetons[0].lower()
    prog_base = Path(programme).name.lower()
    if prog_base.endswith(".exe"):
        prog_base = prog_base[:-4]
    if prog_base == "git":
        return _refus_git(jetons[1:])
    if prog_base == "gh":
        return _refus_gh(jetons[1:])
    return None


def split_segments(cmd: str) -> list:
    """Decoupe sur && || ; et retours ligne, SANS couper a l'interieur d'une
    chaine quotee : un && / ; / saut de ligne dans `git commit -m "a && b"`
    n'est PAS un separateur shell. Fallback strict (split naif) si une quote
    reste ouverte = parse douteux -> on prefere sur-bloquer.
    PAS de decoupe sur le pipe `|` seul : Layer 1 bloque deja la source d'un
    secret, garder `|` entier preserve `git log | grep ...`."""
    segs, buf, i, n, quote = [], [], 0, len(cmd), None
    while i < n:
        c = cmd[i]
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"' and i + 1 < n:
                i += 1
                buf.append(cmd[i])
            i += 1
            continue
        if c in "\"'":
            quote = c
            buf.append(c)
            i += 1
            continue
        if c in ";\n":
            segs.append("".join(buf))
            buf = []
            i += 1
            continue
        if c in "&|" and i + 1 < n and cmd[i + 1] == c:
            segs.append("".join(buf))
            buf = []
            i += 2
            continue
        buf.append(c)
        i += 1
    segs.append("".join(buf))
    if quote is not None:  # quote non fermee = parse douteux
        return re.split(r"&&|\|\||;|\n", cmd)  # fail-safe : decoupe stricte
    return segs


# ─────────────────────────────────────────────────────────────────────────────
# FILTRE COUVRANT POUR LE HUB : NORMALISATION, DESCENTE, INJECTION, FAIL-CLOSED
# ─────────────────────────────────────────────────────────────────────────────

def _has_unclosed_quotes(s: str) -> bool:
    quote = None
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if quote:
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"' and i + 1 < n:
                i += 1
        elif c in "\"'":
            quote = c
        i += 1
    return quote is not None


def _split_shell_segments(cmd: str) -> list[str]:
    """Decoupe un texte shell sur &, &&, ||, |, ;, \\n tout en respectant les quotes."""
    segs = []
    buf = []
    i = 0
    n = len(cmd)
    quote = None
    while i < n:
        c = cmd[i]
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"' and i + 1 < n:
                i += 1
                buf.append(cmd[i])
            i += 1
            continue
        if c in "\"'":
            quote = c
            buf.append(c)
            i += 1
            continue
        if c in ";\n":
            seg = "".join(buf).strip()
            if seg:
                segs.append(seg)
            buf = []
            i += 1
            continue
        if c in "&|":
            # Redirection >&1, 2>&1
            if c == "&" and buf and buf[-1] in (">", "<"):
                buf.append(c)
                i += 1
                continue
            if i + 1 < n and cmd[i + 1] == c:
                seg = "".join(buf).strip()
                if seg:
                    segs.append(seg)
                buf = []
                i += 2
                continue
            seg = "".join(buf).strip()
            if seg:
                segs.append(seg)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    seg = "".join(buf).strip()
    if seg:
        segs.append(seg)
    return segs


def _unwrap_shell(s: str) -> str:
    """Descend dans les shells imbriques (cmd /c, powershell -c, start, call)."""
    current = s.strip()
    while True:
        # cmd /c ou cmd.exe /c (/k)
        m_cmd = re.match(
            r"^(?:cmd(?:\.exe)?)\s+(?:/[a-zA-Z0-9]+\s+)*[/-][ck]\s+(.*)$",
            current,
            re.I | re.DOTALL,
        )
        if m_cmd:
            inner = m_cmd.group(1).strip()
            if (inner.startswith('"') and inner.endswith('"')) or (inner.startswith("'") and inner.endswith("'")):
                inner = inner[1:-1].strip()
            current = inner
            continue

        # powershell / pwsh avec -Command ou -c
        m_ps = re.match(
            r"^(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\s+.*?[/-](?:command|c)\s+(.*)$",
            current,
            re.I | re.DOTALL,
        )
        if m_ps:
            inner = m_ps.group(1).strip()
            if (inner.startswith('"') and inner.endswith('"')) or (inner.startswith("'") and inner.endswith("'")):
                inner = inner[1:-1].strip()
            current = inner
            continue

        # start / call
        m_call = re.match(
            r"^(?:call|start(?:\s+/[a-zA-Z0-9]+)*(?:\s+\"[^\"]*\")?)\s+(.*)$",
            current,
            re.I | re.DOTALL,
        )
        if m_call:
            inner = m_call.group(1).strip()
            if (inner.startswith('"') and inner.endswith('"')) or (inner.startswith("'") and inner.endswith("'")):
                inner = inner[1:-1].strip()
            current = inner
            continue

        break
    return current


_EXE_REGEX = re.compile(
    r"""^\s*
    (?:
        (["'])(?P<quoted_exe>[^"']+)\1
        |
        (?P<unquoted_path>(?:[a-zA-Z]:[^\r\n;|&<]*?|[^\r\n;|&<]*?)[\\/](?:git|gh)(?:\.exe)?)
        |
        (?P<word>[^\s;|&<>]+)
    )
    (?:\s+(?P<args>.*))?$""",
    re.VERBOSE | re.IGNORECASE | re.DOTALL,
)


def _evaluer_segment(seg: str) -> str | None:
    """Evalue un segment unique. Renvoie un motif de refus ou None."""
    unwrapped = _unwrap_shell(seg)
    if unwrapped != seg:
        sub_segs = _split_shell_segments(unwrapped)
        if len(sub_segs) > 1 or sub_segs != [seg]:
            for s in sub_segs:
                motif = _evaluer_segment(s)
                if motif:
                    return motif
            return None
        seg = unwrapped

    # Normalisation caret cmd
    seg_carets = re.sub(r"\^([a-zA-Z0-9_\"'])", r"\1", seg)

    m = _EXE_REGEX.match(seg_carets)
    if not m:
        return None

    prog_stem = None
    args_str = m.group("args") or ""

    if m.group("quoted_exe"):
        raw_exe = m.group("quoted_exe")
        name = Path(raw_exe).name.lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name in ("git", "gh"):
            prog_stem = name

    elif m.group("unquoted_path"):
        raw_path = m.group("unquoted_path")
        name = Path(raw_path).name.lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name in ("git", "gh"):
            prog_stem = name

    elif m.group("word"):
        word = m.group("word")
        word_clean = word.replace('"', '').replace("'", '').replace('^', '').lower()
        name = Path(word_clean).name.lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name in ("git", "gh"):
            prog_stem = name

    if prog_stem is None:
        # Ni git ni gh nomme comme commande dans ce segment
        return None

    # GIT OU GH NOMME : VERIFICATION INJECTIONS
    if "$(" in seg:
        return "injection detectee avec git/gh : substitution $()"
    if "`" in seg:
        return "injection detectee avec git/gh : substitution backtick"
    if re.search(r"%[a-zA-Z0-9_#$@.-]+%", seg):
        return "injection detectee avec git/gh : variable %VAR%"
    if re.search(r"![a-zA-Z0-9_#$@.-]+!", seg):
        return "injection detectee avec git/gh : variable retardee !VAR!"
    if re.search(r"\bext::", seg, re.I):
        return "injection detectee avec git : protocole ext:: interdit"
    if re.search(r"--upload-pack\b", seg, re.I):
        return "injection detectee avec git : option --upload-pack interdite"
    if re.search(r"--receive-pack\b", seg, re.I):
        return "injection detectee avec git : option --receive-pack interdite"
    if re.search(r"--exec\b", seg, re.I):
        return "injection detectee avec git : option --exec interdite"

    # -c / --config-env en LISTE BLANCHE (constitution : n'est sain que ce qui est prouve sain).
    # Une liste noire laissait passer core.pager, credential.helper, diff.external, core.editor...
    # qui EXECUTENT tous un programme. Relecture Claude 2026-11-08.
    if prog_stem == "git":
        # SENSIBLE A LA CASSE : `-C <chemin>` (repertoire) est legitime, seul `-c` pose une config.
        for m_cfg in re.finditer(r"(?:^|\s)(?:-c|--config-env)(?:=|\s+)?([\"']?)([^\s\"'=]+)", seg_carets):
            cle = m_cfg.group(2).lower()
            if cle not in _GIT_C_PERMIS:
                return f"configuration git -c hors liste blanche : {cle} (seul {', '.join(sorted(_GIT_C_PERMIS))})"
        if _GIT_SOUS_COMMANDE_EXEC.search(seg_carets):
            return "sous-commande git qui execute un programme arbitraire : refusee par le hub"

    # Verifications standard via refus_git_gh
    norm_cmd = f"{prog_stem} {args_str}".strip()
    try:
        jetons = shlex.split(norm_cmd)
    except ValueError:
        return "texte inanalysable nommant git/gh : refuse (fail-closed)"

    if not jetons:
        return None

    if jetons[0] == "git":
        return _refus_git(jetons[1:])
    if jetons[0] == "gh":
        return _refus_gh(jetons[1:])
    return None


_GIT_C_PERMIS = frozenset({"safe.directory"})
_GIT_SOUS_COMMANDE_EXEC = re.compile(
    r"\bgit(?:\.exe)?\b.*?\s(?:rebase\b.*\s(?:-x|--exec)\b|difftool\b.*\s(?:-x|--extcmd)\b|"
    r"submodule\s+foreach\b|bisect\s+run\b|filter-branch\b|filter-repo\b)", re.I)
# Variable d'environnement GIT_*/GH_* posee dans la meme commande (cmd `set`, PowerShell `$env:`) :
# GIT_SSH_COMMAND, GIT_CONFIG_PARAMETERS, GIT_EXTERNAL_DIFF, GH_TOKEN... detournent git/gh sans
# que le segment git ne porte rien de suspect.
_ENV_GIT_GH = re.compile(r"(?:\bset\s+\"?|\$env:)(?:GIT|GH)_\w*\s*=", re.I)


def refus_commande_shell(cmd: str) -> str | None:
    """Analyse complete d'une commande shell recue par le hub.

    Renvoie un motif de refus si la commande enfreint la souverainete git/gh,
    utilise des injections interdites, ou est inanalysable tout en nommant git/gh.
    Renvoie None si la commande est permise.
    """
    if not cmd or not isinstance(cmd, str):
        return None

    if _ENV_GIT_GH.search(cmd):
        return "injection : variable d'environnement GIT_*/GH_* posee dans la commande (refusee par le hub)"

    # Fail-closed sur guillemets non fermes si git ou gh est nomme
    if _has_unclosed_quotes(cmd):
        cmd_clean = re.sub(r"\^([a-zA-Z0-9_\"'])", r"\1", cmd)
        cmd_clean = re.sub(r'(?<=\w)["\'](?=\w)', '', cmd_clean)
        if re.search(r"\b(git|gh)(?:\.exe)?\b", cmd_clean, re.I):
            return "texte inanalysable (guillemet non ferme) nommant git/gh : refuse (fail-closed)"

    segments = _split_shell_segments(cmd)
    for seg in segments:
        motif = _evaluer_segment(seg)
        if motif:
            return motif

    return None
