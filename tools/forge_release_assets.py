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

MANIFESTE DE DISTRIBUTION (chantier « installation complete en une commande », P0,
2026-10-02). Ce compositeur lit `distribution/manifest.toml` (+ `platforms/*.toml`,
`packs/*.toml`) : schema VERSIONNE de ce que la distribution contient, par plateforme et
par pack -- composant, source, somme sha256, licence, taille, obligatoire ou non. Le
manifeste vit dans la SOURCE et part avec le snapshot ; le dist, lui, est reconstruit a
chaque promotion. Le validateur est FAIL-CLOSED : un champ manquant, une somme absente,
une version de schema inconnue ou un chemin absolu refusent tout le manifeste, et la
construction ne demarre pas.

Usage :
  LAFORGE_PYTHON tools/forge_release_assets.py --version 0.1.0 --branch beta
  LAFORGE_PYTHON tools/forge_release_assets.py --vendor-lock-only
  LAFORGE_PYTHON tools/forge_release_assets.py --skip-pack   # code + sums only
  LAFORGE_PYTHON tools/forge_release_assets.py --verifier-manifeste
  LAFORGE_PYTHON tools/forge_release_assets.py --sceller-manifeste   # resomme les sources `depot`
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


# ══ MANIFESTE DE DISTRIBUTION (schema v1) ════════════════════════════════════════════
# Trois sources, et une regle par source pour la SOMME -- une somme absente refuse toujours :
#   depot      fichier du depot, chemin RELATIF ; sha256 + taille epingles et VERIFIES contre
#              l'arbre (texte normalise LF, comme les examens geles : un checkout CRLF reste
#              le meme fichier) ; `--sceller-manifeste` les recalcule (maintenance).
#   url        telechargement https ; sha256 + taille EPINGLES, verifies au telechargement.
#   construit  produit par CE compositeur (liste blanche BUILDERS) ; la somme n'existe qu'au
#              build : le manifeste porte le marqueur EXPLICITE "au_build", et `verifier_lot`
#              exige ensuite la somme dans SHA256SUMS du lot.
# Un pack dont un composant ne peut pas encore etre prouve est `A_EPINGLER` : il liste ce
# qui manque (`[[a_epingler]]`), n'a aucun `[[composant]]` sans somme, et ne se compose pas.
DISTRIBUTION = ROOT / "distribution"
SCHEMA = "nokido-distribution"
VERSION_SCHEMA = 1
AU_BUILD = "au_build"
SOURCES = ("depot", "url", "construit")
BUILDERS = {"code": "nokido-{version}-src.tar.gz", "vendor_lock": "vendor.lock",
            "rag_pack": "rag_pack_int8.zip"}
STATUTS_PACK = ("PRET", "A_EPINGLER")
_CLES_COMPOSANT = {"id", "description", "source", "chemin", "url", "construit", "sha256",
                   "taille", "licence", "obligatoire"}
_CLES_REQUISES = ("id", "source", "sha256", "taille", "licence", "obligatoire")
_HEX64 = frozenset("0123456789abcdef")


def _absolu(v: str) -> bool:
    """Chemin absolu de poste (Windows, UNC, POSIX de compte) : interdit dans un livrable."""
    import re
    return bool(re.search(r"(?i)(^|[\s\"'=(])([a-z]:[\\/]|\\\\|/home/|/users/|/root/|/tmp/)", v)) \
        or v.startswith("/")


def sha256_lf(path: Path) -> tuple[str, int]:
    """(sha256, taille) du texte normalise LF ; binaire (NUL ou non-UTF-8) : octets bruts."""
    brut = Path(path).read_bytes()
    try:
        if b"\0" in brut:
            raise UnicodeDecodeError("utf-8", brut, 0, 1, "NUL")
        brut = brut.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    except UnicodeDecodeError:
        pass  # muet-ok : binaire, la somme porte sur les octets tels quels
    return hashlib.sha256(brut).hexdigest(), len(brut)


