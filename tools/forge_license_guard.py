"""forge_license_guard.py — garde-fou conformité AGPLv3 des dépendances Python.

Scanne les licences des paquets INSTALLÉS (via importlib.metadata, stdlib — mêmes
métadonnées que pip-licenses, sans nouvelle dépendance) et BLOQUE (exit 1) toute
dépendance de licence INCOMPATIBLE AGPLv3.

Compatible AGPLv3 (entrée) : MIT, BSD, Apache-2.0, ISC, GPLv3+, LGPLv3+, MPL-2.0,
PSF, zlib, domaine public/CC0, Boost, PostgreSQL, AGPL lui-même.
Incompatible : SSPL, BSL/Business Source, Elastic, Commons Clause, CC-BY-NC,
propriétaire/Other-Proprietary, GPLv2-ONLY (sans « or later »), Redis RSALv.

Inconnu = WARN (pas bloquant : évite les faux positifs sur métadonnées pauvres).
`--strict` transforme inconnu en blocage. `--print-all` liste tout.

`--embarques` juge l'AUTRE moitié de la distribution : les fichiers tiers servis par
le portail (`app/web_hub/static`), que `importlib.metadata` ne voit pas. Chacun doit
être déclaré dans `vendor.lock` (composant, version, licence SPDX, textes sous
`licenses/`) avec son sha256 ; tout autre fichier doit être déclaré maison.

Câblé : pre-commit (déclenché sur requirements*.txt / pyproject.toml) + CI job.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Sous-chaînes de licence INTERDITES (incompatibles AGPLv3 en entrée).
DENY = (
    "sspl", "server side public license",
    # ⚠️ HOMONYMES : DEUX licences s'ecrivent « BSL-1.x », et une seule est interdite.
    #   BSL-1.0  = Boost Software License  -> PERMISSIVE, compatible AGPLv3 (cf. ALLOW)
    #   BSL-1.1  = Business Source License -> source-available, NON libre, interdite
    #              (identifiant SPDX officiel : BUSL-1.1)
    # Les motifs larges « bsl- » et « bsl  » attrapaient donc Boost et refusaient torch
    # 2.13.0, dont l'expression SPDX est « Apache-2.0 AND ... AND BSL-1.0 AND MIT » —
    # que des licences de l'allowlist. Faux positif mesure le 2026-09-07 : le gate etait
    # JUSTE, son diagnostic etait FAUX. On resserre le motif au lieu d'affaiblir le garde,
    # et la couverture de Business Source reste entiere : « business source » (libelle),
    # « busl » (SPDX), « bsl-1.1 » / « bsl 1.1 » (ecriture courante).
    "business source", "bsl-1.1", "bsl 1.1", "busl",
    "elastic license", "elastic-2", "elv2",
    "commons clause",
    "by-nc", "noncommercial", "non-commercial",
    "proprietary", "other/proprietary", "all rights reserved",
    "prosperity", "rsalv", "redis source available",
)
# Sous-chaînes COMPATIBLES connues (allowlist) → classe 'ok' vs 'unknown'.
ALLOW = (
    "mit", "bsd", "apache", "isc", "mpl", "mozilla public",
    "agpl", "affero", "lgpl", "lesser general public",
    "python software foundation", "psf", "python-2",
    "unlicense", "public domain", "cc0", "wtfpl", "zlib", "zpl",
    "boost", "bsl-1.0", "postgresql", "hpnd", "0bsd", "historical permission",
    # GPLv3 (seule ou « ou ulterieure ») et GPLv2 « ou ulterieure » se combinent avec
    # l'AGPLv3 (§13 AGPLv3 / §14 GPLv3). Mesure 2026-09-29 : html2text, marker-pdf,
    # surya-ocr, stegano, pykeepass, pylint sortaient « inconnu » alors que compatibles.
    # La GPLv2 SEULE reste interdite (regle _GPL2_ONLY, evaluee AVANT cette liste).
    "gpl-3", "gplv3", "gpl v3", "general public license v3",
    "gpl-2.0-or-later", "gpl-2.0+", "gplv2+", "general public license v2 or later",
    # Polices (Inter, JetBrains Mono) : l'OFL autorise expressément de les livrer
    # avec un logiciel sous n'importe quelle licence (§2 de l'OFL-1.1).
    "ofl", "open font license",
)
# Overrides par nom de paquet (métadonnée ambiguë mais licence connue OK).
OVERRIDES: dict[str, str] = {
    # PyInstaller : le classifier annonce « GPLv2 » MAIS la licence réelle est
    # GPL-2.0-or-later AVEC exception bootloader (bundling d'apps proprio/(A)GPL
    # explicitement autorisé) → AGPL-compatible. Faux positif du même type que
    # paramiko/LGPL traité dans classify().
    "pyinstaller": "gpl-2.0-or-later with bootloader exception (agpl-compatible)",
    # pyinstaller-hooks-contrib : DOUBLE licence « Apache-2.0 OR GPL-2.0 » →
    # branche Apache retenue (permissive, AGPL-compatible).
    "pyinstaller-hooks-contrib": "apache-2.0",
}

# GPLv2-only (sans « or later ») = incompatible AGPLv3.
_GPL2_ONLY = re.compile(r"gpl.{0,8}v?2(\.0)?\b")
_OR_LATER = re.compile(r"(or later|2\.0\+|v2\+|2\+|or-later)")


def _license_text(dist) -> str:
    """Licence d'un dist : SPDX License-Expression (PEP 639) > classifiers > champ License."""
    meta = dist.metadata
    expr = (meta.get("License-Expression") or "").strip()  # PEP 639 SPDX canonique
    if expr:
        return expr.lower()
    cls = [c for c in meta.get_all("Classifier", []) if c.startswith("License")]
    champ = (meta.get("License") or "").strip()
    # Un classifieur « Other/Proprietary » SEUL est souvent fabrique par l'outil de build :
    # Poetry le pose quand il ne sait pas traduire le texte de licence declare. Mesure
    # 2026-09-29 : androguard (« Apache Licence, Version 2.0 »), archspec (« Apache-2.0 OR
    # MIT »), fastembed (« Apache License ») refuses a tort. Le champ `License` ecrit par
    # l'auteur prime alors ; un vrai « Proprietary » y reste ecrit et reste refuse.
    # Meme regle pour un classifieur GENERIQUE (« OSI Approved » sans nom de licence) :
    # asyncssh declare « EPL-2.0 OR GPL-2.0-or-later » dans `License` et ne porte que ce
    # classifieur vague -- il sortait « inconnu » (mesure 2026-09-29).
    if cls and champ and all(c.lower().strip() == "license :: osi approved"
                             or "other/proprietary" in c.lower() for c in cls):
        return champ.lower()[:300]
    if cls:
        return " ; ".join(cls).lower()
    if champ:
        return champ.lower()[:300]
    # Metadonnees VIDES : le fichier de licence LIVRE avec le paquet (PEP 639). mistralai
    # 2.3.2 : ni `License`, ni classifieur, mais un LICENSE « Apache License, Version 2.0 ».
    return _licence_du_fichier(dist)


