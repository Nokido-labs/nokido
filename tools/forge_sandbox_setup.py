"""forge_sandbox_setup.py -- provision the Nokido code-execution sandbox.

Creates the two low-privilege users that `run`/`orchestrate` child processes
will execute under (see docs/sandbox_user_plan.md):

  LaForgeSandboxOnline   -- standard user, internet allowed
  LaForgeSandboxOffline  -- standard user, outbound blocked except loopback

Idempotent: safe to re-run. Does NOT wire the hub -- that is a separate,
tested step. This script only provisions OS-level resources.

Run as Administrator:
    LAFORGE_PYTHON tools/forge_sandbox_setup.py            # provision
    LAFORGE_PYTHON tools/forge_sandbox_setup.py --status   # show state only
    LAFORGE_PYTHON tools/forge_sandbox_setup.py --teardown # remove everything

Step 0 of the build is NOT here: the `_resolve_ring` fallback fix in
nokido_hub.py must be applied separately.
"""

from __future__ import annotations

import argparse
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX_DIR = ROOT / "sandbox"
WORKSPACE = SANDBOX_DIR / "workspace"
RUN_TMP = ROOT / ".run_tmp"
CREDS_FILE = SANDBOX_DIR / ".sandbox_creds"

USERS = {  # names must be <= 20 chars (New-LocalUser limit)
    "LaForgeSbxOnline": {"online": True},
    "LaForgeSbxOffline": {"online": False},
}
GROUP = "LaForgeSandboxUsers"
USERS_GROUP_SID = "S-1-5-32-545"  # BUILTIN\Users (locale-independent)

# Dedicated trusted runner — NOT a sandbox user. Runs git-tracked tools/ or
# app/ scripts with repo + RAG-db write (action=trusted_script). Non-admin.
TRUSTED_USER = "LaForgeTrusted"
TRUSTED_GROUP = "LaForgeTrustedRunners"  # tag ACL collectif pour tier trusted
LLAMA_DIR = __import__("os").path.expanduser(r"~\llama-vulkan")  # GPU embed server (rebuild jobs)

MINIFORGE_ROOT = __import__("os").path.expanduser(r"~\miniforge3")
# Sous-arbres miniforge3 qui méritent /T explicite : les fichiers EXISTANTS
# (créés avant le grant) ne re-héritent pas — il faut /T pour les couvrir.
# Pour les NOUVEAUX fichiers, l'héritage OI/CI posé sur la racine suffit.
# pkgs + Lib + DLLs + Library + Scripts = base packages. envs/* = environnements.
_MINIFORGE_SUBTREE_NAMES = ("pkgs", "Lib", "DLLs", "Library", "Scripts")


def _icacls_subtrees_parallel(
    paths: list[str],
    principal: str,
    perm: str,
    label: str = "",
    max_workers: int = 4,
    per_timeout: int = 900,
) -> None:
    """Lance icacls /T en parallele sur N sous-arbres. Visibilite live :
    print(start) -> wait -> print(done + elapsed). Evite l effet "tout fige"
    quand /T sur 5+ envs conda sequentiel prend 30+ minutes.

    max_workers=4 : evite de saturer le disque (icacls = I/O bound).
    per_timeout=900s : 15 min par arbre max (les gros envs avec >100k fichiers
    peuvent prendre 10+ min)."""
    import concurrent.futures as _cf
    import subprocess as _sp
    import time as _t

    def _run(path: str) -> tuple[str, bool, float]:
        t0 = _t.monotonic()
        try:
            cmd = ["icacls", path, "/grant", f"{principal}:{perm}", "/T", "/C"]
            r = _sp.run(cmd, capture_output=True, text=True, timeout=per_timeout, errors="replace")
            ok = r.returncode == 0
        except _sp.TimeoutExpired:
            ok = False
        return path, ok, _t.monotonic() - t0

    if not paths:
        return
    suffix = f" [{label}]" if label else ""
    print(f"  icacls /T parallel{suffix} : {len(paths)} arbre(s), {max_workers} worker(s)")
    for p in paths:
        print(f"    start {p}")
    sys.stdout.flush()
    with _cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for path, ok, dt in ex.map(_run, paths):
            tag = "OK " if ok else "FAIL"
            print(f"    [{tag}] {path}  ({dt:.1f}s)")
            sys.stdout.flush()


