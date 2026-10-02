#!/usr/bin/env python3
"""PreToolUse hook — verrouille Bash/PowerShell.

Deux couches, dans l'ordre :

LAYER 1 — DENYLIST SECRETS (inconditionnelle). Tout pattern capable d'imprimer
  un secret stocke dans le transcript est bloque, peu importe le reste. AUCUN
  passthrough ne contourne. Ferme la fuite de PAT GitHub du 2026-05-20
  (`git remote -v` -> URL remote avec token embarque).

LAYER 2 — ROUTING par segment. La commande est decoupee sur && || ; et les
  retours ligne ; CHAQUE segment doit etre un passthrough sanctionne (curl vers
  hub :8766, recovery NSSM, git/gh, ou schtasks Nokido-*). Un seul segment non
  conforme -> toute la commande est bloquee. git/gh + schtasks Nokido-* sont
  autorises en direct : le hub ne peut PAS les executer (sandbox = mauvais owner
  du repo + pas de reseau sortant + non-interactif sans acces GPU) ; les
  variantes qui fuient un secret restent bloquees inconditionnellement par
  LAYER 1.

Fail-open uniquement sur erreur de parse JSON (le harness controle le JSON).
Cable dans .claude/settings.local.json -> hooks.PreToolUse (Bash | PowerShell).
"""

import json
import re
import sys
import time
from pathlib import Path

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)  # fail-open : parse JSON casse = hoquet harness, ne pas bricker

command = (data.get("tool_input", {}) or {}).get("command", "") or ""
low = command.lower()

# ─────────────────────────────────────────────────────────────────────────
# LAYER 0 — DEV MODE BYPASS (TTL + audit log). Si sandbox/.bash_guard_armed
# existe et < 30 min : LAYER 1 (secrets) reste appliquee, LAYER 2 (routing)
# est sautee. Permet pytest, build, debug local quand le hub sandbox est HS.
# Armer via Write/touch ; desarmer = supprimer le fichier ou attendre TTL.
# ─────────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
# HORS `sandbox/` depuis le 2026-09-13. Mesure du jour : `sandbox/` porte
# `LaForgeSandboxUsers:(OI)(CI)(M)` -- le compte que ce garde CONTRAINT pouvait
# donc poser lui-meme le fichier d'armement et sauter LAYER 2, puis effacer sa
# trace dans le journal d'audit voisin. Un garde n'est un garde que si son
# interrupteur est hors de portee de ce qu'il contraint (meme forme que
# l'attestation DEV dont le dossier de jeton etait inscriptible par le client).
# `etat_protege/` est en (RX)/(R) pour les bacs a sable, (F) pour l'owner.
_ARM_FILE = _ROOT / "etat_protege" / ".bash_guard_armed"
_AUDIT_LOG = _ROOT / "etat_protege" / ".bash_guard_audit.log"
_DEV_TTL_S = 1800  # 30 min

_dev_armed = False
try:
    if _ARM_FILE.exists():
        _age = time.time() - _ARM_FILE.stat().st_mtime
        if _age < _DEV_TTL_S:
            _dev_armed = True
except OSError:
    pass