# Formules CANONIQUES qui identifient une licence dans son texte, dans l'ordre ou les
# tester (la plus specifique d'abord). On ne rend JAMAIS le texte lui-meme : la premiere
# version lisait l'en-tete, et « All rights reserved » -- present dans tout texte BSD --
# a fait refuser conda-package-handling et matplotlib-inline (BSD-3), mesure 2026-09-29.
# Le texte GPLv2 contient toujours « or (at your option) any later version » dans son
# annexe-modele : la version reelle n'y est PAS tranchable -> libelle neutre, donc inconnu.
_FORMULES = (
    ("gnu affero general public license", "agpl (fichier)"),
    ("gnu lesser general public license", "lgpl (fichier)"),
    ("gnu library general public license", "lgpl (fichier)"),
    ("mozilla public license", "mpl-2.0 (fichier)"),
    ("apache license", "apache-2.0 (fichier)"),
    ("eclipse public license", "epl (fichier, a instruire)"),
    ("permission is hereby granted, free of charge", "mit (fichier)"),
    ("redistribution and use in source and binary forms", "bsd (fichier)"),
    ("permission to use, copy, modify, and/or distribute", "isc (fichier)"),
    ("this is free and unencumbered software", "unlicense (fichier)"),
)


def _licence_du_fichier(dist) -> str:
    """Libelle canonique de la licence du premier fichier de licence livre ; "" si non reconnue."""
    for f in getattr(dist, "files", None) or []:
        nom = str(f).replace("\\", "/").rsplit("/", 1)[-1].lower()
        if not nom.startswith(("license", "licence", "copying")):
            continue
        try:
            texte = " ".join(Path(f.locate()).read_text(encoding="utf-8", errors="replace").lower().split())
        except (OSError, AttributeError):  # muet-ok : fichier illisible -> "" -> INCONNU, dit par le garde
            continue
        # AGPL / LGPL d'abord : leur texte CITE aussi « GNU General Public License ».
        for formule, libelle in _FORMULES[:3]:
            if formule in texte:
                return libelle
        if "gnu general public license" in texte:
            return ("gpl-3 (fichier)" if "version 3" in texte[:400]
                    else "gnu gpl version 2 (fichier : ou-ulterieure non tranchable)")
        for formule, libelle in _FORMULES[3:]:
            if formule in texte:
                return libelle
    return ""


