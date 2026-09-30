"""
FORGE INTELLIGENCE — forge_git_egress [GREEN]
==============================================
GATE EGRESS GIT SOUVERAIN (cerveau, v1). Reconstruit le set à pousser →
scanne via forge_parity_gate (signaux git_egress : secrets / manifeste /
entropie / fuite host-IP-path) → hard-fail (RED) ou laisse passer + scrub
SovereignMembrane pour les remotes publics.

Plan tranché par le multiplan (interception = WinDivert, unanime) : la couche
WinDivert (verrou réseau inviolable) = v2. v1 = le cerveau, câblable dans
.git/hooks/pre-push (enforcement immédiat).

Anti-dup (CLAUDE.md §3) : aucun module ne fait de pre-push egress-gating
(forge_web_egress=web HTTP ; @safety_audit=scan staged manuel ;
precommit_secret_scan=stage pre-COMMIT ; launch_public_mirror=orchestrateur
miroir). Réutilise : patterns secrets (precommit_secret_scan), SovereignMembrane,
NoiseGuardian, forge_parity_gate (registre signaux + agrégation conservatrice).
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"

import json
import os
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_parity_gate as pg  # noqa: E402

_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git hash-object -t tree /dev/null
MANIFEST_PATH = ROOT / ".git-publish-rules.json"
# Identites PRIVEES de l'owner (nom civil, adresse) : jamais ecrites dans le code
# publie. Decision owner 2026-09-30 : pseudonyme partout, nom civil seulement la
# ou un titulaire identifiable est requis. La liste vit dans ce fichier, suivi
# dans la source, BLOQUE au profil public et exclu de MANIFEST.in. Lu par le
# promoteur (refus de publier), forge_dist_storage et l'export du Knowledge Pack
# (caviardage). Absent -- dist, wheel installee -- : liste vide.
IDENTITES_PRIVEES = ROOT / "config" / "identites_privees.txt"


def identites_privees(chemin: Path | None = None) -> list[re.Pattern]:
    """Une expression reguliere par ligne non vide, `#` = commentaire, sans casse."""
    try:
        lignes = Path(chemin or IDENTITES_PRIVEES).read_text(encoding="utf-8").splitlines()
    except OSError:  # muet-ok : absent hors du depot source (dist, wheel) = aucune identite a proteger
        return []
    return [re.compile(l.strip(), re.IGNORECASE) for l in lignes
            if l.strip() and not l.lstrip().startswith("#")]
# Verrou WinDivert v2 : le gate y écrit son PID pendant un push autorisé
# (gate-as-executor) -> forge_git_egress_lock autorise SES git/ssh enfants.
ALLOW_PIDFILE = Path(os.environ.get("LAFORGE_EGRESS_ALLOW_PIDFILE", r"C:\tmp\forge_git_egress.allow"))

# ── Patterns secrets (repris de scripts/precommit_secret_scan.py) ────────────
_SECRET_RX: list[tuple[str, re.Pattern]] = [
    ("google_api", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("github_pat", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{36,}")),
    ("github_fine", re.compile(r"github_pat_[0-9A-Za-z_]{22,}")),
    ("openai", re.compile(r"\bsk-[0-9A-Za-z]{20,}")),
    ("hf_token", re.compile(r"\bhf_[0-9A-Za-z]{30,}")),
    ("slack", re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}")),
    ("aws_akid", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("gitlab_pat", re.compile(r"\bglpat-[0-9A-Za-z_\-]{20,}")),
    ("groq", re.compile(r"\bgsk_[0-9A-Za-z]{40,}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("generic_secret", re.compile(
        r"(?i)(?:api[_-]?key|secret|passwd|password|token)\s*[:=]\s*['\"][0-9A-Za-z/+_\-]{16,}['\"]")),
]
_LONG_TOKEN_RX = re.compile(r"[0-9A-Za-z+/=_\-]{24,}")
_LEAK_RX = re.compile(
    r"(?:\b(?:10|127|192\.168|172\.(?:1[6-9]|2\d|3[01]))(?:\.\d{1,3}){2,3}\b"   # IP privée
    r"|[A-Za-z]:\\Users\\[^\\\s\"']+"                                            # chemin Win user
    r"|/(?:home|root)/[^/\s\"']+"                                                # chemin *nix user
    r"|\b[\w-]+\.(?:local|lan|internal|corp|duckdns\.org|tailscale\.net)\b)")    # hostname interne


def _glob_to_re(pat: str) -> re.Pattern:
    """** -> .* ; * -> [^/]* ; pour matcher des chemins POSIX."""
    out, i = [], 0
    while i < len(pat):
        if pat[i:i + 2] == "**":
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _path_blocked(path: str, patterns: list[str], degages=None) -> str | None:
    """Motif qui bloque `path`, ou None.

    `degages` : chemins LIBERES nommement (IP_CLEARANCE, owner 2026-09-30 --
    profil public `ip_clearance`, chemin -> statut publiable justifie). Un chemin
    libere n'est jamais bloque ; ses voisins sous le meme motif le restent.
    """
    if degages and path in degages:
        return None
    for pat in patterns:
        if fnmatch(path, pat) or _glob_to_re(pat).match(path):
            return pat
    return None


# ── Signaux parity_gate (group="git_egress") ─────────────────────────────────
@pg.register_signal("git_secrets", group="git_egress")
def _sig_secrets(ctx) -> pg.Finding | None:
    if not (ctx.get("profile") or {}).get("secret_scan", True):
        return None
    content, path = ctx.get("content", ""), ctx.get("path", "?")
    allow = (ctx.get("profile") or {}).get("secret_allow", [])
    for label, rx in _SECRET_RX:
        m = rx.search(content)
        if m:
            # False-positifs VERIFIES (fixture / test-payload / nom-de-cle-vault)
            # epingles par (path-glob + label) dans le manifeste. Le scanner reste
            # STRICT partout ailleurs ; chaque entree est explicite + auditable
            # (.git-publish-rules.json -> profiles.<prof>.secret_allow).
            if any(fnmatch(path, a.get("path", "")) and a.get("label") == label for a in allow):
                continue
            return pg.red(f"secret '{label}' dans {path}", path=path,
                          match=m.group(0)[:10] + "…")
    return None


@pg.register_signal("git_manifest", group="git_egress")
def _sig_manifest(ctx) -> pg.Finding | None:
    prof, path = ctx.get("profile") or {}, ctx.get("path", "?")
    hit = _path_blocked(path, prof.get("blocked_paths", []))
    if hit:
        return pg.red(f"chemin interdit par manifeste ({hit}) : {path}", path=path)
    mx = prof.get("max_file_bytes")
    if mx and len(ctx.get("content", "").encode("utf-8", "ignore")) > mx:
        return pg.red(f"fichier > max {mx} o : {path}", path=path)
    return None


@pg.register_signal("git_entropy", group="git_egress")
def _sig_entropy(ctx) -> pg.Finding | None:
    path = ctx.get("path", "?")
    content = ctx.get("content", "")
    # Docs/prose : l'entropie BRUTE a des faux-positifs (chemins, hashes cités).
    # MAIS un token de format NON-STANDARD (ex GitHub Models) y passait : entropie
    # skippee + _sig_secrets ne matche que les formats connus. Fix racine : sur
    # prose, appliquer l'entropie UNIQUEMENT aux valeurs en CONTEXTE secret
    # (<VAR>_TOKEN ( / _SECRET= / _KEY= / bearer / password=) -> attrape les
    # formats inconnus sans les faux-positifs (un chemin n'est jamais apres _TOKEN().
    if path.lower().endswith((".md", ".markdown", ".rst", ".txt")):
        _ctx_rx = re.compile(
            r"(?i)(?:_TOKEN\s*\(|_TOKEN\s*[:=]|_SECRET\s*[:=]|_KEY\s*[:=]|bearer\s+|password\s*[:=])\s*"
            r"([A-Za-z0-9._\-/+]{16,})"
        )
        for m in _ctx_rx.finditer(content):
            v = m.group(1)
            if "REDACT" in v or "REMOVED" in v or "MASK" in v:
                continue
            if pg.shannon_entropy(v) > 4.0:
                return pg.red(f"secret haute-entropie en contexte ({len(v)}c) dans {path} : {v[:6]}…",
                              path=path)
        return None
    for tok in _LONG_TOKEN_RX.findall(content):
        if pg.shannon_entropy(tok) > 4.6:
            return pg.yellow(f"token haute entropie ({len(tok)}c) dans {path} : {tok[:8]}…",
                             path=path)
    return None


@pg.register_signal("git_host_leak", group="git_egress")
def _sig_host_leak(ctx) -> pg.Finding | None:
    if not (ctx.get("profile") or {}).get("scrub", True):
        return None  # remote privé : pas de souci de fuite host/IP
    path = ctx.get("path", "?")
    leaks = _LEAK_RX.findall(ctx.get("content", ""))
    if leaks:
        return pg.yellow(f"{len(leaks)} fuite(s) host/IP/path dans {path} (scrub membrane requis)",
                         path=path, sample=str(leaks[:2]))
    return None


# ── Git helpers ──────────────────────────────────────────────────────────────
def _git(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout, r.stderr


# Branches dont l'historique ne doit PAS etre reecrit ni la ref supprimee. `beta`
# publie les releases Codeberg : un force-push accidentel corromprait la lignee.
_BRANCHES_PROTEGEES = {"main", "alpha", "beta", "dist", "hackathon/v17-microsoft"}


def _protection_branche(local_sha: str, remote_sha: str, remote_ref: str) -> str | None:
    """Refuse force-push et suppression sur une branche protegee. None = autorise.

    Mesure 2026-08-19 : le gate egress ne portait AUCUNE protection de branche --
    la seule liste PROTEGEES vivait dans le hook du SUPER-depot, qui NE s'execute
    PAS quand on pousse le depot Nokido lui-meme (core.hooksPath -> ce shim egress).
    beta etait donc force-pushable sans garde. On la protege ICI, dans la source
    de verite du gate Nokido, la ou le push de beta passe reellement.
    """
    branche = (remote_ref[len("refs/heads/"):]
               if remote_ref.startswith("refs/heads/") else remote_ref)
    if branche not in _BRANCHES_PROTEGEES:
        return None
    if set(local_sha) == {"0"}:
        return f"suppression de la branche protegee '{branche}' refusee"
    if set(remote_sha) == {"0"}:
        return None  # nouvelle branche cote distant : autorisee
    try:
        n = int(os.environ.get("GIT_PUSH_OPTION_COUNT", "0") or "0")
    except ValueError:
        n = 0
    for i in range(n):
        if os.environ.get("GIT_PUSH_OPTION_%d" % i) in ("force", "force-with-lease"):
            return f"push --force* sur la branche protegee '{branche}' refuse"
    # Non-fast-forward = reecriture d'historique. On ne juge QUE si remote_sha est
    # connu localement : sur une vue distante perimee on n'invente pas un blocage
    # (fail-open sur non-mesure), le reste du gate egress s'applique quand meme.
    if _git(["cat-file", "-e", remote_sha + "^{commit}"], timeout=10)[0] != 0:
        return None
    if _git(["merge-base", "--is-ancestor", remote_sha, local_sha], timeout=15)[0] != 0:
        return ("push non-fast-forward sur '%s' : %s n'est pas un ancetre de %s "
                "(force-push / rebase reecrivant l'historique)"
                % (branche, remote_sha[:8], local_sha[:8]))
    return None


def _resolve_base(local_sha: str, remote_sha: str, local_ref: str = "") -> str:
    """Base de diff. remote_sha=zéros (nouveau ref/force) -> origin/HEAD sinon empty tree.
    L'objet base doit EXISTER localement ; si absent (gc/prune, remote neuf) -> empty
    tree = full-scan de tout ce qui est poussé (fail-safe : on scanne plus, pas moins)."""
    def _exists(sha: str) -> bool:
        rc, _, _ = _git(["cat-file", "-e", sha + "^{commit}"])
        return rc == 0
    if remote_sha and set(remote_sha) != {"0"}:
        return remote_sha if _exists(remote_sha) else _EMPTY_TREE
    cands = []
    if local_ref:
        br = local_ref.rsplit("/", 1)[-1]
        if br:
            cands.append("origin/" + br)  # meme branche cote remote public = delta reel (rapide)
    cands += ["origin/HEAD", "origin/main", "origin/master"]
    for ref in cands:
        rc, out, _ = _git(["rev-parse", "--verify", "-q", ref])
        if rc == 0 and out.strip() and _exists(out.strip()):
            return out.strip()
    return _EMPTY_TREE


def reconstruct(local_sha: str, remote_sha: str, local_ref: str = "") -> dict[str, str]:
    """Map {path: contenu-à-pousser} des fichiers Ajoutés/Modifiés. Skip Deleted."""
    base = _resolve_base(local_sha, remote_sha, local_ref)
    rc, out, err = _git(["diff", "--name-status", "--diff-filter=AM", base, local_sha])
    if rc != 0:
        raise RuntimeError(f"git diff KO: {err.strip()[:200]}")
    files: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        path = parts[-1].strip()
        crc, content, _ = _git(["show", f"{local_sha}:{path}"])
        if crc == 0:
            files[path] = content
    return files


# ── Manifeste / profils ──────────────────────────────────────────────────────
_DEFAULT_MANIFEST = {
    "profiles": {
        "public": {
            "secret_scan": True, "scrub": True, "max_file_bytes": 5_000_000,
            "blocked_paths": [
                "**/secrets/**", "sandbox/secrets/**", "**/.env", "**/.env.*",
                "**/*.pem", "**/*.key", "**/*.p12", "**/*.pfx", "**/vault*.db",
                "RAG_plain_bak/**", "**/LaForge.env",
            ],
        },
        "private": {"secret_scan": True, "scrub": False, "max_file_bytes": 0, "blocked_paths": []},
    },
    "remote_profiles": {},          # sous-chaîne d'URL -> nom de profil
    "default_profile": "public",    # fail-safe : remote inconnu = strict
}


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            for k, v in _DEFAULT_MANIFEST.items():
                m.setdefault(k, v)
            return m
        except Exception:
            pass
    return _DEFAULT_MANIFEST


def resolve_profile(remote_url: str, manifest: dict | None = None) -> tuple[str, dict]:
    manifest = manifest or load_manifest()
    name = manifest.get("default_profile", "public")
    for sub, prof_name in (manifest.get("remote_profiles") or {}).items():
        if sub and sub in (remote_url or ""):
            name = prof_name
            break
    return name, (manifest.get("profiles") or {}).get(name, _DEFAULT_MANIFEST["profiles"]["public"])


# ── Gate ──────────────────────────────────────────────────────────────────────
def scan_files(files: dict[str, str], profile: dict) -> tuple[pg.Severity, list[pg.Finding]]:
    """Évalue chaque fichier via parity_gate (group git_egress) ; agrège le pire."""
    all_findings: list[pg.Finding] = []
    worst = pg.Severity.GREEN
    order = {pg.Severity.GREEN: 0, pg.Severity.UNKNOWN: 1, pg.Severity.YELLOW: 2, pg.Severity.RED: 3}
    for path, content in files.items():
        res = pg.evaluate({"path": path, "content": content, "profile": profile},
                          group="git_egress")
        all_findings.extend(res.findings)
        if order[res.status] > order[worst]:
            worst = res.status
    return worst, all_findings


def _alignment_degraded_hard() -> list:
    """F3 : invariants d'alignement HARD dont l'ancre d'enforcement a disparu (DEGRADED).
    Best-effort : si l'outillage d'alignement est indispo, ne bloque pas (pass), pour ne
    pas wedger les push sur un souci d'outil. Le block ne touche QUE le push (commits saufs)."""
    try:
        try:
            from nokido_agent.tools.forge_alignment_invariants import INVARIANTS, verify_enforcement
        except Exception:
            import importlib.util as _u
            _p = Path(__file__).resolve().parent.parent / "tools" / "forge_alignment_invariants.py"
            _s = _u.spec_from_file_location("forge_alignment_invariants", _p)
            _m = _u.module_from_spec(_s)
            _s.loader.exec_module(_m)
            INVARIANTS, verify_enforcement = _m.INVARIANTS, _m.verify_enforcement
        ver = verify_enforcement()
        sev = {i["id"]: i.get("severity") for i in INVARIANTS}
        return [f"alignment_regression: invariant HARD '{iid}' DEGRADED (ancre d'enforcement disparue)"
                for iid, v in ver.items()
                if v.get("verified") == "DEGRADED" and sev.get(iid) == "hard"]
    except Exception:
        return []