# ─────────────────────────────────────────────────────────────────────────
# LAYER 1 — DENYLIST SECRETS. Scan de la commande ENTIERE. Inconditionnel.
# ─────────────────────────────────────────────────────────────────────────
SECRET_PATTERNS = [
    (
        r"\bgit\b[^\n]*\bremote\b\s+(-v\b|--verbose\b|show\b|get-url\b)",
        "git remote -v/show/get-url imprime les URL remote (PAT embarque)",
    ),
    (
        r"\bgit\b[^\n]*\bconfig\b[^\n]*(--list\b|--get-regexp\b|(?:\s|^)-l(?:\s|$))",
        "git config --list/-l/--get-regexp dumpe la config (URL avec PAT)",
    ),
    (
        r"\bgit\b[^\n]*\bconfig\b[^\n]*--get\b[^\n]*\bremote\.",
        "git config --get remote.* imprime l'URL remote (PAT)",
    ),
    (
        r"(cat|type|more|head|tail|get-content|select-string|findstr|grep|\bgc\b)"
        r"\s+[^\n]*(\.env(\b|$)|\.git[\\/]config|\.mcp\.json|credentials\b|"
        r"_token|_secret|\.key\b|\.pem\b|id_rsa)",
        "lecture d'un fichier de secrets (.env / .git config / .mcp.json / cle)",
    ),
    (
        r"(^|&&|\|\||;|\||\bthen\b)\s*(env|printenv)\s*($|&&|\|\||;|\||>)",
        "dump complet de l'environnement",
    ),
    (r"(get-childitem|gci|\bls\b|\bdir\b)\s+env:", "dump complet de l'environnement (PowerShell)"),
    (
        r"(echo|write-host|write-output|printf)\b[^\n]*\$[^\s]*"
        r"(token|secret|key|passw|api[_-]?key|\bpat\b)",
        "echo d'une variable contenant un secret",
    ),
    (
        r"https?://[^\s/@]+(?::[^\s/@]*)?@",
        "URL http(s) avec credentials embarques (userinfo) - "
        "utiliser un credential helper ou une variable, jamais en clair",
    ),
    (r"\bgh\b\s+auth\s+token\b", "gh auth token imprime le token GitHub en clair"),
    (
        r"\bgh\b\s+auth\s+status\b[^\n]*--show-token\b",
        "gh auth status --show-token imprime le token GitHub",
    ),
]
for rx, why in SECRET_PATTERNS:
    if re.search(rx, low):
        print(
            f"[bash_guard] BLOCKED - fuite de secret.\n"
            f"  Raison : {why}\n"
            f"  Cmd : {command[:200]}\n"
            f"  Regle absolue : aucun passthrough ne contourne cette couche.",
            file=sys.stderr,
        )
        sys.exit(2)

# ─────────────────────────────────────────────────────────────────────────
# LAYER 1.5 — MONITOR. L'outil `Monitor` execute du shell NATIF et reveille la
# boucle du client ; tant qu'aucun matcher ne le nommait, il echappait a toute
# cette politique. Passe-droit releve et ferme le 2026-09-13 sur directive
# owner (« plus de passe-droit sur la politique mise en place »).
#
# UNE seule forme est acceptee : le CLI de surveillance git-tracke, en lecture
# seule, dont le comportement est revu -- meme principe que `trusted_script`
# (« execute = exactement le code revu »). Pas de chainage, pas de substitution,
# pas de shell libre.
#
# Le bypass dev NE s'applique PAS ici, volontairement : il existe pour debloquer
# un shell local quand le hub est HS, pas pour rouvrir un canal d'execution non
# gouverne. Il est donc teste APRES ce bloc.
# ─────────────────────────────────────────────────────────────────────────
_MONITOR_OK = re.compile(
    r"^\s*\"?[^\"\n]*python[^\"\n]*\"?\s+"
    r"\"?[^\"\n]*forge_job_watch_cli\.py\"?\s+"
    # `--task` ajoute le 2026-09-22 : une TACHE M2M doit pouvoir reveiller la
    # boucle comme un job. Sans cet elargissement, `surveiller_tache` existait
    # et restait hors de portee de `Monitor` -- une capacite morte.
    # La forme reste CLOSE : un identifiant, jamais un chemin, et toujours le
    # meme script git-tracke en lecture seule.
    # `--pair [CLIENT]` ajoute le 2026-10-01 (owner : « lance un monitor en fonction du LLM qui le
    # lance ») : le rendu d'un pair cloud doit reveiller la boucle comme un job ou une tache. Le
    # client est un identifiant qui COMMENCE par un alphanumerique -- il ne peut donc pas avaler une
    # option (`--max-s`) ni porter un chemin ; meme script, toujours en lecture seule.
    r"(?:--(?:job|task)\s+[A-Za-z0-9_]+|--pair(?:\s+[A-Za-z0-9][A-Za-z0-9-]*)?)"
    r"(?:\s+--[a-z-]+\s+\d+)*\s*$"
)