def classify(name: str, lic: str) -> str:
    """Retourne 'deny' | 'ok' | 'unknown'."""
    if name.lower() in OVERRIDES:
        lic = OVERRIDES[name.lower()].lower()
    if not lic:
        return "unknown"
    if any(tok in lic for tok in DENY):
        return "deny"
    # GPLv2-only : gpl v2 mentionné, pas 'or later', et pas (a/l)gpl v3.
    # LGPL (toute version) EXCLU : c'est du copyleft faible, AGPL-compatible (linking
    # explicitement autorisé) ; le regex matchait "gpl-2" DANS "lgpl-2.1" = faux positif
    # (ex: paramiko==4.0.0 lgpl-2.1 bloquait le CI à tort).
    if _GPL2_ONLY.search(lic) and not _OR_LATER.search(lic) \
            and "v3" not in lic and "3.0" not in lic \
            and "lgpl" not in lic and "lesser" not in lic:
        return "deny"
    if any(tok in lic for tok in ALLOW):
        return "ok"
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="inconnu = blocage")
    ap.add_argument("--print-all", action="store_true")
    ap.add_argument("--embarques", action="store_true",
                    help="fichiers tiers de app/web_hub/static contre vendor.lock")
    ap.add_argument("--declarees", action="store_true",
                    help="dependances DECLAREES (pyproject + requirements*.txt), pas l'env entier")
    args = ap.parse_args()
    if args.embarques:
        return verifier_embarques()
    if args.declarees:
        return verifier_declarees()

    deny, unknown, ok = [], [], []
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or "?"
        lic = _license_text(dist)
        verdict = classify(name, lic)
        entry = (name, dist.version, lic[:60])
        {"deny": deny, "unknown": unknown, "ok": ok}[verdict].append(entry)

    if args.print_all:
        for n, v, l in sorted(ok):
            print(f"  OK      {n}=={v}  [{l}]")
    for n, v, l in sorted(unknown):
        print(f"  WARN    {n}=={v}  licence inconnue [{l or 'vide'}]")
    for n, v, l in sorted(deny):
        print(f"  DENY    {n}=={v}  INCOMPATIBLE AGPLv3 [{l}]")

    print(f"\n[license-guard] {len(ok)} ok · {len(unknown)} inconnu · {len(deny)} INCOMPATIBLE")
    fail = bool(deny) or (args.strict and bool(unknown))
    if fail:
        print("[license-guard] ÉCHEC : dépendance(s) incompatible(s) AGPLv3 — retirer ou remplacer.")
        return 1
    print("[license-guard] OK : aucune licence incompatible AGPLv3.")
    return 0