def _miniforge_subtrees() -> list[str]:
    """Liste les sous-arbres miniforge3 à couvrir explicitement par icacls /T.
    = sous-dossiers base canoniques + tous les envs/<name>."""
    import os as _os

    paths: list[str] = []
    for name in _MINIFORGE_SUBTREE_NAMES:
        p = _os.path.join(MINIFORGE_ROOT, name)
        if _os.path.isdir(p):
            paths.append(p)
    envs_dir = _os.path.join(MINIFORGE_ROOT, "envs")
    if _os.path.isdir(envs_dir):
        for entry in sorted(_os.listdir(envs_dir)):
            full = _os.path.join(envs_dir, entry)
            if _os.path.isdir(full):
                paths.append(full)
    return paths


# ── PowerShell bridge ────────────────────────────────────────────────────
def ps(script: str, env: dict | None = None, check: bool = True, timeout: int = 120) -> str:
    """Run a PowerShell snippet, return stdout. Raises on failure if check.
    Un timeout (ex. icacls /T sur un gros arbre) ne crashe PAS le provisioning
    quand check=False : traite comme un echec tolere (warning, ACL partielle)."""
    import os

    full_env = os.environ.copy()
    # The hub runs as SYSTEM with a stripped env -> PSModulePath is broken
    # and cmdlet autoload (LocalAccounts, NetSecurity, Security) fails.
    # Force the standard module paths.
    full_env["PSModulePath"] = (
        r"C:\Program Files\WindowsPowerShell\Modules;"
        r"C:\Windows\System32\WindowsPowerShell\v1.0\Modules"
    )
    if env:
        full_env.update(env)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            env=full_env,
            timeout=timeout,
        errors="replace")
    except subprocess.TimeoutExpired:
        if check:
            raise
        print(f"  (timeout {timeout}s - commande lente ignoree, ACL possiblement partielle)")
        return ""
    if check and r.returncode != 0:
        raise RuntimeError(f"PowerShell failed:\n{script}\n--\n{r.stderr.strip()}")
    return (r.stdout or "").strip()


def is_admin() -> bool:
    try:
        out = ps(
            "([Security.Principal.WindowsPrincipal]"
            "[Security.Principal.WindowsIdentity]::GetCurrent())"
            ".IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)"
        )
        return out.strip().lower() == "true"
    except Exception:
        return False


# ── provisioning steps ───────────────────────────────────────────────────
def user_exists(name: str) -> bool:
    out = ps(
        f"if (Get-LocalUser -Name '{name}' -ErrorAction SilentlyContinue) {{'yes'}} else {{'no'}}"
    )
    return out == "yes"


def ensure_user(name: str, password: str) -> None:
    if user_exists(name):
        print(f"  user {name}: exists -> resetting password")
        ps(
            "Set-LocalUser -Name $env:SB_USER "
            "-Password (ConvertTo-SecureString $env:SB_PW -AsPlainText -Force)",
            env={"SB_USER": name, "SB_PW": password},
        )
    else:
        print(f"  user {name}: creating")
        ps(
            "New-LocalUser -Name $env:SB_USER "
            "-Password (ConvertTo-SecureString $env:SB_PW -AsPlainText -Force) "
            "-AccountNeverExpires -PasswordNeverExpires "
            "-Description 'Nokido code-execution sandbox'",
            env={"SB_USER": name, "SB_PW": password},
        )
    # standard Users membership, never Administrators
    ps(
        f"$g=Get-LocalGroup -SID '{USERS_GROUP_SID}'; "
        f"if (-not (Get-LocalGroupMember -Group $g -Member '{name}' "
        f"-ErrorAction SilentlyContinue)) {{ Add-LocalGroupMember -Group $g -Member '{name}' }}"
    )