if (data.get("tool_name") or "").strip() == "Monitor":
    if re.search(r"\$\(|`", command) or not _MONITOR_OK.match(command):
        print(
            "[bash_guard] BLOCKED - Monitor hors politique.\n"
            "  Monitor execute du shell natif : une seule forme est sanctionnee,\n"
            "  le CLI de surveillance git-tracke (lecture seule).\n"
            '  Forme : "<LAFORGE_PYTHON>" "<repo>/tools/forge_job_watch_cli.py" '
            "--job <job_id> | --task <task_id> | --pair [client] [--gel-s N] [--max-s N] [--intervalle N]\n"
            f"  Cmd : {command[:200]}",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(0)

# Si dev-mode arme : Layer 1 (secrets) a passe, on saute Layer 2 (routing).
if _dev_armed:
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOG.open("a", encoding="utf-8") as _f:
            _f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} BYPASS {command[:300]}\n")
    except OSError:
        pass
    sys.exit(0)

# ─────────────────────────────────────────────────────────────────────────
# LAYER 2 — ROUTING. Chaque segment doit etre un passthrough sanctionne.
# ─────────────────────────────────────────────────────────────────────────
ALLOWED_RECOVERY = (
    "nssm restart nokidomcp",
    "nssm restart laforge-master",
    "nssm restart nokido",
)


# Substitution de COMMANDE : `$(...)` et backticks. Volontairement PAS `${...}`,
# qui est de l'expansion de variable et n'execute rien -- un garde qui crie a
# faux se fait desarmer.
_SUBSTITUTION_CMD = re.compile(r"\$\(|`")