# Manifestes de dependances du depot (relatifs a la racine).
MANIFESTES = ("pyproject.toml", "requirements.txt", "requirements-ml.txt", "app/requirements.txt")
_RE_NOM = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _norme(nom: str) -> str:
    """Nom de distribution normalise (PEP 503) : `Foo_Bar.baz` == `foo-bar-baz`."""
    return re.sub(r"[-_.]+", "-", nom).lower()


def dependances_declarees(racine: Path = None) -> dict[str, list[str]]:
    """{nom normalise: [manifestes qui le declarent]} -- dependances ET extras optionnels.

    Une ligne commentee n'est PAS une declaration : `# scapy>=2.5.0` (app/requirements.txt,
    « optionnel ») a ete compte comme declaree par une premiere mesure du 2026-09-29, et
    annonce a tort a l'owner. On lit la ligne apres avoir retire le commentaire.
    """
    racine = Path(racine) if racine else ROOT
    trouve: dict[str, list[str]] = {}

    def _ajoute(spec: str, source: str):
        m = _RE_NOM.match(spec.split("#", 1)[0])
        if m:
            trouve.setdefault(_norme(m.group(1)), []).append(source)

    for rel in MANIFESTES:
        p = racine / rel
        if not p.is_file():
            continue
        texte = p.read_text(encoding="utf-8", errors="replace")
        if rel.endswith(".toml"):
            try:
                import tomllib
                projet = tomllib.loads(texte).get("project", {})
            except Exception as exc:  # noqa: BLE001 - un manifeste illisible se DIT
                print("[license-guard/declarees] %s ILLISIBLE (%s) — NON MESURÉ" % (rel, type(exc).__name__))
                continue
            for spec in projet.get("dependencies", []):
                _ajoute(spec, rel)
            for extra, specs in projet.get("optional-dependencies", {}).items():
                for spec in specs:
                    _ajoute(spec, "%s[%s]" % (rel, extra))
            continue
        for ligne in texte.splitlines():
            s = ligne.strip()
            if not s or s.startswith(("#", "-", "git+", "http")):
                continue
            _ajoute(s, rel)
    return trouve


def verifier_declarees(racine: Path = None) -> int:
    """`--declarees` : la licence de chaque dependance DECLAREE par le depot.

    Le mode par defaut juge l'environnement INSTALLE -- celui de la CI : 0 incompatible le
    2026-09-29, alors que l'interpreteur runtime en portait 13, et qu'une dependance
    optionnelle GPL-2.0-only (scapy) y est importee sans que la CI l'ait jamais vue. Ici on
    part des MANIFESTES. Une dependance declaree mais non installee n'a pas de licence
    lisible hors ligne : elle sort NON MESURÉE, jamais comptee saine.
    """
    decl = dependances_declarees(racine)
    installes = {_norme(d.metadata.get("Name") or ""): d for d in metadata.distributions()}
    deny, unknown, ok, absents = [], [], [], []
    for nom, sources in sorted(decl.items()):
        d = installes.get(nom)
        if d is None:
            absents.append((nom, sources))
            continue
        lic = _license_text(d)
        verdict = classify(nom, lic)
        {"deny": deny, "unknown": unknown, "ok": ok}[verdict].append((nom, d.version, lic[:60], sources))
    for nom, v, lic, src in unknown:
        print("  INCONNU %s==%s [%s] declare par %s" % (nom, v, lic or "vide", ", ".join(src)))
    for nom, v, lic, src in deny:
        print("  DENY    %s==%s [%s] declare par %s" % (nom, v, lic, ", ".join(src)))
    for nom, src in absents:
        print("  NON MESURÉ %s (declare par %s, absent de cet interpreteur)" % (nom, ", ".join(src)))
    print("[license-guard/declarees] %d declarees : %d ok · %d inconnu · %d INCOMPATIBLE · "
          "%d non mesurees (absentes de %s)" % (len(decl), len(ok), len(unknown), len(deny),
                                                 len(absents), sys.executable))
    return 1 if deny else 0


