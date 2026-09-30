"""tools/forge_release_assets.py — build the DOWNLOADABLE release assets for v0.1.

Division of labour (anti-dup) :
  - tools/launch_public_mirror.py  -> clean-slate public REPO + signed commit
    + tag v0.1.0 + GitHub repo creation + push (+ INPI eSoleau IP filing).
  - THIS script                    -> the immutable ASSETS attached to that
    release : the source tarball, the int8 RAG Knowledge Pack, a vendor.lock
    provenance manifest, and a combined SHA256SUMS for reproducibility.

It REUSES existing primitives — `git archive` (honors .gitattributes
export-ignore) for the code, and `forge_knowledge_pack.export_pack` for the
DB. No upload here : uploading needs auth / user's session, so the script
PRINTS the exact `gh release` / Codeberg commands instead (no network).

Usage :
  LAFORGE_PYTHON tools/forge_release_assets.py --version 0.1.0 --branch beta
  LAFORGE_PYTHON tools/forge_release_assets.py --vendor-lock-only
  LAFORGE_PYTHON tools/forge_release_assets.py --skip-pack   # code + sums only
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/deploy : construit les assets telechargeables de la release"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    sp = str(_p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# Vendored frontend bundles KEPT in the release (offline/sovereign).
# The SHA computed at build time IS the real pin ; URL/version are provenance.
#
# LICENCES (owner 2026-09-29 : « pourquoi un projet comme odysseus cite les licences
# des produits le constituant ? »). Ce tableau ne couvrait que 2 des 22 fichiers tiers
# servis par le portail, sans licence ni version. Il porte desormais, pour CHAQUE
# fichier tiers : le composant, la version, la licence (identifiant SPDX) et ses textes
# sous `licenses/`. `forge_license_guard.py --embarques` juge `vendor.lock` qui en sort.
#
# Rien n'y est devine. Mesure du 2026-09-29 : chaque version a ete LUE dans le fichier
# lui-meme (bandeau ou litteral `version`), puis PROUVEE par egalite de sha256 avec le
# fichier amont a cette version (22/22 identiques, octet pour octet). Les polices sont
# des polices VARIABLES : Google Fonts sert le meme fichier pour toutes les graisses,
# d'ou un seul blob pour inter-400..700 -- ce n'est pas une copie fautive.
_J = "https://cdn.jsdelivr.net/npm/"
_INTER = "https://fonts.gstatic.com/s/inter/v20/UcC73FwrK3iLTeHuS_nVMrMxCp50SjIa1ZL7.woff2"
_JBM = ("https://fonts.gstatic.com/s/jetbrainsmono/v24/"
        "tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxDcwg.woff2")
_S = "app/web_hub/static/"


def _v(composant, version, licence, source, *textes):
    return {"composant": composant, "version": version, "licence": licence,
            "source": source, "licence_texte": list(textes)}


VENDORED = {
    _S + "alpine.min.js": _v("Alpine.js", "3.14.8", "MIT", _J + "alpinejs@3.14.8/dist/cdn.min.js",
                             "licenses/alpinejs/LICENSE.md"),
    _S + "babel.min.js": _v("@babel/standalone", "7.29.0", "MIT",
                            _J + "@babel/standalone@7.29.0/babel.min.js",
                            "licenses/babel-standalone/LICENSE"),
    _S + "cytoscape.min.js": _v("Cytoscape.js", "3.28.1", "MIT",
                                _J + "cytoscape@3.28.1/dist/cytoscape.min.js",
                                "licenses/cytoscape/LICENSE"),
    _S + "htmx.min.js": _v("htmx", "2.0.4", "0BSD", _J + "htmx.org@2.0.4/dist/htmx.min.js",
                           "licenses/htmx/LICENSE"),
    _S + "lucide.min.js": _v("Lucide", "0.544.0", "ISC", _J + "lucide@0.544.0/dist/umd/lucide.min.js",
                             "licenses/lucide/LICENSE"),
    _S + "react.min.js": _v("React", "18.3.1", "MIT", _J + "react@18.3.1/umd/react.production.min.js",
                            "licenses/react/LICENSE"),
    _S + "react-dom.min.js": _v("ReactDOM", "18.3.1", "MIT",
                                _J + "react-dom@18.3.1/umd/react-dom.production.min.js",
                                "licenses/react-dom/LICENSE"),
    # Le bundle renvoie a `redoc.standalone.js.LICENSE.txt` : les licences des modules
    # qu'il embarque (dont DOMPurify, Apache-2.0 OU MPL-2.0). Livre sous licenses/.
    _S + "redoc.standalone.js": _v("Redoc", "2.5.3", "MIT", _J + "redoc@2.5.3/bundles/redoc.standalone.js",
                                   "licenses/redoc/LICENSE",
                                   "licenses/redoc/redoc.standalone.js.LICENSE.txt"),
    # Apache-2.0 : le NOTICE amont se redistribue avec le texte de la licence (§4 d).
    _S + "swagger-ui-bundle.js": _v("Swagger UI", "5.32.14", "Apache-2.0",
                                    _J + "swagger-ui-dist@5.32.14/swagger-ui-bundle.js",
                                    "licenses/swagger-ui/LICENSE", "licenses/swagger-ui/NOTICE",
                                    "licenses/swagger-ui/swagger-ui-bundle.js.LICENSE.txt"),
    # La feuille de style embarque normalize.css 7.0.0 (bandeau MIT en tete du fichier).
    _S + "swagger-ui.css": _v("Swagger UI (CSS, inclut normalize.css 7.0.0)", "5.32.14",
                              "Apache-2.0 AND MIT", _J + "swagger-ui-dist@5.32.14/swagger-ui.css",
                              "licenses/swagger-ui/LICENSE", "licenses/swagger-ui/NOTICE",
                              "licenses/normalize.css/LICENSE.md"),
    _S + "tailwind.min.js": _v("Tailwind CSS (Play CDN)", "3.4.17", "MIT",
                               "https://cdn.tailwindcss.com/3.4.17", "licenses/tailwindcss/LICENSE"),
    _S + "vega.min.js": _v("Vega", "5.33.1", "BSD-3-Clause", _J + "vega@5.33.1/build/vega.min.js",
                           "licenses/vega/LICENSE"),
    _S + "vega-lite.min.js": _v("Vega-Lite", "5.23.0", "BSD-3-Clause",
                                _J + "vega-lite@5.23.0/build/vega-lite.min.js",
                                "licenses/vega-lite/LICENSE"),
    _S + "vega-embed.min.js": _v("Vega-Embed", "6.29.0", "BSD-3-Clause",
                                 _J + "vega-embed@6.29.0/build/vega-embed.min.js",
                                 "licenses/vega-embed/LICENSE"),
    # Double licence au choix du distributeur : les deux textes sont livres.
    _S + "vis-network.min.js": _v("vis-network", "9.1.9", "Apache-2.0 OR MIT",
                                  _J + "vis-network@9.1.9/standalone/umd/vis-network.min.js",
                                  "licenses/vis-network/LICENSE-MIT",
                                  "licenses/vis-network/LICENSE-APACHE-2.0"),
    **{_S + "fonts/inter-%d.woff2" % w: _v(
        "Inter", "Google Fonts v20 (latin, police variable)", "OFL-1.1", _INTER, "licenses/inter/OFL.txt")
       for w in (400, 500, 600, 700)},
    **{_S + "fonts/jetbrains-mono-%d.woff2" % w: _v(
        "JetBrains Mono", "Google Fonts v24 (latin, police variable)", "OFL-1.1", _JBM,
        "licenses/jetbrains-mono/OFL.txt")
       for w in (400, 500, 700)},
}

# Fichiers statiques ECRITS PAR NOKIDO (motifs fnmatch, relatifs a la racine). Le garde
# classe par LISTE BLANCHE : un fichier de `static/` qui n'est ni ici ni dans VENDORED
# est NON DECLARE -- jamais presume maison.
PROPRES_STATIC = (
    _S + "hub-compiled.js", _S + "providers.js", _S + "nokido*.js", _S + "nokido*.css",
    _S + "laforge-*.css", _S + "laforge-ds/*",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_code_tarball(out_dir: Path, version: str, branch: str, repo: Path | None = None) -> Path:
    """git archive de <branch> dans <repo> (defaut : ce depot) -> tar.gz.

    `repo` : pour une release du DIST, c'est le clone dist et `branch` son
    commit D. Mesure du 2026-09-30 : archiver la SOURCE contournait la politique
    publique et la generisation que porte le depot dist -- le tarball v0.20.2
    joint a la release contenait 186 chemins bloques (dont docs/ip/**) et 421
    fichiers a marqueurs machine, a cote d'un depot propre.

    `-c safe.directory=*` : SANS lui, cette commande meurt en « detected dubious
    ownership » des qu'elle tourne sous un compte qui n'est pas le proprietaire
    du depot -- c'est-a-dire dans TOUT job detache. Mesure du 2026-09-20 : exit
    128 au milieu d'une promotion, APRES que le commit dist et le tag avaient
    deja ete poses. `forge_dist_publish.sync_snapshot` porte ce drapeau depuis
    la veille ; il manquait ICI, et un contrat tenu d'un seul cote n'est pas un
    contrat. La portee reste locale a cet appel (`-c`), jamais `--global`.
    """
    dest = out_dir / f"nokido-{version}-src.tar.gz"
    depot = Path(repo) if repo else ROOT
    print(f"[code] git archive {branch} ({depot}) -> {dest.name}")
    r = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(depot), "archive",
         "--format=tar.gz", f"--prefix=nokido-{version}/", branch,
         "-o", str(dest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        # `check=True` seul rendait « exit status 128 » et RIEN d'autre : le
        # message de git etait perdu, et il a fallu DEDUIRE la cause au lieu de
        # la lire. Un echec doit dire pourquoi, sinon il coute une enquete.
        raise SystemExit(
            "[code] git archive ECHEC (rc=%d) sur %s :\n  %s"
            % (r.returncode, branch, (r.stderr or r.stdout or "").strip()[:400]))
    return dest


def build_rag_pack(out_dir: Path, version: str) -> Path:
    """Export int8 Knowledge Pack (all embedded chunks) -> zip."""
    from nokido_agent.tools import forge_knowledge_pack as kp

    pack_db = out_dir / "rag_pack_int8.db"
    print(f"[rag] export_pack -> {pack_db.name} (this can take a few minutes)")
    kp.export_pack(out_db=str(pack_db))
    dest = out_dir / "rag_pack_int8.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(pack_db, arcname="rag_pack_int8.db")
    pack_db.unlink()
    print(f"[rag] zipped -> {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
    return dest


def write_vendor_lock(dest=None) -> Path:
    """vendor.lock = provenance (path/source/version/sha) des bundles vendorises.

    `dest` separe DEUX roles qui etaient confondus :

    - sans `dest`, on ecrit a la racine du depot. C'est le chemin de MAINTENANCE
      (`--vendor-lock-only`), lance deliberement par quelqu'un qui a le droit
      d'ecrire la, pour rafraichir un fichier TRACKE.
    - avec `dest`, on ecrit dans le LOT de release. C'est le chemin de
      CONSTRUCTION, et il ne doit RIEN muter de la source.

    Mesure du 2026-09-20 : appelee sans destination au milieu d'une promotion,
    cette fonction ecrivait a la racine du depot source. PermissionError sous le
    compte d'un job detache -- mais le probleme de fond n'est pas le droit :
    c'est qu'un build qui REECRIT SON ENTREE n'est pas reproductible, et que
    `build = snapshot(S)` perd son sens des qu'on touche a l'arbre de travail.
    """
    entries = []
    for rel, meta in VENDORED.items():
        fp = ROOT / rel
        if not fp.exists():
            print(f"[vendor] WARN missing {rel}")
            continue
        entree = {"path": rel}
        # composant / licence / textes : absents des anciennes entrees, on n'invente rien.
        for cle in ("composant", "version", "licence", "source", "licence_texte"):
            if cle in meta:
                entree[cle] = meta[cle]
        entree["sha256"] = sha256_file(fp)
        entree["bytes"] = fp.stat().st_size
        entries.append(entree)
    lock = {
        "_comment": "Provenance of vendored frontend bundles kept in-repo "
                    "(offline/sovereign). SHA256 is the pin. Regenerate via "
                    "tools/forge_release_assets.py --vendor-lock-only.",
        "vendored": entries,
        "propres": list(PROPRES_STATIC),
    }
    dest = Path(dest) if dest else (ROOT / "vendor.lock")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"[vendor] wrote {dest} ({len(entries)} bundles)")
    return dest


def write_sha256sums(out_dir: Path, assets: list) -> Path:
    dest = out_dir / "SHA256SUMS"
    lines = [f"{sha256_file(a)}  {a.name}" for a in assets if a and a.exists()]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[sums] wrote {dest} ({len(lines)} assets)")
    return dest


def write_manifest(out_dir: Path, version: str, branch: str, assets: list) -> Path:
    dest = out_dir / "RELEASE_MANIFEST.json"
    manifest = {
        "version": version,
        "branch": branch,
        "built_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "assets": [
            {"name": a.name, "bytes": a.stat().st_size, "sha256": sha256_file(a)}
            for a in assets if a and a.exists()
        ],
    }
    dest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[manifest] wrote {dest}")
    return dest


def print_upload_help(out_dir: Path, version: str) -> None:
    tag = f"v{version}"
    print("\n" + "=" * 68)
    print("  ASSETS READY — upload manually (needs auth / your session)")
    print("=" * 68)
    print(f"  Dir : {out_dir}")
    print("\n  GitHub Release (secondary access point) :")
    print(f"    gh release create {tag} {out_dir}/* "
          f"--repo user/laforge-dist --title '{tag}' --notes-file -")
    print("\n  Codeberg (sovereign source of truth) :")
    print("    # create repos laforge-dist (code) + laforge-rag (pack) once, then :")
    print(f"    # attach assets to the Codeberg release for tag {tag}")
    print("=" * 68)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--branch", default="beta")
    ap.add_argument("--repo", default=None,
                    help="depot a archiver (defaut : ce depot). Pour une release "
                         "du dist : le clone dist, avec --branch = son commit D.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--skip-pack", action="store_true")
    ap.add_argument("--vendor-lock-only", action="store_true")
    args = ap.parse_args()

    if args.vendor_lock_only:
        write_vendor_lock()
        return 0

    out_dir = Path(args.out) if args.out else (
        Path("C:/tmp") if sys.platform == "win32" else Path("/tmp")
    ) / "laforge-release" / f"v{args.version}"
    out_dir.mkdir(parents=True, exist_ok=True)

    assets = []
    assets.append(build_code_tarball(out_dir, args.version, args.branch, args.repo))
    # Dans le LOT, jamais dans le depot : une construction ne mute pas sa
    # source. Et l'ajouter aux assets lui donne une empreinte au manifeste,
    # alors qu'un fichier ecrit a cote n'en aurait aucune.
    assets.append(write_vendor_lock(out_dir / "vendor.lock"))
    if not args.skip_pack:
        assets.append(build_rag_pack(out_dir, args.version))
    write_sha256sums(out_dir, assets)
    write_manifest(out_dir, args.version, args.branch, assets)
    print_upload_help(out_dir, args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