def ensure_group() -> None:
    out = ps(
        f"if (Get-LocalGroup -Name '{GROUP}' -ErrorAction SilentlyContinue) {{'yes'}} else {{'no'}}"
    )
    if out != "yes":
        print(f"  group {GROUP}: creating")
        ps(
            f"New-LocalGroup -Name '{GROUP}' "
            f"-Description 'Nokido sandbox users (ACL tag, no privileges)'"
        )
    for name in USERS:
        ps(
            f"if (-not (Get-LocalGroupMember -Group '{GROUP}' -Member '{name}' "
            f"-ErrorAction SilentlyContinue)) "
            f"{{ Add-LocalGroupMember -Group '{GROUP}' -Member '{name}' }}"
        )
    print(f"  group {GROUP}: members set")


def user_sid(name: str) -> str:
    return ps(f"(Get-LocalUser -Name '{name}').SID.Value")


def grant_batch_logon() -> None:
    """Grant SeBatchLogonRight to the sandbox + trusted users (needed for
    LogonUser LOGON32_LOGON_BATCH) via secedit."""
    sids = [user_sid(n) for n in (list(USERS) + [TRUSTED_USER])]
    print(f"  batch-logon right: granting to {len(sids)} users")
    # export current policy, merge SIDs into SeBatchLogonRight, re-import
    script = f"""
$tmp = Join-Path $env:TEMP 'lf_secpol.inf'
$db  = Join-Path $env:TEMP 'lf_secpol.sdb'
secedit /export /cfg $tmp /areas USER_RIGHTS | Out-Null
$lines = Get-Content $tmp
$add = {",".join(f"'*{s}'" for s in sids)}
$found = $false
$out = foreach ($l in $lines) {{
  if ($l -match '^SeBatchLogonRight') {{
    $found = $true
    $existing = ($l -split '=')[1].Trim()
    $set = @($existing -split ',' | ForEach-Object {{ $_.Trim() }} | Where-Object {{ $_ }})
    foreach ($s in $add) {{ if ($set -notcontains $s) {{ $set += $s }} }}
    'SeBatchLogonRight = ' + ($set -join ',')
  }} else {{ $l }}
}}
if (-not $found) {{ $out += 'SeBatchLogonRight = ' + ($add -join ',') }}
Set-Content -Path $tmp -Value $out -Encoding Unicode
secedit /configure /db $db /cfg $tmp /areas USER_RIGHTS | Out-Null
Remove-Item $tmp,$db -ErrorAction SilentlyContinue
'ok'
"""
    ps(script)


