"""tools/launch_public_mirror.py — orchestrate the clean-slate public release.

Five phases, each idempotent + safe :

  1. --esoleau-zip   Generate the ZIP archive from beta tip for INPI eSoleau
                     upload. Prints SHA-256 (to include in the eSoleau form).
                     No git mutation, no network.

  2. --prepare       Create the clean-slate staging directory at
                     C:/tmp/laforge-public-staging. `git checkout --orphan`
                     equivalent : copies tracked files from beta tip ONLY,
                     initializes a fresh git repo, single signed commit
                     "v0.1.0 — initial public release" with author
                     user <user@users.noreply.github.com>. Tags v0.1.0. No remote
                     push.

  3. --create-remote Creates the `user/Nokido-public` repo on GitHub
                     (public visibility from the start, since the snapshot
                     is already sanitized). Sets description, homepage,
                     topics. Does NOT push yet.

  4. --push          Push the staging branch + tag to the new remote.
                     REQUIRES --i-have-esoleau-receipt to confirm you
                     uploaded the ZIP to INPI eSoleau and have the PDF
                     receipt. Refuses to run otherwise.

  5. --protect-main  Applies branch protection to `main` on the public
                     repo : require PR, require signed commits, require
                     status checks, no force push. Free-tier compatible
                     via Rulesets.

Each phase can be run independently. They're all idempotent — re-run any
of them and you get the same end state.

NO PHASE WILL PUSH TO PUBLIC OR MAKE PRIVATE NOKIDO.GIT PUBLIC unless
you pass --push AND --i-have-esoleau-receipt explicitly.
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/deploy : orchestre la release publique clean-slate en 5 phases"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent.parent  # private Nokido.git
STAGING = (
    Path("C:/tmp/laforge-public-staging")
    if sys.platform == "win32"
    else Path("/tmp/laforge-public-staging")
)
RELEASE_DIR = Path("C:/tmp") if sys.platform == "win32" else Path("/tmp")

NEW_REPO_NAME = "Nokido-public"
GITHUB_OWNER = "user"
NEW_REPO_FULL = f"{GITHUB_OWNER}/{NEW_REPO_NAME}"

PUBLIC_DESCRIPTION = "Autonomous, Local-First AI Operating System with Neuro-Symbolic Governance"
PUBLIC_HOMEPAGE = f"https://github.com/{NEW_REPO_FULL}"
PUBLIC_TOPICS = [
    "ai",
    "agent",
    "autonomous",
    "llm",
    "mcp",
    "rag",
    "ami",
    "neuro-symbolic",
    "local-first",
    "sovereignty",
    "agplv3",
    "python",
    "rust",
    "deno",
    "ollama",
    "anthropic",
]

# Pseudonyme (decision owner 2026-09-30), comme les commits du dist.
PUBLIC_AUTHOR_NAME = "user"
PUBLIC_AUTHOR_EMAIL = "user@users.noreply.github.com"

VERSION = "0.1.0"
COMMIT_MSG = f"""v{VERSION} — initial public release

Nokido is an Autonomous, Local-First AI Operating System with Neuro-
Symbolic Governance. This commit is the clean-slate snapshot from the
private alpha/beta development branches, sanitized for public release.

Architecture highlights :
  - 25 MCP tools exposed via a local hub on port 8766.
  - 29 LLM providers cascade (3 local + 26 cloud) with quota-aware routing.
  - Persistent RAG memory (~380k chunks, FTS5 + BM25 + FAISS BGE-M3 1024D
    + cross-encoder reranker).
  - Semantic Firewall + Sovereign Membrane (HMAC-aliased anonymization
    before any cloud egress).
  - 6-ring RBAC, DPAPI / Keychain / libsecret vault for secrets.
  - AMI cognitive stack (LeCun world model, Friston active inference,
    Hasani Liquid Neural Networks for edge telemetry).
  - Neuro-symbolic governance : LLMs draft, deterministic scorecard judges.

