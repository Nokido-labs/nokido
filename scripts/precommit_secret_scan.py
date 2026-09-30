#!/usr/bin/env python
"""Nokido pre-commit hook (native Python, no framework deps).

Lance par git automatiquement avant chaque commit via .git/hooks/pre-commit.
Bloque le commit si des secrets sont detectes dans les fichiers stages.

Patterns detectes :
- Cles API : AIza* (Google), ghp_* / github_pat_* (GitHub), sk-* (OpenAI/DeepSeek),
             hf_* (HuggingFace), xoxb-* (Slack), AKIA* (AWS)
- Cles privees : -----BEGIN ... PRIVATE KEY-----
- HMAC secrets : MCP_DEV_SECRET=<hex64>, FORGE_MCP_TOKEN=<hex64>
- Tokens generiques : 40+ chars hex purs avec contexte sensible

Whitelist (faux positifs ignores) :
- .git/, __pycache__/, sandbox/test_repos/ (litellm/etc clones)
- Nokido.env (gitignored anyway)
- *.lock (poetry/npm)
- Tests qui contiennent des fake secrets explicites (test_*.py + comment "fake")

Sortie : exit 0 si OK, exit 1 + liste des hits si secret trouve.
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path

# Patterns secrets (label, regex, severity)
PATTERNS = [
    ("Google API Key",      r"AIza[0-9A-Za-z_-]{35}",                                   "HIGH"),
    ("GitHub Classic PAT",  r"ghp_[0-9A-Za-z]{36}",                                     "HIGH"),
    ("GitHub Fine PAT",     r"github_pat_[0-9A-Za-z_]{82}",                             "HIGH"),
    ("OpenAI/DeepSeek SK",  r"sk-[a-zA-Z0-9]{20,}",                                     "HIGH"),
    ("HuggingFace Token",   r"hf_[A-Za-z0-9]{30,}",                                     "HIGH"),
    ("Slack Bot Token",     r"xox[baprs]-[0-9a-zA-Z]{10,48}",                           "HIGH"),
    ("AWS Access Key",      r"AKIA[0-9A-Z]{16}",                                        "HIGH"),
    ("Private Key Block",   r"-----BEGIN (RSA |DSA |EC |OPENSSH |)PRIVATE KEY-----",    "HIGH"),
    # Patterns contextuels : KEY/SECRET/TOKEN= suivi d'un long hex/base64
    ("HMAC Secret hex",     r"(?:_SECRET|_TOKEN|_KEY)=[a-f0-9]{40,}",                   "MEDIUM"),
]

# Whitelist : ignorer ces paths
WHITELIST_PATHS = [
    re.compile(r"\.git/"),
    re.compile(r"__pycache__/"),
    re.compile(r"sandbox/test_repos/"),
    re.compile(r"\.lock$"),
    re.compile(r"\.pyc$"),
    re.compile(r"\.cache/"),
    re.compile(r"_attic/session_backups/"),  # backups historiques
]


def staged_files() -> list[Path]:
    """Retourne la liste des fichiers stages pour le commit."""
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, encoding="utf-8"
    )
    if r.returncode != 0:
        return []
    return [Path(f) for f in r.stdout.splitlines() if f.strip()]


def is_whitelisted(path: Path) -> bool:
    p = str(path).replace("\\", "/")
    return any(rx.search(p) for rx in WHITELIST_PATHS)


def scan_file(path: Path) -> list[tuple[str, str, int, str]]:
    """Scan un fichier, retourne [(label, severity, line_no, masked_match)]."""
    hits = []
    if not path.exists() or not path.is_file():
        return hits
    # Skip binaires (heuristique)
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return hits
    for label, pattern, severity in PATTERNS:
        for m in re.finditer(pattern, content):
            line_no = content[:m.start()].count("\n") + 1
            matched = m.group(0)
            # Masquer la valeur sensible
            masked = matched[:8] + "..." + matched[-4:] if len(matched) > 16 else "***"
            # Skip les "fake" patterns marques comme tels (test fixtures)
            line_content = content.splitlines()[line_no - 1] if line_no <= len(content.splitlines()) else ""
            if "fake" in line_content.lower() or "dummy" in line_content.lower() or "example" in line_content.lower():
                continue
            hits.append((label, severity, line_no, masked))
    return hits


def main() -> int:
    files = staged_files()
    if not files:
        return 0

    all_hits = []
    scanned = 0
    skipped = 0
    for f in files:
        if is_whitelisted(f):
            skipped += 1
            continue
        scanned += 1
        hits = scan_file(f)
        for label, severity, line_no, masked in hits:
            all_hits.append((f, label, severity, line_no, masked))

    if all_hits:
        print(f"\n[!] NOKIDO PRE-COMMIT : {len(all_hits)} secret(s) detecte(s) dans {scanned} fichier(s) stages")
        print(f"=" * 70)
        for path, label, severity, line_no, masked in all_hits:
            print(f"  [{severity}] {path}:{line_no}  {label}")
            print(f"           Match : {masked}")
        print(f"=" * 70)
        print(f"\nCommit BLOQUE. Pour resoudre :")
        print(f"  1. Retirer les secrets des fichiers concernes")
        print(f"  2. Ajouter au .gitignore si besoin")
        print(f"  3. Si faux positif : ajouter 'fake' ou 'dummy' dans le commentaire de la ligne")
        print(f"  4. Pour bypass d'urgence (NON recommande) : git commit --no-verify\n")
        return 1

    print(f"[OK] Nokido pre-commit : {scanned} fichiers scannes ({skipped} whitelistes), 0 secret detecte")
    return 0


if __name__ == "__main__":
    sys.exit(main())