def set_acls() -> None:
    """Sandbox group: read on .run_tmp, modify on workspace + sandbox state,
    read+exec on the Nokido tree and the python toolchain."""
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "tmp").mkdir(exist_ok=True)
    RUN_TMP.mkdir(exist_ok=True)
    print("  ACLs: .run_tmp=read, workspace+sandbox=modify, miniforge=read")
    sys.stdout.flush()
    # read on the script staging dir
    print(f"    ... icacls /T {RUN_TMP.name}")
    sys.stdout.flush()
    ps(f'icacls "{RUN_TMP}" /grant "{GROUP}:(OI)(CI)(RX)" /T /C', check=False, timeout=300)
    # full control inside the dedicated workspace only
    print(f"    ... icacls /T {WORKSPACE.relative_to(ROOT)}")
    sys.stdout.flush()
    ps(f'icacls "{WORKSPACE}" /grant "{GROUP}:(OI)(CI)(M)" /T /C', check=False, timeout=300)
    # runAs-sandbox services persist state under sandbox/ (heartbeats,
    # rss_watcher_state.json, ...). Without Modify here a runAs service
    # crashes on its first state write -> supervisor restart loop.
    # /T sur sandbox/ peut etre lent (gitingest cache, jobs) -> timeout 900.
    # The DPAPI creds file keeps its restrictive ACL: save_creds() runs
    # last in main() and re-locks it with /inheritance:r.
    print(f"    ... icacls /T {SANDBOX_DIR.name}  (peut etre long, timeout 900s)")
    sys.stdout.flush()
    ps(f'icacls "{SANDBOX_DIR}" /grant "{GROUP}:(OI)(CI)(M)" /T /C', check=False, timeout=900)
    # COMMUNICATIONS.md (racine) : fichier de comms inter-agents qu'un service
    # runAs-sandbox (RSS watcher) doit pouvoir appendre. Grant cible sur ce
    # seul fichier — le reste de la racine reste en lecture seule.
    comms = ROOT / "COMMUNICATIONS.md"
    if not comms.exists():
        comms.touch()
    print("    ... icacls COMMUNICATIONS.md")
    sys.stdout.flush()
    ps(f'icacls "{comms}" /grant "{GROUP}:(M)" /C', check=False)
    # read on the Nokido code tree so scripts can run (no write)
    print("    ... icacls ROOT (no /T)")
    sys.stdout.flush()
    ps(f'icacls "{ROOT}" /grant "{GROUP}:(OI)(CI)(RX)" /C', check=False)
    # the python toolchain lives in the user profile; without RX on it
    # python.exe fails to load as the sandbox user (STATUS_DLL_NOT_FOUND).
    # traverse-only on the profile root, read+exec on miniforge.
    # miniforge3 root : grant OI/CI (héritage couvre les NOUVEAUX fichiers)
    # SANS /T — /T sur ~12 GB d'arbre conda dépasse le timeout 120s par défaut.
    # Les sous-arbres lourds (envs/* + pkgs + Lib) reçoivent /T séparément
    # avec timeout=600 — couvre les fichiers EXISTANTS qui ne re-héritent pas.
    ps(f'icacls __import__("os").path.expanduser("~") /grant "{GROUP}:(X)" /C', check=False)
    ps(f'icacls __import__("os").path.expanduser("~\\miniforge3") /grant "{GROUP}:(OI)(CI)(RX)" /C', check=False)
    _icacls_subtrees_parallel(
        _miniforge_subtrees(), principal=GROUP, perm="(OI)(CI)(RX)", label="sandbox"
    )


def ensure_trusted_group() -> None:
    """Create LaForgeTrustedRunners group + add TRUSTED_USER. Idempotent.
    Sert de tag ACL collectif quand >1 compte trusted existera (Codex, Cursor…)."""
    out = ps(
        f"if (Get-LocalGroup -Name '{TRUSTED_GROUP}' -ErrorAction SilentlyContinue) "
        f"{{'yes'}} else {{'no'}}"
    )
    if out != "yes":
        print(f"  group {TRUSTED_GROUP}: creating")
        ps(
            f"New-LocalGroup -Name '{TRUSTED_GROUP}' "
            f"-Description 'Nokido trusted runners (non-admin)'"
        )
    ps(
        f"if (-not (Get-LocalGroupMember -Group '{TRUSTED_GROUP}' -Member '{TRUSTED_USER}' "
        f"-ErrorAction SilentlyContinue)) "
        f"{{ Add-LocalGroupMember -Group '{TRUSTED_GROUP}' -Member '{TRUSTED_USER}' }}"
    )
    print(f"  group {TRUSTED_GROUP}: members set")