Tested on AMD Ryzen 7 8700G + Radeon 780M iGPU (consumer APU). HumanEval
pass@1 87.8 %, BFCL v4 90-96 %, SWE-bench 10/50 mixed.

Licensed under AGPLv3 + commercial dual model. Contributing requires the
Individual CLA (auto-handled by the CLA Assistant bot).

See MANIFESTO.md for design philosophy, docs/wiki/ for the 19-page
bilingual operator manual, docs/ARCHITECTURE.md for technical internals,
COMMERCIAL.md for proprietary licensing terms.

Contact : GitHub Discussions du depot (@user)
Wiki    : github.com/user/Nokido-public/tree/main/docs/wiki
"""


# ─── Utility helpers ────────────────────────────────────────────────────────


def info(msg: str) -> None:
    print(f"[info] {msg}")


def ok(msg: str) -> None:
    print(f"[ok]   {msg}")


def warn(msg: str) -> None:
    print(f"[warn] {msg}", file=sys.stderr)


def fail(msg: str) -> NoReturn:  # type: ignore
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def run(
    cmd: list[str], cwd: Path | None = None, check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess:
    """Run command, raise on error if check=True."""
    info("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
        encoding="utf-8",
        errors="replace",
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ─── Phase 1 : eSoleau ZIP ──────────────────────────────────────────────────


def phase_esoleau_empreintes(
    branch: str = "alpha",
    root: Path | None = None,
    out_dir: Path | None = None,
) -> Path:
    """e-Soleau par EMPREINTES : dossier probatoire COMPACT, jamais l'archive complete.

    Pourquoi (owner 2026-09-16, source INPI) : l'e-Soleau coute 15 EUR jusqu'a 50 Mo
    (+10 EUR par tranche de 50 Mo) et accepte des EMPREINTES NUMERIQUES sans limite
    de taille. `phase_esoleau_zip` archive tout le code (59 Mo des juin 2026) : au-dela
    de la tranche, et inutile pour dater. Ici on depose ce qui PROUVE : le sha256 du
    contenu de chaque fichier tel que COMMITE (lu par `git archive`, jamais l'arbre de
    travail partage, qui porte l'uncommitted d'autres surfaces), l'identite du commit,
    et les documents IP eux-memes.

    Le zip ne contient AUCUN chemin du poste (les chemins sont relatifs au depot) et
    rend son propre SHA-256, a reporter dans le formulaire INPI.
    """
    import datetime
    import io
    import tarfile
    import zipfile

    root = Path(root) if root else ROOT
    out_dir = Path(out_dir) if out_dir else RELEASE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    def g(*a: str) -> str:
        # `check=True` : un git qui echoue ARRETE la phase, il ne rend pas un dossier vide.
        r = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(root), *a],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        )
        return r.stdout.strip()

    # Un `root` sous la racine (ou hors depot) fait REMONTER git au depot parent :
    # `rev-parse` reussit, puis `git archive` sort le SOUS-ARBRE relatif au cwd — vide.
    # Mesure par le NR le 2026-09-16 : preuve vide sans aucune erreur. On exige l'egalite.
    toplevel = Path(g("rev-parse", "--show-toplevel")).resolve()
    if toplevel != Path(root).resolve():
        raise RuntimeError(
            f"root {root} n'est pas la racine du depot git ({toplevel}) : "
            "on n'archive pas un sous-arbre pour une preuve d'anteriorite")
    commit = g("rev-parse", branch)
    tree = g("rev-parse", f"{branch}^{{tree}}")
    date_commit = g("log", "-1", "--format=%cI", branch)
    auteur = g("log", "-1", "--format=%an", branch)
    version = "?"
    try:
        for ligne in g("show", f"{branch}:pyproject.toml").splitlines():
            if ligne.startswith("version"):
                version = ligne.split('"')[1]
                break
    except subprocess.CalledProcessError:  # muet-ok : pas de pyproject dans ce commit
        version = "?"                     # -> version inconnue, DITE dans TREE.txt et le titre

    tar_bytes = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(root), "archive", "--format=tar", branch],
        capture_output=True, check=True,
    ).stdout
    lignes: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
        for m in tf:
            if not m.isfile():
                continue
            f = tf.extractfile(m)
            if f is None:
                continue
            h = hashlib.sha256(f.read()).hexdigest()
            lignes.append(f"{h}  {m.size:>10}  {m.name}")
    if not lignes:
        raise RuntimeError(f"aucun fichier hache pour {branch} : preuve vide refusee")
    lignes.sort(key=lambda l: l.split("  ", 2)[-1])
    manifest = "\n".join(lignes) + "\n"
    manifest_sha = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    jour = datetime.date.today().isoformat()

    tree_txt = (
        f"branche      : {branch}\n"
        f"commit       : {commit}\n"
        f"tree         : {tree}\n"
        f"date commit  : {date_commit}\n"
        f"auteur       : {auteur}\n"
        f"version      : {version}\n"
        f"fichiers     : {len(lignes)}\n"
        f"manifest sha : {manifest_sha}\n"
        f"genere le    : {jour}\n"
    )
    docs_ip = (
        "docs/ip/IP_TRIAGE_CANDIDATS.md",
        "docs/ip/DECISION_PUBLICATION.json",
        "docs/ARCHITECTURE.md",
        "MANIFESTO.md",
        "LICENSE",
    )
    inclus: list[str] = []
    absents: list[str] = []
    out_zip = out_dir / f"nokido-esoleau-empreintes-{commit[:8]}-{jour}.zip"
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("MANIFEST_SHA256.txt", manifest)
        z.writestr("TREE.txt", tree_txt)
        for rel in docs_ip:
            try:
                blob = subprocess.run(
                    ["git", "-c", "safe.directory=*", "-C", str(root), "show", f"{branch}:{rel}"],
                    capture_output=True, check=True,
                ).stdout
            except subprocess.CalledProcessError:
                absents.append(rel)  # absent de CE commit : dit dans le README, pas avale
                continue
            z.writestr(rel, blob)
            inclus.append(rel)
        readme = (
            f"Nokido v{version} -- preuve d'anteriorite par empreintes numeriques\n"
            # Preuve d'anteriorite : le titulaire legal peut etre requis. Il se
            # donne a l'execution (NOKIDO_AUTEUR_LEGAL), jamais dans le code publie.
            f"Auteur : {os.environ.get('NOKIDO_AUTEUR_LEGAL', 'user')}\n"
            f"Date de generation : {jour}\n"
            f"Commit : {commit}\n"
            f"Empreinte du manifeste : {manifest_sha}\n\n"
            "MANIFEST_SHA256.txt = sha256 du contenu COMMITE de chaque fichier du depot\n"
            "(chemins relatifs au depot). TREE.txt = identite du commit.\n"
            f"Documents joints : {', '.join(inclus) or 'aucun'}\n"
            f"Absents de ce commit : {', '.join(absents) or 'aucun'}\n\n"
            "Reserve : ce depot etablit une DATE et une PATERNITE ; il ne constitue ni une\n"
            "revendication de brevet ni une divulgation des mecanismes IP_HOLD.\n"
            "Reference : docs/ip/DECISION_PUBLICATION.json (option B, 2026-09-16).\n"
        )
        z.writestr("README_IP.txt", readme)

    sha = sha256_file(out_zip)
    size_mb = out_zip.stat().st_size / (1024 * 1024)
    if size_mb > 50:
        warn(f"dossier {size_mb:.1f} Mo > 50 Mo : tranche INPI supplementaire (+10 EUR/50 Mo)")
    print()
    print("=" * 70)
    print("  eSoleau EMPREINTES ready")
    print("=" * 70)
    print(f"  Path     : {out_zip}")
    print(f"  Size     : {size_mb:.2f} MB  ({len(lignes)} fichiers haches, commit {commit[:8]})")
    print(f"  SHA-256  : {sha}")
    print()
    print("  Next step (manual, owner) :")
    print("  1. https://www.inpi.fr/realiser-demarches/propriete-intellectuelle/deposer-une-e-soleau-ou-un-entiercement")
    print("  2. Type : oeuvre logicielle / code source (empreintes)")
    print(f"     Titre : Nokido v{version} -- Autonomous Local-First AI OS (empreintes {commit[:8]})")
    print("     Joindre : le zip ci-dessus ; coller son SHA-256 dans la description.")
    print("  3. Payer 15 EUR. Conserver le recepisse PDF A VIE avec le zip.")
    print("=" * 70)
    return out_zip


def phase_esoleau_zip(beta_branch: str = "beta") -> Path:
    """Generate the ZIP archive from beta tip for INPI eSoleau upload."""
    out_zip = RELEASE_DIR / f"laforge-v{VERSION}-rc.zip"

    if out_zip.exists():
        warn(f"{out_zip} already exists. Deleting + regenerating.")
        out_zip.unlink()

    info(f"git archive {beta_branch} → {out_zip}")
    run(
        [
            "git",
            "-C",
            str(ROOT),
            "archive",
            "--format=zip",
            f"--prefix=laforge-v{VERSION}-rc/",
            beta_branch,
            "-o",
            str(out_zip),
        ]
    )

    sha = sha256_file(out_zip)
    size_mb = out_zip.stat().st_size / (1024 * 1024)

    print()
    print("=" * 70)
    print("  eSoleau ZIP ready")
    print("=" * 70)
    print(f"  Path     : {out_zip}")
    print(f"  Size     : {size_mb:.2f} MB")
    print(f"  SHA-256  : {sha}")
    print()
    print("  Next step (manual) :")
    print("  1. Visit https://www.inpi.fr/fr/services-en-ligne/depot-de-creation-en-ligne-e-soleau")
    print("  2. Create / login account.")
    print("  3. Submit new envelope :")
    print("     Type     : Œuvre logicielle / code source")
    print(f"     Title    : Nokido v{VERSION} — Autonomous Local-First AI OS")
    print(f"     Attach   : {out_zip}")
    print("     Pay 15 € by card.")
    print("  4. Save the PDF receipt FOREVER.")
    print("  5. THEN run : python tools/launch_public_mirror.py --prepare")
    print("=" * 70)

    return out_zip


# ─── Phase 2 : Clean-slate prepare ──────────────────────────────────────────


def phase_prepare(beta_branch: str = "beta") -> Path:
    """Create the clean-slate staging directory + single signed commit."""
    if STAGING.exists():
        warn(f"{STAGING} already exists. Removing for a fresh start.")
        shutil.rmtree(STAGING)

    STAGING.mkdir(parents=True)

    # Use git archive to extract beta tip's tracked files (NO history, NO
    # gitignored runtime artifacts like RAG/embeddings.db, sandbox/, etc.).
    info(f"Extracting beta tip → {STAGING}")
    archive_tmp = STAGING.parent / "_archive.tmp.zip"
    run(
        [
            "git",
            "-C",
            str(ROOT),
            "archive",
            "--format=zip",
            beta_branch,
            "-o",
            str(archive_tmp),
        ]
    )

    # Unzip into staging
    shutil.unpack_archive(str(archive_tmp), str(STAGING))
    archive_tmp.unlink()

    # Verify no leftover .git directory
    if (STAGING / ".git").exists():
        shutil.rmtree(STAGING / ".git")

    # POLITIQUE DE PUBLICATION avant le commit clean-slate. Meme raison que
    # forge_dist_publish : ce bootstrap CREE le depot public et pousse -- son push
    # ne passe PAS par le gate egress du depot source. `git archive` n'applique que
    # export-ignore ; sans cette etape, docs/ip, .agents, config env-specifique
    # partiraient dans le commit initial. On reutilise la MEME fonction (anti-dup),
    # autorite unique `forge_git_egress`. Fail-closed si le profil est illisible.
    import sys as _sys_pol  # noqa: PLC0415
    _tools = str(Path(__file__).resolve().parent)
    if _tools not in _sys_pol.path:
        _sys_pol.path.insert(0, _tools)
    from forge_dist_publish import _appliquer_politique_publique, _generiser_chemins_owner  # noqa: PLC0415
    _appliquer_politique_publique(STAGING)
    # Generisation des chemins owner -> variables d'env (installabilite du dist).
    # Le depot source reste INTACT : on transforme le STAGING seulement.
    _generiser_chemins_owner(STAGING)

    # Initialize fresh git repo
    run(["git", "init", "-b", "main"], cwd=STAGING)

    # Detect signing key configured globally — required for signed commit.
    sign_key_check = run(
        ["git", "config", "--global", "--get", "user.signingkey"],
        check=False,
        capture=True,
    )
    can_sign = bool(sign_key_check.stdout.strip())
    sign_method = run(
        ["git", "config", "--global", "--get", "gpg.format"],
        check=False,
        capture=True,
    ).stdout.strip()

    if not can_sign:
        warn("No global user.signingkey configured. Commit will be UNSIGNED.")
        warn("To enable Verified badge on GitHub :")
        warn("  ssh-keygen -t ed25519 -f ~/.ssh/nokido_signing -C 'user@users.noreply.github.com'")
        warn("  git config --global gpg.format ssh")
        warn("  git config --global user.signingkey ~/.ssh/nokido_signing.pub")
        warn("  Then upload the .pub to https://github.com/settings/keys (Signing key)")
        sign_flag = []
    else:
        info(f"Will sign commit with method={sign_method} key={sign_key_check.stdout.strip()}")
        sign_flag = ["-S"]

    # Stage all
    run(["git", "add", "-A"], cwd=STAGING)

    # Commit with explicit author
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = PUBLIC_AUTHOR_NAME
    env["GIT_AUTHOR_EMAIL"] = PUBLIC_AUTHOR_EMAIL
    env["GIT_COMMITTER_NAME"] = PUBLIC_AUTHOR_NAME
    env["GIT_COMMITTER_EMAIL"] = PUBLIC_AUTHOR_EMAIL

    commit_cmd = ["git", "commit"] + sign_flag + ["-m", COMMIT_MSG]
    subprocess.run(commit_cmd, cwd=STAGING, env=env, check=True, encoding="utf-8", errors="replace")

    # Tag (signed if possible)
    tag_cmd = ["git", "tag"]
    if sign_flag:
        tag_cmd.append("-s")
    tag_cmd += ["-a", f"v{VERSION}", "-m", f"v{VERSION} initial public release"]
    subprocess.run(tag_cmd, cwd=STAGING, env=env, check=True, encoding="utf-8", errors="replace")

    # Verify the commit
    info("Verifying commit...")
    show = run(["git", "log", "-1", "--pretty=fuller"], cwd=STAGING, capture=True)
    print(show.stdout)

    # Count tracked files in the snapshot
    ls = run(["git", "ls-files"], cwd=STAGING, capture=True)
    file_count = sum(1 for line in ls.stdout.splitlines() if line.strip())
    ok(f"Snapshot contains {file_count} tracked files.")

    # Quick sanity check on file count — expect ~1500-2500
    if file_count < 500:
        fail(f"Suspiciously few files ({file_count}). Aborting.")
    if file_count > 5000:
        warn(f"Many files ({file_count}). Verify .gitignore covered all heavy artifacts.")

    print()
    print("=" * 70)
    print("  Clean-slate staging READY")
    print("=" * 70)
    print(f"  Path        : {STAGING}")
    print("  Branch      : main")
    print(f"  Tag         : v{VERSION}")
    print(f"  Files       : {file_count}")
    print(f"  Author      : {PUBLIC_AUTHOR_NAME} <{PUBLIC_AUTHOR_EMAIL}>")
    print(f"  Signed      : {'YES' if sign_flag else 'NO (configure signing first)'}")
    print()
    print("  Inspect with :")
    print(f"    cd {STAGING}")
    print("    git log --pretty=fuller")
    print("    git ls-tree -r HEAD --name-only | head -20")
    print()
    print("  Next step (REQUIRES eSoleau ZIP UPLOADED) :")
    print("    python tools/launch_public_mirror.py --create-remote")
    print("=" * 70)

    return STAGING


# ─── Phase 3 : Create public GitHub repo ────────────────────────────────────


def phase_create_remote() -> str:
    """Create the public GitHub repo (visibility=public from start)."""
    # Check it doesn't already exist
    check = run(
        ["gh", "repo", "view", NEW_REPO_FULL, "--json", "name"],
        check=False,
        capture=True,
    )
    if check.returncode == 0:
        warn(f"Repo {NEW_REPO_FULL} already exists. Skipping creation.")
        return NEW_REPO_FULL

    info(f"Creating {NEW_REPO_FULL} as PUBLIC...")
    run(
        [
            "gh",
            "repo",
            "create",
            NEW_REPO_FULL,
            "--public",
            "--description",
            PUBLIC_DESCRIPTION,
            "--homepage",
            PUBLIC_HOMEPAGE,
            # No clone, no source -- we'll push from our staging dir manually.
        ]
    )

    # Add topics
    for topic in PUBLIC_TOPICS:
        run(
            [
                "gh",
                "api",
                "-X",
                "PUT",
                f"/repos/{NEW_REPO_FULL}/topics",
                "-f",
                f"names[]={topic}",
            ],
            check=False,
            capture=True,
        )

    ok(f"Repo created : https://github.com/{NEW_REPO_FULL}")
    return NEW_REPO_FULL


# ─── Phase 4 : Push the clean snapshot ──────────────────────────────────────


def phase_push(esoleau_confirmed: bool) -> None:
    """Push the staging branch + tag to the public remote.

    REQUIRES --i-have-esoleau-receipt to be passed at command line.
    """
    if not esoleau_confirmed:
        fail(
            "Refusing to push without --i-have-esoleau-receipt.\n"
            "The eSoleau receipt is your proof of authorship dated BEFORE\n"
            "public release. Without it, you lose the strongest legal evidence\n"
            "you can have in case of a copyright dispute later.\n"
            "\n"
            "If you really, really know what you're doing :\n"
            "  python tools/launch_public_mirror.py --push --i-have-esoleau-receipt"
        )

    if not STAGING.exists():
        fail(f"Staging dir not found : {STAGING}. Run --prepare first.")

    # PORTE FAIL-CLOSED (owner 2026-09-15) : pas de push public sans decision BREVET/IP
    # enregistree ET double confirmation owner (forge_publication_gate).
    from forge_publication_gate import porte_publique  # noqa: PLC0415
    _ok_gate, _motif_gate = porte_publique()
    if not _ok_gate:
        fail(_motif_gate)

    # Add remote (idempotent)
    run(
        [
            "git",
            "remote",
            "remove",
            "origin",
        ],
        cwd=STAGING,
        check=False,
        capture=True,
    )

    run(
        [
            "git",
            "remote",
            "add",
            "origin",
            f"https://github.com/{NEW_REPO_FULL}.git",
        ],
        cwd=STAGING,
    )

    info(f"Pushing main + tag v{VERSION}")
    run(["git", "push", "-u", "origin", "main"], cwd=STAGING)
    run(["git", "push", "origin", f"v{VERSION}"], cwd=STAGING)

    print()
    print("=" * 70)
    print(f"  🎉 LAUNCHED — github.com/{NEW_REPO_FULL}")
    print("=" * 70)
    print()
    print("  Next steps :")
    print("    1. python tools/launch_public_mirror.py --protect-main")
    print("    2. Open the launch checklist :")
    print("       cat docs/launch/CHECKLIST.md")
    print("    3. Follow timing : tweet, Show HN, Reddit, Lobsters, awesome-lists.")
    print("=" * 70)


# ─── Phase 5 : Branch protection ────────────────────────────────────────────


def phase_protect_main() -> None:
    """Apply branch protection rules to `main` on the public repo."""
    info(f"Applying branch protection on {NEW_REPO_FULL}/main")

    # Use the Rulesets API. NB (mesure 2026-08-21) : sur un depot PRIVE, rulesets
    # ET branch protection classique renvoient 403 « Upgrade to GitHub Pro or make
    # this repository public ». La protection serveur n'existe donc qu'en PUBLIC
    # (ou avec Pro). Cette fonction ne mord que sur le mirror PUBLIC -> OK ici.
    ruleset = {
        "name": "main-protection",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "required_signatures"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                },
            },
        ],
        "bypass_actors": [],
    }

    rs_path = STAGING / "_ruleset.json"
    rs_path.write_text(json.dumps(ruleset), encoding="utf-8")

    run(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"/repos/{NEW_REPO_FULL}/rulesets",
            "--input",
            str(rs_path),
        ],
        check=False,
    )

    rs_path.unlink(missing_ok=True)

    ok("Branch protection applied (Ruleset: main-protection)")


# ─── CLI ────────────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--esoleau-zip",
        action="store_true",
        help="Phase 1 : generate the INPI eSoleau ZIP from beta tip",
    )
    p.add_argument(
        "--esoleau-empreintes",
        action="store_true",
        help="Phase 1bis : dossier probatoire COMPACT par empreintes sha256 du commit "
             "(< 50 Mo = 15 EUR), a preferer au ZIP complet",
    )
    p.add_argument(
        "--prepare",
        action="store_true",
        help="Phase 2 : clean-slate staging + single signed commit",
    )
    p.add_argument(
        "--create-remote",
        action="store_true",
        help="Phase 3 : create public GitHub repo (no push yet)",
    )
    p.add_argument(
        "--push", action="store_true", help="Phase 4 : push staging to public remote (DESTRUCTIVE)"
    )
    p.add_argument(
        "--protect-main", action="store_true", help="Phase 5 : branch protection on main"
    )
    p.add_argument(
        "--i-have-esoleau-receipt",
        action="store_true",
        help="Confirm you uploaded the ZIP to eSoleau and have the PDF",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Run all phases except --push (push requires manual confirm)",
    )
    p.add_argument("--beta", default="beta", help="Source branch to snapshot (default: beta)")
    args = p.parse_args()

    actions = (
        args.esoleau_zip,
        args.esoleau_empreintes,
        args.prepare,
        args.create_remote,
        args.push,
        args.protect_main,
        args.all,
    )
    if not any(actions):
        p.print_help()
        return 1

    if args.all:
        phase_esoleau_zip(args.beta)
        phase_prepare(args.beta)
        phase_create_remote()
        warn("Skipping --push : you must explicitly request it AFTER eSoleau upload.")
        return 0

    if args.esoleau_zip:
        phase_esoleau_zip(args.beta)

    if args.esoleau_empreintes:
        phase_esoleau_empreintes(args.beta)

    if args.prepare:
        phase_prepare(args.beta)

    if args.create_remote:
        phase_create_remote()

    if args.push:
        phase_push(args.i_have_esoleau_receipt)

    if args.protect_main:
        phase_protect_main()

    return 0


if __name__ == "__main__":
    sys.exit(main())