def _chaines(obj, chemin=""):
    """Toutes les chaines d'une structure TOML lue, avec leur chemin (pour les nommer)."""
    if isinstance(obj, str):
        yield chemin, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _chaines(v, "%s.%s" % (chemin, k) if chemin else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _chaines(v, "%s[%d]" % (chemin, i))


def _lire_toml(chemin: Path, erreurs: list):
    import tomllib
    try:
        with open(chemin, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        erreurs.append("%s : fichier absent" % chemin.name)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        erreurs.append("%s : illisible (%s)" % (chemin.name, exc))
    return None


def _valider_composant(c: dict, ou: str, racine: Path, erreurs: list, avert: list) -> None:
    inconnues = set(c) - _CLES_COMPOSANT
    if inconnues:
        erreurs.append("%s : cle(s) hors schema %s" % (ou, sorted(inconnues)))
    for k in _CLES_REQUISES:
        if k not in c or c[k] in ("", None):
            erreurs.append("%s : champ requis absent : %s" % (ou, k))
    if not isinstance(c.get("obligatoire"), bool):
        erreurs.append("%s : `obligatoire` doit etre vrai ou faux" % ou)
    lic = c.get("licence")
    if isinstance(lic, str) and lic.strip() == "NOASSERTION":
        avert.append("%s : licence NOASSERTION (aucune affirmation de licence)" % ou)
    src, sha, taille = c.get("source"), c.get("sha256"), c.get("taille")
    if src not in SOURCES:
        erreurs.append("%s : source %r hors liste blanche %s" % (ou, src, SOURCES))
        return
    if src == "construit":
        if c.get("construit") not in BUILDERS:
            erreurs.append("%s : constructeur %r inconnu (connus : %s)"
                           % (ou, c.get("construit"), sorted(BUILDERS)))
        if sha != AU_BUILD or taille != AU_BUILD:
            erreurs.append("%s : un composant construit porte sha256 = taille = %r"
                           % (ou, AU_BUILD))
        return
    if not (isinstance(sha, str) and len(sha) == 64 and set(sha) <= _HEX64):
        erreurs.append("%s : sha256 manquante ou mal formee (%r)" % (ou, sha))
    if not (isinstance(taille, int) and not isinstance(taille, bool) and taille > 0):
        erreurs.append("%s : taille manquante ou invalide (%r)" % (ou, taille))
    if src == "url":
        if not str(c.get("url", "")).startswith("https://"):
            erreurs.append("%s : une source url est en https (%r)" % (ou, c.get("url")))
        return
    rel = str(c.get("chemin", ""))
    if not rel or ".." in Path(rel).parts or Path(rel).is_absolute() or _absolu(rel):
        erreurs.append("%s : chemin de depot relatif requis (%r)" % (ou, rel))
        return
    fichier = racine / rel
    if not fichier.is_file():
        erreurs.append("%s : %s absent du depot" % (ou, rel))
        return
    reel, n = sha256_lf(fichier)
    if sha != reel or taille != n:
        erreurs.append("%s : %s a change (sha %s.. / %s octets attendus, %s.. / %s lus) -- "
                       "resceller par --sceller-manifeste" % (ou, rel, str(sha)[:12], taille,
                                                             reel[:12], n))


def valider_manifeste(dossier=None, racine=None) -> dict:
    """Lit et valide TOUT le manifeste. FAIL-CLOSED : la moindre erreur rend ok=False.

    Rend {"ok", "erreurs", "avertissements", "plateformes": {id: [composants]},
          "packs": {id: {"statut", "composants", "a_epingler", "composable"}}}.
    """
    dossier = Path(dossier) if dossier is not None else DISTRIBUTION
    racine = Path(racine) if racine is not None else ROOT
    erreurs: list = []
    avert: list = []
    out = {"ok": False, "erreurs": erreurs, "avertissements": avert, "plateformes": {},
           "packs": {}}
    m = _lire_toml(dossier / "manifest.toml", erreurs)
    if m is None:
        return out
    if m.get("schema") != SCHEMA or m.get("version_schema") != VERSION_SCHEMA:
        erreurs.append("manifest.toml : schema %r v%r inconnu (attendu %s v%d)"
                       % (m.get("schema"), m.get("version_schema"), SCHEMA, VERSION_SCHEMA))
        return out
    docs = {"manifest.toml": m}
    for genre, cle, sous in (("plateforme", "plateformes", "platforms"), ("pack", "packs", "packs")):
        ids = m.get(cle)
        if not isinstance(ids, list) or not ids:
            erreurs.append("manifest.toml : `%s` doit lister au moins un id" % cle)
            continue
        presents = {f.stem for f in (dossier / sous).glob("*.toml")} if (dossier / sous).is_dir() else set()
        for orphelin in sorted(presents - set(ids)):
            erreurs.append("%s/%s.toml : non declare dans manifest.toml (liste blanche)"
                           % (sous, orphelin))
        for i in ids:
            d = _lire_toml(dossier / sous / ("%s.toml" % i), erreurs)
            if d is None:
                continue
            nom = "%s/%s.toml" % (sous, i)
            docs[nom] = d
            if d.get("schema") != "%s/%s" % (SCHEMA, genre) or d.get("version_schema") != VERSION_SCHEMA:
                erreurs.append("%s : schema %r v%r inconnu" % (nom, d.get("schema"),
                                                               d.get("version_schema")))
                continue
            if d.get("id") != i:
                erreurs.append("%s : id %r different du nom de fichier" % (nom, d.get("id")))
            comps = d.get("composant") or []
            vus = set()
            for k, c in enumerate(comps):
                ou = "%s#%s" % (nom, c.get("id", k) if isinstance(c, dict) else k)
                if not isinstance(c, dict):
                    erreurs.append("%s : composant non conforme" % ou)
                    continue
                if c.get("id") in vus:
                    erreurs.append("%s : id de composant en double" % ou)
                vus.add(c.get("id"))
                _valider_composant(c, ou, racine, erreurs, avert)
            if genre == "plateforme":
                if not comps:
                    erreurs.append("%s : une plateforme sans composant ne livre rien" % nom)
                _valider_prerequis(d.get("prerequis"), nom, erreurs)
                out["plateformes"][i] = comps
                continue
            statut, attente = d.get("statut"), d.get("a_epingler") or []
            if statut not in STATUTS_PACK:
                erreurs.append("%s : statut %r hors liste blanche %s" % (nom, statut, STATUTS_PACK))
            elif statut == "PRET" and (not comps or attente):
                erreurs.append("%s : un pack PRET a des composants et rien a epingler" % nom)
            elif statut == "A_EPINGLER" and not attente:
                erreurs.append("%s : un pack A_EPINGLER dit ce qui manque ([[a_epingler]])" % nom)
            for a in attente:
                if not (isinstance(a, dict) and a.get("id") and a.get("raison")):
                    erreurs.append("%s : une entree a_epingler porte un id et une raison" % nom)
            for p in d.get("plateformes") or []:
                if p not in (m.get("plateformes") or []):
                    erreurs.append("%s : plateforme %r non declaree" % (nom, p))
            out["packs"][i] = {"statut": statut, "composants": comps, "a_epingler": attente,
                               "composable": statut == "PRET"}
    for nom, d in docs.items():
        for ou, v in _chaines(d):
            if _absolu(v) and not v.startswith("https://"):
                erreurs.append("%s : chemin absolu interdit dans un livrable (%s = %r)"
                               % (nom, ou, v[:80]))
    out["ok"] = not erreurs
    return out


def _valider_prerequis(prerequis, nom: str, erreurs: list) -> None:
    """Les prerequis cites existent dans le registre `forge_install_prerequis` (une seule source)."""
    if prerequis is None:
        return
    try:
        from nokido_agent.app.forge_install_prerequis import PREREQUIS
        connus = {e["cle"] for e in PREREQUIS}
    except Exception as exc:  # noqa: BLE001 - registre illisible : on refuse, on ne devine pas
        erreurs.append("%s : registre des prerequis illisible (%s)" % (nom, type(exc).__name__))
        return
    for p in prerequis:
        if p not in connus:
            erreurs.append("%s : prerequis %r absent de forge_install_prerequis.PREREQUIS" % (nom, p))


def sceller_manifeste(dossier=None, racine=None) -> dict:
    """MAINTENANCE : recalcule sha256 + taille des composants `depot`, en place, sans rien d'autre.

    Reecrit uniquement les lignes `sha256 =` / `taille =` des blocs `[[composant]]` dont la
    source est `depot` : commentaires et ordre sont conserves. Ne touche JAMAIS une source
    `url` (une somme epinglee se verifie, elle ne se recalcule pas)."""
    import re
    dossier = Path(dossier) if dossier is not None else DISTRIBUTION
    racine = Path(racine) if racine is not None else ROOT
    changes = []
    for f in sorted(list(dossier.glob("platforms/*.toml")) + list(dossier.glob("packs/*.toml"))):
        lignes = f.read_text(encoding="utf-8").splitlines(keepends=True)
        blocs, courant = [], None
        for i, l in enumerate(lignes):
            if l.strip().startswith("["):
                courant = {"debut": i, "entete": l.strip(), "cles": {}}
                blocs.append(courant)
            elif courant is not None:
                m = re.match(r'\s*(\w+)\s*=\s*(.+?)\s*$', l)
                if m:
                    courant["cles"][m.group(1)] = (i, m.group(2))
        for b in blocs:
            cles = b["cles"]
            if b["entete"] != "[[composant]]" or cles.get("source", (0, ""))[1] != '"depot"':
                continue
            rel = cles.get("chemin", (0, '""'))[1].strip('"')
            if not rel or not (racine / rel).is_file():
                continue
            sha, n = sha256_lf(racine / rel)
            for cle, val in (("sha256", '"%s"' % sha), ("taille", str(n))):
                if cle in cles:
                    i = cles[cle][0]
                    nouveau = re.sub(r"=\s*.+?(\s*)$", "= %s\\1" % val, lignes[i], count=1)
                    if nouveau != lignes[i]:
                        lignes[i] = nouveau
                        changes.append("%s : %s %s" % (f.name, rel, cle))
        f.write_text("".join(lignes), encoding="utf-8")
    return {"changes": changes}


def verifier_lot(out_dir: Path, version: str, manifeste: dict | None = None, racine=None) -> dict:
    """Le LOT construit tient-il le manifeste ? Fail-closed.

    * chaque composant `construit` obligatoire est present ET liste dans SHA256SUMS avec sa
      somme reelle (la somme « au_build » doit exister au build) ;
    * aucun fichier texte du lot, ni aucun nom de membre d'archive, ne porte le chemin du
      CHECKOUT (le poste qui construit ne fuit pas dans ce qu'il livre).
    """
    import tarfile
    out_dir = Path(out_dir)
    racine = Path(racine) if racine is not None else ROOT
    man = manifeste if manifeste is not None else valider_manifeste()
    erreurs: list = []
    sommes = {}
    try:
        for l in (out_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            if l.strip():
                h, _, nom = l.partition("  ")
                sommes[nom.strip()] = h.strip()
    except OSError as exc:
        erreurs.append("SHA256SUMS illisible (%s)" % exc)
    for comps in list(man.get("plateformes", {}).values()):
        for c in comps:
            if c.get("source") != "construit" or not c.get("obligatoire"):
                continue
            nom = BUILDERS.get(c.get("construit"), "").format(version=version)
            f = out_dir / nom
            if not f.is_file():
                erreurs.append("%s : %s absent du lot" % (c.get("id"), nom))
            elif sommes.get(nom) != sha256_file(f):
                erreurs.append("%s : somme de %s absente ou fausse dans SHA256SUMS"
                               % (c.get("id"), nom))
    # Le chemin tel quel, en / et en \\, et SANS sa racine de volume : un membre d'archive
    # ne porte jamais de « / » initial ni de lecteur (tar les retire) -- « home/u/nokido/x ».
    posix = racine.as_posix()
    # + la forme ECHAPPEE JSON (2026-10-02, report sous Windows) : json.dumps double les « \ »
    # -- « C:\\Users\\... » -- et un manifeste JSON portant le chemin Windows passait inapercu.
    marques = {str(racine), posix, str(racine).replace("/", "\\"),
               posix.split(":", 1)[-1].lstrip("/"),
               json.dumps(str(racine))[1:-1]}
    marques = {m for m in marques if len(m) > 3 and ("/" in m or "\\" in m)}
    for f in sorted(out_dir.iterdir()):
        if not f.is_file():
            continue
        if f.name.endswith((".tar.gz", ".tgz")):
            try:
                with tarfile.open(f) as t:
                    noms = t.getnames()
            except (tarfile.TarError, OSError) as exc:
                erreurs.append("%s : archive illisible (%s)" % (f.name, exc))
                continue
            texte = "\n".join(noms)
        elif f.suffix == ".zip":
            with zipfile.ZipFile(f) as z:
                texte = "\n".join(z.namelist())
        else:
            texte = f.read_bytes().decode("utf-8", errors="replace")
        for m in marques:
            if m in texte:
                erreurs.append("%s : porte le chemin du checkout (%s)" % (f.name, m))
                break
    return {"ok": not erreurs, "erreurs": erreurs}


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
    ap.add_argument("--verifier-manifeste", action="store_true",
                    help="valider distribution/ (fail-closed) et sortir : 0 valide, 1 refuse")
    ap.add_argument("--sceller-manifeste", action="store_true",
                    help="MAINTENANCE : recalculer sha256/taille des composants `depot`")
    args = ap.parse_args()

    if args.vendor_lock_only:
        write_vendor_lock()
        return 0
    if args.sceller_manifeste:
        print(json.dumps(sceller_manifeste(), ensure_ascii=False, indent=2))
        return 0
    man = valider_manifeste()
    if args.verifier_manifeste or not man["ok"]:
        print(json.dumps({k: man[k] for k in ("ok", "erreurs", "avertissements")},
                         ensure_ascii=False, indent=2))
        if not man["ok"]:
            # FAIL-CLOSED : pas de construction sur un manifeste refuse.
            print("[manifeste] REFUSE : aucune construction", file=sys.stderr)
            return 1
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
    lot = verifier_lot(out_dir, args.version, man)
    if not lot["ok"]:
        print("[lot] REFUSE :\n  " + "\n  ".join(lot["erreurs"]), file=sys.stderr)
        return 1
    print_upload_help(out_dir, args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