def ensure_trusted_user(password: str) -> None:
    """Create LaForgeTrusted -- a standard (non-admin) account that runs
    git-tracked maintenance scripts with repo + DB write. NOT a sandbox user:
    no outbound firewall block, not in the sandbox group."""
    if user_exists(TRUSTED_USER):
        print(f"  user {TRUSTED_USER}: exists -> resetting password")
        ps(
            "Set-LocalUser -Name $env:SB_USER "
            "-Password (ConvertTo-SecureString $env:SB_PW -AsPlainText -Force)",
            env={"SB_USER": TRUSTED_USER, "SB_PW": password},
        )
    else:
        print(f"  user {TRUSTED_USER}: creating")
        ps(
            "New-LocalUser -Name $env:SB_USER "
            "-Password (ConvertTo-SecureString $env:SB_PW -AsPlainText -Force) "
            "-AccountNeverExpires -PasswordNeverExpires "
            "-Description 'Nokido trusted maintenance runner'",
            env={"SB_USER": TRUSTED_USER, "SB_PW": password},
        )
    # standard Users membership, never Administrators
    ps(
        f"$g=Get-LocalGroup -SID '{USERS_GROUP_SID}'; "
        f"if (-not (Get-LocalGroupMember -Group $g -Member '{TRUSTED_USER}' "
        f"-ErrorAction SilentlyContinue)) "
        f"{{ Add-LocalGroupMember -Group $g -Member '{TRUSTED_USER}' }}"
    )


def set_trusted_acls() -> None:
    """LaForgeTrusted: Modify on the whole repo tree (so it can write
    embeddings.db, logs, sandbox), read+exec on the python toolchain and the
    llama GPU server. The creds file keeps its restrictive SYSTEM+Admins ACL
    (re-applied last by save_creds)."""
    import os as _os

    print(f"  ACLs trusted: {ROOT.name}=modify, miniforge+llama=read")
    ps(f'icacls "{ROOT}" /grant "{TRUSTED_USER}:(OI)(CI)(M)" /T /C', check=False, timeout=600)
    ps(f'icacls __import__("os").path.expanduser("~") /grant "{TRUSTED_USER}:(X)" /C', check=False)
    # miniforge3 root : OI/CI sans /T (cf. set_acls). /T scopé sous-arbres.
    ps(
        f'icacls __import__("os").path.expanduser("~\\miniforge3") /grant "{TRUSTED_USER}:(OI)(CI)(RX)" /C',
        check=False,
    )
    subs = list(_miniforge_subtrees())
    if _os.path.isdir(LLAMA_DIR):
        subs.append(LLAMA_DIR)
    _icacls_subtrees_parallel(subs, principal=TRUSTED_USER, perm="(OI)(CI)(RX)", label="trusted")


def set_firewall() -> None:
    """Offline user: block ALL outbound. Loopback stays reachable because the
    Windows Filtering Platform does not filter loopback traffic -- so the hub
    (:8766) and ollama (:11434) remain usable without an explicit allow rule.
    Online user: no rule."""
    off_sid = user_sid("LaForgeSbxOffline")
    sddl = f"D:(A;;CC;;;{off_sid})"
    print("  firewall: Offline outbound-block (loopback is WFP-exempt)")
    # remove stale rules first (idempotent)
    ps(
        "Get-NetFirewallRule -DisplayName 'LaForge-Sandbox-Offline-*' "
        "-ErrorAction SilentlyContinue | Remove-NetFirewallRule",
        check=False,
    )
    ps(
        f"New-NetFirewallRule -DisplayName 'LaForge-Sandbox-Offline-block-out' "
        f"-Direction Outbound -Action Block "
        f'-LocalUser "{sddl}" | Out-Null'
    )