def gate(local_sha: str, remote_sha: str, remote_url: str = "", local_ref: str = "") -> dict:
    """Verdict pour un ref à pousser. RED -> ok=False (bloquer)."""
    manifest = load_manifest()
    prof_name, profile = resolve_profile(remote_url, manifest)
    try:
        files = reconstruct(local_sha, remote_sha, local_ref)
    except Exception as e:  # fail-closed : si on ne peut pas reconstruire, on bloque
        return {"ok": False, "profile": prof_name, "status": "RED",
                "reasons": [f"reconstruction impossible (fail-closed): {e}"], "files": 0}
    worst, findings = scan_files(files, profile)
    reds = [f"{f.signal}: {f.reason}" for f in findings if f.level is pg.Severity.RED]
    align_reds = _alignment_degraded_hard()  # F3 : invariant HARD DEGRADED = regression de garde
    reds += align_reds
    is_red = (worst is pg.Severity.RED) or bool(align_reds)
    return {
        "ok": not is_red,
        "profile": prof_name,
        "status": "RED" if is_red else worst.value.upper(),
        "files": len(files),
        "reasons": reds,
        "warnings": [f"{f.signal}: {f.reason}" for f in findings if f.level is pg.Severity.YELLOW],
    }


def push(remote: str = "origin", refspecs: list[str] | None = None) -> int:
    """Gate-as-executor (verrou WinDivert v2) : scanne le set à pousser ; si
    non-RED, écrit son PID dans ALLOW_PIDFILE (autorise ses git enfants au verrou)
    puis lance `git push`. RED -> refuse. Nettoie le pidfile après.
    Usage : forge_git_egress.py push <remote> [refspec...]"""
    import subprocess
    refspecs = list(refspecs or [])
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])[1].strip() or "HEAD"
    local_sha = _git(["rev-parse", "HEAD"])[1].strip()
    rc, rs, _ = _git(["rev-parse", "--verify", "-q", f"{remote}/{branch}"])
    remote_sha = rs.strip() if (rc == 0 and rs.strip()) else "0" * 40
    rc2, url, _ = _git(["remote", "get-url", remote])
    remote_url = url.strip() if rc2 == 0 else remote  # NE PAS logger (PAT possible)
    v = gate(local_sha, remote_sha, remote_url)
    print(f"[egress] push {remote} {branch} [{v['profile']}] {v['status']} ({v['files']} fichiers)")
    for r in v["reasons"]:
        print(f"   RED  {r}")
    for w in v["warnings"][:10]:
        print(f"   warn {w}")
    if not v["ok"]:
        print("[egress] PUSH REFUSÉ (gate RED).")
        return 1
    try:
        ALLOW_PIDFILE.parent.mkdir(parents=True, exist_ok=True)
        ALLOW_PIDFILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    env = {**os.environ, "FORGE_EGRESS_INNER": "1"}  # le hook pre-push skip (déjà scanné)
    try:
        return subprocess.run(["git", "push", remote, *(refspecs or [branch])],
                              cwd=str(ROOT), env=env).returncode
    finally:
        try:
            ALLOW_PIDFILE.unlink()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    """Entrée hook pre-push. git passe: argv=[name, url] + stdin lignes
    '<local_ref> <local_sha> <remote_ref> <remote_sha>'. Exit 1 = bloque."""
    argv = argv if argv is not None else sys.argv[1:]
    if os.environ.get("FORGE_EGRESS_INNER"):
        print("[egress] inner push (déjà scanné par le gate), skip")
        return 0
    remote_url = argv[1] if len(argv) > 1 else (argv[0] if argv else "")
    lines = [ln for ln in sys.stdin.read().splitlines() if ln.strip()] if not sys.stdin.isatty() else []
    if not lines:
        print("[egress] aucun ref sur stdin, rien à scanner")
        return 0
    blocked = False
    for ln in lines:
        p = ln.split()
        if len(p) < 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = p[0], p[1], p[2], p[3]
        # Garde de branche AVANT l'egress : une suppression/force-push sur une
        # branche protegee est refusee net, meme si le contenu serait "propre".
        prot = _protection_branche(local_sha, remote_sha, remote_ref)
        if prot is not None:
            print(f"[egress] {remote_ref} BRANCHE PROTEGEE -> BLOCK")
            print(f"   RED  {prot}")
            blocked = True
            continue
        if set(local_sha) == {"0"}:  # suppression de ref (branche non protegee)
            continue
        v = gate(local_sha, remote_sha, remote_url, local_ref)
        tag = "BLOCK" if not v["ok"] else "OK"
        print(f"[egress] {remote_ref} [{v['profile']}] {v['status']} "
              f"({v['files']} fichiers) -> {tag}")
        for r in v.get("reasons", []):
            print(f"   RED  {r}")
        for w in v.get("warnings", [])[:10]:
            print(f"   warn {w}")
        if not v["ok"]:
            blocked = True
    if blocked:
        print("[egress] PUSH BLOQUÉ par le gate souverain (secrets/chemin interdit).")
        return 1
    # Verrou WinDivert (enforce 24/7) : autoriser le git APPELANT à sortir. Le hook
    # tourne PRÉ-connexion ; git est un ANCÊTRE du hook (git -> sh -> python) -> on
    # remonte via psutil pour trouver git.exe et écrire son PID dans ALLOW_PIDFILE.
    # Couvre TOUS les pushers (manuel, session_anchor, self_patcher, …) sans router
    # chaque caller. `--no-verify` saute le hook -> pas d'écriture -> verrou bloque.
    try:
        import psutil
        proc = psutil.Process()
        for _ in range(6):
            proc = proc.parent()
            if proc is None:
                break
            if (proc.name() or "").lower() in ("git.exe", "git"):
                ALLOW_PIDFILE.parent.mkdir(parents=True, exist_ok=True)
                ALLOW_PIDFILE.write_text(str(proc.pid), encoding="utf-8")
                break
    except Exception:
        pass
    return 0


def _selftest() -> int:
    """Teste les signaux sur ctx synthétiques (sans git), profil PUBLIC (strict)."""
    pub = load_manifest()["profiles"]["public"]
    cases = {
        "RED_secret": ({"path": "a.py", "content": "key = 'sk-" + "x" * 22 + "'", "profile": pub}, "RED"),
        "RED_manifest": ({"path": "config/.env", "content": "X=1", "profile": pub}, "RED"),
        "YELLOW_leak": ({"path": "b.py", "content": "host = 'localhost'", "profile": pub}, "YELLOW"),
        "GREEN": ({"path": "c.py", "content": "def add(a, b):\n    return a + b", "profile": pub}, "GREEN"),
    }
    ok = True
    for nm, (ctx, expect) in cases.items():
        st = pg.evaluate(ctx, group="git_egress").status.value.upper()
        flag = "OK" if st == expect else "FAIL"
        ok = ok and flag == "OK"
        print(f"[{flag}] {nm}: attendu={expect} obtenu={st}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if len(sys.argv) > 1 and sys.argv[1] == "push":  # gate-as-executor
        raise SystemExit(push(sys.argv[2] if len(sys.argv) > 2 else "origin", sys.argv[3:]))
    raise SystemExit(main())