# Extensions des fichiers statiques qui peuvent venir d'un tiers (code, style, police).
_EXT_EMBARQUEES = (".js", ".mjs", ".css", ".woff2", ".woff", ".ttf", ".otf")


def verifier_embarques(racine: Path = None) -> int:
    """`--embarques` : chaque fichier tiers de `app/web_hub/static` est-il déclaré et licencié ?

    Classement par LISTE BLANCHE (constitution sémantique) : un fichier n'est sain que s'il
    est PROUVÉ tiers déclaré ou maison. Refusés, et nommés : un fichier non déclaré, un
    bundle remplacé sans mise à jour de `vendor.lock` (sha256 différent), une licence
    absente ou interdite, un texte de licence absent.

    La licence jugée est l'identifiant SPDX DÉCLARÉ, jamais le texte : le texte BSD-3 de
    Vega porte « All rights reserved », qui est dans DENY -- le lire ferait refuser une
    licence permissive.
    """
    racine = Path(racine) if racine else ROOT
    lock_p = racine / "vendor.lock"
    try:
        lock = json.loads(lock_p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("[license-guard/embarques] vendor.lock ILLISIBLE (%s: %s) — NON MESURÉ, "
              "ce n'est pas un succès." % (type(exc).__name__, exc))
        return 1
    fautes: list[str] = []
    declares: set[str] = set()
    licences: dict[str, str] = {}
    for e in lock.get("vendored", []):
        rel = e.get("path", "")
        declares.add(rel)
        fp = racine / rel
        if not fp.is_file():
            fautes.append("DÉCLARÉ ABSENT      %s" % rel)
            continue
        if hashlib.sha256(fp.read_bytes()).hexdigest() != e.get("sha256"):
            fautes.append("REMPLACÉ SANS LOCK  %s (sha256 ≠ vendor.lock : regénérer "
                          "`forge_release_assets.py --vendor-lock-only`)" % rel)
        lic = (e.get("licence") or "").strip()
        if not lic:
            fautes.append("SANS LICENCE        %s" % rel)
            continue
        verdict = classify(e.get("composant", rel), lic.lower())
        if verdict != "ok":
            fautes.append("LICENCE %-11s %s [%s]" % (verdict.upper(), rel, lic))
        textes = e.get("licence_texte") or []
        if not textes:
            fautes.append("SANS TEXTE          %s [%s]" % (rel, lic))
        for t in textes:
            tp = racine / t
            if not tp.is_file() or tp.stat().st_size == 0:
                fautes.append("TEXTE ABSENT        %s (pour %s)" % (t, rel))
        licences[e.get("composant", rel)] = lic
    propres = lock.get("propres", [])
    maison = 0
    static = racine / "app" / "web_hub" / "static"
    for fp in sorted(static.rglob("*")) if static.is_dir() else []:
        if not fp.is_file() or fp.suffix.lower() not in _EXT_EMBARQUEES:
            continue
        rel = fp.relative_to(racine).as_posix()
        if rel in declares:
            continue
        if any(fnmatch.fnmatch(rel, m) for m in propres):
            maison += 1
            continue
        fautes.append("NON DÉCLARÉ         %s (ni tiers dans vendor.lock, ni maison)" % rel)
    for f in fautes:
        print("  " + f)
    print("[license-guard/embarques] %d fichier(s) tiers déclaré(s), %d composant(s), "
          "%d fichier(s) maison, %d à corriger" % (len(declares), len(licences), maison, len(fautes)))
    return 1 if fautes else 0


if __name__ == "__main__":
    raise SystemExit(main())