def save_creds(passwords: dict) -> None:
    """DPAPI-encrypt the sandbox passwords (LocalMachine scope) so the hub
    (running as SYSTEM) can decrypt them. File ACL'd to SYSTEM+Admins."""
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    blob = "\n".join(f"{u}={p}" for u, p in passwords.items())
    print(f"  creds: DPAPI-encrypting -> {CREDS_FILE.name}")
    ps(
        "Add-Type -AssemblyName System.Security; "
        "$b=[Text.Encoding]::UTF8.GetBytes($env:SB_BLOB); "
        "$e=[Security.Cryptography.ProtectedData]::Protect($b,$null,'LocalMachine'); "
        f"[IO.File]::WriteAllBytes('{CREDS_FILE}',$e)",
        env={"SB_BLOB": blob},
    )
    # restrict to SYSTEM + Administrators only
    ps(
        f'icacls "{CREDS_FILE}" /inheritance:r '
        f'/grant "SYSTEM:(F)" "Administrateurs:(F)" "Administrators:(F)" /C',
        check=False,
    )


def status() -> None:
    print("=== Nokido sandbox status ===")
    for name in USERS:
        ex = user_exists(name)
        groups = ""
        if ex:
            groups = (
                ps(
                    f"(Get-LocalUser '{name}' | Get-LocalGroup "
                    f"-ErrorAction SilentlyContinue).Name -join ','",
                    check=False,
                )
                or "?"
            )
        print(f"  {name}: {'present' if ex else 'MISSING'}  groups={groups}")
    tex = user_exists(TRUSTED_USER)
    print(f"  {TRUSTED_USER}: {'present' if tex else 'MISSING'}")
    fw = ps(
        "(Get-NetFirewallRule -DisplayName 'LaForge-Sandbox-Offline-*' "
        "-ErrorAction SilentlyContinue).DisplayName -join ','",
        check=False,
    )
    print(f"  firewall rules: {fw or 'none'}")
    print(f"  creds file: {'present' if CREDS_FILE.exists() else 'MISSING'}")
    print(f"  workspace : {'present' if WORKSPACE.exists() else 'MISSING'}")


def teardown() -> None:
    print("=== teardown ===")
    ps(
        "Get-NetFirewallRule -DisplayName 'LaForge-Sandbox-Offline-*' "
        "-ErrorAction SilentlyContinue | Remove-NetFirewallRule",
        check=False,
    )
    for name in list(USERS) + [TRUSTED_USER]:
        ps(f"Remove-LocalUser -Name '{name}' -ErrorAction SilentlyContinue", check=False)
    ps(f"Remove-LocalGroup -Name '{GROUP}' -ErrorAction SilentlyContinue", check=False)
    ps(f"Remove-LocalGroup -Name '{TRUSTED_GROUP}' -ErrorAction SilentlyContinue", check=False)
    if CREDS_FILE.exists():
        CREDS_FILE.unlink()
    print("  users, group, firewall rules, creds removed")


def main() -> int:
    ap = argparse.ArgumentParser(description="Provision the Nokido sandbox.")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--teardown", action="store_true")
    ap.add_argument(
        "--acls-only",
        action="store_true",
        help="re-applique uniquement les ACL (sans toucher aux "
        "users / mots de passe / firewall / creds)",
    )
    args = ap.parse_args()

    if sys.platform != "win32":
        print("Windows only.")
        return 1

    if args.status:
        status()
        return 0

    if not is_admin():
        print("ERROR: run as Administrator (creates users, ACLs, firewall).")
        return 1

    if args.teardown:
        teardown()
        return 0

    if args.acls_only:
        print("=== re-application des ACL seulement ===")
        set_acls()
        set_trusted_acls()
        status()
        return 0

    print("=== provisioning Nokido sandbox ===")
    passwords = {u: secrets.token_urlsafe(24) for u in USERS}
    passwords[TRUSTED_USER] = secrets.token_urlsafe(24)
    for name in USERS:  # sandbox users first
        ensure_user(name, passwords[name])
    ensure_trusted_user(passwords[TRUSTED_USER])  # then the trusted runner
    ensure_group()  # then the group + membership
    ensure_trusted_group()  # group dédié comptes tier trusted
    grant_batch_logon()
    set_acls()
    set_trusted_acls()
    set_firewall()
    save_creds(passwords)
    print("\nDONE. trusted_script operationnel apres restart du hub.")
    status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