def segment_ok(seg: str) -> bool:
    """Un segment shell est-il un passthrough autorise ?"""
    s = seg.strip()
    if not s:
        return True  # segment vide (chaînage) -> neutre
    sl = s.lower()
    # Hub : curl vers :8766 uniquement (plus de substring n'importe ou)
    if sl.startswith("curl") and ("127.0.0.1:8766" in sl or "localhost:8766" in sl):
        # SEUL passthrough ou la substitution reste admise : RULES_SHARED
        # prescrit `-H "Authorization: Bearer $(sed -n ... <cfg>)"` precisement
        # pour ne JAMAIS faire transiter le jeton en clair. L'interdire ici
        # pousserait a l'afficher : le remede serait pire que le mal.
        return True
    # LECON codex (depot ingere le 2026-08-30, prompts/templates/permissions/) :
    # une regle d'auto-approbation n'est PAS evaluee quand la commande porte une
    # substitution ou un wildcard, "to limit the scope of what an approved rule
    # allows". Le routage ci-dessous souffrait du meme trou : il concluait "ce
    # segment commence par git, donc il est sanctionne" sans jamais regarder le
    # reste, si bien que `git log --format=$(<commande arbitraire>)` passait --
    # et la substitution s'execute AVANT git. L'approbation portait sur le nom
    # du binaire, pas sur ce qui allait reellement tourner.
    # La substitution ne rend pas le segment interdit : elle lui retire le
    # BENEFICE de l'approbation automatique. Ecrire la commande en clair, ou
    # passer par le hub.
    if _SUBSTITUTION_CMD.search(s):
        return False
    # Dead-man's switch : recovery hub down via NSSM (admin, pas d'alternative)
    if any(sl.startswith(p) for p in ALLOWED_RECOVERY):
        return True
    # git / gh : le hub ne peut PAS les executer (sandbox = mauvais owner du
    # repo + pas de reseau sortant). LAYER 1 bloque deja les variantes qui
    # fuient un secret (remote -v, config --list/--get remote.*, gh auth token).
    if sl == "git" or sl.startswith("git ") or sl.startswith("git\t"):
        return True
    if sl == "gh" or sl.startswith("gh ") or sl.startswith("gh\t"):
        return True
    # echo : marqueur de sortie inoffensif. Rend lisible le chainage
    # `git ... && echo "---" && git ...`. LAYER 1 bloque deja `echo $TOKEN` ;
    # un echo simple n'execute aucune action a router vers le hub.
    if sl == "echo" or sl.startswith("echo ") or sl.startswith("echo\t"):
        return True
    # Windows Scheduled Tasks — UNIQUEMENT les taches nommees "Nokido-*".
    #   /run /query /end : declenchent/inspectent une tache pre-existante dont
    #     la commande est FIGEE a sa creation -> sur (cf. nssm restart Nokido*).
    #   /create : permis SEULEMENT via /xml pointant DANS le repo Nokido
    #     (XML versionne = revu en commit) ; jamais de /tr inline. Un attaquant
    #     ne peut donc declarer un executeur qu'avec du code deja commite (=
    #     deja sous controle user) -> aucune escalade.
    # SSH freebox@localhost — debug cert AdGuard VM DNS 2026-05-23
    if re.match(r"^ssh\s+(-[a-zA-Z]+\s+\S+\s+)*freebox@192\.168\.1\.166", sl):
        return True
    if sl.startswith("schtasks "):
        if not re.search(r'/tn\s+"?nokido-', sl):
            return False
        if "/create" in sl:
            # La CONTRAINTE ne bouge pas : XML dans le depot (versionne = revu au
            # commit), jamais de /tr inline -- c'est ce qui interdit de declarer un
            # executeur arbitraire. Seul le NOM du dossier est elargi : le
            # renommage LaForge -> Nokido a fige ce motif sur `\nokido\`, dossier
            # qui N'EXISTE PAS (mesure 2026-07-26 : la racine contient `LaForge`).
            # Le garde etait juste, sa cible fausse -- donc la seule route de
            # creation autorisee etait inatteignable, ce qui se lit a tort comme
            # « creer une tache est interdit ». Les deux noms sont acceptes pour
            # que la regle survive au renommage au lieu d'etre re-cassee par lui.
            return ("/tr" not in sl) and bool(
                re.search(r'/xml\s+"?%NOKIDO_WORKSPACE%\\(laforge|nokido)\\', sl)
            )
        return bool(re.search(r"/(run|query|end)\b", sl))
    return False


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


segments = split_segments(command)
if all(segment_ok(seg) for seg in segments):
    sys.exit(0)

# Le message DERIVE de ALLOWED_RECOVERY, il ne le paraphrase pas.
# Mesure 2026-08-16 (hub mort 18 min) : ce texte annoncait « nssm restart
# Nokido* » alors qu'AUCUN service ne porte ce nom -- le seul service Running
# est `LaForge-Master`, et `nssm restart laforge-master` etait DEJA autorise
# juste au-dessus. L'agent a essaye NokidoMCP/NokidoHub/Nokido, s'est fait
# refuser par le SCM, a conclu « aucune relance possible cote agent » et a rendu
# la main : 18 minutes de hub mort pour une commande qui passait.
# Un garde qui decrit ses regles de memoire finit par mentir sur ce qu'il permet.
_PASSTHROUGHS = ["curl vers :8766", "git", "gh", "schtasks /tn Nokido-*"] + list(ALLOWED_RECOVERY)
print(
    "[bash_guard] BLOCKED - execution directe interdite.\n"
    f"  Cmd : {command[:300]}\n"
    "  Regle : toute execution passe par le hub :8766 "
    "(mcp__laforge-sovereign-hub__run, action=shell/python).\n"
    "  Passthroughs (chaque segment doit en etre un) : " + " | ".join(_PASSTHROUGHS) + ".",
    file=sys.stderr,
)
sys.exit(2)
